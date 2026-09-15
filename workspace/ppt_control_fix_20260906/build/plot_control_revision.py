"""Rebuild two scientific figures from one frozen saved control dataset.

Figure contract: slide 12 shows all recorded V/I/amplitude actions in the fs -5%
segment. Slide 14 separates an offline safe-power peak from actual control
performance and the consecutive-sample acceptance rule. No mock data, smoothing,
timing shift, solver rerun, or controller alteration is used.
"""
from pathlib import Path
import csv
import hashlib
import json
import shutil

import numpy as np
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FormatStrFormatter

BUILD = Path(__file__).resolve().parent
ROOT = BUILD.parents[1]
DATA = BUILD / "data"
CONTROL = ROOT / "CTO_virtual_drive_platform_v2_1/results/tables/stage4_5"
ACTIVE = ROOT / "outputs/v2_self_consistent_rebuild/active_stage3_5"
DATA.mkdir(exist_ok=True)
INPUTS = [CONTROL / n for n in ["stage4_control_timeline.csv", "stage5_per_segment_metrics.csv",
    "stage5_integrated_strategy_table.csv", "stage4_5_audit.json"]] + [ACTIVE / "run_stage4_5_control.py"]
manifest = []
for src in INPUTS:
    blob = src.read_bytes()
    (DATA / src.name).write_bytes(blob)
    manifest.append({"source": str(src), "snapshot": str(DATA / src.name),
                     "sha256": hashlib.sha256(blob).hexdigest()})
def read_csv(file):
    with file.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
rows = read_csv(DATA / "stage4_control_timeline.csv")
perseg = read_csv(DATA / "stage5_per_segment_metrics.csv")
integrated = read_csv(DATA / "stage5_integrated_strategy_table.csv")
audit = json.loads((DATA / "stage4_5_audit.json").read_text(encoding="utf-8-sig"))
strategies = audit["strategies"]
assert strategies == ["FIXED_0P9", "PERIODIC_SCAN", "P_AND_O"]
fs_seg = next(s for s in audit["schedule"] if s["case_id"] == "CASE_FS_M5")
start, end = fs_seg["start_s"], fs_seg["end_s"]
dt = audit["control_dt_s"]
threshold = audit["recovery_capture_threshold"]
required = audit["recovery_consecutive_control_samples"]
num = lambda r, k: float(r[k])

def segment_acceptance(control_rows):
    run = 0
    maximum = 0
    prev = None
    first = None
    run_start = None
    recovery = None
    confirmation = None
    for row in control_rows:
        t = num(row, "time_s")
        ok = (prev is None or t - prev <= dt * 1.5) and row["protection_state"] == "NORMAL" \
             and row["frequency_frozen"] == "0" and num(row, "safe_power_capture_ratio") >= threshold
        if ok:
            if run == 0:
                run_start = t
            if first is None:
                first = t
            run += 1
            maximum = max(maximum, run)
            if run >= required and recovery is None:
                recovery = run_start
                confirmation = t
        else:
            run = 0
            run_start = None
        prev = t
    return {"max_consecutive_good": maximum, "first_good_normal_s": first,
            "accepted_run_start_s": recovery, "acceptance_confirmation_s": confirmation,
            "settled": recovery is not None}

rechecks = []
for pm in perseg:
    sr = [r for r in rows if r["strategy"] == pm["strategy"] and r["state_index"] == pm["state_index"]]
    control_rows = [r for r in sr if r["action"] == "CONTROL"]
    result = segment_acceptance(control_rows)
    assert result["settled"] == (pm["settled"] == "1"), pm
    seg = next(s for s in audit["schedule"] if s["state_index"] == int(pm["state_index"]))
    if result["settled"]:
        delay = max(0, result["accepted_run_start_s"] - seg["start_s"]) * 1000
        assert abs(delay - num(pm, "recovery_time_ms")) < 1e-7
    normal = [r for r in control_rows if r["protection_state"] == "NORMAL" and r["frequency_frozen"] == "0"]
    tail_start = seg["start_s"] + 0.75 * (seg["end_s"] - seg["start_s"])
    tail = [r for r in normal if num(r, "time_s") >= tail_start] or normal[-5:] or control_rows[-5:]
    assert abs(np.mean([num(r, "safe_power_capture_ratio") for r in tail]) * 100 - num(pm, "steady_power_capture_pct")) < 1e-8
    rechecks.append({"strategy": pm["strategy"], "state_index": int(pm["state_index"]), **result})
