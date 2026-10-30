"""Recompute each measured display and check the saved six-page manuscript."""

import ast, csv, hashlib, json, re, unicodedata
from fractions import Fraction as F
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def rows(name):
    with (ROOT / name).open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def main():
    pdf = ROOT / "paper/manuscript.pdf"
    reader = PdfReader(pdf)
    assert len(reader.pages) == 6, len(reader.pages)
    pages = [
        unicodedata.normalize("NFKC", page.extract_text()) for page in reader.pages
    ]
    assert all(len(page) > 1000 for page in pages)
    ledger = json.loads(
        (ROOT / "paper/display_ledger.json").read_text(encoding="utf-8")
    )
    checks = 2
    for item in ledger:
        q = item["query"]
        kind = q["kind"]
        if kind == "metric":
            value = F(
                next(
                    r
                    for r in rows("results/" + q["phase"] + "/metrics.csv")
                    if r["candidate"] == q["candidate"] and r["case"] == "original"
                )[q["field"]]
            )
        elif kind == "json":
            value = F(
                str(
                    json.loads((ROOT / q["path"]).read_text(encoding="utf-8"))[q["key"]]
                )
            )
        elif kind == "freeze_count":
            value = F(
                len(
                    json.loads(
                        (ROOT / "data/dependency_freeze.json").read_text(
                            encoding="utf-8"
                        )
                    )["files"]
                )
            )
        elif kind == "threshold":
            value = F(
                str(
                    next(
                        c
                        for c in json.loads(
                            (ROOT / "results/development/selection.json").read_text(
                                encoding="utf-8"
                            )
                        )["candidates"]
                        if c["candidate"] == q["candidate"]
                    )[q["field"]]
                )
            )
        elif kind == "flip_total":
            value = F(
                sum(
                    int(r["decision_flips"])
                    for r in rows("results/" + q["phase"] + "/sensitivity.csv")
                    if r["candidate"] == q["candidate"] and r["case"] == q["case"]
                )
            )
        else:
            assert kind == "input_count"
            data = rows("data/features_" + q["phase"] + ".csv")
            group = q["group"]
            if group == "all":
                value = len(data)
            elif group == "clean":
                value = sum(r["condition"] == "source_clean" for r in data)
            elif group == "calibration":
                value = sum(
                    r["condition"] == "source_clean" and int(r["start_seconds"]) < 300
                    for r in data
                )
            elif group == "controls":
                value = sum(
                    r["condition"] == "source_clean" and int(r["start_seconds"]) >= 300
                    for r in data
                )
            else:
                assert group == "one_noise_level"
                value = sum(r["snr_dB"] == "6" for r in data)
            value = F(value)
        value *= item["multiplier"]
        expected = (
            format(int(value), item["format"])
            if item["format"] == ",d"
            else format(float(value), item["format"])
        )
        assert expected == item["text"]
        assert expected in pages[item["page"]], item
        checks += 2
    text = re.sub(r"\s+", " ", re.sub(r"-[ \t]*\n[ \t]*", "-", " ".join(pages)))
    for phrase in [
        "no quality gate is eligible",
        "accept-all fallback",
        "no later reselection",
        "no claimed quality-detection gain",
        "not clinically acceptable negatives",
        "not a measured device change",
        "No downstream clinical prediction",
        "not peer reviewed",
        "formal-publication projects",
        "clinical quality judgment is unavailable",
    ]:
        assert phrase in text, phrase
        checks += 1
    test_methods = sum(
        1
        for p in (ROOT / "tests").glob("test_*.py")
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    )
    assert (
        test_methods
        == json.loads(
            (ROOT / "results/development/prefreeze_check.json").read_text(
                encoding="utf-8"
            )
        )["fixtures"]
        == 27
    )
    checks += 1
    buildpath = ROOT / "paper/build_receipt.json"
    if buildpath.exists():
        build = json.loads(buildpath.read_text(encoding="utf-8"))
        assert build["status"] == "PASS_COMPILE_AND_SIX_PAGE_VISUAL_REVIEW"
        for name, digest in build["artifact_sha256"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
            checks += 1
        warnings = build["layout_warnings"]
        assert not warnings
        if (ROOT / "paper/main.log").exists():
            assert (
                hashlib.sha256((ROOT / "paper/main.log").read_bytes()).hexdigest()
                == build["private_log_sha256"]
            )
    else:
        log = (ROOT / "paper/main.log").read_text(encoding="utf-8", errors="replace")
        warnings = [
            line
            for line in log.splitlines()
            if any(
                w in line
                for w in ["Overfull", "Underfull", "Missing character", "Unused global"]
            )
        ]
        assert not warnings, warnings
    checks += 1
    result = dict(
        status="PASS_SOURCE_BOUND_DISPLAYS_AND_PDF_TEXT",
        pages=6,
        displays=len(ledger),
        checks=checks,
        pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
        layout_warnings=warnings,
        visual_inspection="Separate recorded page inspection required",
    )
    (ROOT / "paper/verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
