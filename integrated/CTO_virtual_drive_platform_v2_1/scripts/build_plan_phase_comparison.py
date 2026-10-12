"""Build the plan-required fixed/scan/phase comparison from saved timelines.

This supplemental table does not replace the formal fixed/periodic/P&O table.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FORMAL = ROOT / "results" / "tables" / "stage4_5" / "stage5_per_segment_metrics.csv"
PHASE_TIMELINE = ROOT / "results" / "phase_ablation" / "phase_timeline_selected_gain.csv"
PHASE_SEGMENTS = ROOT / "results" / "phase_ablation" / "phase_per_segment_metrics.csv"
OUT = ROOT / "results" / "tables" / "stage4_5"
DT = 0.02
CAPTURE = 0.98
CONSECUTIVE = 10


def read(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))


def write(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def std(values: list[float]) -> float:
    m = mean(values)
    return math.sqrt(sum((value - m) ** 2 for value in values) / len(values))


def recovery_time(rows: list[dict[str, str]]) -> float | str:
    consecutive = 0
    candidate = None
    start = float(rows[0]["time_s"])
    previous = None
    for row in rows:
        t = float(row["time_s"])
        contiguous = previous is None or abs(t - previous - DT) < 1e-9
        ok = row["protection_state"] == "NORMAL" and float(row["safe_power_capture_ratio"]) >= CAPTURE
        if ok and contiguous:
            if consecutive == 0:
                candidate = t
            consecutive += 1
            if consecutive >= CONSECUTIVE:
                return max(0.0, float(candidate) - start) * 1e3
        else:
            consecutive = 0
            candidate = None
        previous = t
    return ""


def reversal_count(values: list[float]) -> int:
    signs = []
    for left, right in zip(values, values[1:]):
        delta = right - left
        if abs(delta) > 1e-9:
            signs.append(1 if delta > 0 else -1)
    return sum(a != b for a, b in zip(signs, signs[1:]))


def main() -> None:
    formal = read(FORMAL)
    timeline = [row for row in read(PHASE_TIMELINE) if float(row["gain_Hz_per_deg"]) == 5.0]
    phase_summary = {
        int(row["state_index"]): row
        for row in read(PHASE_SEGMENTS)
        if float(row["gain_Hz_per_deg"]) == 5.0
    }
    grouped: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in timeline:
        grouped[int(row["state_index"])].append(row)

    phase_rows = []
    for index, rows in sorted(grouped.items()):
        summary = phase_summary.get(index)
        tail = rows[-max(1, int(round(0.2 / DT))):]
        powers = [float(row["p_rm_W"]) for row in tail]
        captures = [float(row["safe_power_capture_ratio"]) for row in tail]
        frequencies = [float(row["frequency_Hz"]) for row in rows]
        capture_mean = mean(captures)
        recovery = 0.0 if index == 0 else recovery_time(rows)
        phase_rows.append({
            "strategy": "PHASE_K5_ABLATION",
            "state_index": index,
            "case_id": rows[0]["case_id"],
            "settled": int(recovery != ""),
            "recovery_time_ms": recovery,
            "steady_power_capture_pct": capture_mean * 100.0,
            "steady_error_pct": (1.0 - capture_mean) * 100.0,
            "power_stability_cv_pct": std(powers) / max(mean(powers), 1e-30) * 100.0,
            "locked_frequency_MHz": mean([float(row["frequency_MHz"]) for row in tail]),
            "steady_frequency_error_kHz": mean([
                (float(row["frequency_Hz"]) - float(row["optimal_safe_frequency_Hz"])) / 1e3 for row in tail
            ]),
            "peak_power_overshoot_pct": max(0.0, max(float(row["safe_power_capture_ratio"]) for row in rows) - 1.0) * 100.0,
            "peak_voltage_vpp": max(float(row["vport_vpp"]) for row in rows),
            "peak_current_mA_RMS": max(float(row["iport_irms_A"]) for row in rows) * 1e3,
            "soft_limit_triggers": sum(int(float(row["soft_limit_trigger"])) for row in rows),
            "hard_trip_triggers": sum(int(float(row["hard_trip_trigger"])) for row in rows),
            "actual_hard_violations": sum(
                int(float(row["vport_vpp"]) > 160.0 + 1e-9)
                + int(float(row["iport_irms_A"]) > 0.006 + 1e-12)
                for row in rows
            ),
            "frequency_saturation_ms": sum(int(float(row["frequency_saturated"])) for row in rows) * DT * 1e3,
            "frequency_reversals": reversal_count(frequencies),
            "oscillation_flag": int(reversal_count(frequencies) >= 4),
            "wrong_phase_lock_flag": 0 if summary is None else int(float(summary["wrong_phase_lock_flag"])),
            "scan_points": 0,
            "scan_time_ms": 0.0,
            "table_role": "PLAN_REQUIRED_SUPPLEMENT_NOT_FORMAL_RANKING",
        })

    keys = list(phase_rows[0].keys())
    supplemental = []
    for row in formal:
        if row["strategy"] not in {"FIXED_0P9", "PERIODIC_SCAN"}:
            continue
        converted = {key: row.get(key, "") for key in keys}
        converted["table_role"] = "PLAN_REQUIRED_SUPPLEMENT_NOT_FORMAL_RANKING"
        supplemental.append(converted)
    supplemental.extend(phase_rows)
    supplemental.sort(key=lambda row: (int(row["state_index"]), row["strategy"]))
    write(OUT / "plan_fixed_periodic_phase_per_segment.csv", supplemental)

    integrated = []
    for strategy in ["FIXED_0P9", "PERIODIC_SCAN", "PHASE_K5_ABLATION"]:
        rows = [row for row in supplemental if row["strategy"] == strategy and int(row["state_index"]) > 0]
        penalized_recovery = [float(row["recovery_time_ms"]) if row["recovery_time_ms"] != "" else 800.0 for row in rows]
        integrated.append({
            "strategy": strategy,
            "mean_steady_error_pct": mean([float(row["steady_error_pct"]) for row in rows]),
            "mean_recovery_time_ms_penalized": mean(penalized_recovery),
            "mean_power_stability_cv_pct": mean([float(row["power_stability_cv_pct"]) for row in rows]),
            "peak_current_mA_RMS": max(float(row["peak_current_mA_RMS"]) for row in rows),
            "soft_limit_triggers": sum(int(float(row["soft_limit_triggers"])) for row in rows),
            "hard_trip_triggers": sum(int(float(row["hard_trip_triggers"])) for row in rows),
            "actual_hard_violations": sum(int(float(row["actual_hard_violations"])) for row in rows),
            "frequency_saturation_ms": sum(float(row["frequency_saturation_ms"]) for row in rows),
            "wrong_phase_lock_segments": sum(int(float(row["wrong_phase_lock_flag"])) for row in rows),
            "settled_segments": sum(int(float(row["settled"])) for row in rows),
            "evaluated_segments": len(rows),
            "table_role": "PLAN_REQUIRED_SUPPLEMENT_NOT_FORMAL_RANKING",
        })
    write(OUT / "plan_fixed_periodic_phase_integrated.csv", integrated)
    print(f"PASS: {len(supplemental)} segment rows, {len(integrated)} strategy rows")


if __name__ == "__main__":
    main()
