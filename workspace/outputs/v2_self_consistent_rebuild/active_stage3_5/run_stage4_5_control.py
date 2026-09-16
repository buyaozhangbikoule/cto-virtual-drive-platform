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
from dataclasses import dataclass, field
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
# 三级扫描阶梯的 6 个常量来自登记表，不写死在代码里：捕获级窗口决定控制器能追
# 多远的 fs 漂移，是一个有后果的设计选择（当前 ±50 kHz 够不到 CASE_LM_P20 /
# CASE_CM_P20，见 scan_parameters.json 的 known_coverage_gap）。
_scan = json.loads((Path(__file__).resolve().parent / "scan_parameters.json").read_text(encoding="utf-8"))
_ladder = _scan["ladder"]
COARSE_HALFWIDTH_HZ = float(_ladder["coarse"]["halfwidth_Hz"])
COARSE_STEP_HZ = float(_ladder["coarse"]["step_Hz"])
FINE_HALFWIDTH_HZ = float(_ladder["fine"]["halfwidth_Hz"])
FINE_STEP_HZ = float(_ladder["fine"]["step_Hz"])
ULTRA_HALFWIDTH_HZ = float(_ladder["ultra"]["halfwidth_Hz"])
ULTRA_STEP_HZ = float(_ladder["ultra"]["step_Hz"])

CONTROL_DT = 20e-3
SCAN_POINT_DT = float(_scan["timing"]["scan_point_dt_s"])
PROBE_AMPLITUDE = 0.40
SCAN_INTERVAL = 0.50
SOFT_STABILIZE = 0.10
HARD_HOLD = 0.06
RECOVERY_HOLD = 0.10
RECOVERY_AMPLITUDE = 0.25
RAMP_STEP = 0.05
P_AND_O_INITIAL_STEP = 0.5e3
P_AND_O_MIN_STEP = 0.1e3
P_AND_O_UPDATE_INTERVAL = 0.10
REFERENCE_ALPHA = 0.02
REFERENCE_STABLE_SAMPLES = 10
DISTURBANCE_MIN_VOTES = 2
DISTURBANCE_CONFIRM_SAMPLES = 3
POWER_DROP_TRIGGER = 0.10
Z_CHANGE_TRIGGER = 0.15
PHASE_CHANGE_TRIGGER_DEG = 5.0
GAMMA_RISE_TRIGGER = 0.10
GAMMA_ABS_TRIGGER = 0.20
REACQUIRE_COOLDOWN = 0.40
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
        # Frequency is frozen during the initial foldback transient, hard hold,
        # recovery hold and ramp-up.  Once soft foldback has been stable for the
        # declared dwell time, a low-amplitude reacquisition scan is allowed.
        soft_stable = (
            self.state == "SOFT_FOLDBACK"
            and self.soft_since is not None
            and (t - self.soft_since) >= SOFT_STABILIZE
        )
        return self.state == "NORMAL" or soft_stable

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


