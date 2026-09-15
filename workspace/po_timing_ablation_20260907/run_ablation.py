"""Registered P&O timing/amplitude/recovery ablation of frozen E04_B.

No changes to PI gains, safety limits, scan amplitude, or acceptance conditions.
No controller access to scenario IDs, disturbance times, or evaluator optimum.
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
PREVIOUS = HERE.parent / "control_factorial_20260907"
FROZEN = HERE / "frozen"
RESULTS = HERE / "results"

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))

def freeze():
    sources = [(PREVIOUS / "run_factorial.py", FROZEN / "round2.py"),
               (PREVIOUS / "frozen/round1.py", FROZEN / "round1.py")]
    sources += [(p, FROZEN / "snapshot" / p.relative_to(PREVIOUS / "frozen/snapshot"))
                for p in (PREVIOUS / "frozen/snapshot").rglob("*")
                if p.is_file() and "__pycache__" not in p.parts]
    for dwell in (.8, 1.6):
        for name in ("E04_B", "E02_000"):
            p = PREVIOUS / f"results/{name}_dwell_{dwell:.1f}s/timeline.csv"
            sources.append((p, FROZEN / f"reference/{name}_{dwell:.1f}s.csv"))
    manifest = []
    for src, dst in sources:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            assert sha(src) == sha(dst), f"Frozen source changed: {src}"
        else:
            shutil.copy2(src, dst)
        manifest.append({"original": str(src), "frozen": dst.relative_to(HERE).as_posix(), "sha256": sha(dst)})
    save_json(HERE / "input_manifest.json", manifest)

def load():
    spec = importlib.util.spec_from_file_location("timing_frozen_round2", FROZEN / "round2.py")
    r = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = r
    spec.loader.exec_module(r)
    r.FROZEN = FROZEN
    base, model, legacy = r.load()
    return r, base, model, legacy

@dataclass(frozen=True)
class Timing:
    interval_s: float
    probe_cap: float
    recovered_clock: bool

    @property
    def name(self):
        return f"T{round(self.interval_s*1000):03d}_A{round(self.probe_cap*100):03d}_R{int(self.recovered_clock)}"

VARIANTS = [Timing(t, a, recovery) for t in (.1, .3, .6) for a in (.4, .7, 1.) for recovery in (False, True)]

def experiment_class(r, base):
    parent = r.experiment_class(base)

    class TimingExperiment(parent):
        def __init__(self, model, legacy, timing, scenarios, optima, pi=True):
            cfg = r.Variant(timing.name if pi else "ANCHOR_E02", amplitude=pi)
            super().__init__(model, legacy, cfg, "P_AND_O", scenarios, optima)
            self.timing = timing
            self.awaiting_recovery = False
            self.probe_id = 0
            self.probe_events = []
            self.active_event = None

        def act(self, action, f, a, duration, reason=""):
            row = super().act(action, f, a, duration, reason)
            if row is None:
                return None
            if self.active_event is not None and self.active_event.get("return_end_s") is not None:
                event = self.active_event
                if self.po_need and not event.get("recovery_ready_end_s"):
                    event.setdefault("recovery_interrupted_s", row["time_s"])
                    self.awaiting_recovery = False
                elif (action == "CONTROL" and row["protection_state"] == "NORMAL"
                      and not row["frequency_frozen"] and not event.get("recovery_ready_end_s")):
                    event["recovery_ready_sample_s"] = row["time_s"]
                    event["recovery_ready_end_s"] = self.t
                    event["recovery_ms"] = (self.t - event["return_end_s"]) * 1000
                    if self.awaiting_recovery:
                        self.po_next = self.t + self.timing.interval_s
                        event["armed_due_s"] = self.po_next
                        self.awaiting_recovery = False
            row.update({"timing_probe_id": self.probe_id, "timing_wait_recovery": int(self.awaiting_recovery),
                        "timing_due_s": self.po_next, "probe_amplitude_cap": self.timing.probe_cap,
                        "probe_interval_s": self.timing.interval_s,
                        "probe_clock": "RECOVERED_CONTROL_END" if self.timing.recovered_clock else "RETURN_END"})
            return row

        def scan(self, reason):
            # Invalidate only the previous probe's recovery timer. The inherited
            # run() retains its original post-scan cooldown/bootstrap schedule.
            self.awaiting_recovery = False
            self.active_event = None
            return super().scan(reason)

        def po_probe(self):
            self.probe_id += 1
            event = {"probe_id": self.probe_id, "start_s": self.t, "completed": False,
                     "due_at_start_s": self.po_next, "cap": self.timing.probe_cap,
                     "clock": "RECOVERED_CONTROL_END" if self.timing.recovered_clock else "RETURN_END"}
            self.probe_events.append(event)
            self.active_event = event
            f0 = self.g.f
            a = min(self.timing.probe_cap, self.g.a)
            ref = self.act("P_AND_O_REFERENCE", f0, a, self.c.CONTROL_DT)
            if ref is None or self.po_need:
                event["abort"] = "REFERENCE_END_OR_PROTECTION"
                return
            candidate = float(np.clip(f0 + self.po_dir*self.po_step, self.m.F_MIN, self.m.F_MAX))
            probe = self.act("P_AND_O_PROBE", candidate, min(a, self.g.a), self.c.CONTROL_DT)
            if probe is None or self.po_need:
                event["abort"] = "PROBE_END_OR_PROTECTION"
                return
            relative = (self.score(probe)-self.score(ref))/max(abs(self.score(ref)), 1e-30)
            selected = candidate if relative > 0 else f0
            if relative <= 0:
                self.po_dir *= -1
            if relative < .005:
                self.po_step = max(self.c.P_AND_O_MIN_STEP, self.po_step/2)
            returned = self.act("P_AND_O_RETURN", selected, self.g.a, self.c.CONTROL_DT)
            if not self.po_need:
                self.g.state = "RAMP_UP"
                event.update({"completed": returned is not None, "return_end_s": self.t,
                              "reference_frequency_Hz": f0, "candidate_Hz": candidate, "selected_Hz": selected,
                              "actual_reference_amplitude": ref["amplitude_command"],
                              "actual_probe_amplitude": probe["amplitude_command"], "relative_score_change": relative})
                if self.timing.recovered_clock:
                    self.awaiting_recovery = True
                    self.po_next = math.inf
                else:
                    self.po_next = self.t + self.timing.interval_s
                    event["armed_due_s"] = self.po_next

    return TimingExperiment

def profiles(original):
    output = [("MAIN_080", .8, original), ("LONG_160", 1.6, original)]
    for seed in (41, 43, 47):
        middle = list(original[1:-1])
        np.random.default_rng(seed).shuffle(middle)
        output.append((f"ORDER_{seed}", .8, [original[0], *middle, original[-1]]))
    output.append(("STABLE_4S", 4., [original[0]]))
    return output

def exact_reproduction(rows, name, dwell):
    expected = [x for x in read_csv(FROZEN / f"reference/{name}_{dwell:.1f}s.csv") if x["strategy"] == "P_AND_O"]
    assert len(rows) == len(expected), (len(rows), len(expected))
    mismatches = []
    for i, (a, b) in enumerate(zip(expected, rows)):
        for k, v in a.items():
            if k == "variant":
                continue
            try:
                x, y = float(v), float(b[k])
                same = x == y or (math.isnan(x) and math.isnan(y))
            except (ValueError, TypeError):
                same = str(b[k]) == v
            if not same:
                mismatches.append((i, k, v, b[k]))
    assert not mismatches, mismatches[:10]
    return {"pass": True, "rows": len(rows), "old_fields": len(expected[0]), "excluded_fields": ["variant"]}

def diagnostics(trial, rows, details, dwell, stable):
    start = 0. if stable else dwell
    rr = [x for x in rows if x["time_s"] >= start]
    events = [x for x in trial.probe_events if x["start_s"] >= start]
    completed = [x for x in events if x["completed"]]
    recovered = [x for x in completed if "recovery_ms" in x and "recovery_interrupted_s" not in x]
    for e, nxt in zip(trial.probe_events, trial.probe_events[1:]):
        e["next_probe_start_s"] = nxt["start_s"]
        e["start_to_start_ms"] = (nxt["start_s"]-e["start_s"])*1000
        if e.get("recovery_ready_end_s") is not None:
            end = nxt["start_s"]
            e["normal_controls_before_next_probe"] = sum(x["action"] == "CONTROL" and x["protection_state"] == "NORMAL"
                for x in rows if e["recovery_ready_end_s"]-trial.c.CONTROL_DT-1e-12 <= x["time_s"] < end-1e-12)
    normal_counts = [x["normal_controls_before_next_probe"] for x in events if "normal_controls_before_next_probe" in x]
    intervals = [x["start_to_start_ms"] for x in events if "start_to_start_ms" in x]
    scans = [x for x in trial.scan_events if x["start_s"] >= start]
    out = {"probe_episodes": len(events), "completed_probes": len(completed), "aborted_probes": len(events)-len(completed),
           "recovery_observed_count": len(recovered),
           "median_recovery_ms": float(np.median([x["recovery_ms"] for x in recovered])) if recovered else None,
           "median_actual_probe_interval_ms": float(np.median(intervals)) if intervals else None,
           "median_normal_controls_between_probes": float(np.median(normal_counts)) if normal_counts else None,
           "completed_scans": len(scans), "detector_triggers": sum(x["detector_trigger"] for x in rr),
           "normal_control_time_ms": sum(x["duration_s"] for x in rr if x["action"] == "CONTROL" and x["protection_state"] == "NORMAL")*1000,
           "probe_action_time_ms": sum(x["duration_s"] for x in rr if x["action"].startswith("P_AND_O"))*1000,
           "ramp_control_time_ms": sum(x["duration_s"] for x in rr if x["action"] == "CONTROL" and x["protection_state"] == "RAMP_UP")*1000,
           "peak_held_voltage_Vpp": max(x["held_command_peak_vpp"] for x in details),
           "peak_held_current_mA": max(x["held_command_peak_irms_mA"] for x in details)}
    for detail in details:
        seg = trial.c.SCHEDULE[detail["state_index"]]
        ss = [x for x in rows if seg["start_s"] <= x["time_s"] < seg["end_s"]]
        triggers = [x["time_s"] for x in ss if x["detector_trigger"] or x["hard_trip_trigger"] or x["soft_limit_trigger"]]
        scans_in = [x for x in trial.scan_events if seg["start_s"] <= x["start_s"] < seg["end_s"]]
        detail["first_observable_or_protection_trigger_delay_ms"] = (min(triggers)-seg["start_s"])*1000 if triggers else None
        detail["first_scan_start_delay_ms"] = (scans_in[0]["start_s"]-seg["start_s"])*1000 if scans_in else None
    return out

def main(out):
    out = Path(out).resolve()
    if out.exists():
        raise FileExistsError("Keep evidence immutable: use a new output directory")
    freeze()
    r, base, model, legacy = load()
    original = list(legacy.SCENARIO_ORDER)
    legacy.STRATEGIES = ["P_AND_O"]
    cls = experiment_class(r, base)
    scenarios = model.scenario_map()
    optima = legacy.optimal_tables(scenarios)
    design = [{"profile": p, "dwell_s": d, "order": order} for p, d, order in profiles(original)]
    save_json(out / "registered_design.json", {"variants": [dict(asdict(c), name=c.name) for c in VARIANTS], "profiles": design,
        "PI_gains": r.PARAMETERS, "scan_amplitude_unchanged": legacy.PROBE_AMPLITUDE,
        "preregistration_README_sha256": sha(HERE / "README.md")})
    started = time.perf_counter()
    summary, audits = [], []
    print("RMS phasors; Vpp=2sqrt(2)Vrms; phase=arg(Zin); hypothetical linear model. No hardware safety claim.", flush=True)
    for profile, dwell, order in profiles(original):
        legacy.SCENARIO_ORDER = list(order)
        base.configure_schedule(legacy, dwell)
        configs = [(c, True) for c in VARIANTS]
        if profile in {"MAIN_080", "LONG_160"}:
            configs.append((VARIANTS[0], False))
        for cfg, pi in configs:
            label = cfg.name if pi else "ANCHOR_E02"
            folder = out / profile / label
            trial = cls(model, legacy, cfg, scenarios, optima, pi=pi)
            rows = trial.run()
            details = base.detailed_metrics(model, legacy, rows, scenarios, optima)
            r.extra_metrics(legacy, rows, details)
            if profile != "STABLE_4S":
                metric = base.aggregate(label, dwell, legacy, rows, details)[0]
            else:
                d = details[0]
                metric = {"variant": label, "strategy": "P_AND_O", "settled_segments_of_7": None,
                          "held_energy_capture_pct": d["held_energy_capture_pct"],
                          "held_command_hard_violation_ms": d["held_command_hard_violation_ms"],
                          "sampled_hard_violation_rows": d["sampled_hard_violation_rows"],
                          "stable_max_good": d["max_consecutive_good"], "stable_settled": d["settled"]}
            metric.update({"profile": profile, **asdict(cfg), "PI_enabled": pi})
            metric.update(diagnostics(trial, rows, details, dwell, profile == "STABLE_4S"))
            audit = {"rows": len(rows), "all_actions_guarded": all(x["guard_called"] == 1 for x in rows),
                     "sampled_hard_violation_rows": sum(x["actual_voltage_hard_violation"] or x["actual_current_hard_violation"] for x in rows)}
            if profile in {"MAIN_080", "LONG_160"} and cfg == VARIANTS[0]:
                audit["exact_previous_reproduction"] = exact_reproduction(rows, "E04_B" if pi else "E02_000", dwell)
            assert audit["all_actions_guarded"] and audit["sampled_hard_violation_rows"] == 0
            base.save_csv(folder / "timeline.csv", rows)
            base.save_csv(folder / "acceptance_and_energy.csv", details)
            save_json(folder / "probe_events.json", trial.probe_events)
            save_json(folder / "scan_events.json", trial.scan_events)
            save_json(folder / "config.json", {"timing": dict(asdict(cfg), name=label), "profile": profile, "dwell_s": dwell,
                "PI_enabled": pi, "schedule": legacy.SCHEDULE, "PI_settings": r.PARAMETERS,
                "scan_amplitude_cap": legacy.PROBE_AMPLITUDE, "soft_vpp":130., "hard_vpp":160.,
                "soft_irms_A":.0055, "hard_irms_A":.006, "control_dt": legacy.CONTROL_DT,
                "acceptance": "NORMAL CONTROL unfrozen capture>=.98, ten consecutive, unchanged"})
            audit["timeline_sha256"] = sha(folder / "timeline.csv")
            save_json(folder / "audit.json", audit)
            summary.append(metric)
            audits.append(dict(audit, profile=profile, variant=label))
            print(profile, label, "pass", metric.get("settled_segments_of_7"), "energy", round(metric["held_energy_capture_pct"], 3),
                  "probes", metric["probe_episodes"], flush=True)
    base.save_csv(out / "summary.csv", summary)
    save_json(out / "run_audit.json", {"runs": audits, "elapsed_wall_s": time.perf_counter()-started,
        "script_sha256": sha(__file__), "total_runs": len(audits), "controller_LTspice_transient_validated": False,
        "noise_or_physical_delay_modelled": False})

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=RESULTS)
    main(parser.parse_args().out)
