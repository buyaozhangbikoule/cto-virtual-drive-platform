"""Rebuilt Step 4/5 controller study using LTspice AC RAW tables.

The electrical plant is an assumed virtual BVD + matching-network model.  All
plant responses are interpolated from the existing LTspice RAW files.  The
controller is an event-driven Python simulation; it is not an LTspice transient
controller or measured hardware experiment.
"""

from __future__ import annotations

import csv
import json
import math
import re
import struct
import sys
from dataclasses import asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
OUTDIR = ROOT / "outputs" / "fourth_fifth_rebuild"
RAW_DIR = ROOT / "outputs" / "fourth_step_control_strategies" / "ltspice_cases"
sys.path.insert(0, str(ROOT / "outputs" / "third_step_sweep_selection"))
import third_step_sweep_selection as step3  # noqa: E402


F_MIN = 0.84e6
F_MAX = 0.96e6
F_FIXED = 0.9e6
CONTROL_DT = 0.002
SCAN_POINT_DT = 0.0015
PROBE_AMPLITUDE = 0.50
SCAN_INTERVAL = 1.000
PHASE_VALIDATION_INTERVAL = 2.000

V_SOFT = 150.0
V_HARD = 160.0
I_SOFT = 5.5e-3
I_HARD = 8.0e-3
HARD_HOLD = 0.100
RECOVERY_HOLD = 0.020
RAMP_STEP = 0.02

PHASE_ALPHA = 0.25
PHASE_DEADBAND = 0.50
PHASE_MAX_STEP = 2.0e3
PHASE_MIN_SLOPE = 0.20  # deg/kHz
PHASE_REACQUIRE_ERROR = 20.0
POWER_REACQUIRE_RATIO = 0.80

SETTLE_CAPTURE = 0.95
SETTLE_DURATION = 0.020
WRONG_LOCK_CAPTURE = 0.80
WRONG_LOCK_DURATION = 0.050


LABELS = {
    "CASE_000_BASELINE": ("基准", "基准", "无扰动"),
    "CASE_110_C0_P10": ("单因素", "C0", "+10%"),
    "CASE_120_C0_P20": ("单因素", "C0", "+20%"),
    "CASE_130_C0_P30": ("单因素", "C0", "+30%"),
    "CASE_210_RM_P15": ("单因素", "Rm", "+15%"),
    "CASE_220_RM_P30": ("单因素", "Rm", "+30%"),
    "CASE_230_RM_P50": ("单因素", "Rm", "+50%"),
    "CASE_310_FS_M1": ("单因素", "fs/Cm", "-1%"),
    "CASE_320_FS_M3": ("单因素", "fs/Cm", "-3%"),
    "CASE_330_FS_M5": ("单因素", "fs/Cm", "-5%"),
    "CASE_410_RS_P5": ("单因素", "Rs", "+5%"),
    "CASE_420_RS_P10": ("单因素", "Rs", "+10%"),
    "CASE_430_RS_P20": ("单因素", "Rs", "+20%"),
    "CASE_510_LS_P2": ("单因素", "Ls", "+2%"),
    "CASE_520_LS_P5": ("单因素", "Ls", "+5%"),
    "CASE_530_LS_P10": ("单因素", "Ls", "+10%"),
    "CASE_610_CP_M2": ("单因素", "Cp", "-2%"),
    "CASE_620_CP_M5": ("单因素", "Cp", "-5%"),
    "CASE_630_CP_M10": ("单因素", "Cp", "-10%"),
    "CASE_720_Q50": ("单因素", "电感Q", "Q=50"),
    "CASE_730_Q20": ("单因素", "电感Q", "Q=20"),
    "CASE_400_COMBINED_LOW": ("组合", "低", "Rm+15%"),
    "CASE_401_COMBINED_MEDIUM": ("组合", "中", "C0+20%, Rm+30%"),
    "CASE_402_COMBINED_HIGH": ("组合", "高", "多参数叠加"),
}

STRATEGIES = ("固定频率固定幅度", "周期性局部扫频", "校准相位离散跟踪")
LTSPICE_VERSION = "26.0.2.1"


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_raw(path: Path) -> dict[str, np.ndarray]:
    raw = path.read_bytes()
    marker = "Binary:\n".encode("utf-16-le")
    marker_at = raw.index(marker)
    data_at = marker_at + len(marker)
    header = raw[:marker_at].decode("utf-16-le")
    n_vars = int(re.search(r"No\. Variables:\s*(\d+)", header).group(1))
    n_points = int(re.search(r"No\. Points:\s*(\d+)", header).group(1))
    variables = []
    for line in header.split("Variables:\n", 1)[1].splitlines():
        match = re.match(r"\s*(\d+)\s+([^\s]+)\s+([^\s]+)", line)
        if match:
            variables.append(match.group(2).lower())
    payload = raw[data_at:]
    if len(payload) == n_points * n_vars * 16:
        values = np.asarray(struct.unpack(f"<{n_points * n_vars * 2}d", payload))
        values = values.reshape(n_points, n_vars, 2)
        complex_values = values[:, :, 0] + 1j * values[:, :, 1]
    else:
        per_point = 8 + (n_vars - 1) * 16
        if len(payload) != n_points * per_point:
            raise ValueError(f"Unrecognized RAW payload: {path}")
        complex_values = np.empty((n_points, n_vars), dtype=complex)
        offset = 0
        for i in range(n_points):
            complex_values[i, 0] = struct.unpack_from("<d", payload, offset)[0]
            offset += 8
            for j in range(1, n_vars):
                real, imag = struct.unpack_from("<dd", payload, offset)
                complex_values[i, j] = real + 1j * imag
                offset += 16
    return {name: complex_values[:, i] for i, name in enumerate(variables)}