@dataclass
class ObservableDisturbanceDetector:
    """Detect load changes from controller-visible electrical quantities only.

    The hidden scenario schedule and precomputed optimum are deliberately not
    accepted as inputs.  They remain available elsewhere only for evaluation.
    """

    ref_power_W: float | None = None
    ref_z: complex | None = None
    ref_phase_deg: float | None = None
    ref_gamma: float | None = None
    bootstrap: list[tuple[float, complex, float, float, float]] = field(default_factory=list)
    bootstrap_frequency_Hz: float | None = None
    stable_count: int = 0
    abnormal_count: int = 0
    cooldown_until: float = -1.0
    state: str = "BOOTSTRAP"

    @staticmethod
    def _phase_distance_deg(value: float, reference: float) -> float:
        return abs((value - reference + 180.0) % 360.0 - 180.0)

    def _empty_result(self) -> dict:
        return {
            "detector_state": self.state,
            "detector_reference_ready": int(self.ref_power_W is not None),
            "detector_vote_count": 0,
            "detector_consecutive_count": self.abnormal_count,
            "detector_trigger": 0,
            "detector_cooldown_active": 0,
            "detector_d_power": math.nan,
            "detector_d_z": math.nan,
            "detector_d_phase_deg": math.nan,
            "detector_gamma_threshold": math.nan,
            "detector_reason": "",
        }

    def _seed_reference(self) -> None:
        self.ref_power_W = float(np.mean([item[0] for item in self.bootstrap]))
        self.ref_z = complex(np.mean([item[1] for item in self.bootstrap]))
        self.ref_phase_deg = float(np.mean([item[2] for item in self.bootstrap]))
        self.ref_gamma = float(np.mean([item[3] for item in self.bootstrap]))
        self.bootstrap.clear()
        self.bootstrap_frequency_Hz = None
        self.stable_count = 0
        self.abnormal_count = 0
        self.state = "READY"

    def _collect_bootstrap(self, power: float, z_value: complex, phase: float,
                           gamma: float, frequency: float) -> None:
        if self.bootstrap_frequency_Hz is None or abs(frequency - self.bootstrap_frequency_Hz) <= 1e-9:
            self.bootstrap_frequency_Hz = frequency
            self.bootstrap.append((power, z_value, phase, gamma, frequency))
        else:
            self.bootstrap = [(power, z_value, phase, gamma, frequency)]
            self.bootstrap_frequency_Hz = frequency
        if len(self.bootstrap) >= REFERENCE_STABLE_SAMPLES:
            self._seed_reference()

    def after_scan(self, t: float) -> None:
        """Freeze old references and require a new stable reference after scan."""
        self.ref_power_W = None
        self.ref_z = None
        self.ref_phase_deg = None
        self.ref_gamma = None
        self.bootstrap.clear()
        self.bootstrap_frequency_Hz = None
        self.stable_count = 0
        self.abnormal_count = 0
        self.cooldown_until = t + REACQUIRE_COOLDOWN
        self.state = "COOLDOWN"

    def observe(self, row: dict, t: float, allow_trigger: bool) -> dict:
        """Return detector annotations without reading case_id or optimum fields."""
        result = self._empty_result()
        eligible = (
            row["action"] == "CONTROL"
            and row["protection_state"] == "NORMAL"
            and not row["frequency_frozen"]
            and row["amplitude_command"] >= 0.999
        )
        if not eligible:
            self.state = "REFERENCE_FROZEN"
            result["detector_state"] = self.state
            return result

        power = float(row["normalized_port_power_W"])
        z_value = complex(row["zin_real_ohm"], row["zin_imag_ohm"])
        phase = float(row["phase_deg"])
        gamma = float(row["gamma"])
        frequency = float(row["frequency_Hz"])

        if t < self.cooldown_until:
            # A post-scan reference may be built during cooldown, but it cannot
            # trigger another scan until the cooldown expires.
            if self.ref_power_W is None:
                self._collect_bootstrap(power, z_value, phase, gamma, frequency)
            self.state = "COOLDOWN"
            result["detector_state"] = self.state
            result["detector_reference_ready"] = int(self.ref_power_W is not None)
            result["detector_cooldown_active"] = 1
            return result

        if self.ref_power_W is None:
            self._collect_bootstrap(power, z_value, phase, gamma, frequency)
            self.state = "BOOTSTRAP"
            result["detector_state"] = self.state
            result["detector_reference_ready"] = int(self.ref_power_W is not None)
            return result

        d_power = (self.ref_power_W - power) / max(abs(self.ref_power_W), 1e-30)
        d_z = abs(z_value - self.ref_z) / max(abs(self.ref_z), 1e-30)
        d_phase = self._phase_distance_deg(phase, self.ref_phase_deg)
        gamma_threshold = max(self.ref_gamma + GAMMA_RISE_TRIGGER, GAMMA_ABS_TRIGGER)
        conditions = {
            "POWER_DROP": d_power > POWER_DROP_TRIGGER,
            "COMPLEX_Z_CHANGE": d_z > Z_CHANGE_TRIGGER,
            "PHASE_CHANGE": d_phase > PHASE_CHANGE_TRIGGER_DEG,
            "REFLECTION_RISE": gamma > gamma_threshold,
        }
        votes = int(sum(conditions.values()))
        reason = "+".join(name for name, active in conditions.items() if active)
        result.update({
            "detector_reference_ready": 1,
            "detector_vote_count": votes,
            "detector_d_power": d_power,
            "detector_d_z": d_z,
            "detector_d_phase_deg": d_phase,
            "detector_gamma_threshold": gamma_threshold,
            "detector_reason": reason,
        })

        if votes >= DISTURBANCE_MIN_VOTES:
            self.abnormal_count += 1
            self.stable_count = 0
            self.state = "SUSPECT"
        else:
            self.abnormal_count = 0
            if votes == 0:
                self.stable_count += 1
            else:
                self.stable_count = 0
            self.state = "READY"

        if allow_trigger and self.abnormal_count >= DISTURBANCE_CONFIRM_SAMPLES:
            self.state = "REACQUIRE"
            self.cooldown_until = t + REACQUIRE_COOLDOWN
            result["detector_consecutive_count"] = self.abnormal_count
            self.abnormal_count = 0
            self.stable_count = 0
            result["detector_trigger"] = 1
            result["detector_reason"] = reason or "MULTIVARIATE_CHANGE"

        # The reference follows slow drift only after ten consecutive clean
        # NORMAL samples.  It remains frozen during suspect/protection/scan/P&O.
        if self.stable_count >= REFERENCE_STABLE_SAMPLES and votes == 0:
            alpha = REFERENCE_ALPHA
            self.ref_power_W = (1.0 - alpha) * self.ref_power_W + alpha * power
            self.ref_z = (1.0 - alpha) * self.ref_z + alpha * z_value
            self.ref_phase_deg = (1.0 - alpha) * self.ref_phase_deg + alpha * phase
            self.ref_gamma = (1.0 - alpha) * self.ref_gamma + alpha * gamma

        result["detector_state"] = self.state
        if not result["detector_trigger"]:
            result["detector_consecutive_count"] = self.abnormal_count
        return result


