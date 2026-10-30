"""Reconstruct derived features from WFDB with independent scalar arithmetic."""

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import wfdb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["development", "later"], required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.phase == "later":
        subprocess.run(
            [sys.executable, str(root / "src/freeze_proof.py")], cwd=root, check=True
        )
    subject = "118" if args.phase == "development" else "119"
    with args.input.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 648
    database = sqlite3.connect(":memory:")
    database.execute(
        "create table windows(record text, start integer, condition text, primary key(record,start))"
    )
    originals = {}
    original_hashes = {}
    checks = 0
    for row in rows:
        assert row["subject_record"] == subject
        record = row["source_record"]
        dataset = row["dataset"]
        start = int(row["start_seconds"])
        assert 0 <= start < 1800 and start % 10 == 0
        noisy = start >= 300 and ((start - 300) // 120) % 2 == 0
        if dataset == "mitdb":
            assert (
                record == subject
                and row["condition"] == "source_clean"
                and row["snr_dB"] == ""
            )
        else:
            suffixes = {
                "e24": "24",
                "e18": "18",
                "e12": "12",
                "e06": "6",
                "e00": "0",
                "e_6": "-6",
            }
            assert record[:3] == subject and record[3:] in suffixes
            assert (
                row["snr_dB"] == suffixes[record[3:]]
                and noisy
                and row["condition"] == "added_electrode_motion"
            )
        database.execute(
            "insert into windows values(?,?,?)", (record, start, row["condition"])
        )
        if record not in originals:
            folder = args.private_root / dataset
            decoded = wfdb.rdrecord(str(folder / record), physical=False)
            for ext, column in [
                ("dat", "source_signal_sha256"),
                ("hea", "source_header_sha256"),
            ]:
                path = folder / (record + "." + ext)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                assert digest == row[column]
                original_hashes[path] = digest
            originals[record] = decoded
        decoded = originals[record]
        assert decoded.sig_name[0] == row["lead"] and row["units"] == "mV"
        first, end = start * 360, (start + 10) * 360
        assert int(row["start_sample"]) == first and int(row["stop_sample"]) == end
        assert (
            hashlib.sha256(
                decoded.d_signal[first:end, 0].astype("<i4").tobytes()
            ).hexdigest()
            == row["digital_window_sha256"]
        )
        values = [
            (int(v) - decoded.baseline[0]) / decoded.adc_gain[0]
            for v in decoded.d_signal[first:end, 0]
        ]
        checks += 10
        for case in ["original", "gain_offset", "quantized_002mV"]:
            x = (
                values
                if case == "original"
                else (
                    [2 * v + 0.5 for v in values]
                    if case == "gain_offset"
                    else [0.02 * round(v / 0.02) for v in values]
                )
            )
            center = math.fsum(x) / len(x)
            variance = math.fsum((v - center) ** 2 for v in x) / len(x)
            high = (
                math.fsum((b - a) ** 2 for a, b in zip(x, x[1:]))
                / (len(x) - 1)
                / variance
            )
            block_means = [math.fsum(x[i : i + 360]) / 360 for i in range(0, 3600, 360)]
            baseline = math.fsum((v - center) ** 2 for v in block_means) / 10 / variance
            for feature, expected in [("B", baseline), ("H", high)]:
                assert math.isclose(
                    float(row[case + "_" + feature]),
                    expected,
                    rel_tol=1e-10,
                    abs_tol=1e-12,
                ), (record, start, case, feature)
                checks += 1
    assert (
        database.execute(
            'select count(*) from windows where condition="source_clean"'
        ).fetchone()[0]
        == 180
    )
    assert (
        database.execute(
            'select count(*) from windows where condition="added_electrode_motion"'
        ).fetchone()[0]
        == 468
    )
    assert (
        database.execute("select count(distinct record) from windows").fetchone()[0]
        == 7
    )
    for record in [subject + x for x in ["e24", "e18", "e12", "e06", "e00", "e_6"]]:
        assert (
            database.execute(
                "select count(*) from windows where record=?", (record,)
            ).fetchone()[0]
            == 78
        )
    checks += 9
    for path, digest in original_hashes.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        checks += 1
    receipt = dict(
        status="PASS_INDEPENDENT_WFDB_SCALAR_FEATURES_AND_SQL",
        phase=args.phase,
        subject_record=subject,
        rows=len(rows),
        numerical_features_checked=3888,
        conditions_checked=checks,
        source_files_unchanged=len(original_hashes),
        wfdb_version=wfdb.__version__,
        numpy_version=np.__version__,
        input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
        no_analysis_or_feature_helper_import=True,
    )
    assert not args.output.exists(), "Keep earlier receipts; use a new output path"
    args.output.write_bytes((json.dumps(receipt, indent=2) + "\n").encode())
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
