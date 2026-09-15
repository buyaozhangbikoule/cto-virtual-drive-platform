"""Create a requirement-by-requirement audit for control and acoustic coupling."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "results" / "audits"


def read_rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    formal_path = ROOT / "results" / "tables" / "stage4_5" / "stage5_per_segment_metrics.csv"
    phase_path = ROOT / "results" / "phase_ablation" / "phase_per_segment_metrics.csv"
    formal = read_rows(formal_path)
    phase = read_rows(phase_path)
    periodic = {
        int(row["state_index"]): row for row in formal if row["strategy"] == "PERIODIC_SCAN" and int(row["state_index"]) > 0
    }
    selected_phase = {
        int(row["state_index"]): row for row in phase if float(row["gain_Hz_per_deg"]) == 5.0
    }

    comparison = []
    for index in sorted(set(periodic) & set(selected_phase)):
        scan = periodic[index]
        ph = selected_phase[index]
        phase_power_error = float(ph["steady_power_error_pct"])
        phase_abs_error = float(ph["steady_abs_phase_error_deg"])
        if abs(phase_power_error) <= 2.0 and phase_abs_error <= 0.5:
            interpretation = "相位闭环在本段可用；周期扫频仍更稳健，是否优先需加入扫描时间/能耗成本"
        elif abs(phase_power_error) <= 2.0:
            interpretation = "功率偶然接近最优但相位未收敛，不能据此认定相位闭环适合"
        else:
            interpretation = "当前相位目标/增益下不适合；周期扫频对该段更稳健"
        comparison.append({
            "state_index": index,
            "case_id": scan["case_id"],
            "periodic_scan_steady_power_error_pct": float(scan["steady_error_pct"]),
            "periodic_scan_recovery_time_ms": scan["recovery_time_ms"],
            "phase_K5_steady_power_error_pct": phase_power_error,
            "phase_K5_steady_abs_phase_error_deg": phase_abs_error,
            "phase_locked_frequency_MHz": float(ph["locked_frequency_MHz"]),
            "model_specific_interpretation": interpretation,
        })
    write_rows(OUT / "scan_vs_phase_scenario_comparison.csv", comparison)

    matrix = [
        {
            "requirement_id": "R1",
            "requirement": "同扰动序列固定频率/固定幅度基线，记录功率与相位偏离",
            "status": "COMPLETED",
            "evidence": "stage4_control_timeline.csv; stage5_per_segment_metrics.csv",
            "gap_or_boundary": "电压电流保护仍会覆盖固定幅度命令；这是受保护基线，不是无保护开环",
        },
        {
            "requirement_id": "R2",
            "requirement": "区分基线较差与模型出错",
            "status": "COMPLETED",
            "evidence": "stage1/stage2/stage3 LTspice RAW/LOG/audit and Python cross-validation",
            "gap_or_boundary": "只证明网表与解析实现一致，不证明假设参数等于真实器件",
        },
        {
            "requirement_id": "R3",
            "requirement": "局部扫频和相位闭环的锁定频率、恢复时间、峰值电流、功率变化",
            "status": "COMPLETED",
            "evidence": "plan_fixed_periodic_phase_per_segment.csv; plan_fixed_periodic_phase_integrated.csv",
            "gap_or_boundary": "相位结果仍标成消融/计划书补充，不替代正式P&O排名",
        },
        {
            "requirement_id": "R4",
            "requirement": "电压、电流或壁面代理约束触发时限制幅度增长",
            "status": "PARTIAL",
            "evidence": "voltage/current foldback, hard trip, hold and ramp-up are implemented",
            "gap_or_boundary": "没有COMSOL/实测壁面代理查找表和阈值，因此壁面代理尚未接入保护状态机",
        },
        {
            "requirement_id": "R5",
            "requirement": "同一单因素/组合扰动下比较固定、周期扫频、相位闭环",
            "status": "COMPLETED_AS_SUPPLEMENT",
            "evidence": "plan_fixed_periodic_phase_per_segment.csv; same representative single-factor/high-combined schedule",
            "gap_or_boundary": "比较覆盖共同代表时间表，不声称遍历全部34个场景；正式第三策略仍是扫描辅助P&O",
        },
        {
            "requirement_id": "R6",
            "requirement": "分析扫频与相位闭环适用场景并限制结论范围",
            "status": "COMPLETED_WITH_MODEL_SCOPE",
            "evidence": "scan_vs_phase_scenario_comparison.csv",
            "gap_or_boundary": "结论仅限当前假设BVD和代表扰动时间表，不能形成通用器械结论",
        },
        {
            "requirement_id": "R7",
            "requirement": "已有COMSOL结果时接入相对声学效率查找表",
            "status": "NOT_STARTED_NO_INPUT",
            "evidence": "none",
            "gap_or_boundary": "没有COMSOL模型/结果；不得生成声学效率和压力代理数值",
        },
        {
            "requirement_id": "R8",
            "requirement": "无COMSOL时定义标准化电学—声场接口字段",
            "status": "COMPLETED",
            "evidence": "interfaces/electro_acoustic_v1/*; electro_acoustic_interface_audit.json",
            "gap_or_boundary": "声学字段是空模板，状态明确为NOT_RUN/NOT_AVAILABLE",
        },
        {
            "requirement_id": "R9",
            "requirement": "逐条限制结论到特定BVD模型与扰动范围",
            "status": "COMPLETED",
            "evidence": "config.yaml scope; control/interface audits; README boundary statements",
            "gap_or_boundary": "汇报或论文仍需沿用这些限定语",
        },
        {
            "requirement_id": "R10",
            "requirement": "明确下一阶段阻抗、功率与水听器验证假设",
            "status": "COMPLETED_AS_PLAN_ONLY",
            "evidence": "docs/NEXT_STAGE_REAL_VALIDATION_PLAN.md",
            "gap_or_boundary": "尚未开展实测",
        },
    ]
    write_rows(OUT / "plan_control_coupling_requirement_matrix.csv", matrix)

    completed = sum(row["status"].startswith("COMPLETED") for row in matrix)
    partial = sum(row["status"] == "PARTIAL" for row in matrix)
    not_started = sum(row["status"].startswith("NOT_STARTED") for row in matrix)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_WITH_GAPS",
        "requirement_count": len(matrix),
        "completed_count": completed,
        "partial_count": partial,
        "not_started_count": not_started,
        "formal_strategy_set": ["FIXED_0P9", "PERIODIC_SCAN", "P_AND_O"],
        "phase_controller_role": "same-schedule ablation, not included in the formal three-strategy ranking",
        "comsol_or_ansys_result_available": False,
        "matrix": matrix,
    }
    (OUT / "plan_control_coupling_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# 计划书控制与声场耦合要求审核",
        "",
        f"总计{len(matrix)}项：完成{completed}项，部分完成{partial}项，未开始{not_started}项。",
        "",
        "|编号|状态|要求|缺口/边界|",
        "|---|---|---|---|",
    ]
    for row in matrix:
        lines.append(f"|{row['requirement_id']}|{row['status']}|{row['requirement']}|{row['gap_or_boundary']}|")
    lines += [
        "",
        "## 当前可成立的结论",
        "",
        "控制部分已经不是单纯找峰值，而是频率、幅度、电压/电流保护共同作用的离散准稳态约束控制。",
        "反射代理可触发异常重捕获，但不是独立硬约束；壁面代理因无声场数据尚未接入。",
        "正式三策略仍是固定频率、周期扫频和扫描辅助P&O；相位闭环只是同时间表消融，不能改名混入正式综合表。",
    ]
    (OUT / "plan_control_coupling_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "completed": completed, "partial": partial, "not_started": not_started}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
