"""Registered static diagnostics and explicitly post-hoc binding-limit stress."""
from dataclasses import asdict, replace
import argparse
import math
from pathlib import Path

import numpy as np
import run_factorial as r


def stress_scenarios(model):
    baseline = model.scenario_map()["CASE_000_BASELINE"]
    return {f"STRESS_RM_M{pct}": replace(baseline, case_id=f"STRESS_RM_M{pct}", factor="Rm", level=f"-{pct}%",
            family="EXPLORATORY_BINDING_CURRENT", bvd=replace(baseline.bvd, rm=baseline.bvd.rm*(1-pct/100)),
            description="Post-hoc diagnostic for binding current; raw Rm only changes, derived Qm changes; not part of main score")
            for pct in (30, 50)}


def main(out):
    if out.exists():
        raise FileExistsError("Preserve diagnostics; choose a new output directory")
    base, model, legacy = r.load()
    cls = r.experiment_class(base)
    scenarios = model.scenario_map()
    scenarios.update(stress_scenarios(model))
    grid = np.arange(800000., 1000000.1, 100.)
    optima, raw_optima, objective_rows = {}, {}, []
    for key, scenario in scenarios.items():
        power = model.response(grid, scenario)["p_rm_W"]
        safe = model.safe_power(grid, scenario)
        idx, safeidx = int(np.argmax(power)), int(np.argmax(safe))
        optima[key] = {"frequency_Hz": float(grid[safeidx]), "power_W": float(safe[safeidx])}
        raw_optima[key] = float(grid[idx])
        objective_rows.append({"case_id": key, "scope": "exploratory" if key.startswith("STRESS") else "registered",
                               "raw_power_peak_Hz": float(grid[idx]), "safe_power_peak_Hz": float(grid[safeidx]),
                               "safe_shift_Hz": float(grid[safeidx]-grid[idx]), "raw_peak_W": float(power[idx]),
                               "safe_peak_W": float(safe[safeidx]), "safe_power_at_raw_peak_W": float(safe[idx]),
                               "allowed_amplitude_at_raw_peak": float(model.allowed_amplitude(grid[idx], scenario, use_soft_limits=True)[0]),
                               "rm_ohm": scenario.bvd.rm, "derived_Qm": 2*math.pi*scenario.bvd.fs*scenario.bvd.lm/scenario.bvd.rm})
    base.save_csv(out / "objective_landscape.csv", objective_rows)
    # Start each scan with the same previously measured baseline phase and a=0.25.
    # This isolates the search itself; it is not a disturbance-detection trial.
    static = []
    phase_ref = float(model.response(900000., scenarios["CASE_000_BASELINE"])["phase_deg"][0])
    variants = [x for x in r.VARIANTS if x.name in {"E02_000", "E03_A", "E05_C", "E07_AC", "D01_LOCAL", "D02_LOCAL_BC"}]
    for case_id in scenarios:
        legacy.SCENARIO_ORDER = [case_id]
        base.configure_schedule(legacy, 1.6)
        for cfg in variants:
            trial = cls(model, legacy, cfg, "PERIODIC_SCAN", scenarios, optima)
            trial.g.a = .25
            trial.phase_reference = phase_ref
            done = trial.scan("STATIC_DIAGNOSTIC_SAME_PRIOR_PHASE")
            result_power = float(model.safe_power(trial.g.f, scenarios[case_id])[0])
            static.append({"case_id": case_id, "variant": cfg.name, "scope": "exploratory" if case_id.startswith("STRESS") else "registered",
                           "completed": int(done), "selected_Hz": trial.g.f, "elapsed_ms": trial.t*1000,
                           "safe_peak_Hz": optima[case_id]["frequency_Hz"], "frequency_error_Hz": trial.g.f-optima[case_id]["frequency_Hz"],
                           "selected_safe_capture_pct": result_power/optima[case_id]["power_W"]*100,
                           "phase_path": trial.phase_path, "phase_hints": len([e for e in trial.phase_events if e["phase_candidate_used"]])})
            folder = out / "static_scans" / case_id / cfg.name
            base.save_csv(folder / "timeline.csv", trial.rows)
            r.save_json(folder / "phase_events.json", trial.phase_events)
    base.save_csv(out / "static_scan_summary.csv", static)

    # Exploratory negative-Rm sequence is separate from original acceptance.
    legacy.SCENARIO_ORDER = ["CASE_000_BASELINE", "STRESS_RM_M30", "CASE_000_BASELINE", "STRESS_RM_M50", "CASE_000_BASELINE"]
    base.configure_schedule(legacy, 1.6)
    stress_summary = []
    for cfg in r.VARIANTS[:8]:
        allrows = []
        for strategy in legacy.STRATEGIES:
            allrows.extend(cls(model, legacy, cfg, strategy, scenarios, optima).run())
        details = base.detailed_metrics(model, legacy, allrows, scenarios, optima)
        r.extra_metrics(legacy, allrows, details)
        base.save_csv(out / "stress_closed_loop" / cfg.name / "timeline.csv", allrows)
        base.save_csv(out / "stress_closed_loop" / cfg.name / "metrics.csv", details)
        for d in details:
            if d["case_id"].startswith("STRESS"):
                stress_summary.append(dict(d, variant=cfg.name))
    base.save_csv(out / "stress_summary.csv", stress_summary)
    r.save_json(out / "diagnostic_config.json", {"stress_design": "post-hoc: original registered maxima did not bind soft limits",
                "not_used_to_tune_gains": True, "main_sequence_scores_not_replaced": True,
                "static_phase_reference_deg": phase_ref, "stress_sequence": legacy.SCHEDULE,
                "stress_parameters": {k: asdict(s) for k, s in stress_scenarios(model).items()},
                "parameter_source": "SCAN_VARIABLES_ON_HYPOTHETICAL_BASELINE"})
    print("Static scans:", len(static), "stress result rows:", len(stress_summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=r.HERE / "diagnostics")
    main(parser.parse_args().out)
