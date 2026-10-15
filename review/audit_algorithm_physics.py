"""Read-only audit of the active v2.1 model, the three-level scan and the phase strategy.

This script imports the frozen active model and recomputes derived quantities.
It writes nothing into ``workspace/`` and overwrites no historical result; the
only output is stdout plus an optional JSON summary under ``review/``.

Run from the repository root:

    python3 review/audit_algorithm_physics.py
    python3 review/audit_algorithm_physics.py --json review/audit_result.json

Every number printed here is derived from the committed model parameters.  No
value is a measured device parameter and none of it is a safety rating.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
ACTIVE = REPO / "workspace" / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5"
sys.path.insert(0, str(ACTIVE))

import model_v2_1 as M  # noqa: E402

# Scan geometry copied from run_stage4_5_control.local_scan so the audit does not
# import matplotlib.  Keep these in sync with that module if the scan changes.
COARSE_SPAN_HZ = 50e3
COARSE_STEP_HZ = 5e3
FINE_SPAN_HZ = 5e3
FINE_STEP_HZ = 1e3
ULTRA_SPAN_HZ = 1e3
ULTRA_STEP_HZ = 0.1e3
PROBE_AMPLITUDE = 0.40
SCAN_POINT_DT = 1.5e-3

# Schedule used by the stage 4/5 closed-loop comparison.
CLOSED_LOOP_SCHEDULE = [
    "CASE_000_BASELINE", "CASE_C0_P30", "CASE_RM_P50", "CASE_FS_M5",
    "CASE_LMATCH_P10", "CASE_QL_20", "CASE_COMBINED_HIGH",
]

FINE_REFERENCE = np.arange(M.F_MIN, M.F_MAX + 0.1, 100.0)
# Phase zero crossings are located on a finer grid than the 100 Hz reference
# grid, because a 100 Hz grid quantises the crossing enough to change the
# reported capture ratio on the steepest scenarios.
PHASE_GRID = np.arange(M.F_MIN, M.F_MAX + 0.1, 10.0)


def probe_power(frequency_hz: float, scenario) -> float:
    """Amplitude-normalised observable port power, exactly the scan objective."""
    q = M.response(frequency_hz, scenario, PROBE_AMPLITUDE)
    return float(q["p_port_W"][0]) / (PROBE_AMPLITUDE ** 2)


def three_level_scan(start_hz: float, scenario) -> tuple[float, float, int]:
    """Replay the coarse/fine/ultrafine scan.  Returns (result, coarse best, points)."""
    points = 0

    def best_over(lo: float, hi: float, step: float) -> tuple[float, int]:
        grid = np.arange(max(M.F_MIN, lo), min(M.F_MAX, hi) + 1, step)
        return max((probe_power(float(f), scenario), float(f)) for f in grid)[1], len(grid)

    coarse, n = best_over(start_hz - COARSE_SPAN_HZ, start_hz + COARSE_SPAN_HZ, COARSE_STEP_HZ)
    points += n
    fine, n = best_over(coarse - FINE_SPAN_HZ, coarse + FINE_SPAN_HZ, FINE_STEP_HZ)
    points += n
    ultra, n = best_over(fine - ULTRA_SPAN_HZ, fine + ULTRA_SPAN_HZ, ULTRA_STEP_HZ)
    points += n
    return ultra, coarse, points


def nearest_phase_zero_capture(phase_deg: np.ndarray, power: np.ndarray, peak_index: int) -> float:
    """Capture ratio at the phase zero crossing closest to the true power peak."""
    sign = np.sign(phase_deg)
    crossings = np.where(np.diff(sign) != 0)[0]
    if crossings.size == 0:
        return math.nan
    j = int(crossings[int(np.argmin(np.abs(crossings - peak_index)))])
    return 100.0 * float(power[j]) / float(power[peak_index])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write a JSON summary here")
    args = parser.parse_args()

    bvd, match = M.BASE_BVD, M.BASE_MATCH
    scenarios = M.all_scenarios()
    summary: dict = {"scope": "read-only recomputation of committed hypothetical model"}

    # ---------------------------------------------------------------- baseline
    print("=" * 78)
    print("1. Baseline self-consistency (hypothetical parameters, not measured)")
    print("=" * 78)
    tau_amp_s = 2 * bvd.qm / (2 * math.pi * bvd.fs)
    f_parallel = bvd.fs * math.sqrt(1 + bvd.cm / bvd.c0)
    k_eff_sq = bvd.cm / (bvd.c0 + bvd.cm)
    baseline = scenarios[0]
    peak = M.safe_power(FINE_REFERENCE, baseline)
    peak_i = int(np.argmax(peak))
    point = M.point_metrics(float(FINE_REFERENCE[peak_i]), baseline)
    print(f"  Rm = {bvd.rm:.4f} ohm,  C0 = {bvd.c0 * 1e12:.4f} pF,  Lm = {bvd.lm:.6f} H,"
          f"  Cm = {bvd.cm * 1e12:.6f} pF")
    print(f"  Qm = {bvd.qm:.1f},  fs = {bvd.fs / 1e6:.4f} MHz,  source = {M.SOURCE_A1_VRMS:.6f} Vrms")
    print(f"  match L = {match.l_h * 1e6:.4f} uH,  C = {match.c_f * 1e12:.4f} pF,"
          f"  QL = {match.ql:g},  QC = {match.qc:g}")
    print(f"  peak safe P_Rm  = {peak[peak_i] * 1e3:.4f} mW at {FINE_REFERENCE[peak_i] / 1e3:.2f} kHz")
    print(f"  Vpp = {point['vport_vpp']:.3f},  Irms = {point['iport_irms_A'] * 1e3:.4f} mA,"
          f"  arg(Zin) = {point['phase_deg']:.3f} deg,  |Gamma| = {point['gamma']:.4f}")
    print(f"  power balance residual = {point['p_source_W'] - (point['p_rs_W'] + point['p_rm_W'] + point['p_l_esr_W'] + point['p_c_esr_W']):.3e} W")
    print()
    print(f"  amplitude time constant 2Qm/w = {tau_amp_s * 1e6:.1f} us")
    print(f"  scan dwell {SCAN_POINT_DT * 1e3:.1f} ms = {SCAN_POINT_DT / tau_amp_s:.1f} tau  (quasi-steady assumption)")
    print(f"  fp - fs = {f_parallel - bvd.fs:.1f} Hz  ({100 * (f_parallel - bvd.fs) / bvd.fs:.3f} % of fs)")
    print(f"  Cm/C0 = {bvd.cm / bvd.c0:.6f}  ->  k_eff = {math.sqrt(k_eff_sq):.4f}")
    summary["baseline"] = {
        "peak_safe_power_mW": float(peak[peak_i] * 1e3),
        "peak_frequency_Hz": float(FINE_REFERENCE[peak_i]),
        "tau_amplitude_us": tau_amp_s * 1e6,
        "scan_dwell_in_tau": SCAN_POINT_DT / tau_amp_s,
        "fp_minus_fs_Hz": f_parallel - bvd.fs,
        "k_eff": math.sqrt(k_eff_sq),
    }

    # ------------------------------------------------------- per-scenario table
    print()
    print("=" * 78)
    print("2. Per-scenario resonance width, three-level scan capture, phase-zero capture")
    print("=" * 78)
    print(f"  {'case':<22}{'peak_kHz':>10}{'FWHM_Hz':>9}{'scan_kHz':>10}{'scan%':>8}{'argZin%':>9}{'argZm%':>8}")
    rows = []
    for scenario in scenarios:
        power = M.safe_power(FINE_REFERENCE, scenario)
        i = int(np.argmax(power))
        width, status, _, _ = M.half_power_width(FINE_REFERENCE, power)
        found, coarse, _ = three_level_scan(M.F0, scenario)
        capture = 100.0 * float(M.safe_power(found, scenario)[0]) / float(power[i])
        power_pg = M.safe_power(PHASE_GRID, scenario)
        i_pg = int(np.argmax(power_pg))
        q = M.response(PHASE_GRID, scenario, 1.0)
        cap_zin = nearest_phase_zero_capture(q["phase_deg"], power_pg, i_pg)
        cap_zm = nearest_phase_zero_capture(np.angle(q["z_m"], deg=True), power_pg, i_pg)
        rows.append({
            "case_id": scenario.case_id,
            "peak_frequency_Hz": float(FINE_REFERENCE[i]),
            "fwhm_Hz": float(width), "fwhm_status": status,
            "scan_result_Hz": found, "coarse_best_Hz": coarse,
            "scan_capture_pct": capture,
            "phase_zin_capture_pct": cap_zin,
            "phase_zmotional_capture_pct": cap_zm,
            "in_closed_loop_schedule": scenario.case_id in CLOSED_LOOP_SCHEDULE,
        })
        print(f"  {scenario.case_id:<22}{FINE_REFERENCE[i] / 1e3:>10.2f}{width:>9.0f}"
              f"{found / 1e3:>10.2f}{capture:>8.2f}{cap_zin:>9.2f}{cap_zm:>8.2f}")
    summary["scenarios"] = rows

    widths = [r["fwhm_Hz"] for r in rows]
    scan_fail = [r for r in rows if r["scan_capture_pct"] < 95.0]
    zin_fail = [r for r in rows if not (r["phase_zin_capture_pct"] >= 95.0)]
    zm_ok = [r for r in rows if r["phase_zmotional_capture_pct"] >= 95.0]
    print()
    print(f"  FWHM range over {len(rows)} scenarios: {min(widths):.0f} - {max(widths):.0f} Hz"
          f"   (fine scan step is {FINE_STEP_HZ:.0f} Hz)")
    print(f"  three-level scan below 95% capture: {[r['case_id'] for r in scan_fail]}")
    print(f"  of those, inside the stage 4/5 closed-loop schedule: "
          f"{[r['case_id'] for r in scan_fail if r['in_closed_loop_schedule']]}")
    print(f"  arg(Zin)=target reaches >=95% capture in {len(rows) - len(zin_fail)}/{len(rows)} scenarios")
    print(f"  motional-branch phase reaches >=95% capture in {len(zm_ok)}/{len(rows)} scenarios")

    # ------------------------------------------------------ scan reach cliff
    print()
    print("=" * 78)
    print("3. How far the single three-level scan reaches from a 0.9 MHz start")
    print("=" * 78)
    print(f"  {'fs shift':>10}{'fs_kHz':>10}{'found_kHz':>11}{'capture%':>10}")
    reach = []
    for pct in (3.0, 5.0, 6.0, 6.5, 6.7, 7.0, 8.0, 10.0):
        drifted = M.shifted_fs(M.BASE_BVD, 1 - pct / 100)
        scenario = M.Scenario(f"FS_DRIFT_{pct}", "audit", "fs", f"-{pct}%", "audit probe",
                              drifted, M.BASE_MATCH, M.BASE_RS)
        power = M.safe_power(FINE_REFERENCE, scenario)
        found, _, _ = three_level_scan(M.F0, scenario)
        capture = 100.0 * float(M.safe_power(found, scenario)[0]) / float(power.max())
        reach.append({"fs_shift_pct": -pct, "found_Hz": found, "capture_pct": capture})
        print(f"  {-pct:>9.1f}%{drifted.fs / 1e3:>10.1f}{found / 1e3:>11.1f}{capture:>10.2f}")
    print("  The scan reports a frequency with no failure flag even when capture collapses.")
    summary["scan_reach"] = reach

    # ---------------------------------------------------- amplitude headroom
    print()
    print("=" * 78)
    print("4. Amplitude limiter behaviour")
    print("=" * 78)
    at_optimum = []
    worst_soft = []
    for scenario in scenarios:
        power = M.safe_power(FINE_REFERENCE, scenario)
        i = int(np.argmax(power))
        at_optimum.append(float(M.allowed_amplitude(FINE_REFERENCE[i], scenario, use_soft_limits=True)[0]))
        a_band = M.allowed_amplitude(FINE_REFERENCE, scenario, use_soft_limits=True)
        worst_soft.append(float(a_band.min()))
    unit = M.response(FINE_REFERENCE, baseline, 1.0)
    j = int(np.argmax(unit["vport_vpp"]))
    probe_v = max(float(M.response(FINE_REFERENCE, s, PROBE_AMPLITUDE)["vport_vpp"].max()) for s in scenarios)
    probe_i = max(float(M.response(FINE_REFERENCE, s, PROBE_AMPLITUDE)["iport_irms_A"].max()) for s in scenarios)
    print(f"  allowed amplitude at each scenario optimum: min {min(at_optimum):.6f}, max {max(at_optimum):.6f}")
    print(f"  -> the {M.VPP_SOFT:.0f} Vpp / {M.IRMS_SOFT * 1e3:.1f} mA soft limits never bind at any registered optimum")
    print(f"  worst in-band allowed amplitude across scenarios: {min(worst_soft):.4f}")
    print(f"  baseline at a=1 peaks at {unit['vport_vpp'][j]:.2f} Vpp near {FINE_REFERENCE[j] / 1e3:.1f} kHz"
          f"  (hard limit {M.VPP_HARD:.0f} Vpp) -> protection does matter off resonance")
    print(f"  scan probe a={PROBE_AMPLITUDE}: worst-case {probe_v:.2f} Vpp and {probe_i * 1e3:.4f} mA")
    print("  -> probe points stay inside the limits by margin, but local_scan never routes them"
          " through Protection.apply")
    summary["amplitude"] = {
        "allowed_at_optimum_min": min(at_optimum),
        "allowed_at_optimum_max": max(at_optimum),
        "worst_in_band_allowed": min(worst_soft),
        "baseline_unit_peak_vpp": float(unit["vport_vpp"][j]),
        "probe_worst_vpp": probe_v,
        "probe_worst_irms_A": probe_i,
    }

    # ---------------------------------------------------------- Qm family
    print()
    print("=" * 78)
    print("5. Qm family only changes bandwidth, never peak power")
    print("=" * 78)
    for case_id in ("CASE_QM_500", "CASE_QM_800", "CASE_QM_1000"):
        scenario = M.scenario_map()[case_id]
        power = M.safe_power(FINE_REFERENCE, scenario)
        width, _, _, _ = M.half_power_width(FINE_REFERENCE, power)
        print(f"  {case_id:<16} peak {power.max() * 1e3:.6f} mW   FWHM {width:.0f} Hz")
    print("  bvd_from_fs_qm holds Rm and fs, so z_m(ws) = Rm for every Qm.")
    print("  Radiation loading changes Rm and Qm together, so this family is not a load scan.")

    # ------------------------------------------------- literature comparison
    print()
    print("=" * 78)
    print("6. Comparison with the two reference papers")
    print("=" * 78)

    def bvd_figures(rm: float, lm: float, cm: float, c0: float) -> dict:
        fs = 1 / (2 * math.pi * math.sqrt(lm * cm))
        return {
            "fs_Hz": fs,
            "Qm": 2 * math.pi * fs * lm / rm,
            "cm_over_c0": cm / c0,
            "k_eff": math.sqrt(cm / (cm + c0)),
            "fp_minus_fs_pct": 100 * (math.sqrt(1 + cm / c0) - 1),
            "c0_F": c0,
        }

    # Janu et al., Ultrasonics 112 (2021) 106341, 40 kHz air-coupled transmitter.
    # Two sets appear in the paper: the linearised initial condition, and the
    # final iterated result.  The final result is the paper's answer.
    catalogue = {
        "Janu 2021 initial": bvd_figures(908.0, 0.0915, 1.7634e-10, 2.8048e-9),
        "Janu 2021 FINAL": bvd_figures(1330.0, 0.2300, 6.9000e-11, 2.2700e-9),
        "project v2.1": bvd_figures(bvd.rm, bvd.lm, bvd.cm, bvd.c0),
    }
    print(f"  {'source':<22}{'fs_kHz':>9}{'Qm':>8}{'Cm/C0':>10}{'k_eff':>8}{'fp-fs %':>9}{'C0':>12}")
    for name, fig in catalogue.items():
        c0_text = f"{fig['c0_F'] * 1e12:.2f} pF" if fig["c0_F"] < 1e-9 else f"{fig['c0_F'] * 1e9:.3f} nF"
        print(f"  {name:<22}{fig['fs_Hz'] / 1e3:>9.2f}{fig['Qm']:>8.1f}{fig['cm_over_c0']:>10.5f}"
              f"{fig['k_eff']:>8.4f}{fig['fp_minus_fs_pct']:>9.3f}{c0_text:>12}")
    summary["literature_bvd"] = catalogue

    # Liu, Wright, Hynynen, Goertz: forward-looking CTO catheter.  The paper
    # states the geometry and the pulsing, not C0, so C0 below is this audit's
    # own coaxial-capacitance estimate and is explicitly a speculation.
    outer_m, inner_m, length_m = 1.35e-3, 0.73e-3, 2.5e-3
    pulse_s, prf_hz, f_drive = 0.1e-3, 909.0, 1.85e6
    duty = pulse_s * prf_hz
    print()
    print("  Liu/Goertz forward-looking CTO catheter (values stated in the paper):")
    print(f"    PZT-5H hollow cylinder OD/ID {outer_m * 1e3:.2f}/{inner_m * 1e3:.2f} mm,"
          f" length {length_m * 1e3:.1f} mm, air backed + lambda/4 epoxy")
    print(f"    drive {f_drive / 1e6:.2f} MHz (3rd length-mode harmonic); other modes at 550 and 1095 kHz")
    print(f"    10-300 Vpp sweep, L-C matched to 50 ohm (+-3) and 0 deg (+-5)")
    print(f"    {pulse_s * 1e3:.1f} ms pulses at PRF {prf_hz:.0f} Hz -> duty {duty * 100:.2f} %")
    print("  [SPECULATIVE] audit's own order-of-magnitude estimates from that geometry:")
    for label, eps_r in (("free eps33T/eps0=3400", 3400.0), ("clamped eps33S/eps0=1470", 1470.0)):
        c0_est = 2 * math.pi * 8.854e-12 * eps_r * length_m / math.log(outer_m / inner_m)
        print(f"    {label:<28} C0 ~ {c0_est * 1e12:6.0f} pF,"
              f"  |1/wC0| at {f_drive / 1e6:.2f} MHz ~ {1 / (2 * math.pi * f_drive * c0_est):5.0f} ohm,"
              f"  ratio to project C0 = {c0_est / bvd.c0:.0f}x")
    area_m2 = math.pi / 4 * (outer_m ** 2 - inner_m ** 2)
    intensity = (2.5e6 ** 2) / (2 * 1.5e6)
    print(f"    face annulus area {area_m2 * 1e6:.3f} mm2; 2.5 MPa peak negative -> I ~ {intensity / 1e4:.0f} W/cm2")
    print(f"    -> pulse-time acoustic power ~ {intensity * area_m2:.2f} W,"
          f" duty-averaged ~ {intensity * area_m2 * duty * 1e3:.0f} mW"
          f"  (project P_Rm = {peak[peak_i] * 1e3:.0f} mW)")
    rise = 1 - math.exp(-pulse_s / tau_amp_s)
    print(f"    a {pulse_s * 1e3:.1f} ms pulse on a Qm={bvd.qm:.0f} resonator (tau={tau_amp_s * 1e6:.0f} us)"
          f" reaches only {rise * 100:.0f} % of steady amplitude")
    summary["catheter_reference"] = {
        "duty_fraction": duty,
        "pulse_amplitude_fraction_at_project_Qm": rise,
        "speculative": True,
    }

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON summary written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
