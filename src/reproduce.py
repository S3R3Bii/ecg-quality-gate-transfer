"""Replay the public derived inputs in a full-history clone, preserving originals."""

import csv, hashlib, json, platform, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    originals = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in ROOT.rglob("*")
        if p.is_file()
        and not any(part in p.parts for part in [".git", "__pycache__", "rendered"])
        and p.name != "reproduction.json"
        and p.suffix not in [".log", ".aux", ".out", ".xdv"]
    }
    fields = documents = 0
    executions = {}
    with tempfile.TemporaryDirectory(prefix="ecg-quality-replay-") as temp:
        folder = Path(temp)
        clone = folder / "study"
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(clone)],
            check=True,
        )

        def run(*args):
            result = subprocess.run(
                [sys.executable, *args], cwd=clone, capture_output=True, text=True
            )
            if result.returncode:
                raise RuntimeError(
                    str(args)
                    + "\n"
                    + result.stdout[-1500:]
                    + "\n"
                    + result.stderr[-1500:]
                )
            return result.stdout

        proof = json.loads(run("src/freeze_proof.py"))
        assert proof["files"] == 36 and proof["recording119_features_absent_at_freeze"]
        run("-m", "unittest", "discover", "-s", "tests")
        for phase in ["development", "later"]:
            output = folder / phase
            run("src/analyze.py", "--phase", phase, "--output", str(output))
            run("src/verify_results.py", "--phase", phase, "--results", str(output))
            for name in [
                "predictions.csv",
                "metrics.csv",
                "strata.csv",
                "sensitivity.csv",
            ]:
                with (ROOT / "results" / phase / name).open(
                    newline="", encoding="utf-8"
                ) as a, (output / name).open(newline="", encoding="utf-8") as b:
                    for x, y in zip(csv.reader(a), csv.reader(b), strict=True):
                        assert x == y, (phase, name)
                        fields += len(x)
            name = (
                "selection.json"
                if phase == "development"
                else "frozen_selection_used.json"
            )
            for name in [name, "verification.json"]:
                assert json.loads(
                    (ROOT / "results" / phase / name).read_text(encoding="utf-8")
                ) == json.loads((output / name).read_text(encoding="utf-8")), (
                    phase,
                    name,
                )
                documents += 1
            executions[phase] = json.loads(
                (output / "execution.json").read_text(encoding="utf-8")
            )
        for name, options in [
            ("fallback", []),
            ("rejected_q099", ["--candidate", "q099"]),
        ]:
            actual = json.loads(
                run(
                    "src/check_window.py",
                    "examples/authored_window.csv",
                    "--sample-rate",
                    "360",
                    "--units",
                    "mV",
                    *options
                )
            )
            assert actual == json.loads(
                (ROOT / "examples" / (name + ".json")).read_text(encoding="utf-8")
            )
    assert {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in originals
    } == originals
    result = dict(
        status="PASS",
        python=platform.python_version(),
        csv_fields_compared=fields,
        json_documents_compared=documents,
        fixtures=27,
        frozen_dependencies=36,
        source_network=False,
        original_files_unchanged=True,
        full_history_clone=True,
        cli_examples=2,
        raw_waveforms_reextracted=False,
        replay_executions=executions,
    )
    (ROOT / "results/reproduction.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps({k: v for k, v in result.items() if k != "replay_executions"}))


if __name__ == "__main__":
    main()
