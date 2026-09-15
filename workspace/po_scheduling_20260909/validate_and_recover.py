"""Independent scheduler checks and fixed-frequency recovery diagnostics."""
import csv
from dataclasses import asdict, replace
import itertools
import json
import math
from pathlib import Path

import numpy as np
import run_study as r


def read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def numeric(row):
    result = {}
    for k, v in row.items():
        try:
            result[k] = float(v)
        except (TypeError, ValueError):
            result[k] = v
    return result


def recovery(previous, base, model, legacy, cls, out=None):
    out = Path(out) if out is not None else r.HERE / "recovery"
    if out.exists():
        raise FileExistsError("Recovery evidence exists; preserve it and use a separate run directory")
    baseline = model.scenario_map()["CASE_000_BASELINE"]
    stress = replace(baseline, case_id="BENCH_RM_M30", factor="Rm", level="-30%",
                     bvd=replace(baseline.bvd, rm=baseline.bvd.rm*.7))
    summary = []
    old_step = legacy.RAMP_STEP
    for scenario, pi, initial, step in itertools.product((baseline, stress), (False, True), (.4, .7, .9), (.025, .05)):
        tag = f"{scenario.case_id}_B{int(pi)}_a{initial*100:.0f}_step{step*1000:.0f}"
        legacy.RAMP_STEP = step
        legacy.SCHEDULE = [dict(state_index=0, case_id=scenario.case_id, start_s=0., end_s=1.62)]
        legacy.TOTAL_TIME = 1.62
        allow = float(model.allowed_amplitude(model.F0, scenario, use_soft_limits=True)[0])
        target = float(model.safe_power(model.F0, scenario)[0])
        # Evaluation-only target: fixed frequency, not an oracle used by the PI.
        opt = {scenario.case_id: dict(frequency_Hz=model.F0, power_W=target)}
        trial = cls(model, legacy, r.Configuration(pi, .1, initial, "R0"), {scenario.case_id: scenario}, opt)
        trial.g.a, trial.g.state = initial, "RAMP_UP"
        trial.act("CONTROL", model.F0, initial, .02, "LOW_AMPLITUDE_MEASUREMENT")
        # No automatic frequency search in this bench; only amplitude recovery.
        recovery_start = trial.t
        while trial.t < legacy.TOTAL_TIME-1e-12:
            command = 1.
            if pi:
                command = trial.servo.propose(trial.last_control_measurement)
                trial.g.regulation_goal = trial.servo.goal
                trial.amplitude_goal_used = trial.servo.goal
            trial.act("CONTROL", model.F0, command, .02, "FIXED_FREQUENCY_RECOVERY_ONLY")
        rows = trial.rows[1:]
        normal = next((x for x in rows if x["protection_state"] == "NORMAL"), None)
        power98 = next((x for x in rows if x["p_rm_W"] >= target*.98), None)
        b = scenario.bvd
        summary.append(dict(name=tag, case_id=scenario.case_id, pi=pi, initial_amplitude=initial,
            step_per_20ms=step, fixed_Hz=model.F0, allowed_amplitude=allow, target_at_fixed_frequency_W=target,
            time_origin_s=recovery_start,
            first_power98_timestamp_ms=None if power98 is None else (power98["time_s"]-recovery_start)*1000,
            first_power98_sample_complete_ms=None if power98 is None else (power98["time_s"]+.02-recovery_start)*1000,
            first_NORMAL_timestamp_ms=None if normal is None else (normal["time_s"]-recovery_start)*1000,
            first_NORMAL_sample_complete_ms=None if normal is None else (normal["time_s"]+.02-recovery_start)*1000,
            NORMAL_reached=int(normal is not None), power98_reached=int(power98 is not None),
            power_overshoot_pct=max(0., max(x["p_rm_W"]/target-1 for x in rows)*100),
            peak_vpp=max(x["vport_vpp"] for x in rows), peak_irms_mA=max(x["iport_irms_A"] for x in rows)*1000,
            final_integral=trial.servo.integral, final_amplitude=rows[-1]["amplitude_command"],
            final_state=rows[-1]["protection_state"], nominal_linear_ramp_updates=math.ceil((allow-initial)/step-1e-9),
            derived_fs_Hz=1/(2*math.pi*math.sqrt(b.lm*b.cm)), derived_Qm=math.sqrt(b.lm/b.cm)/b.rm))
        base.save_csv(out / tag / "timeline.csv", trial.rows)
        r.save_json(out / tag / "config.json", dict(scenario=asdict(scenario), pi=pi, initial=initial, step=step,
             scan_or_probe_enabled=False, prior_holds_excluded=True, time_origin_s=recovery_start,
             source_class="HYPOTHETICAL_BASELINE_AND_SCAN_VARIABLES", target_definition="fixed-frequency soft-limited power"))
    legacy.RAMP_STEP = old_step
    base.save_csv(out / "summary.csv", summary)
    return summary


