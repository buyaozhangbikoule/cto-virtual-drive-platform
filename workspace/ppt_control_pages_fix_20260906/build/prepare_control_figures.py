"""Audit and redraw saved quasi-steady control results, without solver execution.

Python figure contract:
12: the full recorded voltage/current/amplitude history contains protection and scans.
14: offline peak location, power capture and continuous-settling acceptance are distinct.
Keep all actions in the power plot; do not bridge scan gaps in CONTROL frequency.
Data are deterministic hypothetical-model simulations, not measured waveforms.
"""
from pathlib import Path
import ast
import csv
import hashlib
import io
import json

import numpy as np
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FormatStrFormatter

BUILD = Path(__file__).resolve().parent
ROOT = BUILD.parents[1]
TABLES = ROOT / "CTO_virtual_drive_platform_v2_1/results/tables/stage4_5"
CONTROLLER = ROOT / "outputs/v2_self_consistent_rebuild/active_stage3_5/run_stage4_5_control.py"
SWEEP = ROOT / "outputs/v2_self_consistent_rebuild/active_stage3_5/stage3_disturbance/stage3_frequency_response_all_cases.csv"
INPUTS = BUILD / "inputs"
INPUTS.mkdir(exist_ok=True)
manifest = []

def snapshot(path):
    data = path.read_bytes()
    (INPUTS / path.name).write_bytes(data)
    manifest.append({"path": str(path), "snapshot": str(INPUTS / path.name), "sha256": hashlib.sha256(data).hexdigest()})
    return data.decode("utf-8-sig")

def read_numeric_csv(text):
    result = []
    for row in csv.DictReader(io.StringIO(text)):
        converted = {}
        for key, value in row.items():
            try:
                converted[key] = float(value)
            except (TypeError, ValueError):
                converted[key] = value
        result.append(converted)
    return result

timeline = read_numeric_csv(snapshot(TABLES / "stage4_control_timeline.csv"))
stored_segments = read_numeric_csv(snapshot(TABLES / "stage5_per_segment_metrics.csv"))
stored_overall = read_numeric_csv(snapshot(TABLES / "stage5_integrated_strategy_table.csv"))
run_audit = json.loads(snapshot(TABLES / "stage4_5_audit.json"))
controller_text = snapshot(CONTROLLER)
sweep_text = snapshot(SWEEP)
STRATEGIES = run_audit["strategies"]
SCHEDULE = run_audit["schedule"]
CONTROL_DT = run_audit["control_dt_s"]
THRESHOLD = run_audit["recovery_capture_threshold"]
REQUIRED = run_audit["recovery_consecutive_control_samples"]
assert CONTROL_DT == 0.02 and THRESHOLD == 0.98 and REQUIRED == 10

# Execute only the existing postprocessing function definitions, never simulate/main.
function_names = {"episode_count", "scan_episode_count", "segment_metrics", "overall_metrics"}
tree = ast.parse(controller_text)
functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in function_names]
assert len(functions) == len(function_names)
env = {"np": np, "STRATEGIES": STRATEGIES, "SCHEDULE": SCHEDULE, "CONTROL_DT": CONTROL_DT,
       "RECOVERY_CAPTURE_THRESHOLD": THRESHOLD, "RECOVERY_CONSECUTIVE_SAMPLES": REQUIRED,
       "SEGMENT_DURATION": 0.8}
exec(compile(ast.Module(body=functions, type_ignores=[]), "saved_controller_postprocessing_only", "exec"), env)
segments = env["segment_metrics"](timeline)
overall = env["overall_metrics"](timeline, segments)

def compare_table(computed, saved, keys):
    lookup = {tuple(row[key] for key in keys): row for row in saved}
    fields = 0
    for row in computed:
        reference = lookup[tuple(row[key] for key in keys)]
        for key, value in row.items():
            other = reference[key]
            if isinstance(value, (float, int, np.number)):
                assert np.isclose(value, other, rtol=1e-9, atol=1e-9), (keys, key, value, other)
            else:
                assert value == other, (key, value, other)
            fields += 1
    return fields

