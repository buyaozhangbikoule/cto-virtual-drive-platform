"""Fourth ablation: de-embedded motional-branch phase, pure and as a hold stage.

This is an ADDITIONAL ablation.  It replaces nothing.  The formal three
strategies in ``run_stage4_5_control.py`` and the third ablation in
``run_phase_ablation.py`` are untouched, so their outputs stay byte-identical
and the plan's wording does not have to be settled before these numbers exist.

Six variants run on the same schedule and the same gain sweep as the third
ablation, so every change is isolated:

    ARG_ZIN_PURE          the existing signal and controller, recomputed here as
                          a cross-check that this script agrees with the third
                          ablation.  It does, to every printed digit.
    MOTIONAL_PURE         only the error signal changes, from arg(Zin) to the
                          de-embedded arg(Zm).  Isolates what the signal is worth,
                          which turns out to be negative on its own.
    HOLD_FROZEN_NOSLEW    a power scan acquires and the motional phase holds, with
                          re-acquisition from the existing frozen-reference
                          detector.  Reproduces the blind spot described below.
    HOLD_FROZEN_SLEW      same, plus the slew-budget backstop.
    HOLD_SCANREF_NOSLEW   same as HOLD_FROZEN_NOSLEW but the reference is the last
                          scan's measured curve, interpolated at the current
                          frequency.  Isolates the reference fix on its own.
    HOLD_SCANREF_SLEW     both fixes together.

The blind spot the last four variants exist to measure: the frozen detector needs
ten consecutive samples at ONE frequency to build its reference and clears the
buffer on any frequency change, so a phase controller retuning every control tick
can never arm it.  It works while the controller is settled, which is when it is
least needed.  Pure scanning and P&O never show this because their frequency is
constant between updates.

Why the motional phase is a better signal: arg(Zm) = atan((wLm - 1/(wCm))/Rm) is
strictly monotone in frequency, so it has exactly one zero and a non-zero target
is uniquely reachable.  arg(Zin) carries a second zero owned by the matching
network at 1/(2*pi*sqrt(L*(C0+Cmatch))) = 903.95 kHz, which does not move when
the transducer resonance moves, and that is the point a phase controller locks
to once the resonance has gone.

De-embedding uses only what a driver measures at the amplifier terminals, namely
input voltage and source current, plus design values it already knows.  It never
reads Rm, Lm or Cm.

Copy this file next to ``run_stage4_5_control.py`` inside a working copy made by
``handoff.py prepare``, after applying
``review/patches/run_stage4_5_control.edge_aware_scan.patch``, then run it.
Nothing here writes outside ``stage4_5_control/phase_hold_ablation/``.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model_v2_1 import F0, F_MIN, F_MAX, response, safe_power, scenario_map
from run_stage4_5_control import (
    CONTROL_DT, FINE_REFERENCE, SCHEDULE, SCAN_POINT_DT, TOTAL_TIME,
    ObservableDisturbanceDetector, Protection, local_scan, optimal_tables, schedule_at,
)
from run_phase_ablation import (
    GAINS_HZ_PER_DEG, MAX_UPDATE_HZ, PHASE_DEADBAND_DEG, PHASE_PROBE_HZ, SELECTED_GAIN,
)

HERE = Path(__file__).resolve().parent
OUT = HERE / "stage4_5_control" / "phase_hold_ablation"

# (name, signal, scan acquisition, reference kind, slew-budget backstop)
#
# The last two columns decompose the two separate fixes.  HOLD_FROZEN_NOSLEW is
# the first version that was built and it reproduces the original failure, so
# the other two rows show what each fix is worth on its own.
VARIANTS = [
    ("ARG_ZIN_PURE", "ARG_ZIN", False, "FROZEN", False),
    ("MOTIONAL_PURE", "MOTIONAL_DEEMBED", False, "FROZEN", False),
    ("HOLD_FROZEN_NOSLEW", "MOTIONAL_DEEMBED", True, "FROZEN", False),
    ("HOLD_FROZEN_SLEW", "MOTIONAL_DEEMBED", True, "FROZEN", True),
    ("HOLD_SCANREF_NOSLEW", "MOTIONAL_DEEMBED", True, "SCAN_CURVE", False),
    ("HOLD_SCANREF_SLEW", "MOTIONAL_DEEMBED", True, "SCAN_CURVE", True),
]

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Liberation Sans"]
plt.rcParams["svg.fonttype"] = "none"
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                     "legend.frameon": False})
COLORS = {"ARG_ZIN_PURE": "#767676", "MOTIONAL_PURE": "#3775BA",
          "HOLD_FROZEN_NOSLEW": "#C98A2E", "HOLD_FROZEN_SLEW": "#B64342",
          "HOLD_SCANREF_NOSLEW": "#6B4C9A", "HOLD_SCANREF_SLEW": "#2E7D5B"}


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------- signals
def arg_zin_deg(frequency_hz: float, scenario, amplitude: float) -> float:
    return float(response(np.array([frequency_hz]), scenario, amplitude)["phase_deg"][0])


def motional_phase_deg(frequency_hz: float, scenario, amplitude: float) -> float:
    """De-embed arg(Zm) from input voltage and source current.

    The matching inductor, its ESR, the matching capacitor, its ESR and C0 are
    design values, so the motional branch is peeled off analytically.  Verified
    against the model's internal z_m to 1e-15..1e-12 degrees in
    review/proposed_fixes_prototype.py.
    """
    q = response(np.array([frequency_hz]), scenario, amplitude)
    v_input = complex(q["v_input"][0])
    i_source = complex(q["i_source"][0])

    w = 2 * math.pi * frequency_hz
    m = scenario.matching
    r_l = 2 * math.pi * F0 * m.l_h / m.ql
    r_c = 1 / (2 * math.pi * F0 * m.c_f * m.qc)
    z_c_match = r_c + 1 / (1j * w * m.c_f)

    z_parallel = v_input / i_source - r_l - 1j * w * m.l_h
    v_port = i_source * z_parallel
    i_port = i_source - v_port / z_c_match
    i_motional = i_port - 1j * w * scenario.bvd.c0 * v_port
    return float(np.angle(v_port / i_motional, deg=True))


SIGNALS = {"ARG_ZIN": arg_zin_deg, "MOTIONAL_DEEMBED": motional_phase_deg}

# Below this commanded amplitude the drive is off and nothing can be measured, so
# no phase signal exists.  De-embedding makes this explicit because it divides by
# the source current, which is exactly zero during a hard trip.  arg(Zin) hides it:
# in a linear model the angle does not depend on amplitude, so evaluating it at a
# hypothetical full amplitude always returns a number even while the drive is cut.
# Both signals are held to the same rule here, otherwise the comparison would
# credit arg(Zin) with measurements a real driver could not take.
MEASUREMENT_FLOOR_AMPLITUDE = 1e-6

# A phase controller that is chasing a large error changes frequency every
# sample, and the observable detector needs ten samples at one frequency to
# build its reference, so the detector can never arm while the controller is
# chasing.  It works only once the controller has settled, which is when it is
# least needed.  The hold stage therefore carries its own observable trigger:
# with the locally measured slope and the known update clip, the best the
# controller can close in this many samples is MAX_UPDATE_HZ * samples * slope
# degrees.  An error larger than that cannot be walked off in the budget, so a
# scan is the right move.  Near resonance the slope is steep and this threshold
# is hundreds of degrees, so it never fires spuriously; far from resonance the
# slope collapses and it fires at once.  Nothing here reads the plant identity
# or the true optimum.
REACQUIRE_HORIZON_SAMPLES = 10


# Scan-curve reference thresholds, same shape as the frozen detector's.
SCANREF_DROP_TRIGGER = 0.10
SCANREF_CONFIRM_SAMPLES = 3


class ScanCurveReference:
    """A reference that moves with the controller, so retuning cancels out of it.

    The frozen detector stores one measurement taken at one frequency, so the
    moment the controller retunes the residual is dominated by the controller's
    own move rather than by the plant.  That is why it has to clear its reference
    after every scan and rebuild it from ten samples at a standing frequency, and
    that rebuild is what never completes while a phase controller is chasing.

    The scan already measures normalised port power at fifty-odd frequencies
    spanning about 100 kHz.  Keeping that curve and interpolating it at whatever
    frequency the controller is currently on gives a reference defined everywhere
    the scan looked, with no fit and no extra measurement.  The residual is then
    zero wherever the plant still matches the scan, whatever the controller does.

    This is the model-referenced residual of the fault-detection literature, with
    the last scan standing in for the model.

    Caveat: the scan is taken at the probe amplitude and control samples at full
    amplitude.  Dividing by amplitude squared makes the two comparable in a linear
    model only.  On real hardware the two would have to be reconciled.
    """

    def __init__(self) -> None:
        self.frequencies: np.ndarray | None = None
        self.powers: np.ndarray | None = None
        self.abnormal = 0

    def load(self, samples: list[tuple[float, float]]) -> None:
        ordered = sorted(samples)
        self.frequencies = np.array([f for f, _ in ordered])
        self.powers = np.array([p for _, p in ordered])
        self.abnormal = 0

    def observe(self, frequency_hz: float, measured: float) -> dict:
        if self.frequencies is None or not (
                self.frequencies[0] <= frequency_hz <= self.frequencies[-1]):
            self.abnormal = 0
            return {"detector_state": "NO_REFERENCE", "detector_vote_count": 0,
                    "detector_trigger": 0, "detector_reason": ""}
        expected = float(np.interp(frequency_hz, self.frequencies, self.powers))
        residual = abs(measured - expected) / max(abs(expected), 1e-30)
        if residual > SCANREF_DROP_TRIGGER:
            self.abnormal += 1
        else:
            self.abnormal = 0
        trigger = int(self.abnormal >= SCANREF_CONFIRM_SAMPLES)
        if trigger:
            self.abnormal = 0
        return {"detector_state": "SCAN_CURVE", "detector_vote_count": int(residual > SCANREF_DROP_TRIGGER),
                "detector_trigger": trigger,
                "detector_reason": "SCAN_CURVE_RESIDUAL" if trigger else ""}


def read_signal(signal, frequency_hz: float, scenario, amplitude: float) -> tuple[float, bool]:
    """Return the signal and whether it was measurable at this drive level."""
    if amplitude <= MEASUREMENT_FLOOR_AMPLITUDE:
        return math.nan, False
    return signal(frequency_hz, scenario, amplitude), True


def offline_optima(scenarios: dict) -> dict[str, dict]:
    result = {}
    for case_id in {seg["case_id"] for seg in SCHEDULE}:
        p = safe_power(FINE_REFERENCE, scenarios[case_id])
        i = int(np.argmax(p))
        result[case_id] = {"frequency_Hz": float(FINE_REFERENCE[i]), "power_W": float(p[i])}
    return result


# -------------------------------------------------------------------- simulate
def simulate(variant: str, signal_name: str, scan_hold: bool, reference_kind: str,
             use_slew_rule: bool, gain: float,
             scenarios: dict, optima: dict) -> tuple[list[dict], dict]:
    signal = SIGNALS[signal_name]
    rows: list[dict] = []
    protection = Protection()
    detector = ObservableDisturbanceDetector()
    scan_reference = ScanCurveReference()
    scratch: list[dict] = []          # stage-4 schema rows produced by local_scan
    frequency = F0
    t = 0.0
    scan_episodes = 0
    scan_points_before = 0
    negative_slope_samples = 0
    reacquire_pending = False
    reacquire_reason = ""

    base_opt = optima["CASE_000_BASELINE"]["frequency_Hz"]
    target = signal(base_opt, scenarios["CASE_000_BASELINE"], 1.0)
    if reference_kind == "SCAN_CURVE":
        # The curve only exists after a scan, so this variant acquires once up front.
        reacquire_pending = True
        reacquire_reason = "INITIAL_ACQUISITION"

    while t < TOTAL_TIME - 1e-12:
        seg = schedule_at(t)
        scenario = scenarios[seg["case_id"]]
        optimum = optima[seg["case_id"]]

        if scan_hold and reacquire_pending and protection.tracking_allowed(t):
            before = len(scratch)
            frequency, t, converged = local_scan(
                t, variant, frequency, reacquire_reason, scratch, protection, scenarios, optima)
            scan_episodes += 1
            scan_points_before += len(scratch) - before
            seg = schedule_at(t)
            scenario = scenarios[seg["case_id"]]
            optimum = optima[seg["case_id"]]
            # Re-record the target at the frequency the scan just found.  This is
            # the whole point of the hybrid: the target is a measured property of
            # the new operating point, not a constant carried over from before.
            target = signal(frequency, scenario, 1.0)
            detector.after_scan(t)
            if reference_kind == "SCAN_CURVE":
                scan_reference.load([(r["frequency_Hz"], r["normalized_port_power_W"])
                                     for r in scratch[before:]])
            reacquire_pending = False
            reacquire_reason = ""
            continue

        amplitude, pstate, hard, soft, frozen = protection.apply(t, frequency, scenario, 1.0)
        q = response(np.array([frequency]), scenario, amplitude)
        value, available = read_signal(signal, frequency, scenario, amplitude)
        error = target - value if available else math.nan
        power = float(q["p_rm_W"][0])
        z_in = complex(q["z_in"][0])

        lo = max(F_MIN, frequency - PHASE_PROBE_HZ)
        hi = min(F_MAX, frequency + PHASE_PROBE_HZ)
        if available:
            hi_value, _ = read_signal(signal, hi, scenario, amplitude)
            lo_value, _ = read_signal(signal, lo, scenario, amplitude)
            slope = (hi_value - lo_value) / max(hi - lo, 1.0)
            if slope < 0:
                negative_slope_samples += 1
        else:
            slope = math.nan
        update = 0.0
        if (available and pstate == "NORMAL" and not frozen
                and abs(error) > PHASE_DEADBAND_DEG and abs(slope) > 1e-12):
            update = float(np.clip(gain * error * np.sign(slope), -MAX_UPDATE_HZ, MAX_UPDATE_HZ))

        row = {
            "variant": variant, "signal": signal_name, "gain_Hz_per_deg": gain,
            "time_s": t, "duration_s": CONTROL_DT, "action": "CONTROL",
            "state_index": seg["state_index"], "case_id": seg["case_id"],
            "frequency_Hz": frequency, "frequency_MHz": frequency / 1e6,
            "amplitude_command": amplitude, "protection_state": pstate,
            "frequency_frozen": int(frozen or pstate != "NORMAL"),
            "hard_trip_trigger": hard, "soft_limit_trigger": soft,
            "target_signal_deg": target, "signal_deg": value, "signal_error_deg": error,
            "signal_available": int(available),
            "local_dsignal_df_deg_per_Hz": slope, "frequency_update_Hz": update,
            "p_rm_W": power, "p_port_W": float(q["p_port_W"][0]),
            "normalized_port_power_W": float(q["p_port_W"][0]) / max(amplitude * amplitude, 1e-12),
            "zin_real_ohm": float(z_in.real), "zin_imag_ohm": float(z_in.imag),
            "phase_deg": float(q["phase_deg"][0]), "gamma": float(q["gamma"][0]),
            "vport_vpp": float(q["vport_vpp"][0]), "iport_irms_A": float(q["iport_irms_A"][0]),
            "safe_power_capture_ratio": power / max(optimum["power_W"], 1e-30),
            "optimal_safe_frequency_Hz": optimum["frequency_Hz"],
            "frequency_saturated": int(frequency <= F_MIN + 1e-9 or frequency >= F_MAX - 1e-9),
        }

        if scan_hold:
            # Floor the threshold at the controller's own deadband.  Far from
            # resonance the slope collapses and the raw budget falls below the
            # deadband, which would ask for a scan over an error the controller
            # has already decided is too small to act on.  With no noise that
            # never fires, because the target is re-recorded at the acquired
            # frequency and the error sits at zero, but any measurement noise
            # would turn it into scan thrashing.
            closable = (max(MAX_UPDATE_HZ * REACQUIRE_HORIZON_SAMPLES * abs(slope),
                            PHASE_DEADBAND_DEG)
                        if available else math.nan)
            row["closable_error_deg"] = closable
            if reference_kind == "SCAN_CURVE":
                annotations = scan_reference.observe(frequency, row["normalized_port_power_W"])
            else:
                annotations = detector.observe(row, t, allow_trigger=True)
            row.update({k: annotations[k] for k in
                        ("detector_state", "detector_vote_count", "detector_trigger", "detector_reason")})
            if (hard or soft) and not reacquire_pending:
                reacquire_pending = True
                reacquire_reason = "HARD_LIMIT_EVENT" if hard else "SOFT_LIMIT_EVENT"
            elif row["detector_trigger"]:
                reacquire_pending = True
                reacquire_reason = row["detector_reason"] or "DETECTOR_TRIGGER"
            elif use_slew_rule and available and abs(error) > closable:
                reacquire_pending = True
                reacquire_reason = "PHASE_ERROR_NOT_CLOSABLE"
            row["reacquire_request"] = reacquire_reason if reacquire_pending else ""
        else:
            row.update({"detector_state": "NOT_USED", "detector_vote_count": 0,
                        "detector_trigger": 0, "detector_reason": "",
                        "closable_error_deg": math.nan, "reacquire_request": ""})

        rows.append(row)
        frequency = float(np.clip(frequency + update, F_MIN, F_MAX))
        t += CONTROL_DT

    meta = {
        "scan_episodes": scan_episodes,
        "scan_points": scan_points_before,
        "scan_time_s": scan_points_before * SCAN_POINT_DT,
        "negative_slope_samples": negative_slope_samples,
    }
    return rows, meta


def summarize(rows: list[dict], meta: dict, variant: str, gain: float) -> tuple[dict, list[dict]]:
    segments = []
    for seg in SCHEDULE[1:]:
        sr = [r for r in rows if r["state_index"] == seg["state_index"]]
        if not sr:
            continue
        tail = sr[-max(1, int(round(0.20 / CONTROL_DT))):]
        capture = float(np.mean([r["safe_power_capture_ratio"] for r in tail]))
        # Only measurable samples carry a signal error; a tripped drive has none.
        errors = [abs(r["signal_error_deg"]) for r in tail if r["signal_available"]]
        signal_error = float(np.mean(errors)) if errors else math.nan
        unmeasurable = int(sum(not r["signal_available"] for r in tail))
        segments.append({
            "variant": variant, "gain_Hz_per_deg": gain,
            "state_index": seg["state_index"], "case_id": seg["case_id"],
            "steady_power_error_pct": (1.0 - capture) * 100.0,
            "steady_abs_signal_error_deg": signal_error,
            "locked_frequency_MHz": float(np.mean([r["frequency_MHz"] for r in tail])),
            "optimal_frequency_MHz": sr[-1]["optimal_safe_frequency_Hz"] / 1e6,
            "frequency_saturation_ms": sum(r["frequency_saturated"] * CONTROL_DT for r in sr) * 1e3,
            # A wrong lock is a converged signal with lost power.  It is not the
            # only failure: not converging at all loses just as much power and
            # the original flag never fires for it, so both are recorded.
            "tail_unmeasurable_samples": unmeasurable,
            "wrong_lock_flag": int(signal_error <= 0.5 and capture < 0.95),
            "never_converged_flag": int(
                capture < 0.95 and (math.isnan(signal_error) or signal_error > 5.0)),
        })
    summary = {
        "variant": variant, "gain_Hz_per_deg": gain,
        "mean_steady_power_error_pct": float(np.mean([s["steady_power_error_pct"] for s in segments])),
        "mean_abs_signal_error_deg": float(np.nanmean(
            [s["steady_abs_signal_error_deg"] for s in segments])),
        "segments_with_unmeasurable_tail": int(
            sum(s["tail_unmeasurable_samples"] > 0 for s in segments)),
        "segments_at_or_above_95pct": int(sum(s["steady_power_error_pct"] <= 5.0 for s in segments)),
        "segments_evaluated": len(segments),
        "wrong_lock_segments": int(sum(s["wrong_lock_flag"] for s in segments)),
        "never_converged_segments": int(sum(s["never_converged_flag"] for s in segments)),
        "frequency_saturation_ms": float(sum(s["frequency_saturation_ms"] for s in segments)),
        "actual_hard_violations": int(sum(r["vport_vpp"] > 160.0 or r["iport_irms_A"] > 0.006 for r in rows)),
        "negative_slope_samples": meta["negative_slope_samples"],
        "scan_episodes": meta["scan_episodes"],
        "scan_points": meta["scan_points"],
        "scan_time_s": meta["scan_time_s"],
    }
    return summary, segments


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = scenario_map()
    optima = offline_optima(scenarios)

    all_rows: list[dict] = []
    all_segments: list[dict] = []
    summaries: list[dict] = []
    for variant, signal_name, scan_hold, reference_kind, use_slew in VARIANTS:
        for gain in GAINS_HZ_PER_DEG:
            rows, meta = simulate(variant, signal_name, scan_hold, reference_kind,
                                  use_slew, gain, scenarios, optima)
            summary, segments = summarize(rows, meta, variant, gain)
            summaries.append(summary)
            all_segments.extend(segments)
            if gain == SELECTED_GAIN:
                all_rows.extend(rows)

    write_csv(OUT / "phase_hold_gain_sweep_summary.csv", summaries)
    write_csv(OUT / "phase_hold_per_segment_metrics.csv", all_segments)
    write_csv(OUT / "phase_hold_timeline_selected_gain.csv", all_rows)

    # The slew limit is a property of the controller, not of the signal, and it
    # bounds every pure phase variant no matter how good the error signal is.
    slew_hz_per_s = MAX_UPDATE_HZ / CONTROL_DT
    segment_s = SCHEDULE[0]["end_s"] - SCHEDULE[0]["start_s"]

    fig, axes = plt.subplots(2, 1, figsize=(9.0, 5.4), sharex=True)
    for variant, *_ in VARIANTS:
        sel = [r for r in all_rows if r["variant"] == variant]
        axes[0].plot([r["time_s"] for r in sel], [r["frequency_MHz"] for r in sel],
                     color=COLORS[variant], lw=1.0, label=variant)
        axes[1].plot([r["time_s"] for r in sel], [100 * r["safe_power_capture_ratio"] for r in sel],
                     color=COLORS[variant], lw=1.0)
    reference = [r for r in all_rows if r["variant"] == VARIANTS[0][0]]
    axes[0].plot([r["time_s"] for r in reference],
                 [r["optimal_safe_frequency_Hz"] / 1e6 for r in reference],
                 color="#272727", ls=":", lw=0.8, label="constrained optimum")
    axes[0].set_ylabel("Frequency (MHz)")
    axes[1].set_ylabel("Safe power capture (%)")
    axes[1].set_xlabel("Quasi-steady time (s)")
    axes[0].legend(loc="lower left", ncol=2, fontsize=7)
    for ax in axes:
        for seg in SCHEDULE[1:]:
            ax.axvline(seg["start_s"], color="#BBBBBB", lw=0.6)
    fig.suptitle(f"Fourth ablation: de-embedded motional phase, Kphi={SELECTED_GAIN:g} Hz/deg")
    fig.tight_layout()
    for ext, kwargs in (("png", {"dpi": 300}), ("pdf", {}), ("svg", {})):
        fig.savefig(OUT / f"phase_hold_selected_gain.{ext}", bbox_inches="tight", **kwargs)
    plt.close(fig)

    selected = {s["variant"]: s for s in summaries if s["gain_Hz_per_deg"] == SELECTED_GAIN}
    audit = {
        "status": "PASS" if all(s["actual_hard_violations"] == 0 for s in summaries) else "FAIL",
        "model_id": "MODEL_V2_1_HYPOTHETICAL",
        "role": "fourth ablation only; replaces none of the formal three strategies "
                "and does not modify run_phase_ablation.py",
        "variants": {v: {"signal": sig, "scan_acquisition": hold, "reference": ref,
                         "slew_budget_backstop": slew}
                     for v, sig, hold, ref, slew in VARIANTS},
        "signal_definitions": {
            "ARG_ZIN": "arg(Vinput/Isource), positive inductive",
            "MOTIONAL_DEEMBED": "arg(Zm) recovered from Vinput and Isource using the known "
                                "matching network and C0; never reads Rm, Lm or Cm",
        },
        "network_zero_Hz": "1/(2*pi*sqrt(L*(C0+Cmatch))) = 903950 Hz, fixed by the matching "
                           "network and C0, so it does not follow the transducer resonance",
        "control_law": "df=clip(Kphi*(target-signal)*sign(dsignal/df),+-%g Hz)" % MAX_UPDATE_HZ,
        "slew_limit_Hz_per_s": slew_hz_per_s,
        "max_frequency_travel_per_segment_kHz": slew_hz_per_s * segment_s / 1e3,
        "slew_limit_note": "A pure phase controller cannot cross more than this per segment "
                           "whatever the gain or the signal, because the clip binds before the "
                           "gain does.  This is why the scan-then-hold variant differs.",
        "selected_gain_Hz_per_deg": SELECTED_GAIN,
        "selected_summary": selected,
        "scope": "quasi-steady hypothetical electrical model; no sensor noise, measured data, "
                 "acoustic, thermal or hardware timing claim",
    }
    (OUT / "phase_hold_ablation_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