for overall in integrated:
    ms = [r for r in perseg if r["strategy"] == overall["strategy"] and int(r["state_index"]) > 0]
    assert len(ms) == 7
    assert sum(r["settled"] == "0" for r in ms) == int(overall["unsettled_segments"])
    assert abs(np.mean([num(r, "steady_error_pct") for r in ms]) - num(overall, "steady_error_pct")) < 1e-8
    penalties = [num(r, "recovery_time_ms") if r["settled"] == "1" else 800 for r in ms]
    assert abs(np.mean(penalties) - num(overall, "mean_recovery_time_ms_penalized")) < 1e-7

sweep_path = ACTIVE / "stage3_disturbance/stage3_frequency_response_all_cases.csv"
sweep = [r for r in read_csv(sweep_path) if r["case_id"] in ["CASE_000_BASELINE", "CASE_FS_M5"]]
with (DATA / "offline_safe_power_reference.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(sweep[0]))
    writer.writeheader()
    writer.writerows(sweep)
manifest.append({"source": str(sweep_path), "sha256": hashlib.sha256(sweep_path.read_bytes()).hexdigest(),
                 "snapshot": "offline_safe_power_reference.csv", "filter": "baseline and fs -5% only, all frequencies"})
peaks = {}
for case in ["CASE_000_BASELINE", "CASE_FS_M5"]:
    peak = max([r for r in sweep if r["case_id"] == case], key=lambda r: num(r, "safe_power_W"))
    peaks[case] = {"f_MHz": num(peak, "frequency_Hz") / 1e6, "power_mW": num(peak, "safe_power_W") * 1000}
    for row in (r for r in rows if r["case_id"] == case):
        assert abs(num(row, "optimal_safe_frequency_Hz") - num(peak, "frequency_Hz")) < 1e-5
        assert abs(num(row, "optimal_safe_power_W") - num(peak, "safe_power_W")) < 1e-9

fs_details = {}
for s in strategies:
    sr = [r for r in rows if r["strategy"] == s and int(r["state_index"]) == fs_seg["state_index"]]
    cr = [r for r in sr if r["action"] == "CONTROL"]
    result = segment_acceptance(cr)
    first_freq = next((num(r, "time_s") for r in cr if abs(num(r, "frequency_Hz") - peaks["CASE_FS_M5"]["f_MHz"] * 1e6) < 0.01), None)
    pm = next(r for r in perseg if r["strategy"] == s and int(r["state_index"]) == fs_seg["state_index"])
    scans = [r for r in sr if r["action"].startswith("SCAN")]
    fs_details[s] = {**result, "first_control_at_peak_s": first_freq,
        "tail_capture_pct": num(pm, "steady_power_capture_pct"),
        "scan_start_s": num(scans[0], "time_s") if scans else None,
        "scan_end_s": num(scans[-1], "time_s") + num(scans[-1], "duration_s") if scans else None}
assert fs_details["PERIODIC_SCAN"]["max_consecutive_good"] == 6
assert fs_details["P_AND_O"]["max_consecutive_good"] == 9

BLUE, RED, GRAY, NAVY = "#2F73B7", "#C84444", "#737A82", "#17324D"
styles = {"FIXED_0P9": ("固定0.900 MHz", GRAY, "-", None, 1.8),
          "PERIODIC_SCAN": ("周期扫频", BLUE, "--", "o", 2.6),
          "P_AND_O": ("扫描辅助P&O", RED, "-", "^", 1.7)}
mpl.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
    "axes.unicode_minus": False, "svg.fonttype": "none", "pdf.fonttype": 42,
    "font.size": 14, "axes.labelsize": 15, "xtick.labelsize": 13, "ytick.labelsize": 13,
    "axes.titlesize": 16, "axes.titleweight": "bold", "axes.titlecolor": NAVY,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.8,
    "axes.edgecolor": "#77818B", "legend.frameon": False})