segment_fields = compare_table(segments, stored_segments, ["strategy", "state_index"])
overall_fields = compare_table(overall, stored_overall, ["strategy"])
fs_segment = next(seg for seg in SCHEDULE if seg["case_id"] == "CASE_FS_M5")
start, end = fs_segment["start_s"], fs_segment["end_s"]
details = {}
for strategy in STRATEGIES:
    rows = [r for r in timeline if r["strategy"] == strategy and r["state_index"] == fs_segment["state_index"] and r["action"] == "CONTROL"]
    count = maximum = 0
    previous = None
    first_peak_control = first_qualified = None
    for r in rows:
        if first_peak_control is None and abs(r["frequency_Hz"] - 854800) < 0.1:
            first_peak_control = r["time_s"]
        contiguous = previous is None or r["time_s"] - previous <= 1.5 * CONTROL_DT
        ok = contiguous and r["protection_state"] == "NORMAL" and not r["frequency_frozen"] and r["safe_power_capture_ratio"] >= THRESHOLD
        count = count + 1 if ok else 0
        maximum = max(maximum, count)
        if ok and first_qualified is None:
            first_qualified = r["time_s"]
        previous = r["time_s"]
    metric = next(m for m in segments if m["strategy"] == strategy and m["state_index"] == fs_segment["state_index"])
    details[strategy] = {"max_consecutive_qualified_samples": maximum,
                         "first_control_at_peak_s": first_peak_control,
                         "first_qualified_normal_control_s": first_qualified,
                         "metrics": metric}
    assert bool(metric["settled"]) == (maximum >= REQUIRED)
assert details["PERIODIC_SCAN"]["max_consecutive_qualified_samples"] == 6
assert details["P_AND_O"]["max_consecutive_qualified_samples"] == 9

sweep_cases = {}
for row in csv.DictReader(io.StringIO(sweep_text)):
    if row["case_id"] in {"CASE_000_BASELINE", "CASE_FS_M5"}:
        sweep_cases.setdefault(row["case_id"], []).append([float(row["frequency_Hz"]), float(row["safe_power_W"])])
peaks = {}
for case_id, data in sweep_cases.items():
    data.sort()
    arr = np.array(data)
    peak = arr[np.argmax(arr[:, 1])]
    peaks[case_id] = {"frequency_Hz": peak[0], "safe_power_W": peak[1]}
    refs = [r for r in timeline if r["case_id"] == case_id]
    assert refs and all(np.isclose(peak[0], r["optimal_safe_frequency_Hz"], atol=0.1) and
                        np.isclose(peak[1], r["optimal_safe_power_W"], rtol=1e-6) for r in refs)
    sweep_cases[case_id] = arr

COLORS = {"FIXED_0P9": "#70777F", "PERIODIC_SCAN": "#2F73B7", "P_AND_O": "#C84444"}
LABELS = {"FIXED_0P9": "固定0.9 MHz", "PERIODIC_SCAN": "周期扫频", "P_AND_O": "扫描辅助P&O"}
LINES = {"FIXED_0P9": ("-", 1.7), "PERIODIC_SCAN": ("--", 2.5), "P_AND_O": ("-", 1.6)}
NAVY, GRID = "#17324D", "#DDE3E8"
mpl.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "svg.fonttype": "none", "pdf.fonttype": 42,
    "font.size": 15, "axes.titlesize": 17, "axes.labelsize": 16,
    "xtick.labelsize": 14, "ytick.labelsize": 14, "legend.fontsize": 14,
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#70777F"})

def write_figure(fig, stem):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for text in fig.findobj(mpl.text.Text):
        if text.get_visible() and text.get_text():
            b = text.get_window_extent(renderer)
            if b.width and b.height:
                assert b.x0 >= -1 and b.y0 >= -1 and b.x1 <= fig.bbox.width + 1 and b.y1 <= fig.bbox.height + 1, (stem, text.get_text())
    for ext in ("png", "svg", "pdf"):
        fig.savefig(BUILD / f"{stem}.{ext}", dpi=240, facecolor="white")
    plt.close(fig)

def held_series(rows, key, lo, hi, factor=1):
    xs, ys = [], []
    previous_end = None
    for r in rows:
        a, b = max(lo, r["time_s"]), min(hi, r["time_s"] + r["duration_s"])
        if b <= a:
            continue
        if previous_end is not None and a - previous_end > 1e-8:
            xs.append(np.nan); ys.append(np.nan)
        xs.extend([a, b]); ys.extend([r[key] * factor, r[key] * factor])
        previous_end = b
    return np.array(xs), np.array(ys)

def control_series(rows, key):
    xs, ys = [], []
    previous = None
    for r in rows:
        if r["action"] != "CONTROL":
            continue
        if previous is not None and r["time_s"] - previous > 1.5 * CONTROL_DT:
            xs.append(np.nan); ys.append(np.nan)
        xs.append(r["time_s"]); ys.append(r[key]); previous = r["time_s"]
    return np.array(xs), np.array(ys)

def style_axis(ax):
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.8)