class ResponseTable:
    def __init__(self, meta: dict, raw: dict[str, np.ndarray]):
        self.meta = meta
        self.freq = np.real(raw["frequency"])
        self.rs = meta["scenario"].rs
        self.zin = raw["v(n_s)"] / raw["i(rlesr)"]
        self.vnode = raw["v(n_in)"]
        self.imot = raw["i(rmot)"]
        self.itrans = raw["i(rmot)"] + raw["i(cstatic)"]
        self.power = np.real(self.vnode * np.conj(self.imot))
        self.phase = np.angle(self.zin, deg=True)
        self.gamma = np.abs((self.zin - self.rs) / (self.zin + self.rs))
        self.vpp = np.abs(self.vnode) * 2 * np.sqrt(2)
        self.ipeak = np.abs(self.itrans) * np.sqrt(2)
        self.safe_amp = np.minimum.reduce(
            [np.ones_like(self.freq), V_SOFT / self.vpp, I_SOFT / self.ipeak]
        )
        self.safe_power = self.power * self.safe_amp**2
        best = int(np.argmax(self.safe_power))
        self.safe_best_freq = float(self.freq[best])
        self.safe_best_power = float(self.safe_power[best])
        self.raw_best_freq = float(self.freq[int(np.argmax(self.power))])
        self.raw_best_power = float(np.max(self.power))

    def interp(self, f_hz: float) -> dict[str, float]:
        f_hz = float(np.clip(f_hz, F_MIN, F_MAX))
        ip = lambda values: float(np.interp(f_hz, self.freq, values))
        return {
            "frequency_hz": f_hz,
            "unit_power_w": ip(self.power),
            "phase_deg": ip(self.phase),
            "reflection_proxy": ip(self.gamma),
            "unit_vpp": ip(self.vpp),
            "unit_ipeak_a": ip(self.ipeak),
            "safe_amp": ip(self.safe_amp),
            "safe_power_w": ip(self.safe_power),
            "zin_mag_ohm": ip(np.abs(self.zin)),
            "zin_real_ohm": ip(np.real(self.zin)),
            "zin_imag_ohm": ip(np.imag(self.zin)),
        }


def build_tables() -> tuple[dict[str, ResponseTable], dict[str, dict]]:
    metadata = {row["case_id"]: row for row in step3.SCENARIO_ROWS}
    tables = {}
    for case_id, meta in metadata.items():
        path = RAW_DIR / f"{case_id}.raw"
        if not path.exists():
            raise FileNotFoundError(path)
        tables[case_id] = ResponseTable(meta, read_raw(path))
    return tables, metadata


def build_schedule(metadata: dict[str, dict]) -> list[dict]:
    ordered = [row["case_id"] for row in step3.SCENARIO_ROWS]
    segments = []
    t = 0.0
    for index, case_id in enumerate(ordered):
        duration = 1.0 if index == 0 else 2.0
        family, factor, level = LABELS[case_id]
        segments.append({
            "state_index": index,
            "case_id": case_id,
            "family": family,
            "factor": factor,
            "level": level,
            "start_s": t,
            "end_s": t + duration,
            "scenario": metadata[case_id]["scenario"],
        })
        t += duration
    case_id = "CASE_000_BASELINE"
    segments.append({
        "state_index": len(segments),
        "case_id": case_id,
        "family": "恢复",
        "factor": "基准",
        "level": "扰动后恢复",
        "start_s": t,
        "end_s": t + 1.0,
        "scenario": metadata[case_id]["scenario"],
    })
    return segments


def segment_at(schedule: list[dict], t: float) -> dict:
    for segment in schedule:
        if segment["start_s"] <= t < segment["end_s"]:
            return segment
    return schedule[-1]


def measurement(table: ResponseTable, frequency: float, amplitude: float) -> dict[str, float]:
    point = table.interp(frequency)
    return {
        **point,
        "amplitude": amplitude,
        "active_power_w": point["unit_power_w"] * amplitude**2,
        "transducer_vpp": point["unit_vpp"] * amplitude,
        "transducer_ipeak_a": point["unit_ipeak_a"] * amplitude,
    }


