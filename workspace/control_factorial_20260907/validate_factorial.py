"""Separate invariant checks; software tests are not a physical safety proof."""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import run_factorial as r


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def main(results):
    base, model, legacy = r.load()
    cls = r.experiment_class(base)
    scenarios = model.scenario_map()
    optima = legacy.optimal_tables(scenarios)
    checks = []

    def check(name, condition, **data):
        checks.append({"name": name, "pass": bool(condition), **data})
        assert condition, name

    for path in sorted(results.glob("*/timeline.csv")):
        config = json.loads((path.parent / "config.json").read_text(encoding="utf-8"))
        rows = read(path)
        tag = path.parent.name
        check(tag + ":frozen_hard_limits", config["limits"]["Vpp_hard"] == 160 and config["limits"]["Irms_hard_A"] == .006)
        check(tag + ":actual_points_within_limits", all(float(x["vport_vpp"]) <= 160 + 1e-9 and float(x["iport_irms_A"]) <= .006 + 1e-12 for x in rows))
        check(tag + ":no_joint_frequency_jump_and_upward_amplitude", all(
            abs(float(x["frequency_Hz"]) - float(x["previous_frequency_Hz"])) < 1e-8
            or float(x["amplitude_command"]) <= float(x["previous_amplitude"]) + 1e-12 for x in rows))
        check(tag + ":source_ceiling_and_frequency_bounds", all(0 <= float(x["amplitude_command"]) <= 1
              and 800000 <= float(x["frequency_Hz"]) <= 1000000 for x in rows))
        check(tag + ":amplitude_state_sync", all(x["amplitude_command"] == x["internal_amplitude"] for x in rows))
        for strategy in legacy.STRATEGIES:
            sr = [x for x in rows if x["strategy"] == strategy]
            label = tag + ":" + strategy
            check(label + ":guard_each_action", [int(x["guard_call_index"]) for x in sr] == list(range(1, len(sr) + 1)))
            gaps = [abs(float(x["time_s"]) + float(x["duration_s"]) - float(y["time_s"])) for x, y in zip(sr, sr[1:])]
            check(label + ":time_complete", max(gaps, default=0) < 1e-10 and abs(sum(float(x["duration_s"]) for x in sr) - 8 * config["dwell_s"]) < 1e-9)
            hard_ok = recovery_ok = rate_ok = True
            for x in sr:
                if int(x["hard_trip_trigger"]):
                    t = float(x["time_s"])
                    hard_ok &= all(float(y["amplitude_command"]) == 0 for y in sr if t <= float(y["time_s"]) < t + .06 - 1e-10)
                    recovery_ok &= all(float(y["amplitude_command"]) <= .25 + 1e-12 and not y["action"].startswith("SCAN_")
                                       for y in sr if t + .06 - 1e-10 <= float(y["time_s"]) < t + .16 - 1e-10)
                if x["protection_state"] != "RECOVERY_HOLD":
                    rate_ok &= float(x["amplitude_command"]) <= float(x["previous_amplitude"]) + float(x["upward_slew_budget"]) + 1e-10
            check(label + ":60ms_hard_hold", hard_ok)
            check(label + ":100ms_recovery_hold", recovery_ok)
            check(label + ":upward_slew", rate_ok)
        audit = json.loads((path.parent / "audit.json").read_text(encoding="utf-8"))
        check(tag + ":file_hash", r.sha(path) == audit["timeline_sha256"])
        if config["variant"]["name"] == "E02_000":
            check(tag + ":E02_exact_reproduction", audit["E02_exact_reproduction"])

    # Verify the observable-derived score at diverse amplitudes/frequencies.
    comparisons, max_error = 0, 0.
    for scenario in scenarios.values():
        for f in (800000., 821400., 854800., 900000., 925000., 1000000.):
            for a in (.25, .4, 1.):
                q = model.response(f, scenario, a)
                row = {"amplitude_command": a, "p_port_W": float(q["p_port_W"][0]),
                       "vport_vpp": float(q["vport_vpp"][0]), "iport_irms_A": float(q["iport_irms_A"][0])}
                _, allowed, score = r.measured_estimate(row)
                exact = float(model.safe_power(f, scenario)[0])
                error = abs(score - exact) / max(exact, 1e-20)
                max_error = max(max_error, error)
                assert abs(allowed - float(model.allowed_amplitude(f, scenario, use_soft_limits=True)[0])) < 1e-12
                comparisons += 1
    check("observable_constrained_score_matches_exact_model", max_error < 1e-10, points=comparisons, max_relative_error=max_error)
    check("zero_amplitude_measurement_rejected", r.measured_estimate({"amplitude_command": 0.}) is None)

    # With a target below source ceiling, PI must settle, not accumulate windup.
    servo = r.AmplitudeServo()
    a = .25
    for k in range(120):
        row = {"amplitude_command": a, "p_port_W": .2 * a*a, "vport_vpp": 100*a, "iport_irms_A": .007*a}
        target = servo.propose(row)
        a = min(target, a + .05)
        servo.feedback(dict(row, amplitude_command=a, protection_state="RAMP_UP"), .02)
    check("amplitude_PI_subunit_target", abs(a - .0055/.007) < 1e-8 and abs(servo.integral) < 1e-8)
    servo.integral = 100.
    servo.feedback({"amplitude_command": 0., "protection_state": "HARD_TRIP"}, .02)
    check("amplitude_integrator_reset_on_hard_trip", servo.integral == 0.)

    # Reaching a sub-unit servo target must not shorten soft stabilization.
    from dataclasses import replace
    baseline = scenarios["CASE_000_BASELINE"]
    restricted = replace(baseline, bvd=replace(baseline.bvd, rm=baseline.bvd.rm * .5))
    trial = cls(model, legacy, r.VARIANTS[2], "P_AND_O", scenarios, optima)
    trial.g.a = .85
    trial.g.command(0., 900000., 1., restricted, "CONTROL")
    goal = float(model.allowed_amplitude(900000., restricted, use_soft_limits=True)[0])
    trial.g.regulation_goal = goal
    state = trial.g.command(.02, 900000., goal, restricted, "CONTROL")
    check("regulated_target_does_not_bypass_soft_hold", state["state"] == "SOFT_FOLDBACK" and state["frozen"])
    state = trial.g.command(.101, 900000., goal, restricted, "CONTROL")
    check("regulated_target_can_settle_after_soft_hold", state["state"] == "NORMAL" and not state["frozen"])

    # Synthetic algorithm-unit tests only: never used in result figures.
    for slope, reference in ((.01, 0.), (-.01, 0.), (.01, 179.)):
        trial = cls(model, legacy, r.VARIANTS[1], "PERIODIC_SCAN", scenarios, optima)
        trial.phase_reference = reference
        def fake_grid(frequencies, action, scan_a, reason):
            data = []
            for f in frequencies:
                p = .15 / (1 + ((f - 901000.)/300.)**2)
                phase = (reference + slope*(f-901000.) + 180.) % 360. - 180.
                data.append({"frequency_Hz": float(f), "phase_deg": phase, "amplitude_command": 1.,
                             "p_port_W": p, "vport_vpp": 100., "iport_irms_A": .005})
            return data, scan_a
        trial.grid = fake_grid
        outcome, frequency, _ = trial.local_search(900000., .25, "SYNTHETIC_UNIT_TEST")
        check(f"phase_sign_and_wrap:{slope}:{reference}", outcome == "PHASE_HINT_POWER_CONFIRMED" and frequency == 901000.)

    # Change only evaluator optima: commands and guards must remain identical.
    base.configure_schedule(legacy, .8)
    bogus = {k: {"frequency_Hz": 987654., "power_W": value["power_W"] * 37.} for k, value in optima.items()}
    fields = ("time_s", "duration_s", "frequency_Hz", "amplitude_command", "action", "protection_state")
    for cfg in r.VARIANTS[:8]:
        for strategy in ("PERIODIC_SCAN", "P_AND_O"):
            a = cls(model, legacy, cfg, strategy, scenarios, optima).run()
            b = cls(model, legacy, cfg, strategy, scenarios, bogus).run()
            check(cfg.name + ":" + strategy + ":no_evaluator_optimum_leak",
                  [[x[k] for k in fields] for x in a] == [[x[k] for k in fields] for x in b])

    # Matched no-phase controls must never propose a phase-derived candidate.
    for path in results.glob("D*/phase_events.json"):
        events = json.loads(path.read_text(encoding="utf-8"))
        check(path.parent.name + ":phase_disabled_control", not any(e["phase_candidate_used"] for e in events))
    manifest = json.loads((r.HERE / "input_manifest.json").read_text(encoding="utf-8"))
    check("frozen_and_previous_artifacts_unchanged", all(r.sha(x["original"]) == x["sha256"] == r.sha(r.HERE / x["frozen"]) for x in manifest))
    result = {"status": "PASS", "check_count": len(checks), "checks": checks,
              "scope": "Software invariants on registered tests; not continuous-time or hardware safety"}
    r.save_json(results / "independent_tests.json", result)
    print(json.dumps({"status": "PASS", "check_count": len(checks)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=r.RESULTS)
    main(parser.parse_args().results)
