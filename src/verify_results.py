"""Independent key, threshold, selection, confusion and sensitivity reconstruction."""

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from fractions import Fraction
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["development", "later"], required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--results", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    phase = args.phase
    subject = "118" if phase == "development" else "119"
    source = args.input or root / ("data/features_" + phase + ".csv")
    folder = args.results or root / ("results/" + phase)
    receipt_path = args.receipt or folder / "verification.json"

    def csv_rows(name):
        with (folder / name).open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))

    with source.open(newline="", encoding="utf-8") as stream:
        raw = list(csv.DictReader(stream))
    inputs = {(r["source_record"], int(r["start_seconds"])): r for r in raw}
    noisy_times = {t for t in range(300, 1800, 10) if ((t - 300) // 120) % 2 == 0}
    expected_inputs = {(subject, t) for t in range(0, 1800, 10)} | {
        (subject + s, t)
        for s in ["e24", "e18", "e12", "e06", "e00", "e_6"]
        for t in noisy_times
    }
    assert len(raw) == len(inputs) == 648 and set(inputs) == expected_inputs
    assert {r["subject_record"] for r in raw} == {subject}
    selection = (
        json.loads(
            (root / "results/development/selection.json").read_text(encoding="utf-8")
        )
        if phase == "later"
        else json.loads((folder / "selection.json").read_text(encoding="utf-8"))
    )
    configs = {c["candidate"]: c for c in selection["candidates"]}
    assert set(configs) == {"accept_all", "q090", "q095", "q099"}
    checks = 3
    calibration_input = (
        source if phase == "development" else root / "data/features_development.csv"
    )
    with calibration_input.open(newline="", encoding="utf-8") as stream:
        calibration = [
            r
            for r in csv.DictReader(stream)
            if r["source_record"] == "118" and int(r["start_seconds"]) < 300
        ]
    assert len(calibration) == 30
    for candidate, rank, p in [
        ("q090", 27, 0.9),
        ("q095", 29, 0.95),
        ("q099", 30, 0.99),
    ]:
        assert configs[candidate]["quantile"] == p
        for name in ["B", "H"]:
            expected = sorted(float(r["original_" + name]) for r in calibration)[
                rank - 1
            ]
            assert configs[candidate][name + "_threshold"] == expected
            checks += 1
    assert configs["accept_all"] == dict(
        candidate="accept_all", quantile=None, B_threshold=None, H_threshold=None
    )
    predictions = csv_rows("predictions.csv")
    assert len(predictions) == 4 * 3 * 618
    database = sqlite3.connect(":memory:")
    database.execute(
        "create table p(candidate text, variant text, record text, start integer, stratum text, flag integer, primary key(candidate,variant,record,start))"
    )
    observed = set()
    for row in predictions:
        candidate, case, record, start = (
            row["candidate"],
            row["case"],
            row["source_record"],
            int(row["start_seconds"]),
        )
        assert (
            candidate in configs
            and case in ["original", "gain_offset", "quantized_002mV"]
            and start >= 300
        )
        source_row = inputs[(record, start)]
        assert row["subject_record"] == subject
        stratum = (
            "clean"
            if source_row["condition"] == "source_clean"
            else source_row["snr_dB"]
        )
        assert row["stratum"] == stratum
        b, h = float(source_row[case + "_B"]), float(source_row[case + "_H"])
        assert float(row["B"]) == b and float(row["H"]) == h
        config = configs[candidate]
        expected_flag = (
            0
            if candidate == "accept_all"
            else int(b > config["B_threshold"] or h > config["H_threshold"])
        )
        assert int(row["flag"]) == expected_flag
        key = (candidate, case, record, start)
        assert key not in observed
        observed.add(key)
        database.execute(
            "insert into p values(?,?,?,?,?,?)",
            (candidate, case, record, start, stratum, expected_flag),
        )
        checks += 6
    expected_scored = {(record, t) for record, t in expected_inputs if t >= 300}
    assert observed == {
        (candidate, case, record, t)
        for candidate in configs
        for case in ["original", "gain_offset", "quantized_002mV"]
        for record, t in expected_scored
    }

    def count(candidate, case, clause="1=1"):
        return database.execute(
            "select count(*),coalesce(sum(flag),0) from p where candidate=? and variant=? and "
            + clause,
            (candidate, case),
        ).fetchone()

    metrics = csv_rows("metrics.csv")
    assert len(metrics) == 12
    metric_keys = set()
    originals = {}
    for row in metrics:
        candidate, case = row["candidate"], row["case"]
        assert (candidate, case) not in metric_keys
        metric_keys.add((candidate, case))
        negatives, fp = count(candidate, case, "stratum='clean'")
        positives, tp = count(candidate, case, "stratum in ('-6','0','6')")
        assert (negatives, positives) == (150, 234)
        tn, fn = negatives - fp, positives - tp
        integers = dict(n=384, positives=234, negatives=150, tp=tp, fn=fn, fp=fp, tn=tn)
        ratios = dict(
            prevalence=Fraction(234, 384),
            precision=Fraction(tp, tp + fp) if tp + fp else None,
            recall=Fraction(tp, 234),
            specificity=Fraction(tn, 150),
            false_rejection_rate=Fraction(fp, 150),
            balanced_accuracy=(Fraction(tp, 234) + Fraction(tn, 150)) / 2,
        )
        for name, value in integers.items():
            assert int(row[name]) == value
            checks += 1
        for name, value in ratios.items():
            assert (
                row[name] == ""
                if value is None
                else math.isclose(
                    float(row[name]), float(value), rel_tol=1e-10, abs_tol=1e-12
                )
            )
            checks += 1
        assert int(row["selected"]) == int(
            candidate == selection["selected"]["candidate"]
        )
        assert (
            row["eligible"]
            == str(int(candidate == "accept_all" or fp * 20 <= negatives))
            if phase == "development"
            else row["eligible"] == "not_reselected"
        )
        if case == "original":
            originals[candidate] = dict(tp=tp, fp=fp)
    if phase == "development":
        eligible = [
            name
            for name in ["q090", "q095", "q099"]
            if originals[name]["fp"] * 20 <= 150
        ]
        best = (
            sorted(
                eligible,
                key=lambda name: (originals[name]["tp"], configs[name]["quantile"]),
                reverse=True,
            )[0]
            if eligible
            else "accept_all"
        )
        assert selection["selected"] == configs[best]
        assert (
            selection["calibration_record"] == selection["validation_record"] == "118"
        )
        assert selection["search_complete"] is True
        checks += 3
    else:
        used = json.loads(
            (folder / "frozen_selection_used.json").read_text(encoding="utf-8")
        )
        assert (
            used["selected"] == selection["selected"] and used["recalibrated"] is False
        )
        assert used["calibrated_record"] == "118" and used["evaluated_record"] == "119"
        assert set(used["evaluated_candidates"]) == set(configs)
        assert (
            used["frozen_selection_sha256"]
            == hashlib.sha256(
                (root / "results/development/selection.json").read_bytes()
            ).hexdigest()
        )
        checks += 4
    strata = csv_rows("strata.csv")
    assert (
        len(strata) == 84
        and len({(r["candidate"], r["case"], r["stratum"]) for r in strata}) == 84
    )
    for row in strata:
        n, flagged = database.execute(
            "select count(*),sum(flag) from p where candidate=? and variant=? and stratum=?",
            (row["candidate"], row["case"], row["stratum"]),
        ).fetchone()
        assert int(row["n"]) == n and int(row["flagged"]) == flagged
        assert math.isclose(
            float(row["flag_fraction"]),
            float(Fraction(flagged, n)),
            rel_tol=1e-10,
            abs_tol=1e-12,
        )
        checks += 3
    sensitivity = csv_rows("sensitivity.csv")
    assert (
        len(sensitivity) == 56
        and len({(r["candidate"], r["case"], r["stratum"]) for r in sensitivity}) == 56
    )
    for row in sensitivity:
        n, flips = database.execute(
            "select count(*),sum(a.flag!=b.flag) from p a join p b on a.candidate=b.candidate and a.record=b.record and a.start=b.start where a.candidate=? and a.variant=? and b.variant='original' and a.stratum=?",
            (row["candidate"], row["case"], row["stratum"]),
        ).fetchone()
        assert int(row["n"]) == n and int(row["decision_flips"]) == flips
        if row["case"] == "gain_offset":
            assert flips == 0
        checks += 2
    execution = json.loads((folder / "execution.json").read_text(encoding="utf-8"))
    assert (
        execution["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        and execution["source_network"] is False
    )
    assert {c["candidate"] for c in execution["candidates"]} == set(configs)
    assert all(
        c["status"] == "PASS"
        and c["wall_seconds"] >= 0
        and c["seed"] == "not_applicable_no_randomness"
        for c in execution["candidates"]
    )
    receipt = dict(
        status="PASS_INDEPENDENT_THRESHOLDS_METRICS_AND_SQL",
        phase=phase,
        input_rows=648,
        predictions_checked=len(predictions),
        conditions_checked=checks,
        selection=selection["selected"]["candidate"],
        candidate_metrics=12,
        noise_clean_strata=84,
        sensitivity_groups=56,
        input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        output_sha256={
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in [
                "predictions.csv",
                "metrics.csv",
                "strata.csv",
                "sensitivity.csv",
            ]
        },
        no_analysis_helper_import=True,
        population_inference="unavailable_one_later_source_recording",
    )
    assert (
        not receipt_path.exists()
    ), "Retain prior receipts; choose a separate output path"
    receipt_path.write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