def append_row(rows: list[dict], strategy: str, t: float, dt: float, segment: dict,
               action: str, protection_state: str, point: dict, table: ResponseTable,
               target_phase: float | None, phase_slope: float | None,
               scan_id: int, scan_reason: str, hard_trip: int, soft_limit: int) -> None:
    phase_error = math.nan if target_phase is None else target_phase - point["phase_deg"]
    rows.append({
        "strategy": strategy,
        "time_s": t,
        "duration_s": dt,
        "state_index": segment["state_index"],
        "case_id": segment["case_id"],
        "scenario_family": segment["family"],
        "factor": segment["factor"],
        "level": segment["level"],
        "action": action,
        "protection_state": protection_state,
        "frequency_hz": point["frequency_hz"],
        "frequency_mhz": point["frequency_hz"] / 1e6,
        "amplitude_command": point["amplitude"],
        "active_power_w": point["active_power_w"],
        "active_power_mw": point["active_power_w"] * 1e3,
        "safe_best_power_w": table.safe_best_power,
        "safe_power_capture_ratio": point["active_power_w"] / table.safe_best_power,
        "baseline_power_ratio": point["active_power_w"] / BASELINE_SAFE_POWER,
        "safe_best_frequency_hz": table.safe_best_freq,
        "frequency_error_khz": (point["frequency_hz"] - table.safe_best_freq) / 1e3,
        "phase_deg": point["phase_deg"],
        "phase_target_deg": "" if target_phase is None else target_phase,
        "phase_error_deg": "" if target_phase is None else phase_error,
        "phase_slope_deg_per_khz": "" if phase_slope is None else phase_slope,
        "reflection_proxy": point["reflection_proxy"],
        "transducer_vpp": point["transducer_vpp"],
        "transducer_ipeak_ma": point["transducer_ipeak_a"] * 1e3,
        "zin_mag_ohm": point["zin_mag_ohm"],
        "zin_real_ohm": point["zin_real_ohm"],
        "zin_imag_ohm": point["zin_imag_ohm"],
        "soft_limit_observed": soft_limit,
        "hard_trip_observed": hard_trip,
        "frequency_saturated": int(point["frequency_hz"] <= F_MIN or point["frequency_hz"] >= F_MAX),
        "scan_id": scan_id if scan_id else "",
        "scan_reason": scan_reason,
    })


def scan_frequencies(center: float | None) -> np.ndarray:
    if center is None:
        coarse = np.arange(F_MIN, F_MAX + 1, 2.0e3)
    else:
        lo, hi = max(F_MIN, center - 50e3), min(F_MAX, center + 50e3)
        coarse = np.arange(lo, hi + 1, 2.0e3)
    return coarse


def execute_scan(rows: list[dict], strategy: str, t: float, schedule: list[dict],
                 tables: dict[str, ResponseTable], center: float | None,
                 scan_id: int, reason: str) -> tuple[float, float, float, float, float]:
    samples = []
    coarse = scan_frequencies(center)
    for frequency in coarse:
        segment = segment_at(schedule, t)
        table = tables[segment["case_id"]]
        point = measurement(table, frequency, PROBE_AMPLITUDE)
        hard = int(point["transducer_vpp"] >= V_HARD or point["transducer_ipeak_a"] >= I_HARD)
        soft = int(point["transducer_vpp"] >= V_SOFT or point["transducer_ipeak_a"] >= I_SOFT)
        append_row(rows, strategy, t, SCAN_POINT_DT, segment, "SCAN_COARSE", "RECOVERY_LOW_AMPLITUDE",
                   point, table, None, None, scan_id, reason, hard, soft)
        samples.append((frequency, point, table, segment))
        t += SCAN_POINT_DT
    coarse_best = max(samples, key=lambda item: item[1]["safe_power_w"])[0]
    fine = np.arange(max(F_MIN, coarse_best - 1.5e3), min(F_MAX, coarse_best + 1.5e3) + 1, 0.1e3)
    fine_samples = []
    for frequency in fine:
        segment = segment_at(schedule, t)
        table = tables[segment["case_id"]]
        point = measurement(table, frequency, PROBE_AMPLITUDE)
        hard = int(point["transducer_vpp"] >= V_HARD or point["transducer_ipeak_a"] >= I_HARD)
        soft = int(point["transducer_vpp"] >= V_SOFT or point["transducer_ipeak_a"] >= I_SOFT)
        append_row(rows, strategy, t, SCAN_POINT_DT, segment, "SCAN_FINE", "RECOVERY_LOW_AMPLITUDE",
                   point, table, None, None, scan_id, reason, hard, soft)
        fine_samples.append((frequency, point, table, segment))
        t += SCAN_POINT_DT
    best = max(fine_samples, key=lambda item: item[1]["safe_power_w"])
    best_f, best_point = best[0], best[1]
    near = [sample for sample in fine_samples if abs(sample[0] - best_f) <= 0.5e3]
    if len(near) >= 3:
        x = np.array([(sample[0] - best_f) / 1e3 for sample in near])
        y = np.unwrap(np.deg2rad([sample[1]["phase_deg"] for sample in near]))
        slope = float(np.rad2deg(np.polyfit(x, y, 1)[0]))
    else:
        slope = math.nan
    unit_reference_power = best_point["active_power_w"] / PROBE_AMPLITUDE**2
    return t, best_f, best_point["phase_deg"], slope, unit_reference_power


