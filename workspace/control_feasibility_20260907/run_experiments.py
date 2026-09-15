"""Isolated, reproducible ablation; never modify the released platform.

All figures/data are deterministic quasi-steady simulations of a hypothetical
linear BVD. No measured device, acoustic result, or physical safety guarantee.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import time
from dataclasses import asdict

import numpy as np

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
ORIGINAL = WORKSPACE / "outputs/v2_self_consistent_rebuild/active_stage3_5"
RELEASE = WORKSPACE / "CTO_virtual_drive_platform_v2_1/results/tables/stage4_5"
SNAPSHOT = HERE / "snapshot"
RESULTS = HERE / "results_r1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=True), encoding="utf-8")


def save_csv(path, rows):
    if not rows:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open("w", encoding="utf-8-sig", newline="") as h:
        w = csv.DictWriter(h, keys)
        w.writeheader()
        w.writerows(rows)


def snapshot():
    sources = [(ORIGINAL / f, SNAPSHOT / "active_stage3_5" / f)
               for f in ("run_stage4_5_control.py", "model_v2_1.py")]
    sources += [(ORIGINAL.parent / "stage2_matching" / f, SNAPSHOT / "stage2_matching" / f)
                for f in ("stage2_匹配设计参数.json", "stage2_控制源幅度校准.json")]
    sources += [(RELEASE / f, SNAPSHOT / "history" / f)
                for f in ("stage4_control_timeline.csv", "stage5_per_segment_metrics.csv",
                          "stage5_integrated_strategy_table.csv", "stage4_5_audit.json")]
    manifest = []
    for src, dst in sources:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            assert sha(src) == sha(dst), f"Frozen input changed: {src.name}"
        else:
            shutil.copy2(src, dst)
        manifest.append({"original": str(src), "snapshot": str(dst.relative_to(HERE)), "sha256": sha(dst)})
    save_json(HERE / "input_manifest.json", manifest)
    return manifest


def load_legacy():
    sys.path.insert(0, str(SNAPSHOT / "active_stage3_5"))
    import model_v2_1 as model
    spec = importlib.util.spec_from_file_location("legacy_control", SNAPSHOT / "active_stage3_5/run_stage4_5_control.py")
    legacy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = legacy
    spec.loader.exec_module(legacy)
    return model, legacy


def configure_schedule(legacy, dwell):
    legacy.SEGMENT_DURATION = dwell
    legacy.SCHEDULE = [{"state_index": i, "case_id": case, "start_s": i * dwell, "end_s": (i + 1) * dwell}
                       for i, case in enumerate(legacy.SCENARIO_ORDER)]
    legacy.TOTAL_TIME = dwell * len(legacy.SCENARIO_ORDER)


class Guard:
    """Common pointwise MODEL-PREVIEW guard. Not a measured hardware guard.

    Both ablations use this same implementation. E02 only changes readiness for
    reacquisition after a limit event. Existing-drive risk is checked at the
    previously applied frequency; proposed frequency is checked before applying.
    """
    def __init__(self, model, legacy, early_reacquire, adaptive):
        self.m, self.c = model, legacy
        self.early, self.adaptive = early_reacquire, adaptive
        self.state = "NORMAL"
        self.a = 1.0
        self.f = model.F0
        self.hard_until = -1.0
        self.recovery_until = -1.0
        self.soft_since = None
        self.pending = False
        self.last_t = None
        self.calls = 0

    def bounds(self, f, scenario):
        return (float(self.m.allowed_amplitude(f, scenario, use_soft_limits=True)[0]),
                float(self.m.allowed_amplitude(f, scenario, use_soft_limits=False)[0]))

    def tracking_allowed(self, t):
        if t < self.recovery_until - 1e-12:
            return False
        if self.early and self.adaptive and self.pending:
            if self.state in {"HARD_TRIP", "RECOVERY_HOLD", "REACQUIRE_READY"}:
                return True
        return self.state == "NORMAL" or (
            self.state == "SOFT_FOLDBACK" and self.soft_since is not None
            and t - self.soft_since >= self.c.SOFT_STABILIZE - 1e-12)

    def command(self, t, f, target, scenario, role="CONTROL"):
        self.calls += 1
        assert self.m.F_MIN <= f <= self.m.F_MAX
        target = float(np.clip(target, 0, 1))
        prev_f, prev_a = self.f, self.a
        hard = soft = 0
        dt = self.c.CONTROL_DT if self.last_t is None else max(0, t - self.last_t)
        self.last_t = t
        old_soft, old_hard = self.bounds(self.f, scenario)
        if t < self.hard_until - 1e-12:
            self.state, self.a = "HARD_TRIP", 0.0
        elif self.a > old_hard + 1e-12:
            hard = 1
            self.state, self.a = "HARD_TRIP", 0.0
            self.hard_until = t + self.c.HARD_HOLD
            self.recovery_until = self.hard_until + self.c.RECOVERY_HOLD
            self.soft_since = None
            self.pending = self.adaptive
        elif t < self.recovery_until - 1e-12:
            self.state = "RECOVERY_HOLD"
            self.a = min(self.c.RECOVERY_AMPLITUDE, old_soft)
        elif (self.early and self.adaptive and self.pending and role == "CONTROL"
              and self.state in {"HARD_TRIP", "RECOVERY_HOLD", "REACQUIRE_READY"}):
            self.state = "REACQUIRE_READY"
            self.a = min(self.a, self.c.RECOVERY_AMPLITUDE, old_soft)
        else:
            # A changed frequency is allowed only in an explicit low-amplitude
            # scan/probe action. CONTROL never changes frequency during ramp.
            if role == "CONTROL" and abs(f - self.f) > 1e-8:
                raise AssertionError("Frequency selection must be a separate low-amplitude action")
            soft_allow, hard_allow = self.bounds(f, scenario)
            # No frequency jump and simultaneous amplitude increase.
            if abs(f - self.f) > 1e-8:
                assert target <= self.a + 1e-12
            rate_step = self.c.RAMP_STEP * dt / self.c.CONTROL_DT
            candidate = min(target, self.a + rate_step) if target > self.a else target
            if candidate > soft_allow + 1e-12:
                soft = int(self.state != "SOFT_FOLDBACK")
                if self.soft_since is None:
                    self.soft_since = t
                self.a = soft_allow
                self.state = "SOFT_FOLDBACK"
                self.pending = self.pending or self.adaptive
            else:
                self.a = candidate
                if role != "CONTROL":
                    self.state = "LOW_AMPLITUDE"
                elif self.a >= 1.0 - 1e-12:
                    self.state = "NORMAL"
                    self.soft_since = None
                else:
                    self.state = "RAMP_UP"
            self.f = f
            assert self.a <= hard_allow + 1e-12
        frozen = self.state != "NORMAL" or role != "CONTROL"
        return {"a": self.a, "f": self.f, "state": self.state, "hard": hard, "soft": soft,
                "frozen": frozen, "previous_a": prev_a, "previous_f": prev_f,
                "guard_calls": self.calls, "rate_budget": self.c.RAMP_STEP * dt / self.c.CONTROL_DT}


class Experiment:
    def __init__(self, model, legacy, variant, strategy, scenarios, optima):
        self.m, self.c = model, legacy
        self.variant, self.strategy = variant, strategy
        self.scenarios, self.optima = scenarios, optima
        self.g = Guard(model, legacy, variant == "E02", strategy != "FIXED_0P9")
        self.detector = legacy.ObservableDisturbanceDetector()
        self.t, self.rows = 0.0, []
        self.next_scan = 0.0
        self.po_next, self.po_step, self.po_dir = 0.0, legacy.P_AND_O_INITIAL_STEP, 1.0
        self.po_need, self.po_reason = False, ""
        self.scan_id = 0

    def context(self):
        # Time arithmetic must not turn e.g. 4.800000000000000 s into an
        # additional whole 20 ms sample of the previous plant scenario.
        # Rounding only removes sub-picosecond floating-point accumulation.
        seg = self.c.schedule_at(round(self.t, 12) + 1e-13)
        return seg, self.scenarios[seg["case_id"]], self.optima[seg["case_id"]]

    def act(self, action, f, a, duration, reason=""):
        if self.t >= self.c.TOTAL_TIME - 1e-12:
            return None
        seg, scenario, opt = self.context()
        x = self.g.command(self.t, f, a, scenario, action)
        duration = min(duration, self.c.TOTAL_TIME - self.t)
        row = self.c.measure(self.t, duration, self.strategy, action, x["f"], x["a"],
                             x["state"], x["hard"], x["soft"], x["frozen"], seg, scenario, opt, reason)
        row.update({"variant": self.variant, "scan_episode_id": self.scan_id if action.startswith("SCAN") else 0,
                    "guard_called": 1, "guard_call_index": x["guard_calls"],
                    "internal_amplitude": self.g.a, "previous_amplitude": x["previous_a"],
                    "previous_frequency_Hz": x["previous_f"], "requested_amplitude": a,
                    "upward_slew_budget": x["rate_budget"],
                    "power_balance_error_W": float(self.m.response(x["f"], scenario, x["a"])["power_balance_error_W"][0])})
        if action == "CONTROL":
            row.update(self.detector.observe(row, self.t, allow_trigger=self.strategy == "P_AND_O"))
        if self.strategy == "P_AND_O" and (x["hard"] or x["soft"] or row["detector_trigger"]):
            self.po_need = True
            self.po_reason = "HARD_LIMIT_EVENT" if x["hard"] else "SOFT_LIMIT_EVENT" if x["soft"] else "OBSERVABLE_2_OF_4"
            self.po_next = math.inf
        self.rows.append(row)
        self.t += duration
        return row

    def scan_point(self, f, action, scan_a, reason):
        if self.t >= self.c.TOTAL_TIME - 1e-12:
            return None, scan_a
        _, scenario, _ = self.context()
        soft, _ = self.g.bounds(f, scenario)
        # Preview may only reduce the existing low amplitude. Such a reduction
        # is a separate, timed action at the previous frequency.
        if soft < scan_a - 1e-12:
            scan_a = soft
            r = self.act("SCAN_DERATE", self.g.f, scan_a, self.c.CONTROL_DT, reason)
            if r is None or r["protection_state"] in {"HARD_TRIP", "RECOVERY_HOLD"}:
                return None, scan_a
        r = self.act(action, f, min(scan_a, self.g.a), self.c.SCAN_POINT_DT, reason)
        if r is None or r["protection_state"] in {"HARD_TRIP", "RECOVERY_HOLD"} or r["amplitude_command"] <= 1e-12:
            return None, scan_a
        return r, min(scan_a, r["amplitude_command"])

    def scan(self, reason):
        self.scan_id += 1
        center = self.g.f
        scan_a = min(self.c.PROBE_AMPLITUDE, self.g.a)
        r = self.act("SCAN_PREP", center, scan_a, self.c.CONTROL_DT, reason)
        if r is None or r["protection_state"] in {"HARD_TRIP", "RECOVERY_HOLD"}:
            return False
        scan_a = min(scan_a, self.g.a)
        for half_window, step, action in ((50e3, 5e3, "SCAN_COARSE"), (5e3, 1e3, "SCAN_FINE"),
                                          (1e3, 0.1e3, "SCAN_ULTRAFINE")):
            points = np.arange(max(self.m.F_MIN, center - half_window), min(self.m.F_MAX, center + half_window) + 1, step)
            values = []
            for f in points:
                row, scan_a = self.scan_point(float(f), action, scan_a, reason)
                if row is None:
                    return False
                values.append((row["normalized_port_power_W"], float(f)))
            center = max(values)[1]
        row, scan_a = self.scan_point(center, "SCAN_SELECT", scan_a, reason)
        if row is None:
            return False
        self.g.state, self.g.pending, self.g.soft_since = "RAMP_UP", False, None
        self.detector.after_scan(self.t)
        return True

    def po_probe(self):
        f0 = self.g.f
        a = min(self.c.PROBE_AMPLITUDE, self.g.a)
        ref = self.act("P_AND_O_REFERENCE", f0, a, self.c.CONTROL_DT)
        if ref is None or self.po_need:
            return
        candidate = float(np.clip(f0 + self.po_dir * self.po_step, self.m.F_MIN, self.m.F_MAX))
        probe = self.act("P_AND_O_PROBE", candidate, min(a, self.g.a), self.c.CONTROL_DT)
        if probe is None or self.po_need:
            return
        rel = (probe["normalized_port_power_W"] - ref["normalized_port_power_W"]) / max(abs(ref["normalized_port_power_W"]), 1e-30)
        selected = candidate if rel > 0 else f0
        if rel <= 0:
            self.po_dir *= -1
        if rel < 0.005:
            self.po_step = max(self.c.P_AND_O_MIN_STEP, self.po_step / 2)
        self.act("P_AND_O_RETURN", selected, self.g.a, self.c.CONTROL_DT)
        if not self.po_need:
            self.g.state = "RAMP_UP"
            self.po_next = self.t + self.c.P_AND_O_UPDATE_INTERVAL

    def run(self):
        iterations = 0
        while self.t < self.c.TOTAL_TIME - 1e-12:
            iterations += 1
            assert iterations < 100000, "No progress"
            if self.strategy == "PERIODIC_SCAN" and self.t >= self.next_scan and self.g.tracking_allowed(self.t):
                completed = self.scan("PERIODIC_TIMER")
                self.next_scan = self.t + self.c.SCAN_INTERVAL if completed else self.t
                continue
            if self.strategy == "P_AND_O" and self.po_need and self.g.tracking_allowed(self.t):
                completed = self.scan(self.po_reason)
                if completed:
                    self.po_need, self.po_reason = False, ""
                    self.po_step = self.c.P_AND_O_INITIAL_STEP
                    self.po_next = self.t + self.c.REACQUIRE_COOLDOWN + self.c.REFERENCE_STABLE_SAMPLES * self.c.CONTROL_DT
                continue
            if self.strategy == "P_AND_O" and not self.po_need and self.t >= self.po_next and self.g.tracking_allowed(self.t):
                self.po_probe()
                continue
            self.act("CONTROL", self.g.f, 1.0, self.c.CONTROL_DT)
        return self.rows


def compare_history(actual, history):
    with Path(history).open(encoding="utf-8-sig", newline="") as h:
        expected = list(csv.DictReader(h))
    assert len(expected) == len(actual), (len(expected), len(actual))
    errors = []
    numeric_max = 0.0
    for i, (old, new) in enumerate(zip(expected, actual)):
        for key, value in old.items():
            try:
                a, b = float(value), float(new[key])
                equal = (math.isnan(a) and math.isnan(b)) or a == b or math.isclose(a, b, rel_tol=1e-11, abs_tol=1e-12)
                if math.isfinite(a) and math.isfinite(b):
                    numeric_max = max(numeric_max, abs(a - b))
            except (ValueError, TypeError):
                equal = value == str(new[key])
            if not equal:
                errors.append({"row": i, "field": key, "old": value, "new": new[key]})
    return {"rows": len(actual), "fields_per_row": len(expected[0]), "mismatches": errors[:30],
            "mismatch_count": len(errors), "max_absolute_numeric_difference": numeric_max,
            "pass": not errors}


def detailed_metrics(model, legacy, rows, scenarios, optima):
    output = []
    for strategy in legacy.STRATEGIES:
        sr = [r for r in rows if r["strategy"] == strategy]
        for seg in legacy.SCHEDULE:
            rr = [r for r in sr if r["state_index"] == seg["state_index"]]
            control = [r for r in rr if r["action"] == "CONTROL"]
            previous = None
            count = max_count = 0
            first_good = run_start = accepted_start = confirmation = None
            for r in control:
                contiguous = previous is None or r["time_s"] - previous <= legacy.CONTROL_DT * 1.5
                good = contiguous and r["protection_state"] == "NORMAL" and not r["frequency_frozen"] and r["safe_power_capture_ratio"] >= .98
                if good:
                    if first_good is None:
                        first_good = r["time_s"]
                    if count == 0:
                        run_start = r["time_s"]
                    count += 1
                    max_count = max(max_count, count)
                    if count >= 10 and confirmation is None:
                        confirmation, accepted_start = r["time_s"], run_start
                else:
                    count, run_start = 0, None
                previous = r["time_s"]
            energy = sampled_energy = 0.0
            violation_s = 0.0
            coverage = 0.0
            replay_peak_v = replay_peak_i = 0.0
            for r in sr:
                left = max(r["time_s"], seg["start_s"])
                right = min(r["time_s"] + r["duration_s"], seg["end_s"])
                if right - left <= 1e-12:
                    continue
                dt = right - left
                coverage += dt
                q = model.response(r["frequency_Hz"], scenarios[seg["case_id"]], r["amplitude_command"])
                p, v, i = float(q["p_rm_W"][0]), float(q["vport_vpp"][0]), float(q["iport_irms_A"][0])
                energy += p * dt
                sampled_energy += r["p_rm_W"] * dt
                replay_peak_v, replay_peak_i = max(replay_peak_v, v), max(replay_peak_i, i)
                if v > model.VPP_HARD + 1e-9 or i > model.IRMS_HARD + 1e-12:
                    violation_s += dt
            assert math.isclose(coverage, seg["end_s"] - seg["start_s"], abs_tol=1e-10)
            reference = optima[seg["case_id"]]["power_W"] * (seg["end_s"] - seg["start_s"])
            output.append({"strategy": strategy, "state_index": seg["state_index"], "case_id": seg["case_id"],
                           "max_consecutive_good": max_count, "settled": int(confirmation is not None),
                           "first_good_normal_s": first_good, "accepted_start_s": accepted_start,
                           "confirmation_s": confirmation,
                           "confirmation_delay_ms": None if confirmation is None else (confirmation - seg["start_s"]) * 1000,
                           "held_command_energy_J": energy, "sampled_energy_J": sampled_energy,
                           "safe_reference_energy_J": reference, "held_energy_capture_pct": energy / reference * 100,
                           "held_command_hard_violation_ms": violation_s * 1000,
                           "held_command_peak_vpp": replay_peak_v, "held_command_peak_irms_mA": replay_peak_i * 1000,
                           "sampled_hard_violation_rows": sum(bool(r["actual_voltage_hard_violation"] or r["actual_current_hard_violation"]) for r in rr),
                           "scan_action_time_ms": sum(r["duration_s"] for r in rr if r["action"].startswith("SCAN")) * 1000,
                           "low_capture_time_ms_sampled": sum(r["duration_s"] for r in rr if r["safe_power_capture_ratio"] < .98) * 1000})
    return output


def aggregate(variant, dwell, legacy, rows, details):
    result = []
    for strategy in legacy.STRATEGIES:
        ss = [r for r in details if r["strategy"] == strategy and r["state_index"] > 0]
        rr = [r for r in rows if r["strategy"] == strategy and r["time_s"] >= dwell]
        energy = sum(r["held_command_energy_J"] for r in ss)
        reference = sum(r["safe_reference_energy_J"] for r in ss)
        fs = next(r for r in ss if r["case_id"] == "CASE_FS_M5")
        result.append({"variant": variant, "segment_duration_s": dwell, "strategy": strategy,
                       "settled_segments_of_7": sum(r["settled"] for r in ss),
                       "fs_settled": fs["settled"], "fs_max_consecutive_good": fs["max_consecutive_good"],
                       "fs_confirmation_delay_ms": fs["confirmation_delay_ms"],
                       "fs_held_energy_capture_pct": fs["held_energy_capture_pct"],
                       "held_energy_J": energy, "held_energy_capture_pct": energy / reference * 100,
                       "sampled_energy_capture_pct": sum(r["sampled_energy_J"] for r in ss) / reference * 100,
                       "held_command_hard_violation_ms": sum(r["held_command_hard_violation_ms"] for r in ss),
                       "sampled_hard_violation_rows": sum(r["sampled_hard_violation_rows"] for r in ss),
                       "scan_action_time_ms": sum(r["scan_action_time_ms"] for r in ss),
                       "soft_limit_triggers": sum(r["soft_limit_trigger"] for r in rr),
                       "hard_trip_triggers": sum(r["hard_trip_trigger"] for r in rr)})
    return result


def main():
    started = time.perf_counter()
    manifest = snapshot()
    model, legacy = load_legacy()
    scenarios = model.scenario_map()
    optima = legacy.optimal_tables(scenarios)
    registry = []
    for s in scenarios.values():
        b = s.bvd
        physical_fs = 1 / (2 * math.pi * math.sqrt(b.lm * b.cm))
        registry.append({"case_id": s.case_id, "source_class": "HYPOTHETICAL_BASELINE_OR_SCAN_VARIABLE",
                         "c0_F": b.c0, "rm_ohm": b.rm, "lm_H": b.lm, "cm_F": b.cm,
                         "derived_fs_Hz": physical_fs, "derived_Qm": 2 * math.pi * physical_fs * b.lm / b.rm,
                         "legacy_Qm_metadata": b.qm})
    save_csv(RESULTS / "parameter_registry.csv", registry)
    print("RMS phasors; Vpp=2*sqrt(2)*Vrms; Iport is total terminal RMS current; phi=arg(Zin).", flush=True)
    print("Baseline source Vrms:", model.SOURCE_A1_VRMS, "port P_Rm W:", optima["CASE_000_BASELINE"]["power_W"], flush=True)
    summary, audits = [], []
    for dwell in (.8, 1.6):
        configure_schedule(legacy, dwell)
        for variant in ("E00", "E01", "E02"):
            run_dir = RESULTS / f"{variant}_dwell_{dwell:.1f}s"
            rows = []
            for strategy in legacy.STRATEGIES:
                if variant == "E00":
                    rows.extend(legacy.simulate(strategy, scenarios, optima))
                else:
                    rows.extend(Experiment(model, legacy, variant, strategy, scenarios, optima).run())
            if variant == "E00" and dwell == .8:
                check = compare_history(rows, SNAPSHOT / "history/stage4_control_timeline.csv")
                save_json(RESULTS / "baseline_reproduction.json", check)
                assert check["pass"], check
            details = detailed_metrics(model, legacy, rows, scenarios, optima)
            old_metrics = legacy.segment_metrics(rows)
            assert all(int(r["settled"]) == int(d["settled"]) for r, d in zip(old_metrics, details))
            save_csv(run_dir / "timeline.csv", rows)
            save_csv(run_dir / "per_segment_metrics.csv", old_metrics)
            save_csv(run_dir / "acceptance_and_energy.csv", details)
            save_json(run_dir / "config.json", {"variant": variant, "dwell_s": dwell, "schedule": legacy.SCHEDULE,
                      "control_dt_s": .02, "scan_point_dt_s": .0015, "voltage_hard_Vpp": 160, "current_hard_Arms": .006,
                      "voltage_soft_Vpp": 130, "current_soft_Arms": .0055, "hard_hold_s": .06,
                      "recovery_hold_s": .10, "soft_stabilize_s": .10, "ramp_rate_per_s": 2.5,
                      "acceptance_capture": .98, "acceptance_samples": 10,
                      "optimization_objective_unchanged": "normalized measured port power",
                      "guard_model_preview": True, "LTspice_controller_run": False})
            run_summary = aggregate(variant, dwell, legacy, rows, details)
            summary.extend(run_summary)
            audit = {"variant": variant, "dwell_s": dwell, "rows": len(rows), "timeline_sha256": sha(run_dir / "timeline.csv"),
                     "all_sampled_points_within_hard_limits": all(not r["actual_voltage_hard_violation"] and not r["actual_current_hard_violation"] for r in rows),
                     "sampling_gap_safety_proven": False}
            if variant != "E00":
                audit.update({"all_actions_guarded": all(r["guard_called"] == 1 for r in rows),
                              "amplitude_state_consistent": all(r["amplitude_command"] == r["internal_amplitude"] for r in rows),
                              "frequency_change_without_amplitude_increase": all(
                                  abs(r["frequency_Hz"] - r["previous_frequency_Hz"]) < 1e-8 or
                                  r["amplitude_command"] <= r["previous_amplitude"] + 1e-12 for r in rows),
                              "max_power_balance_error_W": max(abs(r["power_balance_error_W"]) for r in rows)})
                assert audit["all_actions_guarded"] and audit["amplitude_state_consistent"] and audit["frequency_change_without_amplitude_increase"]
            assert audit["all_sampled_points_within_hard_limits"]
            save_json(run_dir / "audit.json", audit)
            audits.append(audit)
            print(json.dumps(run_summary, ensure_ascii=False), flush=True)
    save_csv(RESULTS / "summary.csv", summary)
    save_json(RESULTS / "run_audit.json", {"elapsed_wall_s": time.perf_counter() - started,
              "runs": audits, "script_sha256": sha(__file__), "original_inputs_unchanged":
              all(sha(item["original"]) == item["sha256"] for item in manifest)})
    print("FINISHED", time.perf_counter() - started, flush=True)


if __name__ == "__main__":
    main()
