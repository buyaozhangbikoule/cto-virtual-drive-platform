from __future__ import annotations

import csv
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
SWEEP_CSV = ROOT / "outputs/v2_self_consistent_rebuild/active_stage3_5/stage3_disturbance/stage3_frequency_response_all_cases.csv"
TIMELINE_CSV = ROOT / "outputs/v2_self_consistent_rebuild/report_evidence_final/06_控制与保护/stage4_control_timeline.csv"
OUT_DIR = ROOT / "ppt_edit_slide11_python_20260828/figure"

BLUE = "#2F73B7"
RED = "#C84444"
GRAY = "#6D747B"
NAVY = "#17324D"
GRID = "#DDE3E8"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def f(row: dict[str, str], key: str) -> float:
    return float(row[key])


def broken_series(rows: list[dict[str, str]], y_key: str, gap_s: float = 0.031):
    """Insert NaNs across non-control intervals so the plot never implies continuous tracking."""
    xs: list[float] = []
    ys: list[float] = []
    previous: float | None = None
    for row in rows:
        time_s = f(row, "time_s")
        if previous is not None and time_s - previous > gap_s:
            xs.append(np.nan)
            ys.append(np.nan)
        xs.append(time_s)
        ys.append(f(row, y_key))
        previous = time_s
    return np.asarray(xs), np.asarray(ys)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sweep = read_csv(SWEEP_CSV)
    timeline = read_csv(TIMELINE_CSV)

    sweep_cases: dict[str, list[dict[str, str]]] = {}
    for case_id in ("CASE_000_BASELINE", "CASE_FS_M5"):
        rows = [
            row
            for row in sweep
            if row["case_id"] == case_id and 840_000 <= f(row, "frequency_Hz") <= 920_000
        ]
        rows.sort(key=lambda row: f(row, "frequency_Hz"))
        sweep_cases[case_id] = rows

    peaks: dict[str, dict[str, float]] = {}
    for case_id, rows in sweep_cases.items():
        peak = max(rows, key=lambda row: f(row, "safe_power_W"))
        peaks[case_id] = {
            "frequency_MHz": f(peak, "frequency_Hz") / 1e6,
            "power_mW": f(peak, "safe_power_W") * 1e3,
        }

    control: dict[str, list[dict[str, str]]] = {}
    for strategy in ("FIXED_0P9", "PERIODIC_SCAN", "P_AND_O"):
        rows = [
            row
            for row in timeline
            if row["strategy"] == strategy
            and row["action"] == "CONTROL"
            and 2.2 <= f(row, "time_s") < 3.2
        ]
        rows.sort(key=lambda row: f(row, "time_s"))
        control[strategy] = rows

    # These are computed directly from the first CONTROL sample at the new safe peak.
    first_arrival: dict[str, float] = {}
    for strategy in ("PERIODIC_SCAN", "P_AND_O"):
        candidates = [
            row
            for row in control[strategy]
            if abs(f(row, "frequency_MHz") - peaks["CASE_FS_M5"]["frequency_MHz"]) < 5e-8
            and f(row, "safe_power_capture_ratio") >= 0.999
        ]
        first_arrival[strategy] = min(f(row, "time_s") for row in candidates)

    mpl.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 14.5,
            "axes.titlesize": 17,
            "axes.labelsize": 15,
            "xtick.labelsize": 13.5,
            "ytick.labelsize": 13.5,
            "legend.fontsize": 13,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.linewidth": 1.0,
        }
    )

    fig = plt.figure(figsize=(11.0, 7.70), facecolor="white")
    gs = fig.add_gridspec(3, 1, height_ratios=[2.05, 1.30, 1.16], hspace=0.68)
    ax0 = fig.add_subplot(gs[0])
    ax1 = fig.add_subplot(gs[1])
    ax2 = fig.add_subplot(gs[2], sharex=ax1)

    # (a) Offline local sweep: direct evidence for the peak shift.
    for case_id, color, label, width in (
        ("CASE_000_BASELINE", BLUE, "基准场景", 2.7),
        ("CASE_FS_M5", RED, r"$f_s-5\%$场景", 2.7),
    ):
        rows = sweep_cases[case_id]
        ax0.plot(
            [f(row, "frequency_Hz") / 1e6 for row in rows],
            [f(row, "safe_power_W") * 1e3 for row in rows],
            color=color,
            lw=width,
            label=label,
            zorder=3,
        )

    base = peaks["CASE_000_BASELINE"]
    disturbed = peaks["CASE_FS_M5"]
    ax0.axvline(base["frequency_MHz"], color=GRAY, lw=1.5, ls="--", zorder=1)
    ax0.axvline(disturbed["frequency_MHz"], color=RED, lw=1.5, ls=":", zorder=1)
    ax0.scatter(base["frequency_MHz"], base["power_mW"], s=44, color=BLUE, edgecolor="white", zorder=5)
    ax0.scatter(disturbed["frequency_MHz"], disturbed["power_mW"], s=44, color=RED, edgecolor="white", zorder=5)
    ax0.annotate(
        f"基准峰值  {base['frequency_MHz']:.4f} MHz\n{base['power_mW']:.1f} mW",
        xy=(base["frequency_MHz"], base["power_mW"]),
        xytext=(0.918, 149),
        ha="right",
        va="center",
        color=BLUE,
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", lw=1.2, color=BLUE),
    )
    ax0.annotate(
        rf"$f_s-5\%$峰值  {disturbed['frequency_MHz']:.4f} MHz" + f"\n{disturbed['power_mW']:.1f} mW",
        xy=(disturbed["frequency_MHz"], disturbed["power_mW"]),
        xytext=(0.843, 118),
        ha="left",
        va="center",
        color=RED,
        fontweight="bold",
        arrowprops=dict(arrowstyle="->", lw=1.2, color=RED),
    )
    bracket_y = 24
    ax0.annotate(
        "",
        xy=(disturbed["frequency_MHz"], bracket_y),
        xytext=(base["frequency_MHz"], bracket_y),
        arrowprops=dict(arrowstyle="<->", lw=1.3, color=NAVY),
    )
    shift_khz = (disturbed["frequency_MHz"] - base["frequency_MHz"]) * 1000
    ax0.text(
        (disturbed["frequency_MHz"] + base["frequency_MHz"]) / 2,
        bracket_y + 5,
        f"峰位变化 {shift_khz:.1f} kHz",
        ha="center",
        va="bottom",
        color=NAVY,
        fontweight="bold",
    )
    ax0.set_xlim(0.84, 0.92)
    ax0.set_ylim(0, 182)
    ax0.set_xticks(np.arange(0.84, 0.921, 0.01))
    ax0.set_yticks([0, 50, 100, 150])
    ax0.set_xlabel("频率 (MHz)", labelpad=2)
    ax0.set_ylabel("安全运动支路有功功率 (mW)")
    ax0.set_title("a  离线局部扫频：安全功率峰位迁移", loc="left", color=NAVY, fontweight="bold", pad=8)
    ax0.grid(axis="y", color=GRID, lw=0.8)
    ax0.legend(loc="upper center", bbox_to_anchor=(0.5, 1.02), ncol=2, frameon=False)

    styles = {
        "FIXED_0P9": dict(color=GRAY, lw=1.9, ls="-", marker=None, label="固定0.900 MHz"),
        "PERIODIC_SCAN": dict(
            color=BLUE,
            lw=2.7,
            ls="--",
            marker="o",
            markerfacecolor="white",
            markeredgecolor=BLUE,
            markersize=5.5,
            markevery=3,
            label="周期扫频 ○",
        ),
        "P_AND_O": dict(
            color=RED,
            lw=1.8,
            ls="-",
            marker="^",
            markerfacecolor=RED,
            markeredgecolor=RED,
            markersize=5.2,
            markevery=3,
            label="扫描辅助P&O △",
        ),
    }

    # (b) Capture rate. Gaps are intentionally retained when scanning/probing interrupts CONTROL samples.
    for strategy in ("FIXED_0P9", "PERIODIC_SCAN", "P_AND_O"):
        x, y = broken_series(control[strategy], "safe_power_capture_ratio")
        y = y * 100
        ax1.plot(x, y, **styles[strategy], zorder=3)
    ax1.axvline(2.4, color=GRAY, lw=1.3, ls=":", zorder=1)
    ax1.axvline(first_arrival["PERIODIC_SCAN"], color=BLUE, lw=1.2, ls="--", zorder=1)
    ax1.axvline(first_arrival["P_AND_O"], color=RED, lw=1.0, ls=":", zorder=1)
    ax1.text(2.385, 70, "扰动开始\n2.400 s", color=GRAY, ha="right", va="center", fontsize=12.5)
    ax1.annotate(
        "周期扫频通过稳态验收：2.4965 s\nP&O首次到达峰位：2.4985 s",
        xy=(2.4985, 100),
        xytext=(2.53, 47),
        color=NAVY,
        fontsize=12.5,
        ha="left",
        va="center",
        arrowprops=dict(arrowstyle="->", color=NAVY, lw=1.0),
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.88, pad=1.5),
    )
    ax1.text(
        3.18,
        10,
        "100% = 当前场景自身安全峰值\n≠ 恢复基准170.0 mW",
        ha="right",
        va="bottom",
        color=RED,
        fontsize=12.5,
        fontweight="bold",
    )
    ax1.set_ylim(-4, 110)
    ax1.set_yticks([0, 50, 100])
    ax1.set_ylabel("安全功率捕获率 (%)")
    ax1.set_title(
        "b  安全功率捕获率：按当前场景安全最优值归一化",
        loc="left",
        color=NAVY,
        fontweight="bold",
        pad=7,
    )
    ax1.grid(axis="y", color=GRID, lw=0.8)
    ax1.legend(
        loc="center",
        bbox_to_anchor=(0.69, 0.78),
        ncol=3,
        frameon=False,
        handlelength=2.4,
        columnspacing=1.4,
    )
    ax1.tick_params(axis="x", labelbottom=False)

    # (c) Control frequency at CONTROL samples only.
    for strategy in ("FIXED_0P9", "PERIODIC_SCAN", "P_AND_O"):
        x, y = broken_series(control[strategy], "frequency_MHz")
        ax2.plot(x, y, **styles[strategy], zorder=3)
    ax2.axvline(2.4, color=GRAY, lw=1.3, ls=":", zorder=1)
    ax2.axhline(0.9000, color=GRAY, lw=0.9, ls="--", alpha=0.7)
    ax2.axhline(0.8548, color=BLUE, lw=0.9, ls="--", alpha=0.7)
    ax2.text(3.18, 0.9000, "固定 0.9000 MHz", ha="right", va="bottom", color=GRAY, fontweight="bold")
    ax2.text(
        3.18,
        0.8565,
        "周期扫频 / P&O控制样本 0.8548 MHz",
        ha="right",
        va="bottom",
        color=BLUE,
        fontweight="bold",
    )
    ax2.set_xlim(2.2, 3.2)
    ax2.set_ylim(0.849, 0.905)
    ax2.set_xticks(np.arange(2.2, 3.21, 0.2))
    ax2.set_yticks([0.855, 0.875, 0.900])
    ax2.set_xlabel("离散准稳态时间 (s)")
    ax2.set_ylabel("控制频率 (MHz)")
    ax2.set_title("c  CONTROL样本的控制频率（扫描/试探区间不连线）", loc="left", color=NAVY, fontweight="bold", pad=7)
    ax2.grid(axis="both", color=GRID, lw=0.8)

    fig.subplots_adjust(left=0.108, right=0.986, top=0.945, bottom=0.085)

    png = OUT_DIR / "slide11_python_charts_no_overlap.png"
    svg = OUT_DIR / "slide11_python_charts_no_overlap.svg"
    pdf = OUT_DIR / "slide11_python_charts_no_overlap.pdf"
    fig.savefig(png, dpi=300, facecolor="white")
    fig.savefig(svg, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)

    with (OUT_DIR / "slide11_computed_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value", "unit", "source"])
        writer.writerow(["baseline_peak_frequency", f"{base['frequency_MHz']:.4f}", "MHz", "sweep CSV"])
        writer.writerow(["baseline_peak_power", f"{base['power_mW']:.6f}", "mW", "sweep CSV"])
        writer.writerow(["fs_minus5_peak_frequency", f"{disturbed['frequency_MHz']:.4f}", "MHz", "sweep CSV"])
        writer.writerow(["fs_minus5_peak_power", f"{disturbed['power_mW']:.6f}", "mW", "sweep CSV"])
        writer.writerow(["peak_shift", f"{shift_khz:.1f}", "kHz", "computed"])
        writer.writerow(["periodic_first_peak_control_sample", f"{first_arrival['PERIODIC_SCAN']:.4f}", "s", "timeline CSV"])
        writer.writerow(["pando_first_peak_control_sample", f"{first_arrival['P_AND_O']:.4f}", "s", "timeline CSV"])

    print(png)
    print(f"baseline={base['frequency_MHz']:.4f} MHz, {base['power_mW']:.6f} mW")
    print(f"fs-5%={disturbed['frequency_MHz']:.4f} MHz, {disturbed['power_mW']:.6f} mW")
    print(f"shift={shift_khz:.1f} kHz")
    print(f"periodic arrival={first_arrival['PERIODIC_SCAN']:.4f} s")
    print(f"P&O arrival={first_arrival['P_AND_O']:.4f} s")


if __name__ == "__main__":
    main()