def main():
    previous, base, model, legacy = r.load()
    cls = r.make_class(previous, base)
    checks = []
    def check(name, passed, **metadata):
        checks.append(dict(name=name, passed=bool(passed), **metadata))
        if not passed:
            r.save_json(r.HERE / "validation_failure.json", checks)
            raise AssertionError(name)

    paths = sorted(r.RESULTS.glob("*/timeline.csv"))
    check("108_registered_timelines", len(paths) == 108)
    for path in paths:
        tag = path.parent.name
        raw = read(path)
        rows = [numeric(x) for x in raw]
        config = json.loads((path.parent / "config.json").read_text(encoding="utf-8"))
        check(tag+":limits_holds_rate_frozen", config["limits"] == [130,.0055,160,.006]
              and config["ramp_step"] == .05 and config["hard_hold_s"] == .06
              and config["recovery_hold_s"] == .1 and config["soft_hold_s"] == .1)
        check(tag+":pointwise_limits_not_continuous_proof", all(x["vport_vpp"] <= 160+1e-9 and x["iport_irms_A"] <= .006+1e-12 for x in rows))
        check(tag+":guard_each_action", [int(x["guard_call_index"]) for x in rows] == list(range(1,len(rows)+1)))
        check(tag+":amplitude_sync", all(x["amplitude_command"] == x["internal_amplitude"] for x in rows))
        check(tag+":bounds", all(0 <= x["amplitude_command"] <= 1 and 800000 <= x["frequency_Hz"] <= 1000000 for x in rows))
        check(tag+":no_joint_upward_amplitude_frequency_jump", all(abs(x["frequency_Hz"]-x["previous_frequency_Hz"]) < 1e-8
              or x["amplitude_command"] <= x["previous_amplitude"]+1e-12 for x in rows))
        check(tag+":scan_cap_remains_0.4", config["scan_cap"] == .4 and all(x["amplitude_command"] <= .4+1e-12
              for x in rows if x["action"].startswith("SCAN")))
        check(tag+":probe_cap", all(x["amplitude_command"] <= config["setup"]["probe_cap"]+1e-12
              for x in rows if x["action"].startswith("P_AND_O")))
        check(tag+":complete_time", abs(sum(x["duration_s"] for x in rows)-config["dwell_s"]*8) < 1e-9 and
              all(abs(x["time_s"]+x["duration_s"]-y["time_s"]) < 1e-10 for x,y in zip(rows,rows[1:])))
        hard_ok = hold_ok = rate_ok = True
        for x in rows:
            if x["hard_trip_trigger"]:
                t = x["time_s"]
                hard_ok &= all(y["amplitude_command"] == 0 for y in rows if t <= y["time_s"] < t+.06-1e-10)
                hold_ok &= all(y["amplitude_command"] <= .25+1e-12 and not y["action"].startswith("SCAN")
                               for y in rows if t+.06-1e-10 <= y["time_s"] < t+.16-1e-10)
            if x["protection_state"] != "RECOVERY_HOLD":
                rate_ok &= x["amplitude_command"] <= x["previous_amplitude"]+x["upward_slew_budget"]+1e-10
        check(tag+":hard_60ms_recovery_100ms", hard_ok and hold_ok)
        check(tag+":upward_slew", rate_ok)
        gate = config["setup"]["recovery_gate"]
        events = json.loads((path.parent / "probe_events.json").read_text(encoding="utf-8"))
        for e in events:
            if gate != "R0" and e["gate_episode_started"]:
                check(tag+f":gate_at_{e['start_s']}", e["gate_normal_since_s"] is not None
                      and e["start_s"]-e["gate_normal_since_s"] >= config["setup"]["interval_s"]-1e-10
                      and (gate == "R1" or e["gate_stable_count"] >= 10))
        audit = json.loads((path.parent / "audit.json").read_text(encoding="utf-8"))
        check(tag+":file_hash", r.sha(path) == audit["timeline_sha256"])
        if "previous_round_exact_reproduction" in audit:
            check(tag+":previous_exact_reproduction", audit["previous_round_exact_reproduction"]["matched"])

    # Unit-test inherited soft hold independently of matrix coincidences.
    scenarios = model.scenario_map()
    optima = legacy.optimal_tables(scenarios)
    baseline = scenarios["CASE_000_BASELINE"]
    restricted = replace(baseline, bvd=replace(baseline.bvd, rm=baseline.bvd.rm*.5))
    trial = cls(model, legacy, r.Configuration(True,.1,.4,"R2"), scenarios,optima)
    trial.g.a = .85
    trial.g.command(0.,900000.,1.,restricted,"CONTROL")
    goal = float(model.allowed_amplitude(900000.,restricted,use_soft_limits=True)[0])
    trial.g.regulation_goal = goal
    check("PI_target_does_not_bypass_soft_hold", trial.g.command(.02,900000.,goal,restricted)["state"] == "SOFT_FOLDBACK")
    check("PI_target_NORMAL_after_soft_hold", trial.g.command(.101,900000.,goal,restricted)["state"] == "NORMAL")

    # Evaluator oracle poisoning: repeat commands, not the evaluation columns.
    base.configure_schedule(legacy,.8)
    poison = {k: dict(frequency_Hz=987654.,power_W=v["power_W"]*37) for k,v in optima.items()}
    setups = [r.Configuration(pi,.3,.7,g) for pi,g in itertools.product((False,True),("R0","R1","R2"))]
    setups += [r.Configuration(True,.5,.9,"R2"),r.Configuration(True,.1,.4,"R0")]
    fields = ("time_s","duration_s","frequency_Hz","amplitude_command","action","protection_state")
    for setup in setups:
        original = [numeric(x) for x in read(r.RESULTS/f"{setup.name}_dwell_0.8s/timeline.csv")]
        poisoned = cls(model,legacy,setup,scenarios,poison).run()
        check(setup.name+":no_evaluator_oracle_leak", [[x[k] for k in fields] for x in original] == [[x[k] for k in fields] for x in poisoned])

    bench = recovery(previous,base,model,legacy,cls)
    check("24_isolated_recovery_benchmarks", len(bench) == 24)
    check("bench_pointwise_limits", all(x["peak_vpp"] <= 130+1e-9 and x["peak_irms_mA"] <= 5.5+1e-9 for x in bench))
    check("bench_all_reach_fixed_frequency_98pct", all(x["power98_reached"] for x in bench))
    check("bench_PI_all_reach_NORMAL", all(x["NORMAL_reached"] for x in bench if x["pi"]))
    check("bench_no_power_overshoot", all(x["power_overshoot_pct"] < 1e-8 for x in bench))
    manifest = json.loads((r.HERE/"input_manifest.json").read_text(encoding="utf-8"))
    check("prior_and_frozen_files_unchanged", all(r.sha(x["original"]) == x["sha256"] == r.sha(r.HERE/x["frozen"]) for x in manifest))
    r.save_json(r.HERE/"independent_tests.json",dict(status="PASS",count=len(checks),checks=checks,
        scope="Software invariants only; no continuous-time or physical safety proof"))
    print(f"PASS: {len(checks)} checks, {len(bench)} recovery runs",flush=True)


if __name__ == "__main__":
    main()
