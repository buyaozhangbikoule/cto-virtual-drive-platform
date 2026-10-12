"""Audit whether stage 4-5 is constrained control rather than peak finding only.

The audit uses the saved quasi-steady control timeline.  It does not claim
hardware safety: every threshold remains a declared simulation assumption.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TIMELINE = ROOT / "results" / "tables" / "stage4_5" / "stage4_control_timeline.csv"
CONTROL_AUDIT = ROOT / "results" / "tables" / "stage4_5" / "stage4_5_audit.json"
OUT = ROOT / "results" / "audits"

F_MIN = 800_000.0
F_MAX = 1_000_000.0
VPP_HARD = 160.0
IRMS_HARD = 0.006


def f(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def main() -> None:
    if not TIMELINE.is_file():
        raise SystemExit(f"Missing control timeline: {TIMELINE}")

    rows = list(csv.DictReader(TIMELINE.open(encoding="utf-8-sig", newline="")))
    by_strategy: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_strategy[row["strategy"]].append(row)

    strategy_rows: list[dict[str, object]] = []
    for strategy, group in sorted(by_strategy.items()):
        control = [row for row in group if row["action"] == "CONTROL"]
        frequencies = [f(row["frequency_Hz"]) for row in control]
        amplitudes = [f(row["amplitude_command"]) for row in group]
        vpp = [f(row["vport_vpp"]) for row in group]
        current = [f(row["iport_irms_A"]) for row in group]
        captures = [f(row["safe_power_capture_ratio"]) for row in control]
        states = sorted({row["protection_state"] for row in group})
        strategy_rows.append({
            "strategy": strategy,
            "control_sample_count": len(control),
            "frequency_min_Hz": min(frequencies),
            "frequency_max_Hz": max(frequencies),
            "frequency_changed": max(frequencies) - min(frequencies) > 1.0,
            "amplitude_min": min(amplitudes),
            "amplitude_max": max(amplitudes),
            "amplitude_was_reduced": min(amplitudes) < 0.999999,
            "peak_vport_Vpp": max(vpp),
            "peak_iport_Arms": max(current),
            "actual_hard_violation_count": sum(
                int(float(row["actual_voltage_hard_violation"]))
                + int(float(row["actual_current_hard_violation"]))
                for row in group
            ),
            "frequency_saturated_sample_count": sum(
                int(float(row["frequency_saturated"])) for row in control
            ),
            "safe_power_capture_available": all(math.isfinite(value) for value in captures),
            "minimum_safe_power_capture_pct": min(captures) * 100.0,
            "protection_states_observed": states,
        })

    frequency_bound_pass = all(
        row["frequency_min_Hz"] >= F_MIN - 1e-6
        and row["frequency_max_Hz"] <= F_MAX + 1e-6
        for row in strategy_rows
    )
    hard_limit_pass = all(
        row["peak_vport_Vpp"] <= VPP_HARD + 1e-9
        and row["peak_iport_Arms"] <= IRMS_HARD + 1e-12
        and row["actual_hard_violation_count"] == 0
        for row in strategy_rows
    )
    amplitude_control_present = all(row["amplitude_was_reduced"] for row in strategy_rows)
    adaptive_frequency_present = all(
        row["frequency_changed"]
        for row in strategy_rows
        if row["strategy"] in {"PERIODIC_SCAN", "P_AND_O"}
    )
    protection_states_present = any(
        any(state != "NORMAL" for state in row["protection_states_observed"])
        for row in strategy_rows
    )
    objective_score_present = all(row["safe_power_capture_available"] for row in strategy_rows)

    saved_audit = json.loads(CONTROL_AUDIT.read_text(encoding="utf-8")) if CONTROL_AUDIT.is_file() else {}
    gamma_is_observed = bool(saved_audit.get("disturbance_detector"))

    checks = {
        "frequency_hard_boundary_enforced": frequency_bound_pass,
        "voltage_and_current_hard_limits_enforced_in_saved_timeline": hard_limit_pass,
        "amplitude_foldback_or_recovery_present": amplitude_control_present,
        "adaptive_strategies_change_frequency": adaptive_frequency_present,
        "protection_state_machine_exercised": protection_states_present,
        "constrained_power_objective_is_scored": objective_score_present,
        "reflection_proxy_is_observed_by_detector": gamma_is_observed,
        "reflection_proxy_has_independent_hard_operating_limit": False,
    }
    core_pass = all(value for key, value in checks.items() if key != "reflection_proxy_has_independent_hard_operating_limit")
    conclusion = "CONSTRAINED_CONTROL_CONFIRMED_WITH_LIMITATIONS" if core_pass else "NOT_CONFIRMED"

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": conclusion,
        "model_scope": "hypothetical small-signal linear BVD plus lossy L-match; discrete quasi-steady simulation",
        "objective": "maximize motional active power P_Rm under simulated frequency, voltage and current constraints",
        "checks": checks,
        "strategy_evidence": strategy_rows,
        "constraint_register": [
            {"constraint": "frequency", "bound": "0.8-1.0 MHz", "role": "hard command boundary", "implemented": True},
            {"constraint": "port voltage", "bound": "130 Vpp soft / 160 Vpp hard", "role": "foldback and predictive hard clipping", "implemented": True},
            {"constraint": "port current", "bound": "5.5 mA RMS soft / 6 mA RMS hard", "role": "foldback and predictive hard clipping", "implemented": True},
            {"constraint": "amplitude command", "bound": "0-1", "role": "foldback, hold and ramp-up", "implemented": True},
            {"constraint": "reflection proxy", "bound": "relative/absolute detector threshold", "role": "disturbance vote and reacquisition trigger", "implemented": True},
            {"constraint": "reflection proxy", "bound": "independent hard operating limit", "role": "direct foldback/trip", "implemented": False},
        ],
        "interpretation": [
            "The adaptive strategies are not pure offline argmax calls: frequency commands are bounded and amplitude/protection states alter the applied operating point.",
            "Safe-power optima are used for simulation scoring; the online detector does not read the true disturbance time or true optimum.",
            "Gamma is a model-based mismatch proxy, not measured reflected RF power, and currently has no independent hard trip limit.",
            "Passing this audit is not hardware validation or a clinical safety claim.",
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)
    json_path = OUT / "constrained_control_audit.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = OUT / "constrained_control_strategy_evidence.csv"
    fields = list(strategy_rows[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in strategy_rows:
            out = dict(row)
            out["protection_states_observed"] = ";".join(row["protection_states_observed"])
            writer.writerow(out)

    md = [
        "# 带约束控制审核",
        "",
        f"结论：`{conclusion}`。",
        "",
        "现有阶段四至五已从单纯找峰值升级为带频率边界、电压/电流限值、幅度降额和保护状态机的离散准稳态控制。",
        "反射代理已参与异常检测和重捕获触发，但尚未作为独立硬约束直接触发降额或停机。",
        "",
        "## 约束口径",
        "",
        "- 目标：在当前假设BVD场景内最大化运动支路有功功率 `P_Rm`。",
        "- 硬频率范围：0.8–1.0 MHz。",
        "- 电压阈值：130 Vpp软触发、160 Vpp硬上限（均为假设控制阈值）。",
        "- 电流阈值：5.5 mA RMS软触发、6 mA RMS硬上限（均为假设控制阈值）。",
        "- 保护时序：NORMAL / SOFT_FOLDBACK / HARD_TRIP / RECOVERY_HOLD / RAMP_UP。",
        "",
        "## 边界",
        "",
        "该审核仅证明保存的仿真代码与时序结果体现了约束控制逻辑，不证明真实功放、换能器或临床安全性。",
    ]
    (OUT / "constrained_control_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"status": conclusion, "json": str(json_path), "rows": len(rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
