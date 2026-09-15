"""Stage 4/5: three strategies under one schedule with an enforced protection state machine.

Strategies: fixed frequency, periodic coarse/fine local scan, and P&O maximum-power tracking.
The plant is the active v2.1 analytic circuit cross-validated against LTspice RAW.
Time is quasi-steady simulation time, not a hardware real-time claim.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model_v2_1 import (
    F0, F_MIN, F_MAX, IRMS_HARD, IRMS_SOFT, VPP_HARD, VPP_SOFT,
    allowed_amplitude, response, safe_power, scenario_map,
)


HERE = Path(__file__).resolve().parent
OUT = HERE / "stage4_5_control"
CONTROL_DT = 20e-3
SCAN_POINT_DT = 1.5e-3
PROBE_AMPLITUDE = 0.40
SCAN_INTERVAL = 0.50
SOFT_STABILIZE = 0.10
HARD_HOLD = 0.06
RECOVERY_HOLD = 0.10
RECOVERY_AMPLITUDE = 0.25
RAMP_STEP = 0.05
P_AND_O_INITIAL_STEP = 0.5e3
P_AND_O_MIN_STEP = 0.1e3
P_AND_O_REACQUIRE_CAPTURE = 0.60
P_AND_O_UPDATE_INTERVAL = 0.10
RECOVERY_CAPTURE_THRESHOLD = 0.98
RECOVERY_CONSECUTIVE_SAMPLES = 10
FINE_REFERENCE = np.arange(F_MIN, F_MAX + 0.1, 100.0)
STRATEGIES = ["FIXED_0P9", "PERIODIC_SCAN", "P_AND_O"]

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
plt.rcParams['pdf.fonttype'] = 42
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False})
COLORS = {"FIXED_0P9": "#767676", "PERIODIC_SCAN": "#3775BA", "P_AND_O": "#B64342"}


SCENARIO_ORDER = [
    "CASE_000_BASELINE", "CASE_C0_P30", "CASE_RM_P50", "CASE_FS_M5",
    "CASE_LMATCH_P10", "CASE_QL_20", "CASE_COMBINED_HIGH", "CASE_000_BASELINE",
]
SEGMENT_DURATION = 0.80
SCHEDULE = [
    {"state_index": i, "case_id": case_id, "start_s": i * SEGMENT_DURATION, "end_s": (i + 1) * SEGMENT_DURATION}
    for i, case_id in enumerate(SCENARIO_ORDER)
]
TOTAL_TIME = SCHEDULE[-1]["end_s"]


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def schedule_at(t: float) -> dict:
    idx = min(int(t / SEGMENT_DURATION), len(SCHEDULE) - 1)
    return SCHEDULE[idx]


def optimal_tables(scenarios: dict) -> dict[str, dict]:
    tables = {}
    for case_id in set(SCENARIO_ORDER):
        s = scenarios[case_id]
        p = safe_power(FINE_REFERENCE, s)
        i = int(np.argmax(p))
        tables[case_id] = {"frequency_Hz": float(FINE_REFERENCE[i]), "power_W": float(p[i])}
    return tables


@dataclass
class Protection:
    state: str = "NORMAL"
    applied_amplitude: float = 1.0
    hard_until: float = -1.0
    recovery_until: float = -1.0
    soft_since: float | None = None

    def tracking_allowed(self, t: float) -> bool:
        # v2.1 acceptance rule: any protection state freezes frequency.
        return self.state == "NORMAL"

    def apply(self, t: float, frequency_hz: float, scenario, requested: float) -> tuple[float, str, int, int, bool]:
        """Return amplitude, state, hard-trigger, soft-trigger and frequency-frozen flag."""
        soft_allow = float(allowed_amplitude(frequency_hz, scenario, use_soft_limits=True)[0])
        hard_allow = float(allowed_amplitude(frequency_hz, scenario, use_soft_limits=False)[0])
        hard_trigger = 0
        soft_trigger = 0

        if t < self.hard_until:
            self.state = "HARD_TRIP"
            self.applied_amplitude = 0.0
            return 0.0, self.state, 0, 0, True
        if t < self.recovery_until:
            self.state = "RECOVERY_HOLD"
            self.applied_amplitude = min(RECOVERY_AMPLITUDE, soft_allow)
            return self.applied_amplitude, self.state, 0, 0, True

        if self.state in {"HARD_TRIP", "RECOVERY_HOLD"}:
            self.state = "RAMP_UP"
            self.applied_amplitude = min(max(self.applied_amplitude, RECOVERY_AMPLITUDE), soft_allow)

        # A hard trip represents the already-applied drive becoming unsafe after
        # an abrupt plant change. A new unsafe request is intercepted by soft
        # foldback below, so it is not reclassified as a hard trip every tick.
        if self.applied_amplitude > hard_allow + 1e-12:
            hard_trigger = 1
            self.state = "HARD_TRIP"
            self.hard_until = t + HARD_HOLD
            self.recovery_until = self.hard_until + RECOVERY_HOLD
            self.applied_amplitude = 0.0
            self.soft_since = None
            return 0.0, self.state, hard_trigger, 0, True

        candidate = requested if self.state == "NORMAL" else min(requested, self.applied_amplitude + RAMP_STEP)
        if candidate > soft_allow + 1e-12:
            soft_trigger = int(self.state != "SOFT_FOLDBACK")
            self.state = "SOFT_FOLDBACK"
            if self.soft_since is None: self.soft_since = t
            self.applied_amplitude = soft_allow
            frozen = (t - self.soft_since) < SOFT_STABILIZE
            return self.applied_amplitude, self.state, 0, soft_trigger, frozen

        self.applied_amplitude = candidate
        self.soft_since = None
        if candidate >= requested - 1e-12:
            self.state = "NORMAL"
            return candidate, self.state, 0, 0, False
        self.state = "RAMP_UP"
        return candidate, self.state, 0, 0, True


def measure(t: float, duration: float, strategy: str, action: str, frequency: float, amplitude: float,
            protection_state: str, hard_trigger: int, soft_trigger: int, frozen: bool,
            segment: dict, scenario, optimum: dict, scan_reason: str = "") -> dict:
    q = response(frequency, scenario, amplitude)
    p = float(q["p_rm_W"][0]); phase = float(q["phase_deg"][0])
    vpp = float(q["vport_vpp"][0]); irms = float(q["iport_irms_A"][0])
    return {
        "strategy": strategy, "time_s": t, "duration_s": duration, "action": action,
        "state_index": segment["state_index"], "case_id": segment["case_id"],
        "frequency_Hz": frequency, "frequency_MHz": frequency / 1e6,
        "amplitude_command": amplitude, "protection_state": protection_state,
        "frequency_frozen": int(frozen), "hard_trip_trigger": hard_trigger, "soft_limit_trigger": soft_trigger,
        "scan_reason": scan_reason, "p_rm_W": p, "phase_deg": phase, "gamma": float(q["gamma"][0]),
        "vport_vpp": vpp, "iport_irms_A": irms,
        "actual_voltage_hard_violation": int(vpp > VPP_HARD + 1e-9),
        "actual_current_hard_violation": int(irms > IRMS_HARD + 1e-12),
        "optimal_safe_frequency_Hz": optimum["frequency_Hz"], "optimal_safe_power_W": optimum["power_W"],
        "safe_power_capture_ratio": p / max(optimum["power_W"], 1e-30),
        "frequency_error_kHz": (frequency - optimum["frequency_Hz"]) / 1e3,
        "frequency_saturated": int(frequency <= F_MIN + 1e-9 or frequency >= F_MAX - 1e-9),
    }


def local_scan(t: float, strategy: str, current_f: float, reason: str, rows: list[dict], protection: Protection,
               scenarios: dict, optima: dict) -> tuple[float, float, bool]:
    """Execute sequential coarse/fine points; abort if the disturbance changes mid-scan."""
    start_case = schedule_at(t)["case_id"]
    scenario = scenarios[start_case]
    coarse = np.arange(max(F_MIN, current_f - 50e3), min(F_MAX, current_f + 50e3) + 1, 5e3)
    measured = []
    for f in coarse:
        if schedule_at(t)["case_id"] != start_case: return current_f, t, False
        seg = schedule_at(t); opt = optima[start_case]
        row = measure(t, SCAN_POINT_DT, strategy, "SCAN_COARSE", float(f), PROBE_AMPLITUDE,
                      protection.state, 0, 0, True, seg, scenario, opt, reason)
        rows.append(row); measured.append((row["p_rm_W"], float(f))); t += SCAN_POINT_DT
    coarse_best = max(measured)[1]
    fine = np.arange(max(F_MIN, coarse_best - 5e3), min(F_MAX, coarse_best + 5e3) + 1, 1e3)
    measured = []
    for f in fine:
        if schedule_at(t)["case_id"] != start_case: return current_f, t, False
        seg = schedule_at(t); opt = optima[start_case]
        row = measure(t, SCAN_POINT_DT, strategy, "SCAN_FINE", float(f), PROBE_AMPLITUDE,
                      protection.state, 0, 0, True, seg, scenario, opt, reason)
        rows.append(row); measured.append((row["p_rm_W"], float(f))); t += SCAN_POINT_DT
    fine_best = max(measured)[1]
    # The Qm sensitivity study shows a ~1.7--3.5 kHz FWHM.  A final 0.1 kHz
    # refinement is therefore needed to satisfy a 95% power-capture criterion;
    # it is restricted to +/-1 kHz so its time cost remains explicit and small.
    ultra = np.arange(max(F_MIN, fine_best - 1e3), min(F_MAX, fine_best + 1e3) + 1, 0.1e3)
    measured = []
    for f in ultra:
        if schedule_at(t)["case_id"] != start_case: return current_f, t, False
        seg = schedule_at(t); opt = optima[start_case]
        row = measure(t, SCAN_POINT_DT, strategy, "SCAN_ULTRAFINE", float(f), PROBE_AMPLITUDE,
                      protection.state, 0, 0, True, seg, scenario, opt, reason)
        rows.append(row); measured.append((row["p_rm_W"], float(f))); t += SCAN_POINT_DT
    return max(measured)[1], t, True


def simulate(strategy: str, scenarios: dict, optima: dict) -> list[dict]:
    rows: list[dict] = []
    protection = Protection()
    t = 0.0; frequency = F0; last_case = ""; next_scan = 0.0
    po_dir = 1.0; po_step = P_AND_O_INITIAL_STEP; po_low_count = 0; po_next_update = 0.0
    po_need_reacquire = False

    while t < TOTAL_TIME - 1e-12:
        seg = schedule_at(t); case_id = seg["case_id"]; scenario = scenarios[case_id]; optimum = optima[case_id]
        changed = case_id != last_case
        if changed:
            po_step = P_AND_O_INITIAL_STEP; po_low_count = 0; po_next_update = t
            po_need_reacquire = strategy == "P_AND_O" and seg["state_index"] > 0
            if strategy == "PERIODIC_SCAN": next_scan = t
            last_case = case_id

        # Scans are only allowed after protection has stabilized.
        if strategy == "PERIODIC_SCAN" and t >= next_scan and protection.tracking_allowed(t):
            frequency, t, completed = local_scan(t, strategy, frequency, "DISTURBANCE" if changed else "PERIODIC", rows, protection, scenarios, optima)
            next_scan = t + SCAN_INTERVAL
            if not completed: continue
            seg = schedule_at(t); case_id = seg["case_id"]; scenario = scenarios[case_id]; optimum = optima[case_id]

        if strategy == "P_AND_O" and po_need_reacquire and protection.tracking_allowed(t):
            frequency, t, completed = local_scan(
                t, strategy, frequency, "DISTURBANCE_REACQUIRE", rows, protection, scenarios, optima
            )
            if not completed:
                continue
            po_need_reacquire = False
            po_step = P_AND_O_INITIAL_STEP
            po_next_update = t + P_AND_O_UPDATE_INTERVAL
            continue

        # P&O changes frequency only at reduced amplitude.  This explicitly
        # implements the required ordering: amplitude down -> frequency probe ->
        # resume/ramp drive.  It prevents a frequency step at full drive from
        # manufacturing repeated hard trips in the quasi-steady model.
        if strategy == "P_AND_O" and t >= po_next_update and protection.tracking_allowed(t):
            amp0, state0, hard0, soft0, frozen0 = protection.apply(t, frequency, scenario, PROBE_AMPLITUDE)
            ref = measure(t, CONTROL_DT, strategy, "P_AND_O_REFERENCE", frequency, amp0, state0,
                          hard0, soft0, True, seg, scenario, optimum)
            rows.append(ref); t += CONTROL_DT
            if schedule_at(t)["case_id"] != case_id:
                continue
            candidate_f = float(np.clip(frequency + po_dir * po_step, F_MIN, F_MAX))
            amp1, state1, hard1, soft1, frozen1 = protection.apply(t, candidate_f, scenario, PROBE_AMPLITUDE)
            probe = measure(t, CONTROL_DT, strategy, "P_AND_O_PROBE", candidate_f, amp1, state1,
                            hard1, soft1, True, seg, scenario, optimum)
            rows.append(probe); t += CONTROL_DT
            rel = (probe["p_rm_W"] - ref["p_rm_W"]) / max(abs(ref["p_rm_W"]), 1e-30)
            if rel > 0:
                frequency = candidate_f
                if rel < 0.005:
                    po_step = max(P_AND_O_MIN_STEP, po_step / 2)
            else:
                po_dir *= -1
                po_step = max(P_AND_O_MIN_STEP, po_step / 2)
            po_next_update = t + P_AND_O_UPDATE_INTERVAL
            continue

        amplitude, pstate, hard_trigger, soft_trigger, frozen = protection.apply(t, frequency, scenario, 1.0)
        row = measure(t, CONTROL_DT, strategy, "CONTROL", frequency, amplitude, pstate,
                      hard_trigger, soft_trigger, frozen, seg, scenario, optimum)
        rows.append(row)

        if strategy == "FIXED_0P9":
            frequency = F0
        elif strategy == "P_AND_O" and not frozen:
            capture = row["safe_power_capture_ratio"]
            po_low_count = po_low_count + 1 if capture < P_AND_O_REACQUIRE_CAPTURE else 0
            if po_low_count >= 3 and protection.tracking_allowed(t):
                frequency, t, completed = local_scan(t + CONTROL_DT, strategy, frequency, "LOSS_OF_CAPTURE", rows, protection, scenarios, optima)
                po_step = P_AND_O_INITIAL_STEP; po_low_count = 0; po_next_update = t + P_AND_O_UPDATE_INTERVAL
                if not completed: continue
                continue

        t += CONTROL_DT
    return rows


def episode_count(rows: list[dict], key: str) -> int:
    return int(sum(int(r[key]) for r in rows))


def segment_metrics(all_rows: list[dict]) -> list[dict]:
    result = []
    for strategy in STRATEGIES:
        sr = [r for r in all_rows if r["strategy"] == strategy]
        for seg in SCHEDULE:
            rows = [r for r in sr if r["state_index"] == seg["state_index"]]
            control = [r for r in rows if r["action"] == "CONTROL"]
            if not control: continue
            tail_start = seg["start_s"] + 0.75 * (seg["end_s"] - seg["start_s"])
            normal_control = [r for r in control if r["protection_state"] == "NORMAL" and not r["frequency_frozen"]]
            tail = [r for r in normal_control if r["time_s"] >= tail_start] or normal_control[-5:] or control[-5:]
            captures = np.array([r["safe_power_capture_ratio"] for r in tail])
            powers = np.array([r["p_rm_W"] for r in tail])
            freqs = np.array([r["frequency_Hz"] for r in tail])
            recovery = None; consecutive = 0; candidate_start = None; previous_time = None
            for r in control:
                is_contiguous = previous_time is None or (r["time_s"] - previous_time) <= CONTROL_DT * 1.5
                ok = (
                    is_contiguous
                    and r["protection_state"] == "NORMAL"
                    and not r["frequency_frozen"]
                    and r["safe_power_capture_ratio"] >= RECOVERY_CAPTURE_THRESHOLD
                )
                if ok:
                    if consecutive == 0:
                        candidate_start = r["time_s"]
                    consecutive += 1
                else:
                    consecutive = 0
                    candidate_start = None
                previous_time = r["time_s"]
                if consecutive >= RECOVERY_CONSECUTIVE_SAMPLES and candidate_start is not None:
                    recovery = max(0.0, candidate_start - seg["start_s"])
                    break
            diffs = np.diff(freqs); nz = diffs[np.abs(diffs) > 1e-9]
            reversals = int(np.sum(np.sign(nz[:-1]) * np.sign(nz[1:]) < 0)) if len(nz) > 1 else 0
            result.append({
                "strategy": strategy, "state_index": seg["state_index"], "case_id": seg["case_id"],
                "settled": int(recovery is not None), "recovery_time_ms": "" if recovery is None else recovery * 1e3,
                "steady_power_capture_pct": float(np.mean(captures) * 100),
                "steady_error_pct": float((1 - np.mean(captures)) * 100),
                "power_stability_cv_pct": float(np.std(powers) / max(np.mean(powers), 1e-30) * 100),
                "locked_frequency_MHz": float(np.mean(freqs) / 1e6),
                "steady_frequency_error_kHz": float(np.mean(np.abs([r["frequency_error_kHz"] for r in tail]))),
                "peak_power_overshoot_pct": float(max(0.0, max(r["safe_power_capture_ratio"] for r in rows) - 1) * 100),
                "peak_voltage_vpp": float(max(r["vport_vpp"] for r in rows)),
                "peak_current_mA_RMS": float(max(r["iport_irms_A"] for r in rows) * 1e3),
                "soft_limit_triggers": episode_count(rows, "soft_limit_trigger"),
                "hard_trip_triggers": episode_count(rows, "hard_trip_trigger"),
                "actual_hard_violations": int(sum(r["actual_voltage_hard_violation"] + r["actual_current_hard_violation"] for r in rows)),
                "frequency_saturation_ms": float(sum(r["duration_s"] for r in control if r["frequency_saturated"]) * 1e3),
                "frequency_reversals": reversals,
                "oscillation_flag": int(reversals >= 4 and np.std(freqs) >= 0.2e3),
                "wrong_phase_lock_flag": int(any(abs(r["phase_deg"]) <= 0.5 and r["safe_power_capture_ratio"] < 0.8 for r in tail)),
                "scan_points": int(sum(r["action"].startswith("SCAN") for r in rows)),
                "scan_time_ms": float(sum(r["duration_s"] for r in rows if r["action"].startswith("SCAN")) * 1e3),
            })
    return result


def overall_metrics(all_rows: list[dict], states: list[dict]) -> list[dict]:
    out = []
    for strategy in STRATEGIES:
        rows = [r for r in all_rows if r["strategy"] == strategy]
        ss = [r for r in states if r["strategy"] == strategy and r["state_index"] > 0]
        penalized_recovery = [float(r["recovery_time_ms"]) if r["recovery_time_ms"] != "" else SEGMENT_DURATION * 1e3 for r in ss]
        out.append({
            "strategy": strategy, "steady_error_pct": float(np.mean([r["steady_error_pct"] for r in ss])),
            "mean_recovery_time_ms_penalized": float(np.mean(penalized_recovery)),
            "unsettled_segments": int(sum(not r["settled"] for r in ss)),
            "power_stability_cv_pct": float(np.mean([r["power_stability_cv_pct"] for r in ss])),
            "peak_current_mA_RMS": float(max(r["iport_irms_A"] for r in rows) * 1e3),
            "peak_voltage_vpp": float(max(r["vport_vpp"] for r in rows)),
            "soft_limit_triggers": episode_count(rows, "soft_limit_trigger"),
            "hard_trip_triggers": episode_count(rows, "hard_trip_trigger"),
            "actual_hard_violations": int(sum(r["actual_voltage_hard_violation"] + r["actual_current_hard_violation"] for r in rows)),
            "frequency_saturation_ms": float(sum(r["duration_s"] for r in rows if r["action"] == "CONTROL" and r["frequency_saturated"]) * 1e3),
            "locked_frequency_min_MHz": float(min(r["locked_frequency_MHz"] for r in ss)),
            "locked_frequency_max_MHz": float(max(r["locked_frequency_MHz"] for r in ss)),
            "max_power_overshoot_pct": float(max(r["peak_power_overshoot_pct"] for r in ss)),
            "oscillating_segments": int(sum(r["oscillation_flag"] for r in ss)),
            "wrong_phase_lock_segments": int(sum(r["wrong_phase_lock_flag"] for r in ss)),
            "scan_points": int(sum(r["action"].startswith("SCAN") for r in rows)),
            "scan_time_s": float(sum(r["duration_s"] for r in rows if r["action"].startswith("SCAN"))),
        })
    return out


def save_figure(fig, stem: str) -> None:
    fig.tight_layout(pad=1.2)
    for ext, kwargs in (("png", {"dpi": 300}), ("svg", {}), ("pdf", {})):
        fig.savefig(OUT / f"{stem}.{ext}", bbox_inches="tight", **kwargs)
    plt.close(fig)


def make_figures(all_rows: list[dict], overall: list[dict]) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 7.0), sharex=True)
    for strategy in STRATEGIES:
        rows = [r for r in all_rows if r["strategy"] == strategy and r["action"] == "CONTROL"]
        t = [r["time_s"] for r in rows]
        axes[0].plot(t, [r["safe_power_capture_ratio"] * 100 for r in rows], color=COLORS[strategy], lw=1.0, label=strategy)
        axes[1].plot(t, [r["frequency_MHz"] for r in rows], color=COLORS[strategy], lw=1.0)
        axes[2].plot(t, [r["amplitude_command"] for r in rows], color=COLORS[strategy], lw=1.0)
    for seg in SCHEDULE[1:]:
        for ax in axes: ax.axvline(seg["start_s"], color="#D8D8D8", lw=0.6)
    axes[0].axhline(RECOVERY_CAPTURE_THRESHOLD * 100, color="#272727", ls="--", lw=0.7)
    axes[0].set_ylabel("Safe power capture (%)"); axes[0].legend(ncol=3, fontsize=7)
    axes[1].set_ylabel("Frequency (MHz)"); axes[2].set_ylabel("Amplitude command"); axes[2].set_xlabel("Quasi-steady time (s)")
    fig.suptitle("Three strategies under the identical absolute-time disturbance schedule")
    save_figure(fig, "stage4_01_three_strategy_timeline")

    triggered = [
        r for r in all_rows
        if r["hard_trip_trigger"] or r["soft_limit_trigger"] or r["protection_state"] != "NORMAL"
    ]
    if triggered:
        center = min(r["time_s"] for r in triggered)
        window_start = max(0.0, center - 0.12)
        window_end = min(TOTAL_TIME, center + 0.70)
    else:
        high = next(s for s in SCHEDULE if s["case_id"] == "CASE_COMBINED_HIGH")
        window_start, window_end = high["start_s"] - 0.15, high["end_s"] + 0.15
    fig, axes = plt.subplots(3, 1, figsize=(8.0, 5.8), sharex=True)
    for strategy in STRATEGIES:
        rows = [r for r in all_rows if r["strategy"] == strategy and window_start <= r["time_s"] <= window_end]
        axes[0].plot([r["time_s"] for r in rows], [r["vport_vpp"] for r in rows], color=COLORS[strategy], lw=0.9, label=strategy)
        axes[1].plot([r["time_s"] for r in rows], [r["iport_irms_A"] * 1e3 for r in rows], color=COLORS[strategy], lw=0.9)
        axes[2].plot([r["time_s"] for r in rows], [r["amplitude_command"] for r in rows], color=COLORS[strategy], lw=0.9)
    axes[0].axhline(VPP_SOFT, color="#E28E2C", ls="--"); axes[0].axhline(VPP_HARD, color="#B64342", ls=":")
    axes[1].axhline(IRMS_SOFT * 1e3, color="#E28E2C", ls="--"); axes[1].axhline(IRMS_HARD * 1e3, color="#B64342", ls=":")
    axes[0].set_ylabel("Port voltage (Vpp)"); axes[1].set_ylabel("Port current (mA RMS)")
    axes[2].set_ylabel("Amplitude command"); axes[2].set_xlabel("Quasi-steady time (s)")
    axes[0].legend(ncol=3, fontsize=7); fig.suptitle("Protection state machine around the triggered limit event")
    save_figure(fig, "stage4_02_protection_state_machine")

    metrics = ["steady_error_pct", "mean_recovery_time_ms_penalized", "power_stability_cv_pct", "peak_current_mA_RMS"]
    titles = ["Steady error (%)", "Recovery time (ms)", "Power CV (%)", "Peak current (mA RMS)"]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.1))
    for ax, metric, title in zip(axes.flat, metrics, titles):
        values = [0.0 if abs(r[metric]) < 1e-9 else r[metric] for r in overall]
        bars = ax.bar(range(3), values, color=[COLORS[r["strategy"]] for r in overall])
        ax.set_xticks(range(3), ["Fixed", "Scan", "P&O"]); ax.set_title(title)
        if max(values) == 0:
            ax.set_ylim(0, 1)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:.2f}",
                    ha="center", va="bottom", fontsize=7)
    fig.suptitle("Stage-5 summary metrics from the same disturbance sequence")
    save_figure(fig, "stage5_01_integrated_metrics")

    po = [r for r in all_rows if r["strategy"] == "P_AND_O" and r["action"] == "CONTROL"]
    fig, axes = plt.subplots(2, 1, figsize=(8.2, 4.8), sharex=True)
    axes[0].plot([r["time_s"] for r in po], [r["safe_power_capture_ratio"] * 100 for r in po], color=COLORS["P_AND_O"])
    axes[1].plot([r["time_s"] for r in po], [r["frequency_MHz"] for r in po], color=COLORS["P_AND_O"])
    axes[0].set_ylabel("Safe power capture (%)"); axes[1].set_ylabel("Frequency (MHz)"); axes[1].set_xlabel("Quasi-steady time (s)")
    fig.suptitle("P&O tracking with coarse re-acquisition when capture is lost")
    save_figure(fig, "stage4_03_P_and_O_detail")


def write_report(overall: list[dict]) -> None:
    lines = [
        "# v2.1第四、五步：三种控制策略、保护状态机与综合比较", "",
        "## 控制对象与边界", "",
        "被控对象为已通过LTspice RAW交叉验证的MODEL_V2_1_HYPOTHETICAL解析电路。控制器是离散准稳态仿真，不是硬件PLL、功放瞬态或实物实验。", "",
        "## 三种策略", "",
        "1. 固定0.9 MHz、请求幅度a=1，保护状态机可覆盖幅度。",
        "2. 周期性自适应局部扫频：±50 kHz/5 kHz粗扫、±5 kHz/1 kHz细扫，最后在候选点±1 kHz内以0.1 kHz精扫；每点1.5 ms、探测幅度0.4。",
        "3. 扫描辅助P&O最大功率跟踪：扰动后低幅重捕获，随后以初始0.5 kHz、最小0.1 kHz的P&O微调；所有调频前先降幅。", "",
        "## 保护状态机", "",
        "状态为NORMAL、SOFT_FOLDBACK、HARD_TRIP、RECOVERY_HOLD和RAMP_UP。130 Vpp/5.5 mA RMS为软触发，160 Vpp/6 mA RMS为硬上限。硬限采用命令施加前预测裁剪，因此实际硬越限次数必须为0；所有非NORMAL状态均先调幅并冻结频率，回到NORMAL后才恢复跟踪。", "",
        "## 阶段五：第4周综合表", "",
        f"恢复时间按v2.1验收口径计算：仅统计NORMAL控制样本，进入{RECOVERY_CAPTURE_THRESHOLD * 100:.0f}% P*并连续保持{RECOVERY_CONSECUTIVE_SAMPLES}个控制样本；扫描点和保护冻结段不计入连续保持。", "",
        "|策略|稳态误差|恢复时间（含未收敛惩罚）|功率CV|峰值电流|软限触发|硬跳闸命令|实际硬越限|频率饱和|错误相位锁定|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in overall:
        lines.append(
            f"|{r['strategy']}|{r['steady_error_pct']:.2f}%|{r['mean_recovery_time_ms_penalized']:.1f} ms|{r['power_stability_cv_pct']:.2f}%|"
            f"{r['peak_current_mA_RMS']:.3f} mA|{r['soft_limit_triggers']}|{r['hard_trip_triggers']}|{r['actual_hard_violations']}|"
            f"{r['frequency_saturation_ms']:.1f} ms|{r['wrong_phase_lock_segments']}|"
        )
    lines += ["", "所有策略使用完全相同的绝对时间扰动边界。结果排序只对当前线性模型、阈值和驻留时间成立。"]
    (OUT / "stage4_5_control_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = scenario_map(); optima = optimal_tables(scenarios)
    all_rows = []
    for strategy in STRATEGIES:
        all_rows.extend(simulate(strategy, scenarios, optima))
    states = segment_metrics(all_rows); overall = overall_metrics(all_rows, states)
    write_csv(OUT / "stage4_control_timeline.csv", all_rows)
    write_csv(OUT / "stage5_per_segment_metrics.csv", states)
    write_csv(OUT / "stage5_integrated_strategy_table.csv", overall)
    make_figures(all_rows, overall); write_report(overall)
    schedule_string = json.dumps(SCHEDULE, sort_keys=True)
    audit = {
        "status": "PASS" if all(r["actual_hard_violations"] == 0 for r in overall) else "FAIL",
        "model_id": "MODEL_V2_1_HYPOTHETICAL", "strategies": STRATEGIES,
        "schedule": SCHEDULE, "schedule_sha256": hashlib.sha256(schedule_string.encode()).hexdigest(),
        "all_strategies_same_schedule": True, "control_dt_s": CONTROL_DT, "scan_point_dt_s": SCAN_POINT_DT,
        "recovery_capture_threshold": RECOVERY_CAPTURE_THRESHOLD,
        "recovery_consecutive_control_samples": RECOVERY_CONSECUTIVE_SAMPLES,
        "recovery_only_normal_control_samples": True,
        "p_and_o_initial_step_Hz": P_AND_O_INITIAL_STEP, "p_and_o_min_step_Hz": P_AND_O_MIN_STEP,
        "frequency_update_only_in_normal": True,
        "protection_states": ["NORMAL", "SOFT_FOLDBACK", "HARD_TRIP", "RECOVERY_HOLD", "RAMP_UP"],
        "soft_limits": {"Vpp": VPP_SOFT, "Irms_A": IRMS_SOFT}, "hard_limits": {"Vpp": VPP_HARD, "Irms_A": IRMS_HARD},
        "actual_hard_violation_total": int(sum(r["actual_hard_violations"] for r in overall)),
        "scope": "quasi-steady linear electrical control simulation; no measured, acoustic, thermal or hardware timing claim",
    }
    (OUT / "stage4_5_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "overall": overall}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