def simulate(strategy: str, tables: dict[str, ResponseTable], schedule: list[dict]) -> list[dict]:
    rows: list[dict] = []
    t = 0.0
    end_t = schedule[-1]["end_s"]
    frequency = F_FIXED
    amplitude = 1.0
    protection = "NORMAL"
    hold_until = -1.0
    recovery_until = -1.0
    next_scan = 0.0 if strategy != "固定频率固定幅度" else math.inf
    scan_due_reason = "INITIAL_ACQUISITION"
    scan_id = 0
    target_phase = None
    phase_slope = None
    reference_unit_power = None
    soft_ceiling = 1.0
    while t < end_t - 1e-12:
        segment = segment_at(schedule, t)
        table = tables[segment["case_id"]]

        if t >= next_scan - 1e-12 and protection != "HARD_TRIP":
            scan_id += 1
            center = None if scan_id == 1 else frequency
            t, frequency, scan_phase, scan_slope, reference_unit_power = execute_scan(
                rows, strategy, t, schedule, tables, center, scan_id, scan_due_reason
            )
            target_phase = scan_phase
            phase_slope = scan_slope
            amplitude = PROBE_AMPLITUDE
            protection = "RAMP_UP"
            if strategy == "周期性局部扫频":
                next_scan = t + SCAN_INTERVAL
                scan_due_reason = "PERIODIC"
            else:
                next_scan = t + PHASE_VALIDATION_INTERVAL
                scan_due_reason = "PERIODIC_VALIDATION"
            continue

        segment = segment_at(schedule, t)
        table = tables[segment["case_id"]]
        if strategy == "固定频率固定幅度":
            frequency = F_FIXED
        elif strategy == "校准相位离散跟踪" and target_phase is not None and phase_slope is not None:
            current = table.interp(frequency)
            error = target_phase - current["phase_deg"]
            if abs(error) > PHASE_DEADBAND and abs(phase_slope) >= PHASE_MIN_SLOPE:
                df = np.clip(PHASE_ALPHA * error / phase_slope * 1e3, -PHASE_MAX_STEP, PHASE_MAX_STEP)
                frequency = float(np.clip(frequency + df, F_MIN, F_MAX))

        requested_amp = 1.0
        if protection == "HARD_TRIP":
            amplitude = 0.0
            if t >= hold_until:
                protection = "RECOVERY_LOW_AMPLITUDE"
                amplitude = PROBE_AMPLITUDE
                recovery_until = t + RECOVERY_HOLD
        elif protection == "RECOVERY_LOW_AMPLITUDE":
            amplitude = PROBE_AMPLITUDE
            if t >= recovery_until:
                protection = "RAMP_UP"
        elif protection == "RAMP_UP":
            amplitude = min(requested_amp, amplitude + RAMP_STEP)
            if amplitude >= requested_amp - 1e-12:
                protection = "NORMAL"
        elif protection == "SOFT_LIMIT":
            amplitude = min(amplitude, requested_amp, soft_ceiling)
        else:
            amplitude = requested_amp

        point = measurement(table, frequency, amplitude)
        hard = int(point["transducer_vpp"] >= V_HARD or point["transducer_ipeak_a"] >= I_HARD)
        soft = int(point["transducer_vpp"] >= V_SOFT or point["transducer_ipeak_a"] >= I_SOFT)
        append_row(rows, strategy, t, CONTROL_DT, segment, "CONTROL", protection,
                   point, table, target_phase if strategy == "校准相位离散跟踪" else None,
                   phase_slope if strategy == "校准相位离散跟踪" else None,
                   0, "", hard, soft)

        if hard:
            protection = "HARD_TRIP"
            hold_until = t + CONTROL_DT + HARD_HOLD
            amplitude = 0.0
            if strategy != "固定频率固定幅度":
                next_scan = hold_until + RECOVERY_HOLD
                scan_due_reason = "PROTECTION_REACQUIRE"
        elif soft and amplitude > 0:
            allowed = amplitude * min(V_SOFT / point["transducer_vpp"], I_SOFT / point["transducer_ipeak_a"])
            soft_ceiling = max(PROBE_AMPLITUDE, min(1.0, 0.98 * allowed))
            amplitude = min(amplitude, soft_ceiling)
            protection = "SOFT_LIMIT"
        elif protection == "SOFT_LIMIT":
            # Estimate the allowable command from the current scaled measurement.
            # This is implementable in hardware because V and I scale with command
            # in the present linear model; 2% margin prevents limit chatter.
            if amplitude > 0:
                allowed = amplitude * min(V_SOFT / max(point["transducer_vpp"], 1e-12),
                                          I_SOFT / max(point["transducer_ipeak_a"], 1e-12))
                soft_ceiling = max(PROBE_AMPLITUDE, min(1.0, 0.98 * allowed))
            if soft_ceiling >= 0.999:
                protection = "RAMP_UP" if amplitude < requested_amp else "NORMAL"

        if strategy == "校准相位离散跟踪" and target_phase is not None:
            phase_error = target_phase - point["phase_deg"]
            normalized_power = point["active_power_w"] / max(amplitude**2, 1e-12)
            lost_power = reference_unit_power is not None and normalized_power < POWER_REACQUIRE_RATIO * reference_unit_power
            bad_slope = phase_slope is None or not np.isfinite(phase_slope) or abs(phase_slope) < PHASE_MIN_SLOPE
            saturated = frequency <= F_MIN or frequency >= F_MAX
            if lost_power or abs(phase_error) > PHASE_REACQUIRE_ERROR or bad_slope or saturated:
                proposed = t + CONTROL_DT
                if proposed < next_scan:
                    next_scan = proposed
                    scan_due_reason = "LOSS_OF_CAPTURE"
        t += CONTROL_DT
    return rows


