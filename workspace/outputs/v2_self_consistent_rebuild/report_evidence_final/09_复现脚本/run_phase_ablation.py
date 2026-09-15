"""Pure phase-error controller ablation for MODEL_V2_1_HYPOTHETICAL.

This is deliberately separate from the three formal maximum-power strategies.
It uses only port-impedance phase for frequency updates; power is recorded only
for offline assessment.  The local control sign is identified from a symmetric
phase probe, so the update is df = K_phi * e_phi * sign(dphi/df).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model_v2_1 import F0, F_MIN, F_MAX, response, safe_power, scenario_map
from run_stage4_5_control import (
    CONTROL_DT, FINE_REFERENCE, SCHEDULE, SEGMENT_DURATION, TOTAL_TIME,
    Protection, schedule_at,
)


HERE = Path(__file__).resolve().parent
OUT = HERE / "stage4_5_control" / "phase_ablation"
GAINS_HZ_PER_DEG = [5.0, 10.0, 25.0, 50.0, 100.0]
SELECTED_GAIN = 5.0
PHASE_PROBE_HZ = 100.0
PHASE_DEADBAND_DEG = 0.10
MAX_UPDATE_HZ = 500.0


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def offline_optima(scenarios: dict) -> dict[str, dict]:
    result = {}
    for case_id in set(x["case_id"] for x in SCHEDULE):
        p = safe_power(FINE_REFERENCE, scenarios[case_id])
        i = int(np.argmax(p))
        result[case_id] = {"frequency_Hz": float(FINE_REFERENCE[i]), "power_W": float(p[i])}
    return result


def phase_at(frequency_hz: float, scenario) -> float:
    return float(response(np.array([frequency_hz]), scenario, 1.0)["phase_deg"][0])


def simulate(gain_hz_per_deg: float, scenarios: dict, optima: dict, target_phase_deg: float) -> list[dict]:
    rows: list[dict] = []
    protection = Protection()
    frequency = F0
    t = 0.0
    while t < TOTAL_TIME - 1e-12:
        seg = schedule_at(t)
        scenario = scenarios[seg["case_id"]]
        optimum = optima[seg["case_id"]]
        amplitude, pstate, hard, soft, frozen = protection.apply(t, frequency, scenario, 1.0)
        q = response(np.array([frequency]), scenario, amplitude)
        phase = float(q["phase_deg"][0])
        power = float(q["p_rm_W"][0])
        error = target_phase_deg - phase

        lo = max(F_MIN, frequency - PHASE_PROBE_HZ)
        hi = min(F_MAX, frequency + PHASE_PROBE_HZ)
        slope = (phase_at(hi, scenario) - phase_at(lo, scenario)) / max(hi - lo, 1.0)
        update = 0.0
        if pstate == "NORMAL" and not frozen and abs(error) > PHASE_DEADBAND_DEG and abs(slope) > 1e-12:
            update = float(np.clip(gain_hz_per_deg * error * np.sign(slope), -MAX_UPDATE_HZ, MAX_UPDATE_HZ))

        rows.append({
            "gain_Hz_per_deg": gain_hz_per_deg,
            "time_s": t,
            "state_index": seg["state_index"],
            "case_id": seg["case_id"],
            "frequency_Hz": frequency,
            "frequency_MHz": frequency / 1e6,
            "target_phase_deg": target_phase_deg,
            "phase_deg": phase,
            "phase_error_deg": error,
            "local_dphase_df_deg_per_Hz": slope,
            "frequency_update_Hz": update,
            "protection_state": pstate,
            "frequency_frozen": int(frozen or pstate != "NORMAL"),
            "amplitude": amplitude,
            "p_rm_W": power,
            "safe_power_capture_ratio": power / max(optimum["power_W"], 1e-30),
            "optimal_safe_frequency_Hz": optimum["frequency_Hz"],
            "vport_vpp": float(q["vport_vpp"][0]),
            "iport_irms_A": float(q["iport_irms_A"][0]),
            "frequency_saturated": int(frequency <= F_MIN + 1e-9 or frequency >= F_MAX - 1e-9),
            "hard_trip_trigger": hard,
            "soft_limit_trigger": soft,
        })
        frequency = float(np.clip(frequency + update, F_MIN, F_MAX))
        t += CONTROL_DT
    return rows


def summarize(rows: list[dict], gain: float) -> dict:
    segments = []
    for seg in SCHEDULE[1:]:
        sr = [r for r in rows if r["state_index"] == seg["state_index"]]
        tail = sr[-max(1, int(round(0.20 / CONTROL_DT))):]
        capture = float(np.mean([r["safe_power_capture_ratio"] for r in tail]))
        phase_error = float(np.mean([abs(r["phase_error_deg"]) for r in tail]))
        wrong_lock = int(phase_error <= 0.5 and capture < 0.95)
        segments.append({
            "gain_Hz_per_deg": gain,
            "state_index": seg["state_index"],
            "case_id": seg["case_id"],
            "steady_power_error_pct": (1.0 - capture) * 100.0,
            "steady_abs_phase_error_deg": phase_error,
            "locked_frequency_MHz": float(np.mean([r["frequency_MHz"] for r in tail])),
            "frequency_pp_kHz": (max(r["frequency_Hz"] for r in tail) - min(r["frequency_Hz"] for r in tail)) / 1e3,
            "frequency_saturation_ms": sum(r["frequency_saturated"] * CONTROL_DT for r in sr) * 1e3,
            "wrong_phase_lock_flag": wrong_lock,
        })
    return {
        "gain_Hz_per_deg": gain,
        "mean_steady_power_error_pct": float(np.mean([x["steady_power_error_pct"] for x in segments])),
        "mean_abs_phase_error_deg": float(np.mean([x["steady_abs_phase_error_deg"] for x in segments])),
        "max_frequency_pp_kHz": float(max(x["frequency_pp_kHz"] for x in segments)),
        "frequency_saturation_ms": float(sum(x["frequency_saturation_ms"] for x in segments)),
        "wrong_phase_lock_segments": int(sum(x["wrong_phase_lock_flag"] for x in segments)),
        "actual_hard_violations": int(sum(r["vport_vpp"] > 160.0 or r["iport_irms_A"] > 0.006 for r in rows)),
    }, segments


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = scenario_map()
    optima = offline_optima(scenarios)
    baseline_opt = optima["CASE_000_BASELINE"]["frequency_Hz"]
    target_phase = phase_at(baseline_opt, scenarios["CASE_000_BASELINE"])
    all_rows: list[dict] = []
    all_segments: list[dict] = []
    summaries: list[dict] = []
    for gain in GAINS_HZ_PER_DEG:
        rows = simulate(gain, scenarios, optima, target_phase)
        summary, segments = summarize(rows, gain)
        all_rows.extend(rows)
        all_segments.extend(segments)
        summaries.append(summary)
    write_csv(OUT / "phase_gain_sweep_summary.csv", summaries)
    write_csv(OUT / "phase_per_segment_metrics.csv", all_segments)
    write_csv(OUT / "phase_timeline_selected_gain.csv", [r for r in all_rows if r["gain_Hz_per_deg"] == SELECTED_GAIN])

    selected = [r for r in all_rows if r["gain_Hz_per_deg"] == SELECTED_GAIN]
    fig, axes = plt.subplots(3, 1, figsize=(9.0, 7.0), sharex=True)
    axes[0].plot([r["time_s"] for r in selected], [r["frequency_MHz"] for r in selected], color="#3775BA")
    axes[1].plot([r["time_s"] for r in selected], [r["phase_error_deg"] for r in selected], color="#9A4D8E")
    axes[2].plot([r["time_s"] for r in selected], [100*r["safe_power_capture_ratio"] for r in selected], color="#B64342")
    axes[0].set_ylabel("Frequency (MHz)")
    axes[1].set_ylabel("Phase error (deg)")
    axes[2].set_ylabel("Safe power capture (%)")
    axes[2].set_xlabel("Quasi-steady time (s)")
    for ax in axes:
        for seg in SCHEDULE[1:]:
            ax.axvline(seg["start_s"], color="#BBBBBB", lw=0.6)
    fig.suptitle(f"Pure phase-control ablation: Kphi={SELECTED_GAIN:g} Hz/deg")
    fig.tight_layout()
    for ext, kwargs in (("png", {"dpi": 300}), ("pdf", {}), ("svg", {})):
        fig.savefig(OUT / f"phase_ablation_selected_gain.{ext}", bbox_inches="tight", **kwargs)
    plt.close(fig)

    selected_summary = next(x for x in summaries if x["gain_Hz_per_deg"] == SELECTED_GAIN)
    audit = {
        "status": "PASS" if all(x["actual_hard_violations"] == 0 for x in summaries) else "FAIL",
        "model_id": "MODEL_V2_1_HYPOTHETICAL",
        "role": "fourth ablation only; excluded from formal three-strategy ranking",
        "phase_definition": "arg(Vport/Iport), positive inductive",
        "target_phase_deg": target_phase,
        "target_source": "baseline constrained maximum-P_Rm frequency",
        "control_law": "df=clip(Kphi*(phi_target-phi)*sign(dphi/df),+-500 Hz)",
        "selected_gain_Hz_per_deg": SELECTED_GAIN,
        "selected_summary": selected_summary,
        "wrong_phase_lock_seen_in_gain_sweep": any(x["wrong_phase_lock_segments"] > 0 for x in summaries),
        "scope": "quasi-steady hypothetical electrical model; no hardware or acoustic claim",
    }
    (OUT / "phase_ablation_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