def measure(t: float, duration: float, strategy: str, action: str, frequency: float, amplitude: float,
            protection_state: str, hard_trigger: int, soft_trigger: int, frozen: bool,
            segment: dict, scenario, optimum: dict, scan_reason: str = "") -> dict:
    q = response(frequency, scenario, amplitude)
    p = float(q["p_rm_W"][0]); phase = float(q["phase_deg"][0])
    vpp = float(q["vport_vpp"][0]); irms = float(q["iport_irms_A"][0])
    p_port = float(q["p_port_W"][0]); p_source = float(q["p_source_W"][0])
    z_in = complex(q["z_in"][0])
    normalized_port_power = p_port / max(amplitude * amplitude, 1e-12)
    return {
        "strategy": strategy, "time_s": t, "duration_s": duration, "action": action,
        "state_index": segment["state_index"], "case_id": segment["case_id"],
        "frequency_Hz": frequency, "frequency_MHz": frequency / 1e6,
        "amplitude_command": amplitude, "protection_state": protection_state,
        "frequency_frozen": int(frozen), "hard_trip_trigger": hard_trigger, "soft_limit_trigger": soft_trigger,
        "scan_reason": scan_reason, "p_rm_W": p, "p_port_W": p_port, "p_source_W": p_source,
        "normalized_port_power_W": normalized_port_power,
        "zin_real_ohm": float(z_in.real), "zin_imag_ohm": float(z_in.imag), "zin_abs_ohm": abs(z_in),
        "phase_deg": phase, "gamma": float(q["gamma"][0]),
        "vport_vpp": vpp, "iport_irms_A": irms,
        "detector_state": "NOT_EVALUATED", "detector_reference_ready": 0,
        "detector_vote_count": 0, "detector_consecutive_count": 0, "detector_trigger": 0,
        "detector_cooldown_active": 0, "detector_d_power": math.nan, "detector_d_z": math.nan,
        "detector_d_phase_deg": math.nan, "detector_gamma_threshold": math.nan, "detector_reason": "",
        "actual_voltage_hard_violation": int(vpp > VPP_HARD + 1e-9),
        "actual_current_hard_violation": int(irms > IRMS_HARD + 1e-12),
        "optimal_safe_frequency_Hz": optimum["frequency_Hz"], "optimal_safe_power_W": optimum["power_W"],
        "safe_power_capture_ratio": p / max(optimum["power_W"], 1e-30),
        "frequency_error_kHz": (frequency - optimum["frequency_Hz"]) / 1e3,
        "frequency_saturated": int(frequency <= F_MIN + 1e-9 or frequency >= F_MAX - 1e-9),
    }