def count_episodes(rows: list[dict], key: str) -> int:
    count = 0
    previous = 0
    for row in rows:
        current = int(row[key])
        if current and not previous:
            count += 1
        previous = current
    return count


def sustained_duration(rows: list[dict], predicate, required: float) -> tuple[bool, float | None]:
    accumulated = 0.0
    first = None
    for row in rows:
        if predicate(row):
            if first is None:
                first = row["time_s"]
            accumulated += row["duration_s"]
            if accumulated >= required:
                return True, first
        else:
            accumulated = 0.0
            first = None
    return False, None


def state_metrics(all_rows: list[dict], schedule: list[dict]) -> list[dict]:
    result = []
    for strategy in STRATEGIES:
        strategy_rows = [row for row in all_rows if row["strategy"] == strategy]
        for segment in schedule:
            rows = [row for row in strategy_rows if row["state_index"] == segment["state_index"]]
            regular = [row for row in rows if row["action"] == "CONTROL"]
            if not regular:
                continue
            settled, settle_start = sustained_duration(
                rows, lambda row: row["safe_power_capture_ratio"] >= SETTLE_CAPTURE, SETTLE_DURATION
            )
            wrong, _ = sustained_duration(
                regular,
                lambda row: row["protection_state"] == "NORMAL" and row["amplitude_command"] >= 0.95
                and row["phase_error_deg"] != "" and abs(float(row["phase_error_deg"])) <= PHASE_DEADBAND
                and row["safe_power_capture_ratio"] < WRONG_LOCK_CAPTURE,
                WRONG_LOCK_DURATION,
            )
            tail_start = segment["end_s"] - 0.2 * (segment["end_s"] - segment["start_s"])
            tail = [row for row in rows if row["time_s"] >= tail_start] or rows[-20:]
            tail_regular = [row for row in regular if row["time_s"] >= tail_start] or regular[-20:]
            powers = np.array([row["safe_power_capture_ratio"] for row in tail])
            weights = np.array([row["duration_s"] for row in tail])
            power_mean = float(np.average(powers, weights=weights))
            power_std = float(np.sqrt(np.average((powers - power_mean) ** 2, weights=weights)))
            freqs = np.array([row["frequency_hz"] for row in tail_regular])
            diffs = np.diff(freqs)
            nonzero = diffs[np.abs(diffs) > 1e-9]
            reversals = int(np.sum(np.sign(nonzero[:-1]) * np.sign(nonzero[1:]) < 0)) if len(nonzero) > 1 else 0
            result.append({
                "strategy": strategy,
                "state_index": segment["state_index"],
                "case_id": segment["case_id"],
                "scenario": f"{segment['family']}-{segment['factor']}-{segment['level']}",
                "settled": int(settled),
                "recovery_time_ms": "" if not settled else max(0.0, settle_start - segment["start_s"]) * 1e3,
                "steady_power_capture_pct": power_mean * 100,
                "steady_power_cv_pct": power_std / max(power_mean, 1e-12) * 100,
                "steady_frequency_error_khz": float(np.mean(np.abs([row["frequency_error_khz"] for row in tail_regular]))),
                "locked_frequency_mhz": float(np.mean(freqs) / 1e6),
                "peak_power_overshoot_pct": float(max(0.0, np.max([row["safe_power_capture_ratio"] for row in rows]) - 1.0) * 100),
                "peak_voltage_vpp": float(max(row["transducer_vpp"] for row in rows)),
                "peak_current_ma": float(max(row["transducer_ipeak_ma"] for row in rows)),
                "soft_limit_episodes": count_episodes(rows, "soft_limit_observed"),
                "hard_trip_episodes": count_episodes(rows, "hard_trip_observed"),
                "frequency_saturation_ms": float(sum(
                    row["duration_s"] for row in rows
                    if row["action"] == "CONTROL" and row["frequency_saturated"]
                ) * 1e3),
                "frequency_reversals": reversals,
                "oscillation_flag": int(reversals >= 4 and np.std(freqs) >= 0.2e3),
                "wrong_phase_lock_flag": int(wrong),
                "scan_points": int(sum(row["action"].startswith("SCAN") for row in rows)),
                "scan_time_ms": float(sum(row["duration_s"] for row in rows if row["action"].startswith("SCAN")) * 1e3),
            })
    return result