def strategy_legend():
    return [Line2D([0], [0], color=COLORS[s], linestyle=LINES[s][0], linewidth=LINES[s][1],
                   marker=("o" if s == "PERIODIC_SCAN" else "^" if s == "P_AND_O" else None),
                   markerfacecolor="white" if s == "PERIODIC_SCAN" else COLORS[s], markersize=5, label=LABELS[s]) for s in STRATEGIES]

# Page 12: complete recorded action sequence in the same disturbance window as p14.
lo, hi = 2.25, 3.2
fig, axes = plt.subplots(3, 1, figsize=(11.7, 6.5), sharex=True)
fig.subplots_adjust(left=0.12, right=0.985, top=0.885, bottom=0.115, hspace=0.19)
for s in STRATEGIES:
    sr = [r for r in timeline if r["strategy"] == s]
    for ax, key, factor in zip(axes, ["vport_vpp", "iport_irms_A", "amplitude_command"], [1, 1000, 1]):
        x, y = held_series(sr, key, lo, hi, factor)
        ax.plot(x, y, color=COLORS[s], linestyle=LINES[s][0], linewidth=LINES[s][1])
for ax in axes:
    style_axis(ax)
    ax.axvline(start, color="#929AA2", linestyle=":", linewidth=1.2)
    ax.set_xlim(lo, hi)
axes[0].set_ylim(-4, 178); axes[0].set_yticks([0, 80, 160]); axes[0].set_ylabel("端口电压 (Vpp)")
axes[1].set_ylim(-0.2, 6.6); axes[1].set_yticks([0, 3, 6]); axes[1].set_ylabel("端口电流\n(mA RMS)")
axes[2].set_ylim(-0.06, 1.16); axes[2].set_yticks([0, 0.5, 1]); axes[2].set_ylabel("幅度命令 a")
axes[2].set_xlabel("离散准稳态时间 (s)", labelpad=7)
for ax, soft, hard in [(axes[0], 130, 160), (axes[1], 5.5, 6)]:
    ax.axhline(soft, color="#DE9000", linestyle="--", linewidth=1.25)
    ax.axhline(hard, color="#B33A3A", linestyle=":", linewidth=1.45)
axes[2].text(2.42, 1.045, r"$f_s-5\%$，扰动始于2.400 s", color=NAVY, fontsize=14)
for s in ["P_AND_O", "PERIODIC_SCAN"]:
    scan = [r for r in timeline if r["strategy"] == s and r["state_index"] == 3 and r["action"].startswith("SCAN")]
    axes[2].axvspan(scan[0]["time_s"], scan[-1]["time_s"] + scan[-1]["duration_s"], color=COLORS[s], alpha=0.10, linewidth=0)
axes[2].text(2.825, 0.10, "低幅扫描", color=NAVY, fontsize=13)
fig.legend(handles=strategy_legend(), loc="upper center", bbox_to_anchor=(0.56, 0.995), ncol=3,
           frameon=False, columnspacing=1.7, handlelength=2.6)
write_figure(fig, "page12_protection_current")

# Page 14: three independent statements with explicit axes and normalization.
fig = plt.figure(figsize=(10.4, 7.25))
axes = [fig.add_axes([0.13, 0.73, 0.84, 0.20]),
        fig.add_axes([0.13, 0.380, 0.84, 0.195]),
        fig.add_axes([0.13, 0.090, 0.84, 0.185])]
ax0, ax1, ax2 = axes
ax0.set_title("a  离线安全功率峰", loc="left", color=NAVY, weight="bold", pad=10)
for case_id, color in [("CASE_000_BASELINE", COLORS["PERIODIC_SCAN"]), ("CASE_FS_M5", COLORS["P_AND_O"])]:
    arr = sweep_cases[case_id]
    ax0.plot(arr[:, 0] / 1e6, arr[:, 1] * 1000, color=color, linewidth=2)
    peak = peaks[case_id]; x, y = peak["frequency_Hz"] / 1e6, peak["safe_power_W"] * 1000
    ax0.axvline(x, color=color, linestyle=":", linewidth=1)
    ax0.scatter([x], [y], color=color, s=26, edgecolor="white", linewidth=0.7, zorder=4)
    label = "基准" if case_id == "CASE_000_BASELINE" else "fs−5%"
    anchor = (0.894, 110) if case_id == "CASE_000_BASELINE" else (0.861, 110)
    ax0.annotate(f"{label}\n{x:.4f} MHz\n{y:.1f} mW", xy=(x, y), xytext=anchor,
                 ha="right" if case_id == "CASE_000_BASELINE" else "left", va="center", color=color, fontsize=13.5,
                 arrowprops={"arrowstyle": "-", "color": color, "lw": 0.8})
