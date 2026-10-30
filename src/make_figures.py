"""Show the failed constraint, noise tradeoff and source-clean feature drift."""

import csv, hashlib, json, math, shutil
from fractions import Fraction as F
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
COLORS = ["#235d72", "#b65f27", "#667782"]
CANDIDATES = ["q090", "q095", "q099"]
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "svg.fonttype": "none",
        "path.simplify": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "text.color": "#233b49",
        "axes.labelcolor": "#233b49",
        "axes.edgecolor": "#a5b2b7",
        "savefig.facecolor": "white",
    }
)


def rows(name):
    with (ROOT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def finish(fig, axes, name, items):
    for i, ax in enumerate(axes):
        ax.patch.set_gid("data-area-" + str(i))
    for item in items:
        item.pop("artist").set_gid(item["id"])
    files = []
    for ext in ["pdf", "svg", "png"]:
        p = ROOT / "figures" / (name + "." + ext)
        fig.savefig(
            p,
            dpi=155 if ext == "png" else 100,
            metadata={"Date": None} if ext == "svg" else None,
        )
        if ext == "svg":
            p.write_bytes(
                (
                    "\n".join(
                        line.rstrip()
                        for line in p.read_text(encoding="utf-8").splitlines()
                    )
                    + "\n"
                ).encode()
            )
        files.append(p)
    shutil.copyfile(
        ROOT / "figures" / (name + ".pdf"), ROOT / "paper/images" / (name + ".pdf")
    )
    result = dict(
        figure=name,
        axes=[dict(xlim=list(ax.get_xlim()), ylim=list(ax.get_ylim())) for ax in axes],
        items=items,
        files={
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
    )
    plt.close(fig)
    return result


def footer(fig, text):
    fig.text(0.09, 0.025, text, fontsize=8, color="#536873")


def main():
    maps = []
    data = {
        phase: rows("results/" + phase + "/metrics.csv")
        for phase in ["development", "later"]
    }
    fig, ax = plt.subplots(figsize=(8.8, 4.5))
    fig.subplots_adjust(left=0.09, right=0.97, bottom=0.19, top=0.76)
    items = []
    for i, phase in enumerate(["development", "later"]):
        for j, candidate in enumerate(CANDIDATES):
            row = next(
                r
                for r in data[phase]
                if r["candidate"] == candidate and r["case"] == "original"
            )
            value = 100 * F(int(row["fp"]), int(row["negatives"]))
            x = j + (-0.18 if i == 0 else 0.18)
            bar = ax.bar(
                x,
                float(value),
                width=0.32,
                color=COLORS[i],
                label=(
                    ("Development: 118" if i == 0 else "Separate recording: 119")
                    if j == 0
                    else None
                ),
            )[0]
            text = f"{float(value):.1f}%"
            ax.text(x, float(value) + 1, text, ha="center", fontsize=9)
            items.append(
                dict(
                    artist=bar,
                    id=f"rejection-{phase}-{candidate}",
                    axis=0,
                    kind="false_rejections",
                    phase=phase,
                    candidate=candidate,
                    x=x,
                    width=0.32,
                    value_exact=str(value),
                    display=text,
                )
            )
    line = ax.axhline(
        5, color="#6c3441", ls="--", lw=1.1, label="Authored rejection limit: 5%"
    )
    items.append(
        dict(
            artist=line,
            id="authored-limit",
            axis=0,
            kind="authored_limit",
            value_exact="5",
        )
    )
    ax.set(
        xticks=range(3),
        xticklabels=["0.90 quantile", "0.95 quantile", "0.99 quantile"],
        xlim=(-0.6, 2.6),
        ylim=(0, 62),
        ylabel="Source-clean windows flagged (%)",
        xlabel="Candidate thresholds calibrated on the first five minutes of recording 118",
    )
    ax.legend(frameon=False, loc="upper right")
    ax.yaxis.grid(alpha=0.15)
    ax.set_axisbelow(True)
    fig.suptitle(
        "Every candidate exceeds the clean-window rejection limit",
        x=0.09,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.09,
        0.855,
        "150 source-clean windows per recording; recording 119 is a secondary audit, without reselection.",
        fontsize=9,
    )
    footer(
        fig,
        "Derived from PhysioNet MIT-BIH/NSTDB 1.0.0 (ODC-By 1.0). Finite benchmark windows; no population interval.",
    )
    maps.append(finish(fig, [ax], "clean_window_rejections", items))

    fig, axes = plt.subplots(1, 2, figsize=(9.8, 4.6))
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.20, top=0.68, wspace=0.18)
    items = []
    levels = ["-6", "0", "6", "12", "18", "24"]
    for i, phase in enumerate(["development", "later"]):
        table = rows("results/" + phase + "/strata.csv")
        ax = axes[i]
        for j, candidate in enumerate(CANDIDATES):
            values = [
                100 * F(int(r["flagged"]), int(r["n"]))
                for level in levels
                for r in table
                if r["candidate"] == candidate
                and r["case"] == "original"
                and r["stratum"] == level
            ]
            (line,) = ax.plot(
                list(map(int, levels)),
                list(map(float, values)),
                color=COLORS[j],
                marker="o",
                ms=4,
                lw=1.3,
                label=["0.90 quantile", "0.95 quantile", "0.99 quantile"][j],
            )
            items.append(
                dict(
                    artist=line,
                    id=f"detection-{phase}-{candidate}",
                    axis=i,
                    kind="noise_detection",
                    phase=phase,
                    candidate=candidate,
                    levels=levels,
                    values_exact=list(map(str, values)),
                )
            )
        ax.set(
            xlim=(-8, 26),
            ylim=(0, 103),
            xticks=list(map(int, levels)),
            xlabel="Publisher noise level (dB)",
            title="Development: 118" if i == 0 else "Secondary audit: 119",
        )
        ax.grid(alpha=0.15)
        if i == 0:
            ax.set_ylabel("Added-noise windows flagged (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.54, 0.86),
        ncol=3,
        frameon=False,
    )
    fig.suptitle(
        "Noise detection does not make the rejected rules eligible",
        x=0.08,
        ha="left",
        fontweight="bold",
    )
    footer(
        fig,
        "78 windows per noise level/recording. Shared ECG and noise are dependent. These are not clinical quality labels.",
    )
    maps.append(finish(fig, list(axes), "noise_detection_tradeoff", items))

    fig, axes = plt.subplots(2, 1, figsize=(9.2, 6.0))
    fig.subplots_adjust(left=0.10, right=0.97, bottom=0.15, top=0.78, hspace=0.36)
    inputs = {
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
    items = []
    for i, feature in enumerate(["B", "H"]):
        ax = axes[i]
        ax.axvspan(0, 5, color="#d9e6ec", alpha=0.65)
        for j, phase in enumerate(["development", "later"]):
            source = sorted(inputs[phase], key=lambda r: int(r["start_seconds"]))
            values = [F(r["original_" + feature]) for r in source]
            (line,) = ax.plot(
                [int(r["start_seconds"]) / 60 for r in source],
                list(map(float, values)),
                color=COLORS[j],
                lw=0.9,
                label="Source-clean 118" if j == 0 else "Source-clean 119",
            )
            items.append(
                dict(
                    artist=line,
                    id=f"feature-{feature}-{phase}",
                    axis=i,
                    kind="clean_feature",
                    phase=phase,
                    feature=feature,
                    values_exact=list(map(str, values)),
                )
            )
        threshold = F(str(reference[feature + "_threshold"]))
        line = ax.axhline(
            float(threshold),
            color="#667782",
            ls="--",
            lw=1,
            label="Rejected 0.99 threshold",
        )
        items.append(
            dict(
                artist=line,
                id=f"reference-{feature}",
                axis=i,
                kind="reference_threshold",
                feature=feature,
                value_exact=str(threshold),
            )
        )
        ymax = (
            1
            if feature == "B"
            else math.ceil(
                max(float(r["original_H"]) for group in inputs.values() for r in group)
                * 112
            )
            / 100
        )
        ax.set(
            xlim=(0, 30),
            ylim=(0, ymax),
            ylabel=(
                "Block-mean ratio (B)" if feature == "B" else "Slope-energy ratio (H)"
            ),
        )
        ax.grid(alpha=0.15)
    axes[-1].set_xlabel(
        "Elapsed time (minutes); only the first five minutes of 118 calibrate the rules"
    )
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.54, 0.88),
        ncol=3,
        frameon=False,
        fontsize=9,
    )
    fig.suptitle(
        "Source-clean feature values change after short calibration",
        x=0.10,
        ha="left",
        fontweight="bold",
    )
    fig.text(
        0.10,
        0.915,
        "Shading marks the 118 calibration interval; 119 is never recalibrated. Thresholds shown are rejected references.",
        fontsize=9,
    )
    footer(
        fig,
        "180 derived source-clean windows per recording. Signal 0/MLII, 10 seconds each. Raw waveforms are not shown.",
    )
    maps.append(finish(fig, list(axes), "source_clean_feature_drift", items))
    (ROOT / "figures/value_map.json").write_bytes(
        (json.dumps(maps, indent=2) + "\n").encode()
    )
    print(
        json.dumps(
            dict(
                figures=len(maps),
                status="EXPORTED_FOR_VALUE_GEOMETRY_AND_VISUAL_REVIEW",
            )
        )
    )


if __name__ == "__main__":
    main()
