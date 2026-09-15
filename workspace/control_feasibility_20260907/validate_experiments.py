"""Independent checks, including controller blindness to evaluation optima."""
import csv
import json
import math
from pathlib import Path

import run_experiments as exp


def main():
    m, c = exp.load_legacy()
    scenarios = m.scenario_map()
    optima = c.optimal_tables(scenarios)
    checks = []

    def check(name, result, **details):
        checks.append({"check": name, "pass": bool(result), **details})
        if not result:
            raise AssertionError(name)

    reproduction = json.loads((exp.RESULTS / "baseline_reproduction.json").read_text(encoding="utf-8"))
    check("history_reproduced_exactly", reproduction["pass"] and reproduction["max_absolute_numeric_difference"] == 0,
          rows=reproduction["rows"], fields=reproduction["fields_per_row"])
    for path in sorted(exp.RESULTS.glob("E*/timeline.csv")):
        with path.open(encoding="utf-8-sig") as h:
            rows = list(csv.DictReader(h))
        config = json.loads((path.parent / "config.json").read_text(encoding="utf-8"))
        check(path.parent.name + ":limits_and_acceptance_frozen", config["current_hard_Arms"] == .006 and
              config["voltage_hard_Vpp"] == 160 and config["acceptance_samples"] == 10 and config["acceptance_capture"] == .98)
        for strategy in c.STRATEGIES:
            sr = [r for r in rows if r["strategy"] == strategy]
            gaps = [abs(float(a["time_s"]) + float(a["duration_s"]) - float(b["time_s"])) for a, b in zip(sr, sr[1:])]
            check(path.parent.name + ":" + strategy + ":continuous_action_coverage", max(gaps, default=0) < 1e-10)
            if config["variant"] == "E00":
                continue
            check(path.parent.name + ":" + strategy + ":guard_call_per_action",
                  [int(r["guard_call_index"]) for r in sr] == list(range(1, len(sr) + 1)))
            for r in sr:
                if int(r["hard_trip_trigger"]):
                    t = float(r["time_s"])
                    hard_rows = [x for x in sr if t <= float(x["time_s"]) < t + c.HARD_HOLD - 1e-10]
                    hold_rows = [x for x in sr if t + c.HARD_HOLD - 1e-10 <= float(x["time_s"]) < t + c.HARD_HOLD + c.RECOVERY_HOLD - 1e-10]
                    check(path.parent.name + ":" + strategy + ":hard_hold_60ms@" + str(t),
                          all(float(x["amplitude_command"]) == 0 for x in hard_rows))
                    check(path.parent.name + ":" + strategy + ":recovery_hold_100ms@" + str(t),
                          all(float(x["amplitude_command"]) <= .25 + 1e-12 and not x["action"].startswith("SCAN") for x in hold_rows))
            illegal_rises = []
            for r in sr:
                rise = float(r["amplitude_command"]) - float(r["previous_amplitude"])
                if r["protection_state"] != "RECOVERY_HOLD" and rise > float(r["upward_slew_budget"]) + 1e-10:
                    illegal_rises.append(r["time_s"])
            check(path.parent.name + ":" + strategy + ":rise_rate_respected", not illegal_rises)

    # Exhaustive point safety over the already registered hypothetical models.
    tested = 0
    for scenario in scenarios.values():
        for frequency in (800000., 854800., 900000., 1000000.):
            g = exp.Guard(m, c, True, True)
            g.f, g.a = frequency, 1.0
            x = g.command(0.0, frequency, 1.0, scenario)
            q = m.response(x["f"], scenario, x["a"])
            assert q["vport_vpp"][0] <= 160 + 1e-9
            assert q["iport_irms_A"][0] <= .006 + 1e-12
            tested += 1
    check("registered_model_point_safety", True, cases=tested, scope="model-preview only")

    # Preserve the scenario responses but deliberately corrupt the evaluation
    # optima. Frequency/amplitude commands MUST be bitwise unchanged.
    exp.configure_schedule(c, .8)
    fake = {k: {"frequency_Hz": 987654.0, "power_W": v["power_W"] * 37.0} for k, v in optima.items()}
    for strategy in ("PERIODIC_SCAN", "P_AND_O"):
        normal = exp.Experiment(m, c, "E02", strategy, scenarios, optima).run()
        altered = exp.Experiment(m, c, "E02", strategy, scenarios, fake).run()
        fields = ("time_s", "duration_s", "action", "frequency_Hz", "amplitude_command", "protection_state")
        check("E02:" + strategy + ":evaluation_optimum_not_used_by_controller",
              [[r[f] for f in fields] for r in normal] == [[r[f] for f in fields] for r in altered])

    # Clock rounding is a plant numerical correction, not event-trigger access.
    e = exp.Experiment(m, c, "E02", "P_AND_O", scenarios, optima)
    e.t = 2.4 - 1e-14
    check("plant_boundary_roundoff_not_a_whole_sample_delay", e.context()[0]["state_index"] == 3)
    manifest = json.loads((exp.HERE / "input_manifest.json").read_text(encoding="utf-8"))
    check("formal_inputs_untouched", all(exp.sha(x["original"]) == x["sha256"] for x in manifest))
    exp.save_json(exp.RESULTS / "independent_tests.json", {"status": "PASS", "check_count": len(checks), "checks": checks})
    print(json.dumps({"status": "PASS", "check_count": len(checks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
