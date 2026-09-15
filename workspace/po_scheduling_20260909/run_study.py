"""P&O scheduling ablation. New folder, frozen controllers, observable-only gates."""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass, asdict
import importlib.util
import itertools
import json
import math
from pathlib import Path
import shutil
import sys
import time

import numpy as np

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "control_factorial_20260907"
FROZEN = HERE / "frozen"
RESULTS = HERE / "results"


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze():
    files = [(PREVIOUS / "run_factorial.py", FROZEN / "round2.py")]
    files += [(p, FROZEN / "frozen" / p.relative_to(PREVIOUS / "frozen"))
              for p in (PREVIOUS / "frozen").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    for label in ("E02_000", "E04_B"):
        for dwell in (.8, 1.6):
            root = PREVIOUS / "results" / f"{label}_dwell_{dwell:.1f}s"
            files += [(root / name, FROZEN / "reference" / root.name / name)
                      for name in ("timeline.csv", "config.json", "acceptance_and_energy.csv")]
    files += [(PREVIOUS / "ltspice" / name, FROZEN / "prior_AC" / name) for name in ("audit.json", "cross_validation.csv")]
    manifest = []
    for src, dst in files:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            assert sha(src) == sha(dst), f"Frozen source changed: {src}"
        else:
            shutil.copy2(src, dst)
        manifest.append({"original": str(src), "frozen": dst.relative_to(HERE).as_posix(), "sha256": sha(dst)})
    save_json(HERE / "input_manifest.json", manifest)


def load():
    previous = load_file("po_frozen_round2", FROZEN / "round2.py")
    base, model, legacy = previous.load()
    legacy.STRATEGIES = ["P_AND_O"]
    return previous, base, model, legacy


@dataclass(frozen=True)
class Configuration:
    pi: bool
    interval_s: float
    probe_cap: float
    recovery_gate: str

    @property
    def name(self):
        return f"B{int(self.pi)}_T{self.interval_s*1000:.0f}_A{self.probe_cap*100:.0f}_{self.recovery_gate}"


CONFIGURATIONS = [Configuration(*x) for x in itertools.product((False, True), (.1, .3, .5), (.4, .7, .9), ("R0", "R1", "R2"))]


def make_class(previous, base):
    parent = previous.experiment_class(base)
    class SchedulingTrial(parent):
        def __init__(self, model, legacy, setup, scenarios, optima):
            super().__init__(model, legacy, previous.Variant(setup.name, amplitude=setup.pi), "P_AND_O", scenarios, optima)
            self.setup = setup
            self.normal_since = None
            self.stable_count = 0
            self.previous_normal = None
            self.episode_started = False
            self.probe_events = []
            self.pending_episode = None
            self.latest_completed_probe = None

        def act(self, action, f, a, duration, reason=""):
            row = super().act(action, f, a, duration, reason)
            if row is None:
                return None
            ordinary = action == "CONTROL" and row["protection_state"] == "NORMAL" and not row["frequency_frozen"]
            if ordinary:
                if self.normal_since is None:
                    self.normal_since = row["time_s"]
                healthy = row["detector_vote_count"] == 0
                continuous = (self.previous_normal is not None and
                    row["time_s"]-self.previous_normal["time_s"] <= .03 + 1e-12 and
                    abs(row["frequency_Hz"]-self.previous_normal["frequency_Hz"]) <= 1e-8 and
                    abs(row["amplitude_command"]-self.previous_normal["amplitude_command"]) <= .002)
                self.stable_count = self.stable_count + 1 if healthy and continuous else int(healthy)
                self.previous_normal = row
                if self.latest_completed_probe is not None and self.latest_completed_probe.get("first_normal_s") is None:
                    self.latest_completed_probe["first_normal_s"] = row["time_s"]
                    self.latest_completed_probe["recovery_to_normal_ms"] = (row["time_s"]-self.latest_completed_probe["return_end_s"])*1000
            else:
                self.normal_since, self.previous_normal, self.stable_count = None, None, 0
            if action != "CONTROL" or row["hard_trip_trigger"] or row["soft_limit_trigger"] or row["detector_trigger"]:
                self.episode_started = True
            row.update({"gate": self.setup.recovery_gate, "normal_since_s": self.normal_since if self.normal_since is not None else math.nan,
                        "normal_stable_samples": self.stable_count, "configured_probe_cap": self.setup.probe_cap,
                        "configured_probe_wait_s": self.setup.interval_s, "routine_timer_due": int(self.t >= self.po_next),
                        "normal_but_detector_not_eligible": int(ordinary and row["amplitude_command"] < .999)})
            return row

        def gate_ready(self):
            if self.setup.recovery_gate == "R0" or not self.episode_started:
                return True
            if self.normal_since is None or self.t-self.normal_since < self.setup.interval_s - 1e-12:
                return False
            return self.setup.recovery_gate == "R1" or self.stable_count >= 10

        def po_probe(self):
            episode = {"start_s": self.t, "completed": False, "return_end_s": None, "first_normal_s": None,
                       "gate_normal_since_s": self.normal_since, "gate_stable_count": self.stable_count,
                       "gate_episode_started": self.episode_started, "reason": "ROUTINE_P_AND_O"}
            self.probe_events.append(episode)
            self.latest_completed_probe = None
            f0 = self.g.f
            a = min(self.setup.probe_cap, self.g.a)
            ref = self.act("P_AND_O_REFERENCE", f0, a, self.c.CONTROL_DT)
            if ref is None or self.po_need:
                episode["abort"] = "REFERENCE_OR_PROTECTION"
                return
            episode["reference_amplitude"] = ref["amplitude_command"]
            candidate = float(np.clip(f0 + self.po_dir*self.po_step, self.m.F_MIN, self.m.F_MAX))
            probe = self.act("P_AND_O_PROBE", candidate, min(a, self.g.a), self.c.CONTROL_DT)
            if probe is None or self.po_need:
                episode["abort"] = "PROBE_OR_PROTECTION"
                return
            episode["probe_amplitude"] = probe["amplitude_command"]
            relative = (self.score(probe)-self.score(ref))/max(abs(self.score(ref)), 1e-30)
            selected = candidate if relative > 0 else f0
            if relative <= 0:
                self.po_dir *= -1
            if relative < .005:
                self.po_step = max(self.c.P_AND_O_MIN_STEP, self.po_step/2)
            returned = self.act("P_AND_O_RETURN", selected, self.g.a, self.c.CONTROL_DT)
            if not self.po_need:
                self.g.state = "RAMP_UP"
                self.po_next = self.t + self.setup.interval_s
                if returned is not None:
                    episode.update({"completed": True, "return_end_s": self.t, "return_amplitude": returned["amplitude_command"],
                                    "selected_Hz": selected, "configured_next_due_s": self.po_next})
                    self.latest_completed_probe = episode

        def run(self):
            iterations = 0
            while self.t < self.c.TOTAL_TIME-1e-12:
                iterations += 1
                assert iterations < 100000, "No time progress"
                if self.po_need and self.g.tracking_allowed(self.t):
                    done = self.scan(self.po_reason)
                    if done:
                        self.po_need, self.po_reason = False, ""
                        self.po_step = self.c.P_AND_O_INITIAL_STEP
                        self.po_next = self.t + self.c.REACQUIRE_COOLDOWN + self.c.REFERENCE_STABLE_SAMPLES*self.c.CONTROL_DT
                    continue
                if not self.po_need and self.t >= self.po_next and self.g.tracking_allowed(self.t) and self.gate_ready():
                    self.po_probe()
                    continue
                target = 1.
                if self.cfg.amplitude:
                    target = self.servo.propose(self.last_control_measurement)
                    self.g.regulation_goal = self.servo.goal
                    self.amplitude_goal_used = self.servo.goal if self.servo.goal is not None else math.nan
                self.act("CONTROL", self.g.f, target, self.c.CONTROL_DT)
            return self.rows
    return SchedulingTrial


def evaluate(base, previous, model, legacy, setup, dwell, trial, scenarios, optima):
    rows = trial.rows
    details = base.detailed_metrics(model, legacy, rows, scenarios, optima)
    previous.extra_metrics(legacy, rows, details)
    strict = legacy.segment_metrics(rows)
    assert all(int(a["settled"]) == int(b["settled"]) for a, b in zip(details, strict))
    summary = base.aggregate(setup.name, dwell, legacy, rows, details)[0]
    summary.update(asdict(setup))
    summary["name"] = setup.name
    main_rows = [x for x in rows if x["time_s"] >= dwell]
    time_by_action = {}
    for x in main_rows:
        time_by_action[x["action"]] = time_by_action.get(x["action"], 0.) + x["duration_s"]
    events = [x for x in trial.probe_events if x["start_s"] >= dwell]
    intervals = [y["start_s"]-x["start_s"] for x, y in zip(events, events[1:])]
    recoveries = [x["recovery_to_normal_ms"] for x in events if x.get("recovery_to_normal_ms") is not None]
    summary.update({"routine_probe_attempts": len(events), "routine_probe_completed": sum(x["completed"] for x in events),
                    "probe_actions_ms": sum(v for k, v in time_by_action.items() if k.startswith("P_AND_O"))*1000,
                    "mean_actual_probe_start_interval_ms": np.mean(intervals)*1000 if intervals else math.nan,
                    "median_probe_recovery_to_normal_ms": float(np.median(recoveries)) if recoveries else math.nan,
                    "normal_detector_ineligible_ms": sum(x["duration_s"] for x in main_rows if x["normal_but_detector_not_eligible"])*1000,
                    "state_independent_passed_segments": sum(x["state_independent_control_pass"] for x in details if x["state_index"] > 0),
                    "peak_held_voltage_Vpp": max(x["held_command_peak_vpp"] for x in details if x["state_index"] > 0),
                    "peak_held_current_mA": max(x["held_command_peak_irms_mA"] for x in details if x["state_index"] > 0)})
    good_time = 0.
    for segment in legacy.SCHEDULE[1:]:
        for row in rows:
            dt = min(row["time_s"]+row["duration_s"], segment["end_s"])-max(row["time_s"], segment["start_s"])
            if dt <= 1e-12:
                continue
            p = float(model.response(row["frequency_Hz"], scenarios[segment["case_id"]], row["amplitude_command"])["p_rm_W"][0])
            if p/optima[segment["case_id"]]["power_W"] >= .98:
                good_time += dt
    summary["all_action_power_98_time_pct"] = good_time/(dwell*7)*100
    return details, strict, summary


def assert_previous_reference(rows, setup, dwell):
    tag = "E04_B" if setup.pi else "E02_000"
    path = FROZEN / "reference" / f"{tag}_dwell_{dwell:.1f}s/timeline.csv"
    with path.open(encoding="utf-8-sig", newline="") as h:
        old = [x for x in csv.DictReader(h) if x["strategy"] == "P_AND_O"]
    assert len(old) == len(rows), (len(old), len(rows))
    mismatches = []
    for i, (a, b) in enumerate(zip(old, rows)):
        for key, value in a.items():
            if key == "variant":
                continue
            try:
                x, y = float(value), float(b[key])
                same = x == y or math.isnan(x) and math.isnan(y)
            except ValueError:
                same = value == str(b[key])
            if not same:
                mismatches.append((i, key, value, b[key]))
    assert not mismatches, mismatches[:10]
    return {"matched": True, "reference": path.relative_to(HERE).as_posix(), "rows": len(rows), "mismatch_count": 0}


def main(out):
    if out.exists():
        raise FileExistsError("Use a fresh directory; evidence must not be overwritten")
    freeze()
    previous, base, model, legacy = load()
    cls = make_class(previous, base)
    scenarios = model.scenario_map()
    optima = legacy.optimal_tables(scenarios)
    start = time.perf_counter()
    allsummary, audit = [], []
    print("RMS phasors; arg(Zin); probe cap independent of scan cap=0.4; no LTspice transient.", flush=True)
    for dwell in (.8, 1.6):
        base.configure_schedule(legacy, dwell)
        for setup in CONFIGURATIONS:
            trial = cls(model, legacy, setup, scenarios, optima)
            trial.run()
            details, strict, summary = evaluate(base, previous, model, legacy, setup, dwell, trial, scenarios, optima)
            folder = out / f"{setup.name}_dwell_{dwell:.1f}s"
            base.save_csv(folder / "timeline.csv", trial.rows)
            base.save_csv(folder / "acceptance_and_energy.csv", details)
            base.save_csv(folder / "original_per_segment_metrics.csv", strict)
            save_json(folder / "probe_events.json", trial.probe_events)
            save_json(folder / "scan_events.json", trial.scan_events)
            save_json(folder / "config.json", {"setup": asdict(setup), "dwell_s": dwell, "schedule": legacy.SCHEDULE,
                       "scan_cap": legacy.PROBE_AMPLITUDE, "limits": [130,.0055,160,.006], "control_dt_s": .02,
                       "hard_hold_s": .06, "recovery_hold_s": .1, "soft_hold_s": .1, "ramp_step": legacy.RAMP_STEP,
                       "PI_Kp": .6, "PI_Ki_per_s": .8, "acceptance_unchanged": "98%,10 CONTROL NORMAL unfrozen samples"})
            item = {"name": setup.name, "dwell_s": dwell, "rows": len(trial.rows), "timeline_sha256": sha(folder / "timeline.csv")}
            if setup.interval_s == .1 and setup.probe_cap == .4 and setup.recovery_gate == "R0":
                item["previous_round_exact_reproduction"] = assert_previous_reference(trial.rows, setup, dwell)
            save_json(folder / "audit.json", item)
            audit.append(item)
            allsummary.append(summary)
            print(setup.name, dwell, summary["settled_segments_of_7"], round(summary["held_energy_capture_pct"], 2), flush=True)
    base.save_csv(out / "summary.csv", allsummary)
    save_json(out / "run_audit.json", {"runs": audit, "elapsed_wall_s": time.perf_counter()-start, "script_sha256": sha(__file__),
                    "new_LTspice_runs": False, "known_model_guard": True, "noise_and_hardware_delays_modelled": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=RESULTS)
    main(parser.parse_args().out)
