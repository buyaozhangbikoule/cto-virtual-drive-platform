"""Registered deterministic A/B/C ablation of the frozen E02 controller.

New algorithms use measured rows, not scenario IDs or evaluation optima. The
unchanged model-preview Guard still accesses the true plant: no physical safety
claim. All controller times are quasi-steady assumed dwell times.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, asdict
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "control_feasibility_20260907"
FROZEN = HERE / "frozen"
RESULTS = HERE / "results"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def freeze():
    files = [(PREVIOUS / "run_experiments.py", FROZEN / "round1.py")]
    files += [(p, FROZEN / "snapshot" / p.relative_to(PREVIOUS / "snapshot"))
              for p in (PREVIOUS / "snapshot").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    for dwell in (.8, 1.6):
        for name in ("timeline.csv", "config.json", "acceptance_and_energy.csv"):
            path = Path(f"results_r1/E02_dwell_{dwell:.1f}s") / name
            files.append((PREVIOUS / path, FROZEN / "reference" / path.relative_to("results_r1")))
    manifest = []
    for src, dst in files:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            assert sha(dst) == sha(src), f"Frozen input changed: {src}"
        else:
            shutil.copy2(src, dst)
        manifest.append({"original": str(src), "frozen": dst.relative_to(HERE).as_posix(), "sha256": sha(dst)})
    save_json(HERE / "input_manifest.json", manifest)


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load():
    spec = importlib.util.spec_from_file_location("factorial_frozen_round1", FROZEN / "round1.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, *module.load_legacy()


@dataclass(frozen=True)
class Variant:
    name: str
    phase: bool = False
    amplitude: bool = False
    constrained: bool = False
    local_only: bool = False


VARIANTS = [Variant("E02_000"), Variant("E03_A", phase=True), Variant("E04_B", amplitude=True),
            Variant("E05_C", constrained=True), Variant("E06_AB", True, True),
            Variant("E07_AC", True, False, True), Variant("E08_BC", False, True, True),
            Variant("E09_ABC", True, True, True), Variant("D01_LOCAL", local_only=True),
            Variant("D02_LOCAL_BC", amplitude=True, constrained=True, local_only=True)]

PARAMETERS = {"phase_probe_Hz": 500., "phase_slope_floor_deg_per_Hz": 1e-5,
              "phase_max_shift_Hz": 50000., "local_contrast": .002,
              "amplitude_Kp": .6, "amplitude_Ki_per_s": .8, "amplitude_snap_power_error": .005,
              "source": "HYPOTHETICAL_CONTROL_SETTINGS_NOT_LITERATURE_VALUES"}


def measured_estimate(row):
    """Use observable row only; no access to plant, scenario or optimum."""
    a = float(row["amplitude_command"])
    if a < 1e-9:
        return None
    g = max(float(row["p_port_W"]) / a**2, 0.)
    allow = min(1., 130. * a / max(float(row["vport_vpp"]), 1e-30),
                .0055 * a / max(float(row["iport_irms_A"]), 1e-30))
    return g, allow, g * allow**2


class AmplitudeServo:
    """Independent power-error PI on a², with conditional integration."""
    def __init__(self):
        self.integral = 0.
        self.goal = None
        self.error = 0.
        self.target_power = math.nan
        self.request = 1.
        self.integration_enabled = False

    def reset(self):
        self.integral, self.integration_enabled = 0., False

    def propose(self, row):
        estimate = measured_estimate(row) if row else None
        if estimate is None:
            self.goal = None
            return 1.
        gain, self.goal, self.target_power = estimate
        w = float(row["amplitude_command"])**2
        self.error = (self.target_power - float(row["p_port_W"])) / max(gain, 1e-12)
        raw = w + PARAMETERS["amplitude_Kp"] * self.error + self.integral
        w_goal = self.goal**2
        w_request = min(max(raw, 0.), w_goal)
        if abs(w_goal - w) <= PARAMETERS["amplitude_snap_power_error"] * max(w_goal, 1e-12):
            w_request = w_goal
            self.integral = 0.
        self.integration_enabled = abs(raw - w_request) < 1e-10
        self.request = math.sqrt(w_request)
        return self.request

    def feedback(self, row, dt):
        if row["protection_state"] in {"HARD_TRIP", "RECOVERY_HOLD", "SOFT_FOLDBACK", "REACQUIRE_READY"}:
            self.reset()
        elif self.integration_enabled and abs(row["amplitude_command"] - self.request) < 1e-9:
            self.integral += PARAMETERS["amplitude_Ki_per_s"] * self.error * dt


def experiment_class(base):
    class RegulatedGuard(base.Guard):
        def __init__(self, model, legacy, active, adaptive):
            super().__init__(model, legacy, True, adaptive)
            self.regulation_active = active
            self.regulation_goal = None

        def command(self, t, f, target, scenario, role="CONTROL"):
            out = super().command(t, f, target, scenario, role)
            # Reaching a permitted sub-unit regulation target is not a ramp.
            # No change to holds, protection limits, or capture acceptance.
            if (self.regulation_active and role == "CONTROL" and self.state == "RAMP_UP"
                    and self.regulation_goal is not None
                    and abs(self.a - self.regulation_goal) < 1e-9
                    and abs(target - self.regulation_goal) < 1e-9):
                if self.soft_since is not None and t - self.soft_since < self.c.SOFT_STABILIZE - 1e-12:
                    self.state = "SOFT_FOLDBACK"
                    out["state"], out["frozen"] = "SOFT_FOLDBACK", True
                else:
                    self.state = "NORMAL"
                    self.soft_since = None
                    out["state"], out["frozen"] = "NORMAL", False
            return out

    class FactorExperiment(base.Experiment):
        def __init__(self, model, legacy, cfg, strategy, scenarios, optima):
            super().__init__(model, legacy, "E02", strategy, scenarios, optima)
            self.cfg, self.variant = cfg, cfg.name
            self.g = RegulatedGuard(model, legacy, cfg.amplitude, strategy != "FIXED_0P9")
            self.servo = AmplitudeServo()
            self.last_control_measurement = None
            self.phase_reference = None
            self.phase_stable_rows = []
            self.phase_events = []
            self.scan_events = []
            self.phase_slope = math.nan
            self.phase_candidate = math.nan
            self.phase_path = "DISABLED"
            self.amplitude_goal_used = math.nan

        def act(self, action, f, a, duration, reason=""):
            if action != "CONTROL":
                self.servo.reset()
            row = super().act(action, f, a, duration, reason)
            if row is None:
                return None
            estimate = measured_estimate(row)
            row.update({"phase_reference_deg": self.phase_reference if self.phase_reference is not None else math.nan,
                        "phase_slope_deg_per_Hz": self.phase_slope, "phase_candidate_Hz": self.phase_candidate,
                        "phase_path": self.phase_path,
                        "measured_allowed_amplitude": estimate[1] if estimate else math.nan,
                        "measured_constrained_score_W": estimate[2] if estimate else math.nan,
                        "amplitude_loop_enabled": int(self.cfg.amplitude),
                        "amplitude_target_power_W": self.servo.target_power if self.cfg.amplitude else math.nan,
                        "amplitude_goal": self.amplitude_goal_used, "amplitude_integral": self.servo.integral})
            if action == "CONTROL" and self.cfg.amplitude:
                self.servo.feedback(row, duration)
            self.last_control_measurement = row
            if action == "CONTROL" and row["protection_state"] == "NORMAL" and not row["detector_vote_count"]:
                if self.phase_stable_rows and abs(row["frequency_Hz"] - self.phase_stable_rows[-1][0]) > 1e-8:
                    self.phase_stable_rows = []
                self.phase_stable_rows.append((row["frequency_Hz"], row["phase_deg"]))
                if len(self.phase_stable_rows) >= 10:
                    self.phase_reference = float(np.angle(np.mean(np.exp(1j * np.deg2rad(
                        [x[1] for x in self.phase_stable_rows[-10:]]))), deg=True))
            else:
                self.phase_stable_rows = []
            return row

        def score(self, row):
            estimate = measured_estimate(row)
            if estimate is None:
                return -math.inf
            return estimate[2] if self.cfg.constrained else estimate[0]

        def grid(self, frequencies, action, scan_a, reason):
            records = []
            for frequency in frequencies:
                row, scan_a = self.scan_point(float(frequency), action, scan_a, reason)
                if row is None:
                    return None, scan_a
                records.append(row)
            return records, scan_a

        def pick(self, records):
            return max(records, key=lambda r: (self.score(r), r["frequency_Hz"]))

        def bracketed(self, records):
            if len(records) < 3:
                return False
            best = self.pick(records)
            best_score = self.score(best)
            return (records[0]["frequency_Hz"] < best["frequency_Hz"] < records[-1]["frequency_Hz"]
                    and best_score > max(self.score(records[0]), self.score(records[-1]))
                    * (1 + PARAMETERS["local_contrast"]))

        def local_search(self, center, scan_a, reason):
            """A/LOCAL: power confirms; phase only proposes a bounded candidate."""
            initial = np.unique(np.clip([center - 500., center, center + 500.], self.m.F_MIN, self.m.F_MAX))
            records, scan_a = self.grid(initial, "SCAN_LOCAL_PROBE", scan_a, reason)
            if records is None:
                return "INTERRUPTED", None, scan_a
            bracket = records if self.bracketed(records) else None
            path = "LOCAL_POWER_BRACKET" if bracket else "FALLBACK_NO_LOCAL_BRACKET"
            phase_event = {"time_s": self.t, "reference_deg": self.phase_reference,
                           "center_Hz": center, "slope_deg_per_Hz": None, "candidate_Hz": None,
                           "phase_candidate_used": False}
            if bracket is None and self.cfg.phase and self.phase_reference is not None and len(records) == 3:
                wrap = lambda x: (x + 180.) % 360. - 180.
                slope = wrap(records[-1]["phase_deg"] - records[0]["phase_deg"]) / (initial[-1] - initial[0])
                self.phase_slope = slope
                phase_event["slope_deg_per_Hz"] = slope
                if abs(slope) >= PARAMETERS["phase_slope_floor_deg_per_Hz"]:
                    delta = wrap(self.phase_reference - records[1]["phase_deg"]) / slope
                    delta = float(np.clip(delta, -50000., 50000.))
                    candidate = float(np.clip(round((center + delta) / 100.) * 100., self.m.F_MIN, self.m.F_MAX))
                    self.phase_candidate = candidate
                    phase_event.update({"candidate_Hz": candidate, "phase_candidate_used": True})
                    points = np.arange(max(self.m.F_MIN, candidate - 2000.), min(self.m.F_MAX, candidate + 2000.) + 1., 1000.)
                    hinted, scan_a = self.grid(points, "SCAN_PHASE_CANDIDATE", scan_a, reason)
                    if hinted is None:
                        phase_event["outcome"] = "INTERRUPTED"
                        self.phase_events.append(phase_event)
                        return "INTERRUPTED", None, scan_a
                    if (self.bracketed(hinted) and self.score(self.pick(hinted)) > self.score(self.pick(records))
                            * (1 + PARAMETERS["local_contrast"])):
                        bracket = hinted
                        path = "PHASE_HINT_POWER_CONFIRMED"
                    else:
                        path = "FALLBACK_PHASE_NOT_CONFIRMED"
                else:
                    path = "FALLBACK_PHASE_SLOPE_SMALL"
            if bracket is not None:
                best = self.pick(bracket)
                span = 500. if bracket is records else 1000.
                f = best["frequency_Hz"]
                fine, scan_a = self.grid(np.arange(max(self.m.F_MIN, f - span), min(self.m.F_MAX, f + span) + 1., 100.),
                                         "SCAN_LOCAL_FINE", scan_a, reason)
                if fine is None:
                    phase_event["outcome"] = "INTERRUPTED"
                    self.phase_events.append(phase_event)
                    return "INTERRUPTED", None, scan_a
                candidate_row = self.pick(fine)
                # Require an interior fine-grid maximum; otherwise full fallback.
                if fine[0]["frequency_Hz"] < candidate_row["frequency_Hz"] < fine[-1]["frequency_Hz"]:
                    phase_event["outcome"] = path
                    self.phase_events.append(phase_event)
                    return path, candidate_row["frequency_Hz"], scan_a
                path = "FALLBACK_FINE_EDGE"
            phase_event["outcome"] = path
            self.phase_events.append(phase_event)
            return path, None, scan_a

        def scan(self, reason):
            start = self.t
            self.scan_id += 1
            center = self.g.f
            scan_a = min(self.c.PROBE_AMPLITUDE, self.g.a)
            self.phase_slope, self.phase_candidate = math.nan, math.nan
            self.phase_path = "FULL_SCAN"
            r = self.act("SCAN_PREP", center, scan_a, self.c.CONTROL_DT, reason)
            if r is None or r["protection_state"] in {"HARD_TRIP", "RECOVERY_HOLD"}:
                return False
            scan_a = min(scan_a, self.g.a)
            selected = None
            if self.cfg.phase or self.cfg.local_only:
                self.phase_path, selected, scan_a = self.local_search(center, scan_a, reason)
                if self.phase_path == "INTERRUPTED":
                    return False
            if selected is None:
                for half_window, step, action in ((50e3, 5e3, "SCAN_COARSE"), (5e3, 1e3, "SCAN_FINE"), (1e3, .1e3, "SCAN_ULTRAFINE")):
                    points = np.arange(max(self.m.F_MIN, center - half_window), min(self.m.F_MAX, center + half_window) + 1, step)
                    records, scan_a = self.grid(points, action, scan_a, reason)
                    if records is None:
                        return False
                    center = self.pick(records)["frequency_Hz"]
                selected = center
            row, scan_a = self.scan_point(selected, "SCAN_SELECT", scan_a, reason)
            if row is None:
                return False
            self.g.state, self.g.pending, self.g.soft_since = "RAMP_UP", False, None
            self.detector.after_scan(self.t)
            self.phase_reference = row["phase_deg"]
            self.phase_stable_rows = []
            self.scan_events.append({"start_s": start, "end_s": self.t, "duration_ms": (self.t - start) * 1000,
                                     "reason": reason, "path": self.phase_path, "selected_Hz": selected,
                                     "selected_score_W": self.score(row)})
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
            relative = (self.score(probe) - self.score(ref)) / max(abs(self.score(ref)), 1e-30)
            selected = candidate if relative > 0 else f0
            if relative <= 0:
                self.po_dir *= -1
            if relative < .005:
                self.po_step = max(self.c.P_AND_O_MIN_STEP, self.po_step / 2)
            self.act("P_AND_O_RETURN", selected, self.g.a, self.c.CONTROL_DT)
            if not self.po_need:
                self.g.state = "RAMP_UP"
                self.po_next = self.t + self.c.P_AND_O_UPDATE_INTERVAL

        def run(self):
            iterations = 0
            while self.t < self.c.TOTAL_TIME - 1e-12:
                iterations += 1
                assert iterations < 100000
                if self.strategy == "PERIODIC_SCAN" and self.t >= self.next_scan and self.g.tracking_allowed(self.t):
                    done = self.scan("PERIODIC_TIMER")
                    self.next_scan = self.t + self.c.SCAN_INTERVAL if done else self.t
                    continue
                if self.strategy == "P_AND_O" and self.po_need and self.g.tracking_allowed(self.t):
                    done = self.scan(self.po_reason)
                    if done:
                        self.po_need, self.po_reason = False, ""
                        self.po_step = self.c.P_AND_O_INITIAL_STEP
                        self.po_next = self.t + self.c.REACQUIRE_COOLDOWN + self.c.REFERENCE_STABLE_SAMPLES * self.c.CONTROL_DT
                    continue
                if self.strategy == "P_AND_O" and not self.po_need and self.t >= self.po_next and self.g.tracking_allowed(self.t):
                    self.po_probe()
                    continue
                target = 1.
                if self.cfg.amplitude:
                    target = self.servo.propose(self.last_control_measurement)
                    self.g.regulation_goal = self.servo.goal
                    self.amplitude_goal_used = self.servo.goal if self.servo.goal is not None else math.nan
                self.act("CONTROL", self.g.f, target, self.c.CONTROL_DT)
            return self.rows

    return FactorExperiment


def extra_metrics(legacy, rows, details):
    for detail in details:
        rr = [r for r in rows if r["strategy"] == detail["strategy"] and r["state_index"] == detail["state_index"]]
        control = [r for r in rr if r["action"] == "CONTROL"]
        n = best = 0
        previous = None
        for r in control:
            good = r["safe_power_capture_ratio"] >= .98 and (previous is None or r["time_s"] - previous <= .03 + 1e-12)
            n = n + 1 if good else 0
            best = max(best, n)
            previous = r["time_s"]
        detail["state_independent_control_max_good"] = best
        detail["state_independent_control_pass"] = int(best >= 10)
        detail["tail_frequency_Hz"] = control[-1]["frequency_Hz"] if control else math.nan
        detail["tail_capture_pct"] = control[-1]["safe_power_capture_ratio"] * 100 if control else math.nan
        detail["tail_amplitude"] = control[-1]["amplitude_command"] if control else math.nan


def main(out):
    global RESULTS
    RESULTS = Path(out)
    if RESULTS.exists():
        raise FileExistsError("Use a fresh results directory; do not overwrite evidence")
    freeze()
    base, model, legacy = load()
    cls = experiment_class(base)
    scenarios = model.scenario_map()
    optima = legacy.optimal_tables(scenarios)
    started = time.perf_counter()
    summary, runs = [], []
    print("RMS phasors, port total current; phase=arg(Zin). No acoustic/clinical claim.", flush=True)
    for dwell in (.8, 1.6):
        base.configure_schedule(legacy, dwell)
        for cfg in VARIANTS:
            folder = RESULTS / f"{cfg.name}_dwell_{dwell:.1f}s"
            rows, phase_events, scan_events = [], [], []
            for strategy in legacy.STRATEGIES:
                trial = cls(model, legacy, cfg, strategy, scenarios, optima)
                rows.extend(trial.run())
                phase_events += [dict(e, strategy=strategy) for e in trial.phase_events]
                scan_events += [dict(e, strategy=strategy) for e in trial.scan_events]
            details = base.detailed_metrics(model, legacy, rows, scenarios, optima)
            extra_metrics(legacy, rows, details)
            old_metrics = legacy.segment_metrics(rows)
            assert all(int(x["settled"]) == int(y["settled"]) for x, y in zip(details, old_metrics))
            metrics = base.aggregate(cfg.name, dwell, legacy, rows, details)
            for metric in metrics:
                ss = [d for d in details if d["strategy"] == metric["strategy"] and d["state_index"] > 0]
                metric.update(asdict(cfg))
                metric["state_independent_passed_segments"] = sum(d["state_independent_control_pass"] for d in ss)
                metric["completed_scans"] = sum(e["strategy"] == metric["strategy"] for e in scan_events)
                metric["phase_hints_tried"] = sum(e["strategy"] == metric["strategy"] and e["phase_candidate_used"] for e in phase_events)
                metric["phase_hints_confirmed"] = sum(e["strategy"] == metric["strategy"] and e["outcome"] == "PHASE_HINT_POWER_CONFIRMED" for e in phase_events)
                metric["peak_held_voltage_Vpp"] = max(d["held_command_peak_vpp"] for d in ss)
                metric["peak_held_current_mA"] = max(d["held_command_peak_irms_mA"] for d in ss)
            summary.extend(metrics)
            base.save_csv(folder / "timeline.csv", rows)
            base.save_csv(folder / "per_segment_metrics.csv", old_metrics)
            base.save_csv(folder / "acceptance_and_energy.csv", details)
            save_json(folder / "phase_events.json", phase_events)
            save_json(folder / "scan_events.json", scan_events)
            save_json(folder / "config.json", {"variant": asdict(cfg), "dwell_s": dwell, "schedule": legacy.SCHEDULE,
                      "settings": PARAMETERS, "limits": {"Vpp_soft": 130, "Vpp_hard": 160, "Irms_soft_A": .0055, "Irms_hard_A": .006},
                      "source_amplitude_max": 1, "acceptance": "unchanged NORMAL CONTROL unfrozen capture>=98% 10 consecutive"})
            audit = {"name": cfg.name, "dwell_s": dwell, "rows": len(rows), "timeline_sha256": sha(folder / "timeline.csv"),
                     "pointwise_hard_violations": sum(bool(r["actual_voltage_hard_violation"] or r["actual_current_hard_violation"]) for r in rows),
                     "all_actions_guarded": all(r["guard_called"] == 1 for r in rows),
                     "amplitude_state_consistent": all(r["amplitude_command"] == r["internal_amplitude"] for r in rows)}
            assert audit["pointwise_hard_violations"] == 0 and audit["all_actions_guarded"] and audit["amplitude_state_consistent"]
            if cfg.name == "E02_000":
                reference = FROZEN / f"reference/E02_dwell_{dwell:.1f}s/timeline.csv"
                # Variant name differs; every original numeric/action/state field is preserved.
                with reference.open(encoding="utf-8-sig") as h:
                    old = list(csv.DictReader(h))
                assert len(old) == len(rows)
                mismatches = []
                for a, b in zip(old, rows):
                    for key, value in a.items():
                        if key == "variant":
                            continue
                        try:
                            x, y = float(value), float(b[key])
                            equal = (math.isnan(x) and math.isnan(y)) or x == y
                        except ValueError:
                            equal = value == str(b[key])
                        if not equal:
                            mismatches.append((key, value, b[key]))
                audit["E02_exact_reproduction"] = not mismatches
                assert not mismatches, mismatches[:10]
            save_json(folder / "audit.json", audit)
            runs.append(audit)
            print(cfg.name, dwell, [(r["strategy"], r["settled_segments_of_7"], round(r["held_energy_capture_pct"], 2)) for r in metrics], flush=True)
    base.save_csv(RESULTS / "summary.csv", summary)
    save_json(RESULTS / "run_audit.json", {"script_sha256": sha(__file__), "runs": runs,
              "elapsed_wall_s": time.perf_counter() - started, "hypothetical_model": True,
              "noise_or_physical_delay_modelled": False, "controller_LTspice_transient_validated": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=RESULTS)
    main(parser.parse_args().out)
