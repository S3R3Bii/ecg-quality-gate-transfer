"""Rebuild plot values from observations and compare actual SVG coordinates."""

import csv, hashlib, json, math, re
from fractions import Fraction as F
from pathlib import Path
from xml.etree import ElementTree as E

ROOT = Path(__file__).resolve().parents[1]
SVG = "{http://www.w3.org/2000/svg}"


def rows(name):
    with (ROOT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def vertices(node):
    path = node.find(".//" + SVG + "path")
    assert path is not None
    numbers = [
        float(x)
        for x in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", path.attrib["d"])
    ]
    assert len(numbers) % 2 == 0
    points = list(zip(numbers[::2], numbers[1::2]))
    return points[:-1] if points[0] == points[-1] else points


def main():
    predictions = {
        phase: rows("results/" + phase + "/predictions.csv")
        for phase in ["development", "later"]
    }
    features = {
        phase: [
            r
            for r in rows("data/features_" + phase + ".csv")
            if r["condition"] == "source_clean"
        ]
        for phase in ["development", "later"]
    }
    selection = json.loads(
        (ROOT / "results/development/selection.json").read_text(encoding="utf-8")
    )
    reference = next(c for c in selection["candidates"] if c["candidate"] == "q099")
    maps = json.loads((ROOT / "figures/value_map.json").read_text(encoding="utf-8"))
    vc = cc = hc = 0
    for fig in maps:
        tree = E.parse(ROOT / "figures" / (fig["figure"] + ".svg"))
        ids = {node.get("id"): node for node in tree.iter() if node.get("id")}
        areas = []
        for i, axis in enumerate(fig["axes"]):
            points = vertices(ids["data-area-" + str(i)])
            areas.append(
                (
                    min(x for x, y in points),
                    max(x for x, y in points),
                    min(y for x, y in points),
                    max(y for x, y in points),
                )
            )
        for item in fig["items"]:
            axis = fig["axes"][item["axis"]]
            xmin, xmax = axis["xlim"]
            ymin, ymax = axis["ylim"]
            kind = item["kind"]
            if kind == "false_rejections":
                group = [
                    r
                    for r in predictions[item["phase"]]
                    if r["candidate"] == item["candidate"]
                    and r["case"] == "original"
                    and r["stratum"] == "clean"
                ]
                assert len(group) == 150
                value = 100 * F(sum(int(r["flag"]) for r in group), 150)
                assert F(item["value_exact"]) == value
                j = ["q090", "q095", "q099"].index(item["candidate"])
                x = j + (-0.18 if item["phase"] == "development" else 0.18)
                assert (
                    item["x"] == x
                    and item["width"] == 0.32
                    and axis == dict(xlim=[-0.6, 2.6], ylim=[0, 62])
                )
                expected = [
                    (x - 0.16, 0),
                    (x + 0.16, 0),
                    (x + 0.16, float(value)),
                    (x - 0.16, float(value)),
                ]
                assert item["display"] == f"{float(value):.1f}%" and item[
                    "display"
                ] in "".join(tree.getroot().itertext())
                vc += 1
            elif kind == "authored_limit":
                assert F(item["value_exact"]) == 5 and axis["ylim"] == [0, 62]
                expected = [(xmin, 5), (xmax, 5)]
                vc += 1
            elif kind == "noise_detection":
                levels = ["-6", "0", "6", "12", "18", "24"]
                assert item["levels"] == levels
                values = []
                for level in levels:
                    group = [
                        r
                        for r in predictions[item["phase"]]
                        if r["candidate"] == item["candidate"]
                        and r["case"] == "original"
                        and r["stratum"] == level
                    ]
                    assert len(group) == 78
                    values.append(100 * F(sum(int(r["flag"]) for r in group), 78))
                assert list(map(F, item["values_exact"])) == values and axis == dict(
                    xlim=[-8, 26], ylim=[0, 103]
                )
                expected = [
                    (int(level), float(value)) for level, value in zip(levels, values)
                ]
                vc += 6
            elif kind == "clean_feature":
                source = sorted(
                    features[item["phase"]], key=lambda r: int(r["start_seconds"])
                )
                assert len(source) == 180
                values = [F(r["original_" + item["feature"]]) for r in source]
                assert list(map(F, item["values_exact"])) == values
                expected = [
                    (int(r["start_seconds"]) / 60, float(value))
                    for r, value in zip(source, values)
                ]
                vc += 180
            else:
                assert kind == "reference_threshold"
                value = F(str(reference[item["feature"] + "_threshold"]))
                assert F(item["value_exact"]) == value
                expected = [(xmin, float(value)), (xmax, float(value))]
                vc += 1
            if kind in ["clean_feature", "reference_threshold"]:
                feature = item["feature"]
                ymax_expected = (
                    1
                    if feature == "B"
                    else math.ceil(
                        max(
                            float(r["original_H"])
                            for group in features.values()
                            for r in group
                        )
                        * 112
                    )
                    / 100
                )
                assert axis == dict(xlim=[0, 30], ylim=[0, ymax_expected])
            actual = vertices(ids[item["id"]])
            left, right, top, bottom = areas[item["axis"]]
            converted = [
                (
                    left + (x - xmin) / (xmax - xmin) * (right - left),
                    bottom - (y - ymin) / (ymax - ymin) * (bottom - top),
                )
                for x, y in expected
            ]
            assert len(actual) == len(converted), (
                item["id"],
                len(actual),
                len(converted),
            )
            for a, b in zip(actual, converted):
                assert max(abs(x - y) for x, y in zip(a, b)) < 0.00002, (
                    item["id"],
                    a,
                    b,
                )
                cc += 2
        for name, digest in fig["files"].items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
            hc += 1
        image = ROOT / "paper/images" / (fig["figure"] + ".pdf")
        assert (
            image.read_bytes()
            == (ROOT / "figures" / (fig["figure"] + ".pdf")).read_bytes()
        )
    result = dict(
        status="PASS_SOURCE_VALUES_AND_ACTUAL_SVG_GEOMETRY",
        figures=3,
        value_checks=vc,
        coordinate_checks=cc,
        export_hash_checks=hc,
    )
    (ROOT / "figures/verification.json").write_bytes(
        (json.dumps(result, indent=2) + "\n").encode()
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