def local_scan(t: float, strategy: str, current_f: float, reason: str, rows: list[dict], protection: Protection,
               scenarios: dict, optima: dict) -> tuple[float, float, bool]:
    """Execute low-amplitude sequential scans using observable port power.

    The plant schedule is consulted only to produce the physical response at the
    current time.  Scenario identity is not used to trigger or abort the scan.
    """
    coarse = np.arange(max(F_MIN, current_f - COARSE_HALFWIDTH_HZ),
                       min(F_MAX, current_f + COARSE_HALFWIDTH_HZ) + 1, COARSE_STEP_HZ)
    measured = []
    for f in coarse:
        seg = schedule_at(t); scenario = scenarios[seg["case_id"]]; opt = optima[seg["case_id"]]
        row = measure(t, SCAN_POINT_DT, strategy, "SCAN_COARSE", float(f), PROBE_AMPLITUDE,
                      protection.state, 0, 0, True, seg, scenario, opt, reason)
        rows.append(row); measured.append((row["normalized_port_power_W"], float(f))); t += SCAN_POINT_DT
    coarse_best = max(measured)[1]
    fine = np.arange(max(F_MIN, coarse_best - FINE_HALFWIDTH_HZ),
                     min(F_MAX, coarse_best + FINE_HALFWIDTH_HZ) + 1, FINE_STEP_HZ)
    measured = []
    for f in fine:
        seg = schedule_at(t); scenario = scenarios[seg["case_id"]]; opt = optima[seg["case_id"]]
        row = measure(t, SCAN_POINT_DT, strategy, "SCAN_FINE", float(f), PROBE_AMPLITUDE,
                      protection.state, 0, 0, True, seg, scenario, opt, reason)
        rows.append(row); measured.append((row["normalized_port_power_W"], float(f))); t += SCAN_POINT_DT
    fine_best = max(measured)[1]
    # The Qm sensitivity study shows a ~1.7--3.5 kHz FWHM.  A final 0.1 kHz
    # refinement is therefore needed to satisfy a 95% power-capture criterion;
    # it is restricted to +/-1 kHz so its time cost remains explicit and small.
    ultra = np.arange(max(F_MIN, fine_best - ULTRA_HALFWIDTH_HZ),
                      min(F_MAX, fine_best + ULTRA_HALFWIDTH_HZ) + 1, ULTRA_STEP_HZ)
    measured = []
    for f in ultra:
        seg = schedule_at(t); scenario = scenarios[seg["case_id"]]; opt = optima[seg["case_id"]]
        row = measure(t, SCAN_POINT_DT, strategy, "SCAN_ULTRAFINE", float(f), PROBE_AMPLITUDE,
                      protection.state, 0, 0, True, seg, scenario, opt, reason)
        rows.append(row); measured.append((row["normalized_port_power_W"], float(f))); t += SCAN_POINT_DT
    return max(measured)[1], t, True


