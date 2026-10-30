"""Retain the finite development search; later evaluation uses frozen thresholds."""

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CASES = ["original", "gain_offset", "quantized_002mV"]
QUANTILES = [("q090", 0.90), ("q095", 0.95), ("q099", 0.99)]


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def nearest_rank(values, p):
    if not values or not 0 < p <= 1 or not all(math.isfinite(v) for v in values):
        raise ValueError("Invalid quantile input")
    return sorted(values)[math.ceil(p * len(values)) - 1]


def flag(baseline, high, config):
    if not all(math.isfinite(v) and v >= 0 for v in [baseline, high]):
        raise ValueError("Invalid features are unavailable")
    if config["candidate"] == "accept_all":
        return False
    return baseline > config["B_threshold"] or high > config["H_threshold"]


def load_input(path, subject):
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    noise_starts = {t for t in range(300, 1800, 10) if ((t - 300) // 120) % 2 == 0}
    assert len(noise_starts) == 78
    expected = {(subject, t) for t in range(0, 1800, 10)}
    expected |= {
        (subject + suffix, t)
        for suffix in ["e24", "e18", "e12", "e06", "e00", "e_6"]
        for t in noise_starts
    }
    actual = set()
    for row in rows:
        key = (row["source_record"], int(row["start_seconds"]))
        assert key not in actual and row["subject_record"] == subject
        actual.add(key)
        assert row["condition"] == (
            "source_clean"
            if row["source_record"] == subject
            else "added_electrode_motion"
        )
        assert row["dataset"] == (
            "mitdb" if row["source_record"] == subject else "nstdb"
        )
        expected_snr = {
            "e24": "24",
            "e18": "18",
            "e12": "12",
            "e06": "6",
            "e00": "0",
            "e_6": "-6",
        }.get(row["source_record"][3:], "")
        assert row["snr_dB"] == expected_snr
        assert row["units"] == "mV" and row["lead"] == "MLII"
        assert (
            int(row["start_sample"]) == key[1] * 360
            and int(row["stop_sample"]) == (key[1] + 10) * 360
        )
        for case in CASES:
            for feature in ["B", "H"]:
                value = float(row[case + "_" + feature])
                assert math.isfinite(value) and value >= 0
                row[case + "_" + feature] = value
        for name in [
            "source_header_sha256",
            "source_signal_sha256",
            "digital_window_sha256",
        ]:
            assert len(row[name]) == 64 and all(
                c in "0123456789abcdef" for c in row[name]
            )
    assert actual == expected and len(rows) == 648
    return rows


def metrics(rows):
    primary = [r for r in rows if r["stratum"] == "clean" or int(r["stratum"]) <= 6]
    positive = [r for r in primary if r["stratum"] != "clean"]
    negative = [r for r in primary if r["stratum"] == "clean"]
    tp = sum(r["flag"] for r in positive)
    fp = sum(r["flag"] for r in negative)
    fn, tn = len(positive) - tp, len(negative) - fp
    return dict(
        n=len(primary),
        positives=len(positive),
        negatives=len(negative),
        tp=tp,
        fn=fn,
        fp=fp,
        tn=tn,
        prevalence=len(positive) / len(primary),
        precision=tp / (tp + fp) if tp + fp else "",
        recall=tp / len(positive),
        specificity=tn / len(negative),
        false_rejection_rate=fp / len(negative),
        balanced_accuracy=(tp / len(positive) + tn / len(negative)) / 2,
    )


def choose(candidates):
    feasible = [
        c
        for c in candidates
        if c["candidate"] != "accept_all" and c["fp"] * 20 <= c["negatives"]
    ]
    if not feasible:
        return "accept_all"
    return max(feasible, key=lambda c: (c["tp"], c["quantile"]))["candidate"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["development", "later"], required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    phase = args.phase
    subject = "118" if phase == "development" else "119"
    if phase == "later":
        subprocess.run(
            [sys.executable, str(root / "src/freeze_proof.py")], cwd=root, check=True
        )
    source = args.input or root / ("data/features_" + phase + ".csv")
    output = args.output or root / ("results/" + phase)
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Preserve existing results; replay into a separate output directory"
        )
    output.mkdir(parents=True, exist_ok=True)
    data = load_input(source, subject)
    baseline = dict(
        candidate="accept_all", quantile=None, B_threshold=None, H_threshold=None
    )
    if phase == "development":
        calibration = [
            row
            for row in data
            if row["condition"] == "source_clean" and int(row["start_seconds"]) < 300
        ]
        assert len(calibration) == 30
        configs = [baseline] + [
            dict(
                candidate=name,
                quantile=p,
                B_threshold=nearest_rank([r["original_B"] for r in calibration], p),
                H_threshold=nearest_rank([r["original_H"] for r in calibration], p),
            )
            for name, p in QUANTILES
        ]
    else:
        frozen = json.loads(
            (root / "results/development/selection.json").read_text(encoding="utf-8")
        )
        # The pre-later development note fixes a secondary audit of every candidate.
        configs = frozen["candidates"]
    scored = [r for r in data if int(r["start_seconds"]) >= 300]
    assert len(scored) == 618
    predictions, summaries, strata, sensitivity, executions = [], [], [], [], []
    for config in configs:
        started = time.perf_counter()
        for case in CASES:
            subset = []
            for row in scored:
                b, h = row[case + "_B"], row[case + "_H"]
                item = dict(
                    candidate=config["candidate"],
                    case=case,
                    subject_record=subject,
                    source_record=row["source_record"],
                    start_seconds=row["start_seconds"],
                    stratum=(
                        "clean" if row["condition"] == "source_clean" else row["snr_dB"]
                    ),
                    B=format(b, ".17g"),
                    H=format(h, ".17g"),
                    flag=int(flag(b, h, config)),
                )
                subset.append(item)
            predictions.extend(subset)
            summaries.append(
                dict(
                    candidate=config["candidate"],
                    quantile=config["quantile"],
                    case=case,
                    **metrics(subset)
                )
            )
            for stratum in ["clean", "-6", "0", "6", "12", "18", "24"]:
                group = [r for r in subset if r["stratum"] == stratum]
                strata.append(
                    dict(
                        candidate=config["candidate"],
                        case=case,
                        stratum=stratum,
                        n=len(group),
                        flagged=sum(r["flag"] for r in group),
                        flag_fraction=sum(r["flag"] for r in group) / len(group),
                    )
                )
        for case in CASES[1:]:
            original_flags = {
                (r["source_record"], r["start_seconds"]): r["flag"]
                for r in predictions
                if r["candidate"] == config["candidate"] and r["case"] == "original"
            }
            for stratum in ["clean", "-6", "0", "6", "12", "18", "24"]:
                group = [
                    r
                    for r in predictions
                    if r["candidate"] == config["candidate"]
                    and r["case"] == case
                    and r["stratum"] == stratum
                ]
                flips = sum(
                    r["flag"]
                    != original_flags[(r["source_record"], r["start_seconds"])]
                    for r in group
                )
                if case == "gain_offset":
                    assert (
                        flips == 0
                    ), "Preserve and investigate any numerical decision boundary"
                sensitivity.append(
                    dict(
                        candidate=config["candidate"],
                        case=case,
                        stratum=stratum,
                        n=len(group),
                        decision_flips=flips,
                    )
                )
        executions.append(
            dict(
                candidate=config["candidate"],
                status="PASS",
                wall_seconds=time.perf_counter() - started,
                seed="not_applicable_no_randomness",
            )
        )
    if phase == "development":
        originals = [r for r in summaries if r["case"] == "original"]
        selected_id = choose(originals)
        selected = next(c for c in configs if c["candidate"] == selected_id)
        selection = dict(
            phase="development",
            calibration_record="118",
            calibration_windows=30,
            validation_record="118",
            source_clean_validation_windows=150,
            lower_snr_positive_windows=234,
            candidates=configs,
            selected=selected,
            objective="false rejection <=0.05; maximum lower-SNR true positives; ties prefer larger quantile; accept-all fallback",
            search_complete=True,
            boundary_winner=selected_id in ["q090", "q099"],
        )
        write_json(output / "selection.json", selection)
    else:
        selected_id = frozen["selected"]["candidate"]
        write_json(
            output / "frozen_selection_used.json",
            dict(
                phase="later",
                selected=frozen["selected"],
                calibrated_record="118",
                evaluated_record="119",
                recalibrated=False,
                evaluated_candidates=[c["candidate"] for c in configs],
                secondary_audit="All three rejected development candidates are descriptive checks fixed in DEVELOPMENT.md before recording119 features; none is reselected",
                frozen_selection_sha256=hashlib.sha256(
                    (root / "results/development/selection.json").read_bytes()
                ).hexdigest(),
            ),
        )
    for row in summaries:
        row["selected"] = int(row["candidate"] == selected_id)
        row["eligible"] = (
            int(row["candidate"] == "accept_all" or row["fp"] * 20 <= row["negatives"])
            if phase == "development"
            else "not_reselected"
        )
    write_csv(output / "predictions.csv", predictions)
    write_csv(output / "metrics.csv", summaries)
    write_csv(output / "strata.csv", strata)
    write_csv(output / "sensitivity.csv", sensitivity)
    write_json(
        output / "execution.json",
        dict(
            phase=phase,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            python=sys.version.split()[0],
            candidates=executions,
            source_network=False,
            input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            limitation="Runtime is an execution observation, not a deterministic replay target or benchmark claim",
        ),
    )
    print(
        json.dumps(
            dict(
                status="PASS_ANALYSIS",
                phase=phase,
                selected=selected_id,
                configurations=len(configs),
                predictions=len(predictions),
                original_primary=[r for r in summaries if r["case"] == "original"],
            )
        )
    )


if __name__ == "__main__":
    main()
