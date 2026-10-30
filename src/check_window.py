"""Demonstrate the frozen gate; return no clinical or clean-signal judgment."""

import argparse
import csv
import json
from pathlib import Path

from analyze import flag
from features import features


def evaluate(values, config, diagnostic=False):
    b, h = features(values)
    rejected = flag(b, h, config)
    reasons = []
    if config["candidate"] == "accept_all":
        reasons.append("No candidate satisfied the development clean-window constraint")
    else:
        if b > config["B_threshold"]:
            reasons.append(
                "Baseline-block ratio exceeds this frozen candidate threshold"
            )
        if h > config["H_threshold"]:
            reasons.append("Slope-energy ratio exceeds this frozen candidate threshold")
    return dict(
        status="DEMONSTRATION_ONLY",
        rule=config["candidate"],
        diagnostic_rejected_candidate=diagnostic,
        flag=int(rejected),
        quality_judgment="unavailable",
        features=dict(B=b, H=h),
        reasons=reasons,
        scope="Offline numerical exercise; no clinical classification, alarm-suppression or device-validation instruction",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--sample-rate", type=int, required=True, choices=[360])
    parser.add_argument("--units", required=True, choices=["mV"])
    parser.add_argument(
        "--candidate",
        choices=["q090", "q095", "q099"],
        help="Inspect a rejected candidate; never a deployment selection",
    )
    args = parser.parse_args()
    try:
        if args.input.stat().st_size > 1_000_000:
            raise ValueError("Window file exceeds the exercise size bound")
        with args.input.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != ["mV"]:
                raise ValueError("Expected one column named mV")
            values = [float(row["mV"]) for row in reader]
        root = Path(__file__).resolve().parents[1]
        selection = json.loads(
            (root / "results/development/selection.json").read_text(encoding="utf-8")
        )
        config = (
            selection["selected"]
            if not args.candidate
            else next(
                c for c in selection["candidates"] if c["candidate"] == args.candidate
            )
        )
        result = evaluate(values, config, bool(args.candidate))
        print(json.dumps(result, allow_nan=False))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(
            json.dumps(
                dict(
                    status="UNAVAILABLE",
                    reason=str(error),
                    flag=None,
                    quality_judgment="unavailable",
                )
            )
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