def simulate(strategy: str, scenarios: dict, optima: dict) -> list[dict]:
    rows: list[dict] = []
    protection = Protection()
    detector = ObservableDisturbanceDetector()
    t = 0.0; frequency = F0; next_scan = 0.0
    po_dir = 1.0; po_step = P_AND_O_INITIAL_STEP; po_next_update = 0.0
    po_need_reacquire = False
    po_reacquire_reason = ""

    while t < TOTAL_TIME - 1e-12:
        seg = schedule_at(t); case_id = seg["case_id"]; scenario = scenarios[case_id]; optimum = optima[case_id]

        # Scans are only allowed after protection has stabilized.
        if strategy == "PERIODIC_SCAN" and t >= next_scan and protection.tracking_allowed(t):
            frequency, t, completed = local_scan(t, strategy, frequency, "PERIODIC_TIMER", rows, protection, scenarios, optima)
            next_scan = t + SCAN_INTERVAL
            detector.after_scan(t)
            seg = schedule_at(t); case_id = seg["case_id"]; scenario = scenarios[case_id]; optimum = optima[case_id]

        if strategy == "P_AND_O" and po_need_reacquire and protection.tracking_allowed(t):
            frequency, t, completed = local_scan(
                t, strategy, frequency, po_reacquire_reason or "OBSERVABLE_REACQUIRE", rows, protection, scenarios, optima
            )
            po_need_reacquire = False
            po_reacquire_reason = ""
            po_step = P_AND_O_INITIAL_STEP
            detector.after_scan(t)
            po_next_update = t + REACQUIRE_COOLDOWN + REFERENCE_STABLE_SAMPLES * CONTROL_DT
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
            candidate_f = float(np.clip(frequency + po_dir * po_step, F_MIN, F_MAX))
            probe_seg = schedule_at(t); probe_case = probe_seg["case_id"]
            probe_scenario = scenarios[probe_case]; probe_optimum = optima[probe_case]
            amp1, state1, hard1, soft1, frozen1 = protection.apply(t, candidate_f, probe_scenario, PROBE_AMPLITUDE)
            probe = measure(t, CONTROL_DT, strategy, "P_AND_O_PROBE", candidate_f, amp1, state1,
                            hard1, soft1, True, probe_seg, probe_scenario, probe_optimum)
            rows.append(probe); t += CONTROL_DT
            rel = (
                probe["normalized_port_power_W"] - ref["normalized_port_power_W"]
            ) / max(abs(ref["normalized_port_power_W"]), 1e-30)
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
        row.update(detector.observe(row, t, allow_trigger=strategy == "P_AND_O"))
        rows.append(row)

        if strategy == "FIXED_0P9":
            frequency = F0
        elif strategy == "P_AND_O":
            if (hard_trigger or soft_trigger) and not po_need_reacquire:
                po_need_reacquire = True
                po_reacquire_reason = "HARD_LIMIT_EVENT" if hard_trigger else "SOFT_LIMIT_EVENT"
                po_step = P_AND_O_INITIAL_STEP
                po_next_update = math.inf
            elif row["detector_trigger"]:
                po_need_reacquire = True
                po_reacquire_reason = "OBSERVABLE_2_OF_4"
                po_step = P_AND_O_INITIAL_STEP
                po_next_update = math.inf

        t += CONTROL_DT
    return rows


def episode_count(rows: list[dict], key: str) -> int:
    return int(sum(int(r[key]) for r in rows))


def scan_episode_count(rows: list[dict]) -> int:
    count = 0
    previous_scan = False
    for row in sorted(rows, key=lambda item: item["time_s"]):
        current_scan = row["action"].startswith("SCAN")
        if current_scan and not previous_scan:
            count += 1
        previous_scan = current_scan
    return count


