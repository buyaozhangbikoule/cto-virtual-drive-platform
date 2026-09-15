"""Replot saved stage-2 LTspice samples at the frozen calibrated source.

Figure contract: quantitative two-panel comparison. Power supports the matched /
unmatched ratio at 0.9 MHz. Reflection is an input-plane, dimensionless proxy.
No solver rerun, invented samples, smoothing, or changed circuit parameters.
The source data are a deterministic linear-model frequency sweep, not measurements.
"""
from pathlib import Path
import csv
import hashlib
import json

import numpy as np
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

BUILD = Path(__file__).resolve().parent
ROOT = BUILD.parents[1]
STAGE2 = ROOT / "outputs/v2_self_consistent_rebuild/stage2_matching"
AUDIT = ROOT / "CTO_virtual_drive_platform_v2_1/evidence/ltspice/stage2/stage2_audit.json"
SOURCE = STAGE2 / "stage2_LTspice逐频数据.csv"
audit = json.loads(AUDIT.read_text(encoding="utf-8-sig"))
vs = audit["calibration"]["source_Vrms_for_a1"]
factor = vs**2
assert audit["status"] == "PASS"

groups = {name: [] for name in ("BEFORE", "IDEAL", "ACTIVE_LOSSY")}
with SOURCE.open(encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        groups[row["scenario"]].append([
            float(row["frequency_Hz"]), float(row["p_rm_W"]) * factor,
            float(row["gamma"]),
        ])
groups = {name: np.array(data) for name, data in groups.items()}
at_f0 = {}
for name, arr in groups.items():
    assert len(arr) == 20001 and np.all(np.diff(arr[:, 0]) > 0)
    i = int(np.argmin(np.abs(arr[:, 0] - 900000)))
    assert arr[i, 0] == 900000
    at_f0[name] = {"p_rm_mW": float(arr[i, 1] * 1000), "gamma": float(arr[i, 2])}
ratio = at_f0["ACTIVE_LOSSY"]["p_rm_mW"] / at_f0["BEFORE"]["p_rm_mW"]
assert abs(ratio - audit["p_rm_improvement_active_vs_before_at_f0"]) < 1e-8
assert abs(at_f0["ACTIVE_LOSSY"]["p_rm_mW"] - 170) < 0.001

mpl.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "svg.fonttype": "none", "pdf.fonttype": 42,
    "font.size": 15, "axes.labelsize": 16, "xtick.labelsize": 14,
    "ytick.labelsize": 14, "legend.fontsize": 13,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#6A7480", "axes.linewidth": 0.8,
})
fig, axes = plt.subplots(2, 1, figsize=(10, 6.7), sharex=True,
                         gridspec_kw={"height_ratios": [1.4, 1]})
fig.subplots_adjust(left=0.12, right=0.975, bottom=0.12, top=0.945, hspace=0.19)
styles = {
    "BEFORE": ("未匹配", "#70777F", "--", 1.8),
    "IDEAL": ("理想匹配", "#2878BC", ":", 2.0),
    "ACTIVE_LOSSY": ("v2.1有损匹配", "#DB7A00", "-", 2.3),
}
for name, arr in groups.items():
    label, color, ls, lw = styles[name]
    for ax, col, scale in [(axes[0], 1, 1000), (axes[1], 2, 1)]:
        ax.plot(arr[:, 0] / 1e6, arr[:, col] * scale,
                color=color, linestyle=ls, linewidth=lw, label=label)
for ax in axes:
    ax.axvline(0.9, color="#8C969F", linestyle="--", linewidth=0.9, zorder=0)
    ax.grid(True, color="#DCE2E8", linewidth=0.65, alpha=0.8)
    ax.set_xlim(0.8, 1.0)
    ax.set_xticks(np.arange(0.8, 1.0001, 0.025))
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
axes[0].set_ylim(-3, 225)
axes[0].set_yticks([0, 50, 100, 150, 200])
axes[0].set_ylabel("机械支路有功功率 $P_{Rm}$ (mW)")
axes[0].legend(loc="upper center", ncol=3, frameon=False,
               bbox_to_anchor=(0.5, 1.145), handlelength=2.1, columnspacing=1.1)
for name, xytext in [("ACTIVE_LOSSY", (0.923, 163)), ("BEFORE", (0.818, 53))]:
    p = at_f0[name]["p_rm_mW"]
    label, color, _, _ = styles[name]
    axes[0].scatter([0.9], [p], s=34, color=color, edgecolor="white", linewidth=0.7, zorder=5)
    text = f"{label}\n{p:.1f} mW" if name == "ACTIVE_LOSSY" else f"{label}\n{p:.3f} mW"
    axes[0].annotate(text, xy=(0.9, p), xytext=xytext, fontsize=14,
                     color=color, weight="bold", ha="left", va="center",
                     arrowprops={"arrowstyle": "-", "color": color, "lw": 0.9})
axes[1].set_ylim(-0.04, 1.055)
axes[1].set_yticks([0, 0.5, 1.0])
axes[1].set_ylabel("输入反射代理 $|\\Gamma_{proxy}|$")
axes[1].set_xlabel("频率 (MHz)", labelpad=9)
axes[1].annotate("0.9000 MHz", xy=(0.9, 0.065), xytext=(0.916, 0.25),
                 color="#17324D", fontsize=13,
                 arrowprops={"arrowstyle": "-", "color": "#8C969F", "lw": 0.9})
fig.canvas.draw()
renderer = fig.canvas.get_renderer()
for text in fig.findobj(mpl.text.Text):
    if text.get_visible() and text.get_text():
        box = text.get_window_extent(renderer)
        if box.width and box.height:
            assert box.x0 >= -1 and box.y0 >= -1, text.get_text()
            assert box.x1 <= fig.bbox.width + 1 and box.y1 <= fig.bbox.height + 1, text.get_text()
for ext in ("png", "svg", "pdf"):
    fig.savefig(BUILD / f"matching_calibrated.{ext}", dpi=240, facecolor="white")
plt.close(fig)

with (BUILD / "matching_calibrated_source_data.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["scenario", "frequency_Hz", "P_Rm_W_at_frozen_source", "gamma_proxy"])
    for name, arr in groups.items():
        for row in arr:
            writer.writerow([name, *row])
record = {
    "source_csv": str(SOURCE), "source_csv_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "audit_json": str(AUDIT), "audit_json_sha256": hashlib.sha256(AUDIT.read_bytes()).hexdigest(),
    "source_Vrms": vs, "Rs_ohm": 50, "power_scaling_factor_from_1Vrms": factor,
    "method": "Saved LTspice frequency samples, power multiplied by Vs^2 under the linear AC model; Gamma unchanged.",
    "frequency_comparison_Hz": 900000, "at_f0": at_f0, "active_to_before_ratio": ratio,
    "simulation_rerun": False, "data_class": "Hypothetical linear BVD simulation, not measured",
}
(BUILD / "plot_audit.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"source_Vrms": vs, "scale": factor, "at_f0": at_f0, "ratio": ratio}, ensure_ascii=False))
