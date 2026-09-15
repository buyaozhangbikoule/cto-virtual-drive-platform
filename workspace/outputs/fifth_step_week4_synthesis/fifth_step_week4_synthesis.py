"""Step 5 / Week 4 synthesis.

Build a final comparison table from Step 4 LTspice-RAW-based controller results
and include the Step 2 single-factor scan as prerequisite evidence.
"""

from pathlib import Path
import csv
import json
import math
import shutil

ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
OUTDIR = ROOT / "outputs" / "fifth_step_week4_synthesis"
STEP4 = ROOT / "outputs" / "fourth_step_control_strategies"
STEP2 = ROOT / "outputs" / "single_factor_disturbance_results"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def fnum(row, key, default=0.0):
    val = row.get(key, "")
    if val == "" or val is None:
        return default
    return float(val)


def inum(row, key, default=0):
    val = row.get(key, "")
    if val == "" or val is None:
        return default
    return int(float(val))


def classify_oscillation(strategy_rows, state_metrics):
    max_jitter = max(fnum(m, "稳态频率抖动_kHz") for m in state_metrics)
    reversals = sum(inum(m, "频率方向反转次数") for m in state_metrics)
    if max_jitter >= 1.0 or reversals >= 20:
        return "是"
    if max_jitter >= 0.2 or reversals > 0:
        return "轻微"
    return "否"


def locked_frequency_summary(strategy_rows):
    # State-lock frequency: mean of last 5 steps in each state.
    by_state = {}
    for r in strategy_rows:
        by_state.setdefault(inum(r, "state_index"), []).append(r)
    locks = []
    for state, rows in sorted(by_state.items()):
        tail = rows[-5:]
        locks.append(sum(fnum(r, "frequency_mhz") for r in tail) / len(tail))
    return min(locks), sum(locks) / len(locks), max(locks)


def peak_overshoot(strategy_rows):
    # Frequency overshoot beyond that state's max-power frequency.
    return max(abs(fnum(r, "power_frequency_error_kHz")) for r in strategy_rows)


def power_stability(strategy_rows):
    captures = [fnum(r, "power_capture_pct") for r in strategy_rows]
    mean = sum(captures) / len(captures)
    var = sum((x - mean) ** 2 for x in captures) / len(captures)
    return math.sqrt(var), min(captures), mean