def observable_trigger_evaluation(all_rows: list[dict]) -> list[dict]:
    """Use the hidden schedule only after simulation to score observable triggers."""
    rows = [r for r in all_rows if r["strategy"] == "P_AND_O"]
    output = []
    for segment in SCHEDULE[1:]:
        segment_rows = [
            r for r in rows
            if segment["start_s"] <= r["time_s"] < segment["end_s"]
        ]
        control = [r for r in segment_rows if r["action"] == "CONTROL"]
        events = [
            r for r in control
            if r["detector_trigger"] or r["hard_trip_trigger"] or r["soft_limit_trigger"]
        ]
        scans = [r for r in segment_rows if r["action"].startswith("SCAN")]
        first_event = events[0] if events else None
        first_scan = scans[0] if scans else None
        if first_event is None:
            source = "NONE"
        elif first_event["hard_trip_trigger"]:
            source = "HARD_LIMIT_EVENT"
        elif first_event["soft_limit_trigger"]:
            source = "SOFT_LIMIT_EVENT"
        else:
            source = "OBSERVABLE_2_OF_4"
        output.append({
            "state_index": segment["state_index"],
            "case_id": segment["case_id"],
            "first_control_capture_pct_evaluation_only": "" if not control else control[0]["safe_power_capture_ratio"] * 100,
            "trigger_observed": int(first_event is not None),
            "trigger_source": source,
            "trigger_delay_ms": "" if first_event is None else (first_event["time_s"] - segment["start_s"]) * 1e3,
            "scan_started": int(first_scan is not None),
            "scan_start_delay_ms": "" if first_scan is None else (first_scan["time_s"] - segment["start_s"]) * 1e3,
            "event_rows_in_segment": len(events),
            "scan_points_in_segment": len(scans),
            "detector_reason": "" if first_event is None else first_event["detector_reason"],
            "note": "schedule and optimum fields are used here for post-run scoring only",
        })
    return output


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
            "observable_detector_triggers": episode_count(rows, "detector_trigger"),
            "limit_event_triggers": episode_count(rows, "soft_limit_trigger") + episode_count(rows, "hard_trip_trigger"),
            "scan_episodes": scan_episode_count(rows),
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

    po_control = [r for r in all_rows if r["strategy"] == "P_AND_O" and r["action"] == "CONTROL"]
    fig, axes = plt.subplots(3, 1, figsize=(8.4, 5.8), sharex=True)
    t_control = [r["time_s"] for r in po_control]
    axes[0].plot(t_control, [r["normalized_port_power_W"] * 1e3 for r in po_control], color="#272727", lw=0.9)
    axes[0].set_ylabel("Normalized Pport (mW)")
    axes[1].step(t_control, [r["detector_vote_count"] for r in po_control], where="post", color="#3775BA", lw=1.0)
    axes[1].axhline(DISTURBANCE_MIN_VOTES, color="#B64342", ls="--", lw=0.8, label="2-of-4 threshold")
    trigger_rows = [r for r in po_control if r["detector_trigger"]]
    axes[1].scatter([r["time_s"] for r in trigger_rows], [r["detector_vote_count"] for r in trigger_rows],
                    color="#B64342", marker="v", s=22, zorder=3, label="confirmed trigger")
    limit_rows = [r for r in po_control if r["hard_trip_trigger"] or r["soft_limit_trigger"]]
    axes[1].scatter([r["time_s"] for r in limit_rows], [0.25] * len(limit_rows),
                    color="#E28E2C", marker="s", s=18, zorder=3, label="safety-limit event")
    axes[1].set_ylabel("Abnormal votes"); axes[1].set_ylim(-0.2, 4.4); axes[1].legend(fontsize=7, ncol=2)
    axes[2].plot(t_control, [r["frequency_MHz"] for r in po_control], color=COLORS["P_AND_O"], lw=1.0)
    scan_starts = []
    previous_scan = False
    for row in [r for r in all_rows if r["strategy"] == "P_AND_O"]:
        current_scan = row["action"].startswith("SCAN")
        if current_scan and not previous_scan:
            scan_starts.append(row)
        previous_scan = current_scan
    axes[2].scatter([r["time_s"] for r in scan_starts], [r["frequency_MHz"] for r in scan_starts],
                    facecolors="none", edgecolors="#3775BA", s=28, label="reacquisition scan start")
    axes[2].set_ylabel("Frequency (MHz)"); axes[2].set_xlabel("Quasi-steady time (s)"); axes[2].legend(fontsize=7)
    for segment in SCHEDULE[1:]:
        for axis in axes:
            axis.axvline(segment["start_s"], color="#D8D8D8", lw=0.6)
    fig.suptitle("Observable disturbance detection and scan-assisted P&O")
    save_figure(fig, "stage4_04_observable_disturbance_detector")