ax0.set_xlim(0.84, 0.92); ax0.set_ylim(0, 195); ax0.set_yticks([0, 100, 180])
ax0.set_ylabel("安全功率 (mW)", fontsize=15)
ax0.set_xlabel("频率 (MHz)", labelpad=4, fontsize=15)
ax0.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
ax1.set_title("b  功率捕获率（含扫描、保护样本）", loc="left", color=NAVY, weight="bold", pad=29)
ax2.set_title("c  控制频率（扫描区间断线）", loc="left", color=NAVY, weight="bold", pad=12)
for s in STRATEGIES:
    rows = [r for r in timeline if r["strategy"] == s and r["time_s"] + r["duration_s"] > 2.2 and r["time_s"] < end]
    x, y = held_series(rows, "safe_power_capture_ratio", 2.2, end, 100)
    ax1.plot(x, y, color=COLORS[s], linestyle=LINES[s][0], linewidth=LINES[s][1])
    cx, cy = control_series(rows, "frequency_MHz")
    ax2.plot(cx, cy, color=COLORS[s], linestyle=LINES[s][0], linewidth=LINES[s][1])
    controls = [r for r in rows if r["action"] == "CONTROL" and r["time_s"] >= 2.2]
    if s != "FIXED_0P9":
        marked = controls[(0 if s == "PERIODIC_SCAN" else 1)::3]
        for ax, key, factor in [(ax1, "safe_power_capture_ratio", 100), (ax2, "frequency_MHz", 1)]:
            ax.plot([r["time_s"] for r in marked], [r[key] * factor for r in marked], linestyle="none",
                    marker="o" if s == "PERIODIC_SCAN" else "^", markersize=4.5,
                    markerfacecolor="white" if s == "PERIODIC_SCAN" else COLORS[s], markeredgecolor=COLORS[s])
for ax in axes:
    style_axis(ax)
for ax in [ax1, ax2]:
    ax.set_xlim(2.2, end)
    ax.axvline(start, color="#929AA2", linestyle=":", linewidth=1)
    ax.axvline(end, color="#929AA2", linestyle=":", linewidth=1)
    ax.set_xticks([2.2, 2.4, 2.6, 2.8, 3.0, 3.2])
ax1.set_ylim(-4, 112); ax1.set_yticks([0, 50, 100]); ax1.set_ylabel("捕获率 (%)", fontsize=15)
ax1.axhline(98, color="#7E8790", linestyle=":", linewidth=0.8)
ax1.legend(handles=strategy_legend(), loc="lower left", bbox_to_anchor=(0.0, 1.005), ncol=3,
           frameon=False, fontsize=11.5, borderaxespad=0, columnspacing=1.2)
ax1.tick_params(labelbottom=False)
ax2.set_ylim(0.849, 0.911); ax2.set_yticks([0.8548, 0.9000]); ax2.yaxis.set_major_formatter(FormatStrFormatter("%.4f"))
ax2.set_ylabel("频率 (MHz)", fontsize=15); ax2.set_xlabel("离散准稳态时间 (s)", fontsize=15, labelpad=7)
ax2.axhline(0.8548, color=COLORS["PERIODIC_SCAN"], linestyle=":", linewidth=0.8)
write_figure(fig, "page14_peak_and_acceptance_current")

report = {
    "solver_rerun": False, "source_inputs": manifest,
    "control_bundle_id": next(m["sha256"][:12] for m in manifest if m["path"].endswith("stage4_control_timeline.csv")),
    "schedule_sha256": run_audit["schedule_sha256"],
    "postprocessing_fields_verified": {"per_segment": segment_fields, "integrated": overall_fields},
    "fs_window": fs_segment, "fs_results": details, "offline_peaks": peaks,
    "integrated": overall,
    "acceptance": {"minimum_capture": THRESHOLD, "consecutive_control_samples": REQUIRED,
                   "require_normal": True, "require_frequency_unfrozen": True, "maximum_control_gap_s": CONTROL_DT * 1.5},
    "plotting": {"power_and_protection": "all recorded actions, sample-held over duration_s", "frequency": "CONTROL samples only; scan/probe gaps not bridged", "data_offsets": False},
}
(BUILD / "control_revision_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"bundle": report["control_bundle_id"], "fields_verified": report["postprocessing_fields_verified"],
    "consecutive": {s: details[s]["max_consecutive_qualified_samples"] for s in STRATEGIES}, "peaks": peaks}, ensure_ascii=False))
