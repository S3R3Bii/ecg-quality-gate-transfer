"""Verify the committed pre-later manifest, ancestry and all frozen Git/file bytes."""

import hashlib, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT)

    path = "data/dependency_freeze.json"
    raw = (ROOT / path).read_bytes()
    assert raw == git("show", "HEAD:" + path)
    freeze = git("log", "--format=%H", "--", path).decode().splitlines()[-1]
    assert raw == git("show", freeze + ":" + path)
    manifest = json.loads(raw)
    dev = manifest["development_commit"]
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", dev, freeze], cwd=ROOT, check=True
    )
    assert not any(
        p.startswith("results/later/") or p.startswith("data/features_later")
        for p in git("ls-tree", "-r", "--name-only", freeze).decode().splitlines()
    )
    for item in manifest["files"]:
        data = (ROOT / item["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert data == git("show", freeze + ":" + item["path"])
    result = dict(
        status="PASS_COMMITTED_BEFORE_LATER",
        files=len(manifest["files"]),
        development_commit=dev,
        freeze_commit=freeze,
        later_exports_absent_at_freeze=True,
        recording119_features_absent_at_freeze=True,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