def write_report(overall: list[dict]) -> None:
    lines = [
        "# v2.1第四、五步：三种控制策略、保护状态机与综合比较", "",
        "## 控制对象与边界", "",
        "被控对象为已通过LTspice RAW交叉验证的MODEL_V2_1_HYPOTHETICAL解析电路。控制器是离散准稳态仿真，不是硬件PLL、功放瞬态或实物实验。", "",
        "## 三种策略", "",
        "1. 固定0.9 MHz、请求幅度a=1，保护状态机可覆盖幅度。",
        "2. 周期性自适应局部扫频：±50 kHz/5 kHz粗扫、±5 kHz/1 kHz细扫，最后在候选点±1 kHz内以0.1 kHz精扫；每点1.5 ms、探测幅度0.4。",
        "3. 扫描辅助P&O最大功率跟踪：控制器不读取场景切换或真实最优功率；由端口功率、复阻抗、相位和反射代理的2-of-4连续判据，或可观测软/硬限事件触发低幅重捕获，随后以初始0.5 kHz、最小0.1 kHz的P&O微调。", "",
        "## 可观测扰动检测", "",
        "每20 ms由匹配网络输入侧Vinput/Isource计算Zin及其相位，同时计算端口有功功率和反射代理。功率按幅度命令平方归一化。NORMAL且幅度稳定的连续10个样本用于建立/更新参考；保护、扫描和P&O试探期间冻结参考。", "",
        f"本轮假设触发阈值为：归一化端口功率下降>{POWER_DROP_TRIGGER*100:.0f}%、复阻抗相对变化>{Z_CHANGE_TRIGGER*100:.0f}%、相位变化>{PHASE_CHANGE_TRIGGER_DEG:.0f}°、反射代理>max(参考+{GAMMA_RISE_TRIGGER:.2f}, {GAMMA_ABS_TRIGGER:.2f})。至少{DISTURBANCE_MIN_VOTES}项连续{DISTURBANCE_CONFIRM_SAMPLES}个控制样本成立才进入REACQUIRE；扫描后冷却{REACQUIRE_COOLDOWN:.1f} s。以上均为假设控制阈值，不是实测整定值。", "",
        "## 保护状态机", "",
        "状态为NORMAL、SOFT_FOLDBACK、HARD_TRIP、RECOVERY_HOLD和RAMP_UP。130 Vpp/5.5 mA RMS为软触发，160 Vpp/6 mA RMS为硬上限。硬限采用命令施加前预测裁剪，因此实际硬越限次数必须为0；硬跳闸、恢复保持、渐升和软降额初始稳定段冻结频率，软降额稳定后才允许以0.4幅度执行重捕获扫描。", "",
        "## 阶段五：第4周综合表", "",
        f"恢复时间按v2.1验收口径计算：仅统计NORMAL控制样本，进入{RECOVERY_CAPTURE_THRESHOLD * 100:.0f}% P*并连续保持{RECOVERY_CONSECUTIVE_SAMPLES}个控制样本；扫描点和保护冻结段不计入连续保持。", "",
        "|策略|稳态误差|恢复时间（含未收敛惩罚）|功率CV|峰值电流|软限触发|硬跳闸命令|可观测检测触发|扫描次数|实际硬越限|频率饱和|错误相位锁定|", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in overall:
        lines.append(
            f"|{r['strategy']}|{r['steady_error_pct']:.2f}%|{r['mean_recovery_time_ms_penalized']:.1f} ms|{r['power_stability_cv_pct']:.2f}%|"
            f"{r['peak_current_mA_RMS']:.3f} mA|{r['soft_limit_triggers']}|{r['hard_trip_triggers']}|{r['observable_detector_triggers']}|{r['scan_episodes']}|{r['actual_hard_violations']}|"
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
    trigger_evaluation = observable_trigger_evaluation(all_rows)
    write_csv(OUT / "stage4_control_timeline.csv", all_rows)
    write_csv(OUT / "stage4_observable_trigger_evaluation.csv", trigger_evaluation)
    write_csv(OUT / "stage5_per_segment_metrics.csv", states)
    write_csv(OUT / "stage5_integrated_strategy_table.csv", overall)
    make_figures(all_rows, overall); write_report(overall)
    schedule_string = json.dumps(SCHEDULE, sort_keys=True)
    po_rows = [row for row in all_rows if row["strategy"] == "P_AND_O"]
    detector_logic_pass = all(
        row["detector_vote_count"] >= DISTURBANCE_MIN_VOTES
        and row["detector_consecutive_count"] >= DISTURBANCE_CONFIRM_SAMPLES
        for row in po_rows if row["detector_trigger"]
    )
    allowed_scan_reasons = {"OBSERVABLE_2_OF_4", "SOFT_LIMIT_EVENT", "HARD_LIMIT_EVENT"}
    observable_scan_reason_pass = all(
        row["scan_reason"] in allowed_scan_reasons
        for row in po_rows if row["action"].startswith("SCAN")
    )
    audit_pass = (
        all(r["actual_hard_violations"] == 0 for r in overall)
        and detector_logic_pass
        and observable_scan_reason_pass
    )
    audit = {
        "status": "PASS" if audit_pass else "FAIL",
        "model_id": "MODEL_V2_1_HYPOTHETICAL", "strategies": STRATEGIES,
        "schedule": SCHEDULE, "schedule_sha256": hashlib.sha256(schedule_string.encode()).hexdigest(),
        "all_strategies_same_schedule": True, "control_dt_s": CONTROL_DT, "scan_point_dt_s": SCAN_POINT_DT,
        "recovery_capture_threshold": RECOVERY_CAPTURE_THRESHOLD,
        "recovery_consecutive_control_samples": RECOVERY_CONSECUTIVE_SAMPLES,
        "recovery_only_normal_control_samples": True,
        "p_and_o_initial_step_Hz": P_AND_O_INITIAL_STEP, "p_and_o_min_step_Hz": P_AND_O_MIN_STEP,
        "controller_uses_case_change_as_trigger": False,
        "controller_uses_optimal_safe_power_as_trigger": False,
        "schedule_and_optimum_used_for_evaluation_only": True,
        "detector_logic_pass": detector_logic_pass,
        "observable_scan_reason_pass": observable_scan_reason_pass,
        "allowed_reacquisition_reasons": sorted(allowed_scan_reasons),
        "p_and_o_objective": "amplitude-normalized observable port active power",
        "disturbance_detector": {
            "measurement_vector": ["P_port/a^2", "complex_Zin", "phase", "reflection_proxy", "Vpp", "Irms"],
            "reference_alpha": REFERENCE_ALPHA,
            "reference_stable_samples": REFERENCE_STABLE_SAMPLES,
            "minimum_votes": DISTURBANCE_MIN_VOTES,
            "consecutive_samples": DISTURBANCE_CONFIRM_SAMPLES,
            "thresholds_are_hypothetical": True,
            "power_drop_fraction": POWER_DROP_TRIGGER,
            "complex_z_change_fraction": Z_CHANGE_TRIGGER,
            "phase_change_deg": PHASE_CHANGE_TRIGGER_DEG,
            "gamma_rise": GAMMA_RISE_TRIGGER,
            "gamma_absolute": GAMMA_ABS_TRIGGER,
            "post_scan_cooldown_s": REACQUIRE_COOLDOWN,
        },
        "frequency_update_only_after_protection_stabilized": True,
        "protection_states": ["NORMAL", "SOFT_FOLDBACK", "HARD_TRIP", "RECOVERY_HOLD", "RAMP_UP"],
        "soft_limits": {"Vpp": VPP_SOFT, "Irms_A": IRMS_SOFT}, "hard_limits": {"Vpp": VPP_HARD, "Irms_A": IRMS_HARD},
        "actual_hard_violation_total": int(sum(r["actual_hard_violations"] for r in overall)),
        "observable_trigger_evaluation": trigger_evaluation,
        "scope": "quasi-steady linear electrical control simulation; no sensor noise, measured data, acoustic, thermal or hardware timing claim",
    }
    (OUT / "stage4_5_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "overall": overall}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
