import copy
import csv
import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analyze import choose, flag, load_input, nearest_rank
from check_window import evaluate
from features import features, transformed
from source_reader import decode, noise_at


class SignalChecks(unittest.TestCase):
    def test_packed_signed_values(self):
        values = [(-2047, -1), (0, 2047), (1024, -1024)]
        packed = bytearray()
        for a, b in values:
            a, b = a % 4096, b % 4096
            packed.extend([a & 255, ((a >> 8) & 15) | ((b >> 8) << 4), b & 255])
        self.assertEqual(
            decode(bytes(packed), "212", 3).tolist(), [list(v) for v in values]
        )

    def test_little_endian_signed_values(self):
        data = struct.pack("<hhhh", -32767, 32767, -1, 1024)
        self.assertEqual(decode(data, "16", 2).tolist(), [[-32767, 32767], [-1, 1024]])

    def test_missing_packed_sentinel(self):
        with self.assertRaises(ValueError):
            decode(bytes([0, 8, 0]), "212", 1)

    def test_missing_16bit_sentinel(self):
        with self.assertRaises(ValueError):
            decode(struct.pack("<hh", -32768, 0), "16", 1)

    def test_truncated_packed_source(self):
        with self.assertRaises(ValueError):
            decode(bytes([0, 0]), "212", 1)

    def test_truncated_16bit_source(self):
        with self.assertRaises(ValueError):
            decode(bytes([0, 0]), "16", 1)

    def test_unknown_encoding(self):
        with self.assertRaises(ValueError):
            decode(bytes([0, 0]), "80", 1)

    def test_schedule_transitions(self):
        for second, expected in [
            (299, False),
            (300, True),
            (419, True),
            (420, False),
            (539, False),
            (540, True),
            (1739, False),
            (1740, True),
            (1799, True),
        ]:
            with self.subTest(second=second):
                self.assertEqual(noise_at(second), expected)

    def test_complete_noisy_window_count(self):
        self.assertEqual(sum(noise_at(t) for t in range(0, 1800, 10)), 78)

    def test_analytical_alternating_signal(self):
        b, h = features([1.0, -1.0] * 1800)
        self.assertEqual(b, 0)
        self.assertEqual(h, 4)

    def test_analytical_block_signal(self):
        x = np.repeat(np.array([-1.0, 1.0] * 5), 360)
        b, h = features(x)
        self.assertEqual(b, 1)
        self.assertAlmostEqual(h, 36 / 3599)

    def test_gain_offset_invariance(self):
        x = np.arange(3600, dtype=float) % 31 - 15
        self.assertTrue(
            np.allclose(features(x), features(2 * x + 0.5), rtol=1e-10, atol=1e-12)
        )

    def test_flat_unavailable(self):
        with self.assertRaises(ValueError):
            features([3.0] * 3600)

    def test_nonfinite_unavailable(self):
        for value in [float("nan"), float("inf"), float("-inf")]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                features([0.0] * 3599 + [value])

    def test_wrong_window_length(self):
        for length in [0, 3599, 3601]:
            with self.subTest(length=length), self.assertRaises(ValueError):
                features([1.0, -1.0] * (length // 2) + ([1.0] if length % 2 else []))

    def test_unknown_transform(self):
        with self.assertRaises(ValueError):
            transformed([0.0], "resampled")

    def test_nearest_rank_not_interpolation(self):
        self.assertEqual(nearest_rank([4, 1, 3, 2], 0.5), 2)
        self.assertEqual(nearest_rank([1, 1, 2, 2], 0.99), 2)

    def test_quantile_guard(self):
        for values, p in [([], 0.9), ([1], 0), ([1], 1.1), ([float("nan")], 0.9)]:
            with self.subTest(p=p), self.assertRaises(ValueError):
                nearest_rank(values, p)

    def test_strict_inference_boundary(self):
        config = dict(candidate="q099", B_threshold=0.4, H_threshold=0.2)
        self.assertFalse(flag(0.4, 0.2, config))
        self.assertTrue(flag(0.400001, 0.2, config))
        self.assertTrue(flag(0.4, 0.200001, config))

    def test_invalid_features_do_not_become_acceptance(self):
        for b, h in [(-1, 0.1), (0.1, -1), (float("nan"), 0.1), (0.1, float("inf"))]:
            with self.subTest(b=b), self.assertRaises(ValueError):
                flag(b, h, dict(candidate="accept_all"))

    def test_selection_constraint_and_tie_break(self):
        rows = [
            dict(candidate="q090", quantile=0.9, tp=90, fp=6, negatives=100),
            dict(candidate="q095", quantile=0.95, tp=80, fp=5, negatives=100),
            dict(candidate="q099", quantile=0.99, tp=80, fp=3, negatives=100),
        ]
        self.assertEqual(choose(rows), "q099")

    def test_selection_recall_objective(self):
        rows = [
            dict(candidate="q095", quantile=0.95, tp=81, fp=5, negatives=100),
            dict(candidate="q099", quantile=0.99, tp=80, fp=0, negatives=100),
        ]
        self.assertEqual(choose(rows), "q095")

    def test_selection_fallback(self):
        self.assertEqual(
            choose(
                [dict(candidate="q099", quantile=0.99, tp=100, fp=6, negatives=100)]
            ),
            "accept_all",
        )

    def test_complete_public_keys(self):
        self.assertEqual(
            len(load_input(ROOT / "data/features_development.csv", "118")), 648
        )

    def test_wrong_keys_and_duplicate_controls(self):
        with (ROOT / "data/features_development.csv").open(
            newline="", encoding="utf-8"
        ) as source:
            original = list(csv.DictReader(source))
        for defect in ["duplicate", "subject", "snr", "missing"]:
            rows = copy.deepcopy(original)
            if defect == "duplicate":
                rows.append(rows[0])
            elif defect == "subject":
                rows[0]["subject_record"] = "119"
            elif defect == "snr":
                rows[-1]["snr_dB"] = "24"
            else:
                rows.pop()
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "input.csv"
                with path.open("w", newline="", encoding="utf-8") as output:
                    writer = csv.DictWriter(output, list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
                with self.subTest(defect=defect), self.assertRaises(AssertionError):
                    load_input(path, "118")

    def test_fallback_never_reports_clean_quality(self):
        result = evaluate([1.0, -1.0] * 1800, dict(candidate="accept_all"))
        self.assertEqual(result["flag"], 0)
        self.assertEqual(result["quality_judgment"], "unavailable")
        self.assertEqual(result["status"], "DEMONSTRATION_ONLY")

    def test_cli_authored_signal_and_flat_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "authored.csv"
            for flat, expected in [(False, 0), (True, 2)]:
                with path.open("w", newline="", encoding="utf-8") as output:
                    writer = csv.writer(output, lineterminator="\n")
                    writer.writerow(["mV"])
                    writer.writerows(
                        [
                            [0.0 if flat else (-1.0 if i % 2 else 1.0)]
                            for i in range(3600)
                        ]
                    )
                run = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "src/check_window.py"),
                        str(path),
                        "--sample-rate",
                        "360",
                        "--units",
                        "mV",
                    ],
                    capture_output=True,
                    text=True,
                )
                with self.subTest(flat=flat):
                    self.assertEqual(run.returncode, expected, run.stderr)
                    result = json.loads(run.stdout)
                    self.assertEqual(
                        result["status"],
                        "UNAVAILABLE" if flat else "DEMONSTRATION_ONLY",
                    )


if __name__ == "__main__":
    unittest.main()
