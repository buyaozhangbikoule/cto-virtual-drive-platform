"""Create publication/PPT-ready parameter-versus-peak-power trend figures.

Source: existing stage-3 deterministic single-factor summary.  This script does
not generate circuit simulations; it expects the formally registered Lm-only
and Cm-only cases to already be present in the stage-3 source table.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results" / "tables" / "stage3_disturbance" / "stage3_scenario_registry_and_summary.csv"
OUT = ROOT / "figures" / "stage3_disturbance" / "parameter_peak_trends"
SOURCE_EXPORT = ROOT / "results" / "tables" / "stage3_disturbance" / "stage3_parameter_peak_trends_source.csv"
QA_PATH = OUT / "stage3_parameter_peak_trends_QA.json"

FACTOR_ORDER = ["C0", "Rm", "fs", "Lm", "Cm", "Rs", "Lmatch", "Cmatch", "inductor_Q", "Qm"]
FACTOR_TITLES = {
    "C0": r"$C_0$ increase",
    "Rm": r"$R_m$ increase",
    "fs": r"$f_s$ decrease",
    "Lm": r"$L_m$ increase (only)",
    "Cm": r"$C_m$ increase (only)",
    "Rs": r"$R_s$ increase",
    "Lmatch": r"$L_{match}$ increase",
    "Cmatch": r"$C_{match}$ decrease",
    "inductor_Q": "Inductor Q",
    "Qm": r"$Q_m$",
}
COLORS = {
    "C0": "#3775BA",
    "Rm": "#B64342",
    "fs": "#42949E",
    "Lm": "#5E83B5",
    "Cm": "#C16B52",
    "Rs": "#767676",
    "Lmatch": "#9A4D8E",
    "Cmatch": "#E28E2C",
    "inductor_Q": "#5B7FCA",
    "Qm": "#7BAA5B",
}

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
    "font.size": 7,
    "axes.titlesize": 8,
    "axes.labelsize": 7,
    "xtick.labelsize": 6.4,
    "ytick.labelsize": 6.4,
    "axes.linewidth": 0.75,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "legend.frameon": False,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
})


def read_rows() -> list[dict]:
    with SOURCE.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["power_peak_W"] = float(row["power_peak_W"])
        row["power_peak_Hz"] = float(row["power_peak_Hz"])
    return rows


def build_series(rows: list[dict]) -> tuple[dict[str, list[dict]], float]:
    baseline = next(row for row in rows if row["case_id"] == "CASE_000_BASELINE")
    baseline_w = baseline["power_peak_W"]
    by_factor: dict[str, list[dict]] = {}
    for factor in FACTOR_ORDER:
        factor_rows = [row for row in rows if row["family"] == "single_factor" and row["factor"] == factor]
        if factor in {"inductor_Q", "Qm"}:
            series = factor_rows
        else:
            series = [
                {
                    **baseline,
                    "factor": factor,
                    "level": "Baseline",
                    "case_id": f"CASE_BASELINE_FOR_{factor.upper()}",
                }
            ] + factor_rows
        by_factor[factor] = series
    return by_factor, baseline_w


def export_source(by_factor: dict[str, list[dict]], baseline_w: float) -> None:
    rows = []
    for factor in FACTOR_ORDER:
        for order, row in enumerate(by_factor[factor]):
            rows.append({
                "factor": factor,
                "display_order": order,
                "case_id": row["case_id"],
                "level": row["level"],
                "power_peak_Hz": row["power_peak_Hz"],
                "power_peak_W": row["power_peak_W"],
                "power_peak_mW": row["power_peak_W"] * 1e3,
                "change_vs_baseline_pct": (row["power_peak_W"] / baseline_w - 1) * 100,
                "source_class": "DERIVED_RESULT from MODEL_V2_1_HYPOTHETICAL",
            })
    with SOURCE_EXPORT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def panel_label(axis, index: int) -> None:
    axis.text(-0.16, 1.06, chr(ord("a") + index), transform=axis.transAxes,
              fontsize=9, fontweight="bold", va="top")


def save_figure(fig: plt.Figure, stem: str, *, make_tiff: bool = False) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{stem}.png", dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight", facecolor="white")
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight", facecolor="white")
    if make_tiff:
        fig.savefig(OUT / f"{stem}.tiff", dpi=600, bbox_inches="tight", facecolor="white")


def make_absolute(by_factor: dict[str, list[dict]], baseline_w: float) -> None:
    fig, axes = plt.subplots(2, 5, figsize=(13.2, 5.8), sharey=True, constrained_layout=True)
    axes_flat = axes.ravel()
    baseline_mw = baseline_w * 1e3
    all_values = [row["power_peak_W"] * 1e3 for values in by_factor.values() for row in values]
    y_min = np.floor((min(all_values) - 4) / 5) * 5
    y_max = np.ceil((max(all_values) + 3) / 5) * 5

    for index, factor in enumerate(FACTOR_ORDER):
        axis = axes_flat[index]
        rows = by_factor[factor]
        x = np.arange(len(rows))
        y = np.array([row["power_peak_W"] * 1e3 for row in rows])
        labels = [row["level"].replace("Qm=", "") for row in rows]
        axis.plot(x, y, color=COLORS[factor], marker="o", markersize=4.2, linewidth=1.6)
        axis.axhline(baseline_mw, color="#8A8A8A", linestyle="--", linewidth=0.75)
        axis.set_xticks(x, labels, rotation=28, ha="right")
        axis.set_ylim(y_min, y_max)
        axis.set_title(FACTOR_TITLES[factor], fontweight="bold")
        axis.grid(axis="y", color="#D8D8D8", linewidth=0.5, alpha=0.7)
        panel_label(axis, index)
        for xx, yy in zip(x, y):
            axis.annotate(f"{yy:.1f}", (xx, yy), xytext=(0, 4), textcoords="offset points",
                          ha="center", va="bottom", fontsize=5.8, color="#333333")

    fig.supylabel(r"Peak motional active power, $P_{Rm,peak}$ (mW)", fontsize=8)
    fig.supxlabel("Registered disturbance level (categorical)", fontsize=8)
    fig.suptitle("Parameter-to-active-power-peak trends under the same frozen source",
                 fontsize=10, fontweight="bold")
    save_figure(fig, "stage3_05_parameter_peak_trends_absolute", make_tiff=True)
    plt.close(fig)


def make_relative_zoom(by_factor: dict[str, list[dict]], baseline_w: float) -> None:
    fig, axes = plt.subplots(2, 5, figsize=(13.2, 5.8), constrained_layout=True)
    axes_flat = axes.ravel()

    for index, factor in enumerate(FACTOR_ORDER):
        axis = axes_flat[index]
        rows = by_factor[factor]
        x = np.arange(len(rows))
        delta = np.array([(row["power_peak_W"] / baseline_w - 1) * 100 for row in rows])
        labels = [row["level"].replace("Qm=", "") for row in rows]
        axis.plot(x, delta, color=COLORS[factor], marker="o", markersize=4.2, linewidth=1.6)
        axis.axhline(0, color="#777777", linestyle="--", linewidth=0.75)
        axis.set_xticks(x, labels, rotation=28, ha="right")
        axis.set_title(FACTOR_TITLES[factor], fontweight="bold")
        axis.grid(axis="y", color="#D8D8D8", linewidth=0.5, alpha=0.7)
        panel_label(axis, index)
        span = float(np.ptp(delta))
        if span < 1e-8:
            axis.set_ylim(-0.10, 0.10)
        else:
            margin = max(span * 0.28, 0.025)
            axis.set_ylim(float(delta.min() - margin), float(delta.max() + margin))
        for xx, yy in zip(x, delta):
            axis.annotate(f"{yy:+.2f}%", (xx, yy), xytext=(0, 4), textcoords="offset points",
                          ha="center", va="bottom", fontsize=5.8, color="#333333")

    fig.supylabel(r"Change in $P_{Rm,peak}$ relative to baseline (%)", fontsize=8)
    fig.supxlabel("Registered disturbance level (categorical)", fontsize=8)
    fig.suptitle("Relative peak-power sensitivity (independent y-scale in each panel)",
                 fontsize=10, fontweight="bold")
    save_figure(fig, "stage3_06_parameter_peak_trends_relative_zoom")
    plt.close(fig)


def write_qa(by_factor: dict[str, list[dict]], baseline_w: float) -> None:
    changes = {
        factor: [100 * (row["power_peak_W"] / baseline_w - 1) for row in rows]
        for factor, rows in by_factor.items()
    }
    qa = {
        "status": "PASS",
        "core_conclusion": "Under the same frozen Thevenin source, Lm-only/Cm-only shifts, prescribed fs drift, source/matching errors and inductor loss reduce active-power peak height more strongly than C0 or Qm in the registered v2.1 ranges.",
        "archetype": "quantitative grid",
        "backend": "Python/matplotlib only",
        "source_data": str(SOURCE_EXPORT.relative_to(ROOT)),
        "source_scope": "deterministic MODEL_V2_1_HYPOTHETICAL outputs; not measured data",
        "statistics": "No error bars or hypothesis tests: this is a deterministic parameter sweep, not replicated experimental sampling.",
        "absolute_figure": "shared y-axis across all panels for honest magnitude comparison",
        "relative_zoom_figure": "independent y-axis per panel; intended only to reveal within-factor direction and small changes",
        "baseline_power_peak_mW": baseline_w * 1e3,
        "max_abs_change_pct_by_factor": {factor: max(abs(v) for v in values) for factor, values in changes.items()},
        "known_missing_cases": [],
        "lm_cm_only_convention": (
            "For Lm-only/Cm-only scans, only the named motional element changes; "
            "all other BVD elements are frozen and the resulting fs/Qm are derived."
        ),
        "reviewer_risks": [
            "Do not compare apparent slopes across panels in the relative-zoom figure because y-scales differ.",
            "Categorical x spacing represents registered levels, not continuous dose-response sampling.",
            "Conclusions are limited to the frozen source, hypothetical BVD model and declared disturbance ranges."
        ],
    }
    QA_PATH.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = read_rows()
    by_factor, baseline_w = build_series(rows)
    export_source(by_factor, baseline_w)
    make_absolute(by_factor, baseline_w)
    make_relative_zoom(by_factor, baseline_w)
    write_qa(by_factor, baseline_w)
    print(json.dumps({
        "status": "PASS",
        "factors": FACTOR_ORDER,
        "baseline_peak_mW": baseline_w * 1e3,
        "output_directory": str(OUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