def step_series(rs, key, scale=1):
    xs, ys = [], []
    for r in rs:
        t = num(r, "time_s")
        stop = min(t + num(r, "duration_s"), end)
        if stop < 2.30 or t >= end:
            continue
        xs.extend([max(t, 2.30), stop])
        ys.extend([num(r, key) * scale] * 2)
    return np.asarray(xs), np.asarray(ys)

def draw_actions(ax, key, scale=1):
    for s in strategies:
        rs = [r for r in rows if r["strategy"] == s and num(r, "time_s") < end]
        name, color, ls, marker, lw = styles[s]
        x, y = step_series(rs, key, scale)
        ax.plot(x, y, color=color, ls=ls, lw=lw, label=name)
        # Mark selected CONTROL samples only, without moving the data.
        cs = [r for r in rs if r["action"] == "CONTROL" and 2.30 <= num(r, "time_s") < end]
        if marker:
            ax.plot([num(r, "time_s") for r in cs[::3]], [num(r, key) * scale for r in cs[::3]],
                    linestyle="none", marker=marker, ms=4.5, color=color,
                    markerfacecolor="white" if marker == "o" else color, markeredgewidth=1)
    ax.set_xlim(2.30, end)
    ax.axvline(start, color="#A9AFB7", ls=":", lw=1.1)
    ax.grid(axis="y", color="#DDE3E8", lw=0.65)

def legend_handles():
    return [Line2D([0], [0], color=c, ls=ls, marker=m, ms=5, lw=lw,
                   markerfacecolor="white" if m == "o" else c, label=name)
            for name, c, ls, m, lw in styles.values()]

def export(fig, name):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for txt in fig.findobj(mpl.text.Text):
        if txt.get_visible() and txt.get_text():
            box = txt.get_window_extent(renderer)
            if box.width and box.height:
                assert box.x0 > -1 and box.y0 > -1 and box.x1 < fig.bbox.width + 1 and box.y1 < fig.bbox.height + 1, txt.get_text()
    for ext in ["png", "svg", "pdf"]:
        fig.savefig(BUILD / f"{name}.{ext}", dpi=240, facecolor="white")
    plt.close(fig)

# Slide 12: recorded output states, not predicted pre-protection peak values.
fig, axes = plt.subplots(3, 1, figsize=(12.2, 6.55), sharex=True,
                          gridspec_kw={"height_ratios": [1.15, 1, 1]})
fig.subplots_adjust(left=0.105, right=0.985, top=0.885, bottom=0.12, hspace=0.18)
fig.legend(handles=legend_handles(), loc="upper center", ncol=3, bbox_to_anchor=(0.55, 0.998), fontsize=14)
for ax, key, scale, label in zip(axes, ["vport_vpp", "iport_irms_A", "amplitude_command"], [1, 1000, 1],
                               ["端口电压 (Vpp)", "端口电流 (mA RMS)", "幅度命令 a"]):
    draw_actions(ax, key, scale)
    ax.set_ylabel(label)
axes[0].set_ylim(-6, 177)
axes[0].set_yticks([0, 80, 130, 160])
axes[0].axhline(130, color="#DD8A00", ls="--", lw=1.3)
axes[0].axhline(160, color="#BF3B3B", ls=":", lw=1.5)
axes[0].text(2.69, 162, "160 Vpp硬边界", color="#BF3B3B", fontsize=12, va="bottom")
axes[0].text(2.42, 77, "保护停机\n随后保持、渐升", fontsize=12, color=NAVY)
axes[1].set_ylim(-0.2, 6.5)
axes[1].set_yticks([0, 2, 4, 6])
axes[1].axhline(5.5, color="#DD8A00", ls="--", lw=1.3)
axes[1].axhline(6, color="#BF3B3B", ls=":", lw=1.5)
axes[2].set_ylim(-0.04, 1.13)
axes[2].set_yticks([0, 0.4, 1])
axes[2].set_xticks([2.4, 2.6, 2.8, 3.0, 3.2])
axes[2].set_xlabel("离散准稳态时间 (s)，fs−5%段：2.4–3.2 s")
axes[2].text(2.64, 0.1, "淡色带：低幅扫描 a = 0.40", fontsize=12, color=NAVY)
for s in ["PERIODIC_SCAN", "P_AND_O"]:
    d = fs_details[s]
    axes[2].axvspan(d["scan_start_s"], d["scan_end_s"], color=styles[s][1], alpha=0.075, zorder=0)
