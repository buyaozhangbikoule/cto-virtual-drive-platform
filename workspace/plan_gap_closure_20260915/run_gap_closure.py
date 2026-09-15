"""补齐计划书条款缺口 1、3、4（见 docs/05_计划书符合性审核_2026-09-15.md 第 5 节）。

1. 选频表加 V/I 约束检查      -> gap1_selection_with_constraints.csv
3. 扰动表加 fp / |Z|极大      -> gap3_resonance_pair_drift.csv
4. 电压峰 != 功率峰 的明确结论 -> gap4_voltage_vs_power_peak.csv

本批次【只写入自己的 outputs/ 目录】，不重跑、不覆盖 active_stage3_5 下的任何历史结果。
口径与 run_stage3_selection.py 一致：0.84-0.96 MHz、500 Hz 步长、amplitude=1。

    python3 workspace/plan_gap_closure_20260915/run_gap_closure.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ACTIVE = HERE.parent / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5"
sys.path.insert(0, str(ACTIVE))
import model_v2_1 as m  # noqa: E402

# 与 run_stage3_selection.py 相同的扫描口径
INITIAL_START, INITIAL_STOP, INITIAL_STEP = 0.84e6, 0.96e6, 0.5e3
CRITERIA = ("max_power", "min_abs_phase", "min_reflection")
DENSE = np.linspace(m.F_MIN, m.F_MAX, 400001)


def grid(start: float, stop: float, step: float) -> np.ndarray:
    return start + np.arange(int(round((stop - start) / step)) + 1) * step


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        w = csv.DictWriter(handle, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def pick_index(q: dict, criterion: str) -> int:
    if criterion == "max_power":
        return int(np.argmax(q["p_rm_W"]))
    if criterion == "min_abs_phase":
        return int(np.argmin(np.abs(q["phase_deg"])))
    return int(np.argmin(q["gamma"]))


# ---------------------------------------------------------------- 缺口 1
def gap1_selection_with_constraints() -> list[dict]:
    """三准则选点 + 计划书第 3 周要求的 V/I 约束检查。

    计划书原文：「设定电压、电流和功率的相对上限，作为控制器不得越过的模型内部约束。」
    原选频表在 amplitude=1 下评估，未施加该约束。这里补上三件事：
      - 该点在 a=1 下是否越软/硬限
      - 该点允许的最大幅度（受 V/I 约束）
      - 施加约束后该点【实际可交付】的功率
    并额外给出「约束内最优」的一列，即只在合规频率中选点的结果。
    """
    rows = []
    f = grid(INITIAL_START, INITIAL_STOP, INITIAL_STEP)
    for s in m.all_scenarios():
        q = m.response(f, s, 1.0)
        a_soft = m.allowed_amplitude(f, s, use_soft_limits=True)
        a_hard = m.allowed_amplitude(f, s, use_soft_limits=False)
        # 约束内可交付功率：把幅度推到软限允许的最大值
        deliverable = q["p_rm_W"] * a_soft**2
        row = {"case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level}
        for c in CRITERIA:
            i = pick_index(q, c)
            row[f"{c}_frequency_Hz"] = float(f[i])
            row[f"{c}_vport_vpp_at_a1"] = float(q["vport_vpp"][i])
            row[f"{c}_iport_irms_A_at_a1"] = float(q["iport_irms_A"][i])
            row[f"{c}_exceeds_V_soft"] = int(q["vport_vpp"][i] > m.VPP_SOFT)
            row[f"{c}_exceeds_V_hard"] = int(q["vport_vpp"][i] > m.VPP_HARD)
            row[f"{c}_exceeds_I_soft"] = int(q["iport_irms_A"][i] > m.IRMS_SOFT)
            row[f"{c}_exceeds_I_hard"] = int(q["iport_irms_A"][i] > m.IRMS_HARD)
            row[f"{c}_admissible_at_a1"] = int(
                q["vport_vpp"][i] <= m.VPP_HARD and q["iport_irms_A"][i] <= m.IRMS_HARD
            )
            row[f"{c}_max_allowed_amplitude_soft"] = float(a_soft[i])
            row[f"{c}_max_allowed_amplitude_hard"] = float(a_hard[i])
            row[f"{c}_p_rm_W_at_a1"] = float(q["p_rm_W"][i])
            row[f"{c}_deliverable_p_rm_W"] = float(deliverable[i])
        # 约束内最优：只在 a=1 下合规的频率中选功率最大者
        ok = (q["vport_vpp"] <= m.VPP_HARD) & (q["iport_irms_A"] <= m.IRMS_HARD)
        if ok.any():
            j = int(np.argmax(np.where(ok, deliverable, -np.inf)))
            row["constrained_best_frequency_Hz"] = float(f[j])
            row["constrained_best_deliverable_p_rm_W"] = float(deliverable[j])
        else:
            row["constrained_best_frequency_Hz"] = math.nan
            row["constrained_best_deliverable_p_rm_W"] = math.nan
        rows.append(row)
    return rows


# ---------------------------------------------------------------- 缺口 3
def gap3_resonance_pair_drift() -> list[dict]:
    """串联与并联谐振点【成对】记录，含反谐振漂移。

    计划书第四章：「既要观察串联谐振，也要观察并联谐振特征；不能只以阻抗最低
    作为唯一工作点判据。」第六章把「串联/并联谐振点的漂移」列为分析指标。
    原扰动汇总表 47 列中只有 zin_abs_min_Hz，没有任何并联谐振列。
    """
    base = m.scenario_map()["CASE_000_BASELINE"]
    zb0 = np.abs(m.response(DENSE, base, 1.0)["z_bvd"])
    fs0 = float(DENSE[int(np.argmin(zb0))])
    fp0 = float(DENSE[int(np.argmax(zb0))])
    rows = []
    for s in m.all_scenarios():
        q = m.response(DENSE, s, 1.0)
        zb = np.abs(q["z_bvd"])
        zin = np.abs(q["z_in"])
        i_min, i_max = int(np.argmin(zb)), int(np.argmax(zb))
        b = s.bvd
        fp_theory = b.fs * math.sqrt(1 + b.cm / b.c0)
        rows.append({
            "case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level,
            "fs_declared_Hz": float(b.fs),
            "fs_measured_Hz": float(DENSE[i_min]),
            "zbvd_abs_min_ohm": float(zb[i_min]),
            "fp_theory_Hz": float(fp_theory),
            "fp_measured_Hz": float(DENSE[i_max]),
            "zbvd_abs_max_ohm": float(zb[i_max]),
            "fp_minus_fs_Hz": float(DENSE[i_max] - DENSE[i_min]),
            "fs_drift_from_baseline_Hz": float(DENSE[i_min] - fs0),
            "fp_drift_from_baseline_Hz": float(DENSE[i_max] - fp0),
            "zin_abs_min_Hz": float(DENSE[int(np.argmin(zin))]),
            "zin_abs_max_Hz": float(DENSE[int(np.argmax(zin))]),
            "zin_abs_max_ohm": float(zin.max()),
            "cm_over_c0": float(b.cm / b.c0),
            "k_eff_percent": float(math.sqrt((b.cm / b.c0) / (1 + b.cm / b.c0)) * 100),
        })
    return rows


# ---------------------------------------------------------------- 缺口 4
def gap4_voltage_vs_power_peak() -> list[dict]:
    """「电压最大并不必然意味着有功功率最大」——计划书第 2 周点名要求的认识。

    数据一直存在，但从未被写成一条明确结论。这张表把两个峰逐场景并排列出，
    并标注电压峰是否已越过导师给定的 160 Vpp 硬上限。
    """
    rows = []
    for s in m.all_scenarios():
        q = m.response(DENSE, s, 1.0)
        iv = int(np.argmax(q["vport_vpp"]))
        ip = int(np.argmax(q["p_rm_W"]))
        rows.append({
            "case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level,
            "voltage_peak_Hz": float(DENSE[iv]),
            "voltage_peak_vport_vpp": float(q["vport_vpp"][iv]),
            "voltage_peak_p_rm_W": float(q["p_rm_W"][iv]),
            "power_peak_Hz": float(DENSE[ip]),
            "power_peak_vport_vpp": float(q["vport_vpp"][ip]),
            "power_peak_p_rm_W": float(q["p_rm_W"][ip]),
            "separation_Hz": float(DENSE[iv] - DENSE[ip]),
            "power_at_voltage_peak_ratio": float(q["p_rm_W"][iv] / q["p_rm_W"][ip]),
            "voltage_peak_exceeds_V_hard": int(q["vport_vpp"][iv] > m.VPP_HARD),
        })
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    g1, g3, g4 = gap1_selection_with_constraints(), gap3_resonance_pair_drift(), gap4_voltage_vs_power_peak()
    write_csv(OUT / "gap1_selection_with_constraints.csv", g1)
    write_csv(OUT / "gap3_resonance_pair_drift.csv", g3)
    write_csv(OUT / "gap4_voltage_vs_power_peak.csv", g4)

    audit = {
        "status": "PASS",
        "batch": "plan_gap_closure_20260915",
        "model_source_class": "ASSUMED_BASELINE; 与 active_stage3_5 同一模型，未改动任何参数",
        "drive_mode": f"FROZEN_A1 (SOURCE_MAX_AMPLITUDE={m.SOURCE_MAX_AMPLITUDE})",
        "gap1_selection_constraints": {
            c: {
                "exceeds_V_hard": sum(r[f"{c}_exceeds_V_hard"] for r in g1),
                "exceeds_V_soft": sum(r[f"{c}_exceeds_V_soft"] for r in g1),
                "exceeds_I_hard": sum(r[f"{c}_exceeds_I_hard"] for r in g1),
                "max_vport_vpp": max(r[f"{c}_vport_vpp_at_a1"] for r in g1),
                "mean_deliverable_p_rm_mW": sum(r[f"{c}_deliverable_p_rm_W"] for r in g1) / len(g1) * 1e3,
            } for c in CRITERIA
        },
        "gap3_resonance": {
            "scenarios_with_resolvable_fp": sum(1 for r in g3 if r["fp_minus_fs_Hz"] > 0),
            "fp_minus_fs_range_Hz": [min(r["fp_minus_fs_Hz"] for r in g3), max(r["fp_minus_fs_Hz"] for r in g3)],
            "max_abs_fp_drift_Hz": max(abs(r["fp_drift_from_baseline_Hz"]) for r in g3),
        },
        "gap4_voltage_vs_power": {
            "scenarios_where_peaks_differ": sum(1 for r in g4 if abs(r["separation_Hz"]) > 1.0),
            "scenarios_where_voltage_peak_exceeds_hard_limit": sum(r["voltage_peak_exceeds_V_hard"] for r in g4),
            "min_power_ratio_at_voltage_peak": min(r["power_at_voltage_peak_ratio"] for r in g4),
        },
        "note": "本批次不重跑也不覆盖 active_stage3_5 下的历史结果；仅新增派生表。",
    }
    (OUT / "gap_closure_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
