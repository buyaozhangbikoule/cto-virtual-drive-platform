"""Compare three frequency-selection criteria and scan window/step trade-offs."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model_v2_1 import F0, F_MIN, F_MAX, all_scenarios, response


HERE = Path(__file__).resolve().parent
OUT = HERE / "stage3_selection"
INITIAL_START = 0.84e6
INITIAL_STOP = 0.96e6
INITIAL_STEP = 0.5e3
REFERENCE_STEP = 10.0
STEPS = [0.1e3, 0.5e3, 1.0e3, 2.0e3]
WINDOWS = [20e3, 50e3, 100e3]
SCAN_POINT_TIME_S = 1.5e-3

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
plt.rcParams['pdf.fonttype'] = 42
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False})


def grid(start: float, stop: float, step: float) -> np.ndarray:
    return start + np.arange(int(round((stop - start) / step)) + 1) * step


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def selected(freq: np.ndarray, q: dict[str, np.ndarray]) -> dict[str, dict]:
    indices = {
        "max_power": int(np.argmax(q["p_rm_W"])),
        "min_abs_phase": int(np.argmin(np.abs(q["phase_deg"]))),
        "min_reflection": int(np.argmin(q["gamma"])),
    }
    result = {}
    for name, i in indices.items():
        z = q["z_in"][i]
        result[name] = {
            "frequency_Hz": float(freq[i]), "p_rm_W": float(q["p_rm_W"][i]),
            "phase_deg": float(q["phase_deg"][i]), "abs_phase_deg": float(abs(q["phase_deg"][i])),
            "gamma": float(q["gamma"][i]), "zin_real_ohm": float(z.real),
            "zin_imag_ohm": float(z.imag), "zin_abs_ohm": float(abs(z)),
            "vport_vpp": float(q["vport_vpp"][i]), "iport_irms_A": float(q["iport_irms_A"][i]),
        }
    return result


def objective_value(name: str, point: dict) -> float:
    if name == "max_power": return point["p_rm_W"]
    if name == "min_abs_phase": return point["abs_phase_deg"]
    return point["gamma"]


def initial_rows(scenarios) -> list[dict]:
    freq = grid(INITIAL_START, INITIAL_STOP, INITIAL_STEP)
    rows = []
    for s in scenarios:
        picks = selected(freq, response(freq, s))
        row = {"case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level,
               "scan_start_Hz": INITIAL_START, "scan_stop_Hz": INITIAL_STOP,
               "step_Hz": INITIAL_STEP, "points": len(freq), "scan_time_proxy_ms": len(freq) * SCAN_POINT_TIME_S * 1e3}
        for criterion, point in picks.items():
            for key, value in point.items(): row[f"{criterion}_{key}"] = value
        row["power_vs_phase_frequency_delta_kHz"] = (picks["max_power"]["frequency_Hz"] - picks["min_abs_phase"]["frequency_Hz"]) / 1e3
        row["power_vs_reflection_frequency_delta_kHz"] = (picks["max_power"]["frequency_Hz"] - picks["min_reflection"]["frequency_Hz"]) / 1e3
        rows.append(row)
    return rows


def tradeoff_rows(scenarios) -> list[dict]:
    rows = []
    global_f = grid(F_MIN, F_MAX, REFERENCE_STEP)
    global_refs = {s.case_id: selected(global_f, response(global_f, s)) for s in scenarios}
    for half in WINDOWS:
        start, stop = max(F_MIN, F0 - half), min(F_MAX, F0 + half)
        ref_f = grid(start, stop, REFERENCE_STEP)
        window_refs = {s.case_id: selected(ref_f, response(ref_f, s)) for s in scenarios}
        for step in STEPS:
            f = grid(start, stop, step)
            for s in scenarios:
                picks = selected(f, response(f, s))
                for criterion, point in picks.items():
                    same_ref = window_refs[s.case_id][criterion]
                    global_ref = global_refs[s.case_id][criterion]
                    value = objective_value(criterion, point)
                    ref_value = objective_value(criterion, same_ref)
                    if criterion == "max_power":
                        objective_loss = max(0.0, (ref_value - value) / max(ref_value, 1e-30) * 100)
                    else:
                        objective_loss = max(0.0, value - ref_value)
                    rows.append({
                        "case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level,
                        "criterion": criterion, "window_halfwidth_kHz": half / 1e3, "step_kHz": step / 1e3,
                        "start_Hz": start, "stop_Hz": stop, "points": len(f),
                        "scan_time_proxy_ms": len(f) * SCAN_POINT_TIME_S * 1e3,
                        "selected_Hz": point["frequency_Hz"], "same_window_reference_Hz": same_ref["frequency_Hz"],
                        "global_reference_Hz": global_ref["frequency_Hz"],
                        "grid_frequency_error_Hz": abs(point["frequency_Hz"] - same_ref["frequency_Hz"]),
                        "total_frequency_error_vs_global_Hz": abs(point["frequency_Hz"] - global_ref["frequency_Hz"]),
                        "window_excludes_global_optimum": int(global_ref["frequency_Hz"] < start or global_ref["frequency_Hz"] > stop),
                        "objective_value": value, "same_window_reference_objective": ref_value,
                        "objective_loss_pct_or_abs": objective_loss,
                    })
    return rows


def aggregate_tradeoffs(rows: list[dict]) -> list[dict]:
    out = []
    for criterion in ("max_power", "min_abs_phase", "min_reflection"):
        for half in WINDOWS:
            for step in STEPS:
                group = [r for r in rows if r["criterion"] == criterion and r["window_halfwidth_kHz"] == half / 1e3 and r["step_kHz"] == step / 1e3]
                out.append({
                    "criterion": criterion, "window_halfwidth_kHz": half / 1e3, "step_kHz": step / 1e3,
                    "points": group[0]["points"], "scan_time_proxy_ms": group[0]["scan_time_proxy_ms"],
                    "mean_grid_frequency_error_Hz": float(np.mean([r["grid_frequency_error_Hz"] for r in group])),
                    "max_grid_frequency_error_Hz": float(np.max([r["grid_frequency_error_Hz"] for r in group])),
                    "mean_total_error_vs_global_Hz": float(np.mean([r["total_frequency_error_vs_global_Hz"] for r in group])),
                    "max_total_error_vs_global_Hz": float(np.max([r["total_frequency_error_vs_global_Hz"] for r in group])),
                    "global_optimum_excluded_cases": int(sum(r["window_excludes_global_optimum"] for r in group)),
                    "mean_objective_loss_pct_or_abs": float(np.mean([r["objective_loss_pct_or_abs"] for r in group])),
                    "max_objective_loss_pct_or_abs": float(np.max([r["objective_loss_pct_or_abs"] for r in group])),
                })
    return out


def save_figure(fig, stem: str) -> None:
    fig.tight_layout(pad=1.2)
    for ext, kwargs in (("png", {"dpi": 300}), ("svg", {}), ("pdf", {})):
        fig.savefig(OUT / f"{stem}.{ext}", bbox_inches="tight", **kwargs)
    plt.close(fig)


def make_figures(scenarios, initial: list[dict], aggregate: list[dict]) -> None:
    scenario_by_id = {s.case_id: s for s in scenarios}
    selected_ids = ["CASE_000_BASELINE", "CASE_FS_M5", "CASE_LMATCH_P10", "CASE_COMBINED_HIGH"]
    fig, axes = plt.subplots(len(selected_ids), 1, figsize=(7.2, 7.8), sharex=True)
    f = grid(INITIAL_START, INITIAL_STOP, INITIAL_STEP)
    colors = {"max_power": "#B64342", "min_abs_phase": "#3775BA", "min_reflection": "#42949E"}
    for ax, case_id in zip(axes, selected_ids):
        s = scenario_by_id[case_id]; q = response(f, s); picks = selected(f, q)
        ax.plot(f / 1e6, q["p_rm_W"] * 1e3, color="#272727", lw=1.1)
        for criterion, point in picks.items():
            ax.axvline(point["frequency_Hz"] / 1e6, color=colors[criterion], lw=0.9, ls="--", label=criterion)
        ax.set_ylabel("P_Rm (mW)"); ax.set_title(case_id.replace("CASE_", ""), loc="left", fontsize=8)
    axes[0].legend(ncol=3, fontsize=6); axes[-1].set_xlabel("Frequency (MHz)")
    fig.suptitle("Three offline selection criteria on the initial 0.84-0.96 MHz scan")
    save_figure(fig, "stage3_selection_01_criteria_examples")

    power = [r for r in aggregate if r["criterion"] == "max_power"]
    error = np.array([[next(r for r in power if r["window_halfwidth_kHz"] == h and r["step_kHz"] == st)["max_total_error_vs_global_Hz"] / 1e3 for st in [0.1, 0.5, 1.0, 2.0]] for h in [20.0, 50.0, 100.0]])
    times = np.array([[next(r for r in power if r["window_halfwidth_kHz"] == h and r["step_kHz"] == st)["scan_time_proxy_ms"] for st in [0.1, 0.5, 1.0, 2.0]] for h in [20.0, 50.0, 100.0]])
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0))
    for ax, matrix, title, fmt in ((axes[0], error, "Worst total frequency error (kHz)", ".1f"), (axes[1], times, "Scan-time proxy (ms)", ".0f")):
        im = ax.imshow(matrix, cmap="Blues", aspect="auto")
        for i in range(matrix.shape[0]):
            for j in range(matrix.shape[1]): ax.text(j, i, format(matrix[i, j], fmt), ha="center", va="center", fontsize=7)
        ax.set_xticks(range(4), ["0.1", "0.5", "1", "2"]); ax.set_yticks(range(3), ["±20", "±50", "±100"])
        ax.set_xlabel("Step (kHz)"); ax.set_ylabel("Window (kHz)"); ax.set_title(title)
        fig.colorbar(im, ax=ax, fraction=0.045, pad=0.03)
    fig.suptitle("Maximum-power selection: accuracy vs scan duration across all scenarios")
    save_figure(fig, "stage3_selection_02_window_step_tradeoff")

    rows = [r for r in initial if r["case_id"] in selected_ids]
    x = np.arange(len(rows)); w = 0.23
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    for j, (criterion, color) in enumerate(colors.items()):
        ax.bar(x + (j - 1) * w, [r[f"{criterion}_frequency_Hz"] / 1e6 for r in rows], width=w, label=criterion, color=color)
    ax.set_xticks(x, [r["case_id"].replace("CASE_", "") for r in rows], rotation=18)
    ax.set_ylabel("Selected frequency (MHz)"); ax.set_ylim(0.84, 0.96); ax.legend(ncol=3, fontsize=7)
    fig.suptitle("The three 'best' frequencies are not generally identical")
    save_figure(fig, "stage3_selection_03_selected_frequency_comparison")


def write_report(initial: list[dict], aggregate: list[dict]) -> None:
    baseline = next(r for r in initial if r["case_id"] == "CASE_000_BASELINE")
    power_rows = [r for r in aggregate if r["criterion"] == "max_power"]
    recommended = min(
        [r for r in power_rows if r["global_optimum_excluded_cases"] == 0 and r["max_grid_frequency_error_Hz"] <= 500],
        key=lambda r: r["scan_time_proxy_ms"], default=None,
    )
    lines = [
        "# v2.1第三步：三种扫频选点准则与步长/窗口比较", "",
        "## 初始设置", "",
        f"- 扫频范围：0.84-0.96 MHz；步长：0.5 kHz；每点时间代理：{SCAN_POINT_TIME_S*1e3:.1f} ms。",
        "- 三种准则：最大运动支路有功、最小绝对输入相位、最小反射代理。", "",
        "## 基准场景结果", "",
        f"- 最大功率频率：{baseline['max_power_frequency_Hz']/1e6:.6f} MHz。",
        f"- 最小绝对相位频率：{baseline['min_abs_phase_frequency_Hz']/1e6:.6f} MHz。",
        f"- 最小反射频率：{baseline['min_reflection_frequency_Hz']/1e6:.6f} MHz。",
        "", "三个指标分别定义并输出，不能把相位零点直接当成功率最大点。", "",
        "## 精度与扫描时间", "",
    ]
    if recommended:
        lines.append(
            f"以全部28个活动场景、全局10 Hz参考网格为验收基准，满足窗口不漏掉最大功率点且离散误差不超过0.5 kHz的最快组合为："
            f"±{recommended['window_halfwidth_kHz']:.0f} kHz窗口、{recommended['step_kHz']:.1f} kHz步长，"
            f"{recommended['points']}点，扫描时间代理约{recommended['scan_time_proxy_ms']:.1f} ms。"
        )
    lines += [
        "", "窗口误差和步长误差必须分开：步长决定局部离散误差；窗口过窄会完全漏掉漂移后的全局最优点。",
        "当前结果只适用于活动v2.1线性模型与所列扰动范围。",
    ]
    (OUT / "stage3_selection_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = all_scenarios()
    initial = initial_rows(scenarios)
    tradeoffs = tradeoff_rows(scenarios)
    aggregate = aggregate_tradeoffs(tradeoffs)
    write_csv(OUT / "stage3_initial_three_criteria.csv", initial)
    write_csv(OUT / "stage3_window_step_all_cases.csv", tradeoffs)
    write_csv(OUT / "stage3_window_step_aggregate.csv", aggregate)
    make_figures(scenarios, initial, aggregate)
    write_report(initial, aggregate)
    audit = {
        "status": "PASS", "model_id": "MODEL_V2_1_HYPOTHETICAL", "scenario_count": len(scenarios),
        "initial_scan": {"start_Hz": INITIAL_START, "stop_Hz": INITIAL_STOP, "step_Hz": INITIAL_STEP},
        "reference_step_Hz": REFERENCE_STEP, "tested_steps_Hz": STEPS, "tested_half_windows_Hz": WINDOWS,
        "scan_point_time_proxy_s": SCAN_POINT_TIME_S,
        "scope": "offline quasi-steady electrical selection study; scan time is a declared proxy, not hardware timing",
    }
    (OUT / "stage3_selection_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "initial_rows": len(initial), "tradeoff_rows": len(tradeoffs)}, ensure_ascii=False))


if __name__ == "__main__": main()