export(fig, "slide12_protection_current")

# Slide 14: offline peak, all action power, all action frequency.
fig = plt.figure(figsize=(10.5, 7.05))
gs = fig.add_gridspec(3, 1, height_ratios=[1.15, 1, 1], left=0.115, right=0.975,
                     bottom=0.095, top=0.955, hspace=0.69)
a, b, c = [fig.add_subplot(gs[i]) for i in range(3)]
for case, color in [("CASE_000_BASELINE", BLUE), ("CASE_FS_M5", RED)]:
    rs = [r for r in sweep if r["case_id"] == case and 840000 <= num(r, "frequency_Hz") <= 920000]
    peak = peaks[case]
    a.plot([num(r, "frequency_Hz") / 1e6 for r in rs], [num(r, "safe_power_W") * 1000 for r in rs], color=color, lw=2.2)
    a.axvline(peak["f_MHz"], color=color, ls=":" if color == RED else "--", lw=1.1)
    a.scatter([peak["f_MHz"]], [peak["power_mW"]], s=28, color=color, edgecolors="white", zorder=5)
a.set_title("a  离线安全功率峰值迁移", loc="left", pad=8)
a.set_xlim(0.84, 0.92)
a.set_ylim(-3, 210)
a.set_yticks([0, 100, 200])
a.set_ylabel("安全 $P_{Rm}$ (mW)")
a.set_xlabel("频率 (MHz)", labelpad=1)
a.grid(axis="y", color="#DDE3E8", lw=0.65)
a.text(0.857, 122, "fs−5%：0.8548 MHz\n140.2 mW", color=RED, fontsize=13, weight="bold")
a.text(0.917, 168, "基准：0.9000 MHz\n170.0 mW", color=BLUE, fontsize=13, weight="bold", ha="right")
draw_actions(b, "safe_power_capture_ratio", 100)
b.set_title("b  功率捕获率，含保护与扫描样本", loc="left", pad=8)
b.set_ylabel("功率捕获率 (%)")
b.set_ylim(-5, 120)
b.set_yticks([0, 50, 100])
b.axhline(98, color="#AFB4BA", ls=":", lw=0.9, zorder=0)
b.tick_params(labelbottom=False)
b.text(2.405, 12, "扰动开始", color=GRAY, fontsize=12)
draw_actions(c, "frequency_MHz")
c.set_title("c  控制与扫描频率，保留选频过程", loc="left", pad=8)
c.set_ylabel("频率 (MHz)")
c.set_ylim(0.842, 0.958)
c.set_yticks([0.85, 0.90, 0.95])
c.set_xticks([2.4, 2.6, 2.8, 3.0, 3.2])
c.set_xlabel("离散准稳态时间 (s)")
c.text(2.53, 0.855, "新峰位 0.8548 MHz", color=NAVY, fontsize=12, va="bottom")
c.axhline(peaks["CASE_FS_M5"]["f_MHz"], color="#CBD1D8", ls=":", lw=0.8, zorder=0)
fig.legend(handles=legend_handles(), loc="center", ncol=3, bbox_to_anchor=(0.56, 0.342), fontsize=12.5,
           handlelength=2.4, columnspacing=1.35)
export(fig, "slide14_peak_and_acceptance_current")

report = {"source_manifest": manifest, "controller_rerun": False, "LTspice_rerun": False,
    "claim": "Both adaptive strategies reach the new peak but fail the 10-sample acceptance within the fs -5% segment.",
    "schedule_sha256": audit["schedule_sha256"], "period_s": dt, "threshold": threshold,
    "required_consecutive_samples": required, "fs_segment": fs_seg, "peaks": peaks,
    "fs_details": fs_details, "integrated": integrated, "acceptance_rechecks": rechecks,
    "curve_rendering": "All saved actions, zero-order hold using recorded durations; no temporal or vertical offset. Frequency scan samples retained.",
    "scope": "Hypothetical BVD electrical quasi-steady simulation, no measured transducer/hardware safety claim."}
(BUILD / "control_revision_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"fs_details": fs_details, "peaks": peaks, "metrics_checked": len(rechecks)}, ensure_ascii=False))