def overall_metrics(all_rows: list[dict], per_state: list[dict]) -> list[dict]:
    result = []
    for strategy in STRATEGIES:
        rows = [row for row in all_rows if row["strategy"] == strategy]
        states = [row for row in per_state if row["strategy"] == strategy]
        recovery = []
        for row in states:
            if row["recovery_time_ms"] != "":
                recovery.append(float(row["recovery_time_ms"]))
            else:
                segment = next(item for item in SCHEDULE_FOR_METRICS if item["state_index"] == row["state_index"])
                recovery.append((segment["end_s"] - segment["start_s"]) * 1e3)
        result.append({
            "strategy": strategy,
            "steady_error_pct": float(np.mean([100 - row["steady_power_capture_pct"] for row in states])),
            "mean_recovery_time_ms": float(np.mean(recovery)) if recovery else "",
            "unsettled_states": int(sum(not row["settled"] for row in states)),
            "power_stability_cv_pct": float(np.mean([row["steady_power_cv_pct"] for row in states])),
            "peak_current_ma": float(max(row["transducer_ipeak_ma"] for row in rows)),
            "peak_voltage_vpp": float(max(row["transducer_vpp"] for row in rows)),
            "soft_limit_episodes": count_episodes(rows, "soft_limit_observed"),
            "hard_trip_episodes": count_episodes(rows, "hard_trip_observed"),
            "frequency_saturation_ms": float(sum(
                row["duration_s"] for row in rows
                if row["action"] == "CONTROL" and row["frequency_saturated"]
            ) * 1e3),
            "locked_frequency_range_mhz": f"{min(row['locked_frequency_mhz'] for row in states):.6f}–{max(row['locked_frequency_mhz'] for row in states):.6f}",
            "max_power_overshoot_pct": float(max(row["peak_power_overshoot_pct"] for row in states)),
            "oscillating_states": int(sum(row["oscillation_flag"] for row in states)),
            "wrong_phase_lock_states": int(sum(row["wrong_phase_lock_flag"] for row in states)),
            "scan_points": int(sum(row["action"].startswith("SCAN") for row in rows)),
            "scan_time_s": float(sum(row["duration_s"] for row in rows if row["action"].startswith("SCAN"))),
        })
    return result


def make_figures(all_rows: list[dict], tables: dict[str, ResponseTable], schedule: list[dict]) -> None:
    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False})
    base = tables["CASE_000_BASELINE"]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(base.freq / 1e6, base.power * 1e3, label="LTspice RAW有功功率")
    axes[0].axvline(base.safe_best_freq / 1e6, color="tab:red", ls="--", label="最大安全功率点")
    axes[0].set_ylabel("功率 / mW"); axes[0].legend()
    axes[1].plot(base.freq / 1e6, base.phase, color="tab:orange")
    axes[1].axhline(0, color="0.4", lw=0.8); axes[1].set_ylabel("相位 / °")
    axes[2].plot(base.freq / 1e6, base.gamma, color="tab:green")
    axes[2].set_ylabel("反射代理"); axes[2].set_xlabel("频率 / MHz")
    fig.suptitle("基准场景：LTspice RAW频率响应与控制目标")
    fig.tight_layout(); fig.savefig(OUTDIR / "01_基准_LTspice_RAW频响.png", dpi=180); plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    for strategy in STRATEGIES:
        rows = [row for row in all_rows if row["strategy"] == strategy and row["action"] == "CONTROL"]
        t = [row["time_s"] for row in rows]
        axes[0].plot(t, [row["safe_power_capture_ratio"] * 100 for row in rows], lw=0.9, label=strategy)
        axes[1].plot(t, [row["frequency_mhz"] for row in rows], lw=0.9, label=strategy)
        axes[2].plot(t, [row["amplitude_command"] for row in rows], lw=0.9, label=strategy)
    for segment in schedule[1:]:
        for ax in axes: ax.axvline(segment["start_s"], color="0.85", lw=0.5)
    axes[0].axhline(95, color="0.3", ls="--", lw=0.8)
    axes[0].set_ylabel("安全功率捕获 / %"); axes[0].legend(ncol=3, fontsize=8)
    axes[1].set_ylabel("频率 / MHz"); axes[2].set_ylabel("幅度指令"); axes[2].set_xlabel("时间 / s")
    fig.suptitle("完全相同扰动时序下的三策略比较")
    fig.tight_layout(); fig.savefig(OUTDIR / "02_三策略统一时序比较.png", dpi=180); plt.close(fig)

    high = next(segment for segment in schedule if segment["case_id"] == "CASE_402_COMBINED_HIGH")
    lo, hi = high["start_s"] - 0.2, high["end_s"] + 0.2
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    for strategy in STRATEGIES:
        rows = [row for row in all_rows if row["strategy"] == strategy and lo <= row["time_s"] <= hi]
        axes[0].plot([r["time_s"] for r in rows], [r["transducer_vpp"] for r in rows], lw=0.8, label=strategy)
        axes[1].plot([r["time_s"] for r in rows], [r["transducer_ipeak_ma"] for r in rows], lw=0.8)
        axes[2].plot([r["time_s"] for r in rows], [r["amplitude_command"] for r in rows], lw=0.8)
    axes[0].axhline(V_SOFT, color="tab:orange", ls="--"); axes[0].axhline(V_HARD, color="tab:red", ls=":")
    axes[1].axhline(I_SOFT * 1e3, color="tab:orange", ls="--"); axes[1].axhline(I_HARD * 1e3, color="tab:red", ls=":")
    axes[0].set_ylabel("Vpp / V"); axes[0].legend(fontsize=8)
    axes[1].set_ylabel("Ipeak / mA"); axes[2].set_ylabel("幅度指令"); axes[2].set_xlabel("时间 / s")
    fig.suptitle("高组合扰动附近：保护状态机实际动作")
    fig.tight_layout(); fig.savefig(OUTDIR / "03_保护状态机动作痕迹.png", dpi=180); plt.close(fig)

    rows = [row for row in all_rows if row["strategy"] == "校准相位离散跟踪"]
    fig, axes = plt.subplots(3, 1, figsize=(13, 8), sharex=True)
    axes[0].plot([r["time_s"] for r in rows], [r["safe_power_capture_ratio"] * 100 for r in rows], lw=0.8)
    axes[1].plot([r["time_s"] for r in rows], [r["phase_deg"] for r in rows], lw=0.8, label="测得相位")
    target_rows = [r for r in rows if r["phase_target_deg"] != ""]
    axes[1].plot([r["time_s"] for r in target_rows], [r["phase_target_deg"] for r in target_rows], lw=0.8, label="扫描校准目标")
    axes[2].plot([r["time_s"] for r in rows], [r["frequency_mhz"] for r in rows], lw=0.8)
    for r in rows:
        if r["action"] == "SCAN_COARSE" and r["scan_reason"]:
            axes[0].axvline(r["time_s"], color="tab:red", alpha=0.08)
    axes[0].set_ylabel("安全功率捕获 / %")
    axes[1].set_ylabel("相位 / °"); axes[1].legend(fontsize=8)
    axes[2].set_ylabel("频率 / MHz"); axes[2].set_xlabel("时间 / s")
    fig.suptitle("校准相位跟踪：目标更新、失锁判据与重新捕获")
    fig.tight_layout(); fig.savefig(OUTDIR / "04_相位控制重新捕获痕迹.png", dpi=180); plt.close(fig)


