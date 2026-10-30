"""Create a minimal derived projection; preserve all waveform originals privately."""

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np

from features import features, transformed
from source_reader import noise_at, read, sha256

CASES = ["original", "gain_offset", "quantized_002mV"]
FIELDS = [
    "subject_record",
    "source_record",
    "dataset",
    "condition",
    "snr_dB",
    "start_seconds",
    "start_sample",
    "stop_sample",
    "lead",
    "units",
    "source_header_sha256",
    "source_signal_sha256",
    "digital_window_sha256",
] + [case + "_" + feature for case in CASES for feature in ["B", "H"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["development", "later"], required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.phase == "later":
        subprocess.run(
            [sys.executable, str(root / "src/freeze_proof.py")], cwd=root, check=True
        )
    assert (
        not args.output.exists()
    ), "Keep prior derived projections; use a separate output path"
    subject = "118" if args.phase == "development" else "119"
    qualification = json.loads(
        (root / "data/original_verification.json").read_text(encoding="utf-8")
    )
    assert qualification["status"] == "PASS_ORIGINALS_AND_INDEPENDENT_WFDB"
    qualified = {row["record"]: row for row in qualification["native_records"]}
    record_list = [("mitdb", subject, "")] + [
        ("nstdb", subject + suffix, str(snr))
        for suffix, snr in [
            ("e24", 24),
            ("e18", 18),
            ("e12", 12),
            ("e06", 6),
            ("e00", 0),
            ("e_6", -6),
        ]
    ]
    rows = []
    for dataset, record, snr in record_list:
        folder = args.private_root / dataset
        assert sha256(folder / (record + ".hea")) == qualified[record]["header_sha256"]
        assert sha256(folder / (record + ".dat")) == qualified[record]["signal_sha256"]
        meta, digital, physical = read(folder, record)
        for start in range(0, 1800, 10):
            if dataset == "nstdb" and not noise_at(start):
                continue
            first, end = start * 360, (start + 10) * 360
            x = physical[first:end, 0]
            row = dict(
                subject_record=subject,
                source_record=record,
                dataset=dataset,
                condition=(
                    "source_clean" if dataset == "mitdb" else "added_electrode_motion"
                ),
                snr_dB=snr,
                start_seconds=start,
                start_sample=first,
                stop_sample=end,
                lead=meta["signals"][0]["label"],
                units="mV",
                source_header_sha256=qualified[record]["header_sha256"],
                source_signal_sha256=qualified[record]["signal_sha256"],
                digital_window_sha256=hashlib.sha256(
                    digital[first:end, 0].astype("<i4").tobytes()
                ).hexdigest(),
            )
            for case in CASES:
                b, h = features(transformed(x, case))
                row[case + "_B"] = format(b, ".17g")
                row[case + "_H"] = format(h, ".17g")
            for feature in ["B", "H"]:
                assert math.isclose(
                    float(row["original_" + feature]),
                    float(row["gain_offset_" + feature]),
                    abs_tol=1e-12,
                    rel_tol=1e-10,
                )
            rows.append(row)
        assert sha256(folder / (record + ".dat")) == qualified[record]["signal_sha256"]
    assert len(rows) == 648
    assert len({(row["source_record"], row["start_seconds"]) for row in rows}) == 648
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(
        json.dumps(
            dict(
                status="PASS_FEATURE_EXTRACTION",
                phase=args.phase,
                recording=subject,
                rows=len(rows),
                numeric_features=len(rows) * 6,
                waveform_samples_public=0,
                feature_projection_sha256=sha256(args.output),
            )
        )
    )


if __name__ == "__main__":
    main()