def erroneous_phase_lock(strategy_rows, state_metrics):
    # Wrong lock: last 5 steps have low phase error while power capture is poor
    # or the operating frequency remains far from the max-power point.
    wrong_states = []
    by_state = {}
    for r in strategy_rows:
        by_state.setdefault(inum(r, "state_index"), []).append(r)
    for state, rows in sorted(by_state.items()):
        tail = rows[-5:]
        phase_abs = sum(abs(fnum(r, "phase_deg")) for r in tail) / len(tail)
        capture = sum(fnum(r, "power_capture_pct") for r in tail) / len(tail)
        freq_err = sum(abs(fnum(r, "power_frequency_error_kHz")) for r in tail) / len(tail)
        if phase_abs <= 2.0 and (capture < 80.0 or freq_err >= 10.0):
            wrong_states.append((state, tail[0]["序列标签"], phase_abs, capture, freq_err))
    return wrong_states


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    overview = read_csv(STEP4 / "第四步_三策略总览.csv")
    timeseries = read_csv(STEP4 / "第四步_控制时序明细.csv")
    state_metrics = read_csv(STEP4 / "第四步_逐状态收敛与振荡指标.csv")
    gain_scan = read_csv(STEP4 / "第四步_相位跟踪增益扫描.csv")
    response = read_csv(STEP4 / "第四步_LTspice响应表_场景特征.csv")
    single_trends = read_csv(STEP2 / "单因素扰动_趋势表.csv")
    single_fixed = read_csv(STEP2 / "单因素扰动_固定0p9MHz指标.csv")
    single_features = read_csv(STEP2 / "单因素扰动_特征汇总.csv")

    ts_by_strategy = {}
    for r in timeseries:
        ts_by_strategy.setdefault(r["strategy"], []).append(r)
    sm_by_strategy = {}
    for r in state_metrics:
        sm_by_strategy.setdefault(r["strategy"], []).append(r)

    synthesis = []
    wrong_lock_rows = []
    for row in overview:
        strategy = row["控制策略"]
        srows = ts_by_strategy[strategy]
        mrows = sm_by_strategy[strategy]
        lock_min, lock_mean, lock_max = locked_frequency_summary(srows)
        stability_std, worst_capture, mean_capture = power_stability(srows)
        wrong_states = erroneous_phase_lock(srows, mrows)
        for state, label, phase_abs, capture, freq_err in wrong_states:
            wrong_lock_rows.append({
                "策略": strategy,
                "state_index": state,
                "序列标签": label,
                "稳态相位误差_abs_deg": phase_abs,
                "稳态功率恢复_pct": capture,
                "稳态功率频率误差_abs_kHz": freq_err,
                "判据": "相位误差≤2°且功率恢复<80%或偏离功率峰≥10kHz",
            })
        synthesis.append({
            "策略": strategy,
            "稳态误差_功率频率误差_kHz": f"{fnum(row, '平均稳态功率频率误差_kHz'):.2f}",
            "稳态误差_相位_deg": f"{fnum(row, '平均稳态相位误差_deg'):.2f}",
            "恢复时间_平均步数": f"{fnum(row, '平均收敛步数'):.2f}",
            "未收敛状态数": inum(row, "未收敛状态数"),
            "功率稳定性_std_pct": f"{stability_std:.2f}",
            "平均功率恢复_pct": f"{mean_capture:.2f}",
            "最差功率恢复_pct": f"{worst_capture:.2f}",
            "峰值电流_mApeak": f"{max(fnum(r, 'transducer_current_mA_peak') for r in srows):.3f}",
            "约束触发_软电流": inum(row, "软电流约束触发次数"),
            "约束触发_硬电流": inum(row, "硬电流约束触发次数"),
            "约束触发_硬电压": inum(row, "硬电压约束触发次数"),
            "约束触发_任一硬约束": inum(row, "任一硬约束触发次数"),
            "频率饱和_步数": inum(row, "频率上下限饱和步数"),
            "锁定频率_min_MHz": f"{lock_min:.6f}",
            "锁定频率_mean_MHz": f"{lock_mean:.6f}",
            "锁定频率_max_MHz": f"{lock_max:.6f}",
            "峰值过冲_相对功率峰_kHz": f"{peak_overshoot(srows):.2f}",
            "是否振荡": classify_oscillation(srows, mrows),
            "是否错误锁定到相位零点但功率较低": "是" if wrong_states else "否",
            "错误锁定状态数": len(wrong_states),
            "控制开销_扫频测点数": inum(row, "总扫频测点数_控制开销代理"),
            "综合判定": (
                "功率恢复最佳，但需要扫频开销"
                if strategy == "周期性局部扫频"
                else "简单但对失配/漂移恢复不足"
                if strategy == "固定频率固定幅度"
                else "相位误差小但存在错误锁定风险，不宜单独作为功率最大化控制"
            ),
        })

    prerequisite = []
    for r in single_trends:
        prerequisite.append({
            "参数变化": r["参数变化"],
            "主要影响峰位": r["主要影响峰位"],
            "主要影响峰高": r["主要影响峰高"],
            "主要影响峰宽": r["主要影响峰宽"],
            "固定0p9MHz功率最大变化_pct": r["固定0p9MHz功率最大变化_pct"],
            "结论用途": "用于解释组合扰动和设计扫频/相位控制器",
        })

    write_csv(OUTDIR / "第五步_第4周综合比较表.csv", synthesis)
    write_csv(OUTDIR / "第五步_错误锁定明细.csv", wrong_lock_rows or [{
        "策略": "无",
        "state_index": "",
        "序列标签": "",
        "稳态相位误差_abs_deg": "",
        "稳态功率恢复_pct": "",
        "稳态功率频率误差_abs_kHz": "",
        "判据": "无错误锁定",
    }])
    write_csv(OUTDIR / "第五步_单因素扫描前置验收表.csv", prerequisite)
    write_csv(OUTDIR / "第五步_相位增益扫描复核表.csv", gain_scan)
    shutil.copy2(STEP4 / "第四步_三策略总览.csv", OUTDIR / "source_第四步_三策略总览.csv")
    shutil.copy2(STEP4 / "第四步_逐状态收敛与振荡指标.csv", OUTDIR / "source_第四步_逐状态指标.csv")
    shutil.copy2(STEP4 / "第四步_LTspice响应表_场景特征.csv", OUTDIR / "source_第四步_LTspice响应特征.csv")
    shutil.copy2(STEP2 / "单因素扰动_趋势表.csv", OUTDIR / "source_第二步_单因素趋势表.csv")
    shutil.copy2(STEP2 / "单因素扰动_固定0p9MHz指标.csv", OUTDIR / "source_第二步_固定0p9MHz指标.csv")
    shutil.copy2(STEP2 / "单因素扰动_特征汇总.csv", OUTDIR / "source_第二步_特征汇总.csv")

    report_lines = [
        "# 第五步：第4周综合比较",
        "",
        "## 1. 前置条件检查",
        "",
        "用户提出的当前最直接任务——`C0、Rm、fs、Rs/匹配参数、ESR` 的单因素三等级扫描——已经在第二步完成，并包含峰位、峰高、峰宽与固定0.9 MHz指标。第五步直接引用该前置结果，不再重复仿真。",
        "",
        "单因素结论简表：",
        "",
        "| 参数变化 | 主要影响峰位 | 主要影响峰高 | 主要影响峰宽 |",
        "|---|---|---|---|",
    ]
    for r in prerequisite:
        report_lines.append(f"| {r['参数变化']} | {r['主要影响峰位']} | {r['主要影响峰高']} | {r['主要影响峰宽']} |")
    report_lines.extend([
        "",
        "## 2. 第4周综合比较表",
        "",
        "| 策略 | 稳态误差 | 恢复时间 | 功率稳定性 | 峰值电流 | 约束触发 | 频率饱和 | 锁定频率 | 峰值过冲 | 振荡 | 错误锁定 |",
        "|---|---:|---:|---:|---:|---|---:|---|---:|---|---|",
    ])
    for r in synthesis:
        constraints = f"软I {r['约束触发_软电流']} / 硬I {r['约束触发_硬电流']} / 硬V {r['约束触发_硬电压']}"
        lock = f"{r['锁定频率_min_MHz']}–{r['锁定频率_max_MHz']} MHz"
        report_lines.append(
            f"| {r['策略']} | {r['稳态误差_功率频率误差_kHz']} kHz / {r['稳态误差_相位_deg']}° | "
            f"{r['恢复时间_平均步数']} 步 | std {r['功率稳定性_std_pct']}% | {r['峰值电流_mApeak']} mApeak | "
            f"{constraints} | {r['频率饱和_步数']} | {lock} | {r['峰值过冲_相对功率峰_kHz']} kHz | "
            f"{r['是否振荡']} | {r['是否错误锁定到相位零点但功率较低']} |"
        )
    report_lines.extend([
        "",
        "## 3. 解释",
        "",
        "- 固定频率固定幅度：实现最简单、无扫频开销，但在 fs 漂移和高复杂度组合扰动下会明显偏离最大功率点。",
        "- 周期性局部扫频：功率恢复和稳定性最好，且没有频率饱和，但控制开销最高。",
        "- 相位误差离散跟踪：相位误差最小，但会错误锁定到相位零点附近；这些点不一定是最大功率点，因此功率恢复很差，并伴随振荡/方向反转。",
        "",
        "## 4. 错误锁定判据",
        "",
        "若某状态最后5步平均 `|phase| ≤ 2°`，但功率恢复 `<80%` 或与最大功率频率偏差 `≥10 kHz`，判为“错误锁定到相位零点但功率较低”。",
        "",
        "## 5. 建议",
        "",
        "第4周报告应把周期性局部扫频作为当前最佳功率恢复策略；相位跟踪只能作为阻抗相位辅助指标，不能单独作为功率最大化控制。下一轮应加入“扫频选功率点 + 电压/电流约束限幅”的第四策略。",
        "",
    ])
    (OUTDIR / "第五步_第4周综合比较报告.md").write_text("\n".join(report_lines), encoding="utf-8")

    manifest = {
        "source_step4": str(STEP4),
        "source_step2": str(STEP2),
        "single_factor_prerequisite": "completed",
        "wrong_lock_rule": "|phase|<=2 deg and (power capture <80% or max-power frequency error >=10 kHz)",
        "synthesis_rows": len(synthesis),
        "wrong_lock_rows": len(wrong_lock_rows),
    }
    (OUTDIR / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"outdir={OUTDIR}")
    for r in synthesis:
        print(r["策略"], r["平均功率恢复_pct"], r["是否振荡"], r["是否错误锁定到相位零点但功率较低"], r["错误锁定状态数"])


if __name__ == "__main__":
    main()