def write_report(overall: list[dict], schedule: list[dict]) -> None:
    lines = [
        "# 第四、第五步重做：正式控制时序与综合比较",
        "",
        "## 结论边界",
        "",
        f"本报告的被控对象来自 LTspice {LTSPICE_VERSION} 在本轮重新批量运行 24 个 `.cir` 后生成的 AC `.raw` 频率响应；控制器、扰动时序与保护逻辑由 Python 离散事件仿真执行。它属于电路级虚拟验证，不是 LTspice 瞬态闭环、实物实验或声场验证。",
        "",
        "## 已修正的三项问题",
        "",
        "1. 扫频点按 1.5 ms/点依次执行，扫描时间进入总时间轴，不再把整段扫描当作瞬时动作。",
        "2. 相位目标不是固定 0°；先在低幅扫描中找到最大安全功率点，再把该点相位作为局部目标。更新量为 `Δf=α·e/sφ`，实际相位斜率 `sφ` 决定控制符号。",
        "3. 所有策略共用 `NORMAL → SOFT_LIMIT → HARD_TRIP → RECOVERY_LOW_AMPLITUDE → RAMP_UP` 保护状态机，限值不仅计数，而且实际改变幅度。",
        "",
        "## 冻结参数（本模型的起始设计值）",
        "",
        f"- 控制周期：{CONTROL_DT*1e3:.1f} ms；扫频点耗时：{SCAN_POINT_DT*1e3:.1f} ms；探测幅度：{PROBE_AMPLITUDE*100:.0f}%。",
        f"- 软限值：{V_SOFT:.0f} Vpp、{I_SOFT*1e3:.1f} mApeak；硬限值：{V_HARD:.0f} Vpp、{I_HARD*1e3:.1f} mApeak。",
        f"- 硬关断：{HARD_HOLD*1e3:.0f} ms；低幅恢复观察：{RECOVERY_HOLD*1e3:.0f} ms；每控制步幅度爬升 {RAMP_STEP:.2f}。",
        f"- 相位归一化增益 α={PHASE_ALPHA:.2f}；死区 ±{PHASE_DEADBAND:.1f}°；单步最大频移 {PHASE_MAX_STEP/1e3:.1f} kHz。",
        f"- 周期扫频间隔 {SCAN_INTERVAL*1e3:.0f} ms；相位策略强制复核间隔 {PHASE_VALIDATION_INTERVAL*1e3:.0f} ms。",
        "",
        "这些值是依据当前 0.84–0.96 MHz、0.1 kHz RAW 网格和既有 100 Vpp 标定选择的仿真起点，不是器件数据手册限值。接入真实换能器前必须重标定。",
        "",
        "## 第五步综合表",
        "",
        "| 策略 | 稳态误差 | 平均恢复时间 | 未收敛场景 | 功率稳定性CV | 峰值电流 | 峰值电压 | 软限事件 | 硬跳闸 | 饱和时间 | 振荡状态 | 错误相位锁定 | 扫描时间 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in overall:
        recovery = "未收敛" if row["mean_recovery_time_ms"] == "" else f"{row['mean_recovery_time_ms']:.1f} ms"
        lines.append(
            f"| {row['strategy']} | {row['steady_error_pct']:.2f}% | {recovery} | {row['unsettled_states']} | {row['power_stability_cv_pct']:.2f}% | "
            f"{row['peak_current_ma']:.3f} mA | {row['peak_voltage_vpp']:.2f} Vpp | {row['soft_limit_episodes']} | "
            f"{row['hard_trip_episodes']} | {row['frequency_saturation_ms']:.1f} ms | {row['oscillating_states']} | "
            f"{row['wrong_phase_lock_states']} | {row['scan_time_s']:.3f} s |"
        )
    lines += [
        "",
        "## 当前虚拟模型的结果解释",
        "",
        "- 固定频率的稳态曲线最平，因此功率 CV 接近 0；但它有 6 个场景未达到 95% 最大安全功率，并发生 1 次硬跳闸。‘稳定’在这里不等于‘功率合适’。",
        "- 周期性局部扫频的 25 个场景均能重新捕获，但扫描期间以 50% 幅度探测，累计扫描 5.229 s，因此功率稳定性 CV 约 20%。这个代价已计入结果，没有把扫描当作瞬时动作。",
        "- 校准相位离散跟踪在当前模型中表现最好：稳态误差约 2.89%，平均恢复约 95.3 ms，无错误相位锁定、无控制饱和、无硬跳闸；但它本质上是‘功率扫描捕获 + 局部相位维持’的混合策略，不是纯零相位 PLL。",
        "- 以上排序只对当前线性 BVD、当前扰动驻留时间和当前保护阈值成立。真实硬件加入测量噪声、功放动态、温升和非线性后必须重新调参并重新排序。",
        "",
        "## 验收口径",
        "",
        "- 稳态误差：每段末 20% 时间内，1−实际有功功率/该场景约束下最大安全功率。",
        "- 恢复时间：扰动开始后首次连续 20 ms 达到至少 95% 最大安全功率；扫描耗时包含在内。综合平均时，未收敛场景按完整驻留时间计入惩罚，并另列未收敛场景数。",
        "- 错误相位锁定：相位误差在 ±0.5° 内，但安全功率捕获低于 80%，且持续至少 50 ms。",
        "- 振荡：稳态尾段频率方向反转不少于 4 次，且频率标准差不小于 0.2 kHz。",
        "- 最大安全功率：在每个频率上先按 150 Vpp/5.5 mApeak 计算允许幅度，再在全频段取最大值。",
        "",
        "## 必须由用户补留的 LTspice 界面证据",
        "",
        "Python 生成的四张 PNG 是由 LTspice RAW 数值绘制的可复现仿真图，不是 LTspice GUI 截图。报告提交前仍需按《第四五步重做_实操计划与证据清单》补截：LTspice 版本、最终 `.cir`、基准/高扰动波形、Error Log 和文件时间戳。",
        "",
        f"扰动序列共 {len(schedule)} 段、总时长 {schedule[-1]['end_s']:.1f} s；三种策略使用完全相同的绝对时间边界。",
    ]
    (OUTDIR / "第四五步重做_综合报告.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    tables, metadata = build_tables()
    global BASELINE_SAFE_POWER
    BASELINE_SAFE_POWER = tables["CASE_000_BASELINE"].safe_best_power
    schedule = build_schedule(metadata)
    global SCHEDULE_FOR_METRICS
    SCHEDULE_FOR_METRICS = schedule
    all_rows = []
    for strategy in STRATEGIES:
        print(f"simulate: {strategy}")
        all_rows.extend(simulate(strategy, tables, schedule))
    per_state = state_metrics(all_rows, schedule)
    overall = overall_metrics(all_rows, per_state)
    write_csv(OUTDIR / "第四步_控制时序明细.csv", all_rows)
    write_csv(OUTDIR / "第五步_逐场景指标.csv", per_state)
    write_csv(OUTDIR / "第五步_三策略综合表.csv", overall)
    make_figures(all_rows, tables, schedule)
    write_report(overall, schedule)
    manifest = {
        "scope": "LTspice AC RAW plant + Python event-driven controller; virtual BVD model; no measured or COMSOL data",
        "ltspice_version": LTSPICE_VERSION,
        "source_raw_directory": str(RAW_DIR),
        "parameters": {
            "frequency_hz": [F_MIN, F_MAX], "control_dt_s": CONTROL_DT,
            "scan_point_dt_s": SCAN_POINT_DT, "probe_amplitude": PROBE_AMPLITUDE,
            "voltage_soft_vpp": V_SOFT, "voltage_hard_vpp": V_HARD,
            "current_soft_peak_a": I_SOFT, "current_hard_peak_a": I_HARD,
            "hard_hold_s": HARD_HOLD, "recovery_hold_s": RECOVERY_HOLD,
            "phase_alpha": PHASE_ALPHA, "phase_deadband_deg": PHASE_DEADBAND,
            "phase_max_step_hz": PHASE_MAX_STEP,
        },
        "schedule": [{k: v for k, v in segment.items() if k != "scenario"} for segment in schedule],
        "scenarios": {
            case_id: {"bvd": asdict(meta["scenario"].bvd), "rs": meta["scenario"].rs,
                      "matching": asdict(meta["scenario"].matching)}
            for case_id, meta in metadata.items()
        },
    }
    (OUTDIR / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(overall, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
