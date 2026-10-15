"""Prototype and verification for the three scan/phase fixes proposed in the review.

This is a PROPOSAL, not a change to the frozen platform.  It imports the active
v2.1 model read-only and reimplements the scan and phase logic beside it, so the
committed results under ``workspace/`` are untouched and remain comparable.

Four parts:

1. Edge-aware three-level scan.  The current ``local_scan`` returns the argmax of
   each level without checking whether that argmax sits on the window edge.  When
   the true peak is outside the window every level pins to its left edge and the
   scan silently returns 844.0 kHz.  The fix re-centres on the edge and rescans,
   stops at the band limit, and reports a converged flag.

2. Probe amplitude routed through the protection limiter instead of being passed
   straight to the measurement.

3. De-embedding the motional branch from quantities a driver can actually
   measure, namely input voltage and source current, given the known matching
   network and C0.

4. Why the motional phase is a better error signal than arg(Zin): it is strictly
   monotone in frequency, so it has exactly one zero and cannot lock to the wrong
   point, whereas arg(Zin) acquires an extra zero owned by the matching network.

Run from the repository root:

    python3 review/proposed_fixes_prototype.py

No value here is a measured device parameter or a safety rating.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
ACTIVE = REPO / "workspace" / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5"
sys.path.insert(0, str(ACTIVE))

import model_v2_1 as M  # noqa: E402

COARSE_SPAN_HZ, COARSE_STEP_HZ = 50e3, 5e3
FINE_SPAN_HZ, FINE_STEP_HZ = 5e3, 1e3
ULTRA_SPAN_HZ, ULTRA_STEP_HZ = 1e3, 0.1e3
PROBE_AMPLITUDE = 0.40
SCAN_POINT_DT = 1.5e-3
MAX_RECENTRES = 3
EDGE_TOL_HZ = 1.0

FINE_REFERENCE = np.arange(M.F_MIN, M.F_MAX + 0.1, 100.0)


# --------------------------------------------------------------------------- 1
def probe_power(frequency_hz: float, scenario, amplitude: float = PROBE_AMPLITUDE) -> float:
    q = M.response(frequency_hz, scenario, amplitude)
    return float(q["p_port_W"][0]) / (amplitude ** 2)


def sweep_level(center: float, span: float, step: float, scenario) -> tuple[float, bool, int]:
    """Return (argmax frequency, argmax sits on a non-band window edge, point count)."""
    lo, hi = max(M.F_MIN, center - span), min(M.F_MAX, center + span)
    grid = np.arange(lo, hi + 1, step)
    powers = np.array([probe_power(float(f), scenario) for f in grid])
    i = int(np.argmax(powers))
    on_edge = i in (0, len(grid) - 1)
    # Hitting the band limit is not a failure, there is nowhere further to look.
    at_band_limit = (
        (i == 0 and abs(grid[0] - M.F_MIN) < EDGE_TOL_HZ)
        or (i == len(grid) - 1 and abs(grid[-1] - M.F_MAX) < EDGE_TOL_HZ)
    )
    return float(grid[i]), bool(on_edge and not at_band_limit), len(grid)


def scan_current(start_hz: float, scenario) -> dict:
    """The scan as committed: three levels, argmax each time, no edge check."""
    points = 0
    best, _, n = sweep_level(start_hz, COARSE_SPAN_HZ, COARSE_STEP_HZ, scenario)
    points += n
    coarse = best
    best, _, n = sweep_level(best, FINE_SPAN_HZ, FINE_STEP_HZ, scenario)
    points += n
    best, _, n = sweep_level(best, ULTRA_SPAN_HZ, ULTRA_STEP_HZ, scenario)
    points += n
    return {"frequency_Hz": best, "coarse_Hz": coarse, "points": points,
            "converged": None, "recentres": 0}


def scan_edge_aware(start_hz: float, scenario) -> dict:
    """Proposed scan: re-centre the coarse level whenever its argmax is on an edge."""
    points = 0
    center = start_hz
    recentres = 0
    while True:
        best, on_edge, n = sweep_level(center, COARSE_SPAN_HZ, COARSE_STEP_HZ, scenario)
        points += n
        if not on_edge or recentres >= MAX_RECENTRES:
            break
        center = best
        recentres += 1
    coarse = best
    converged = not on_edge

    best, fine_edge, n = sweep_level(best, FINE_SPAN_HZ, FINE_STEP_HZ, scenario)
    points += n
    best, ultra_edge, n = sweep_level(best, ULTRA_SPAN_HZ, ULTRA_STEP_HZ, scenario)
    points += n
    return {"frequency_Hz": best, "coarse_Hz": coarse, "points": points,
            "converged": converged and not fine_edge and not ultra_edge,
            "recentres": recentres}


# --------------------------------------------------------------------------- 3
def deembed_motional_phase(frequency_hz: float, scenario, amplitude: float) -> float:
    """Recover arg(Zm) from input voltage and source current only.

    A real driver measures v_input and i_source at the amplifier terminals.  The
    matching inductor, its ESR, the matching capacitor, its ESR and C0 are design
    values the driver already knows, so the motional branch can be peeled off
    analytically.  Nothing here reads Rm, Lm or Cm.
    """
    q = M.response(frequency_hz, scenario, amplitude)
    v_input = complex(q["v_input"][0])
    i_source = complex(q["i_source"][0])

    w = 2 * math.pi * frequency_hz
    m = scenario.matching
    r_l = 2 * math.pi * M.F0 * m.l_h / m.ql
    r_c = 1 / (2 * math.pi * M.F0 * m.c_f * m.qc)
    z_c_match = r_c + 1 / (1j * w * m.c_f)

    z_in = v_input / i_source
    z_parallel = z_in - r_l - 1j * w * m.l_h
    v_port = i_source * z_parallel
    i_port = i_source - v_port / z_c_match
    i_motional = i_port - 1j * w * scenario.bvd.c0 * v_port
    return float(np.angle(v_port / i_motional, deg=True))


def main() -> int:
    scenarios = M.all_scenarios()

    print("=" * 80)
    print("1. Edge-aware scan vs the committed scan, all 34 registered scenarios")
    print("=" * 80)
    print(f"  {'case':<22}{'peak_kHz':>10}{'now_kHz':>9}{'now%':>8}{'new_kHz':>9}{'new%':>8}{'pts':>5}{'conv':>6}")
    worse = []
    fixed = []
    for scenario in scenarios:
        power = M.safe_power(FINE_REFERENCE, scenario)
        i = int(np.argmax(power))
        old = scan_current(M.F0, scenario)
        new = scan_edge_aware(M.F0, scenario)
        cap_old = 100.0 * float(M.safe_power(old["frequency_Hz"], scenario)[0]) / float(power[i])
        cap_new = 100.0 * float(M.safe_power(new["frequency_Hz"], scenario)[0]) / float(power[i])
        if cap_new < cap_old - 1e-6:
            worse.append(scenario.case_id)
        if cap_old < 95.0 <= cap_new:
            fixed.append(scenario.case_id)
        print(f"  {scenario.case_id:<22}{FINE_REFERENCE[i] / 1e3:>10.2f}"
              f"{old['frequency_Hz'] / 1e3:>9.2f}{cap_old:>8.2f}"
              f"{new['frequency_Hz'] / 1e3:>9.2f}{cap_new:>8.2f}"
              f"{new['points']:>5d}{str(new['converged']):>6}")
    print()
    print(f"  fixed by the change: {fixed}")
    print(f"  made worse by the change: {worse if worse else 'none'}")

    print()
    print("=" * 80)
    print("2. Search reach after the fix")
    print("=" * 80)
    print(f"  {'fs shift':>9}{'peak_kHz':>10}{'now_kHz':>9}{'now%':>8}{'new_kHz':>9}{'new%':>8}{'pts':>5}{'ms':>7}{'conv':>6}")
    for pct in (5.0, 6.5, 7.0, 8.0, 10.0, 11.0, 12.0):
        drifted = M.shifted_fs(M.BASE_BVD, 1 - pct / 100)
        scenario = M.Scenario(f"FS_{pct}", "audit", "fs", f"-{pct}%", "probe",
                              drifted, M.BASE_MATCH, M.BASE_RS)
        power = M.safe_power(FINE_REFERENCE, scenario)
        i = int(np.argmax(power))
        old = scan_current(M.F0, scenario)
        new = scan_edge_aware(M.F0, scenario)
        cap_old = 100.0 * float(M.safe_power(old["frequency_Hz"], scenario)[0]) / float(power[i])
        cap_new = 100.0 * float(M.safe_power(new["frequency_Hz"], scenario)[0]) / float(power[i])
        print(f"  {-pct:>8.1f}%{FINE_REFERENCE[i] / 1e3:>10.2f}"
              f"{old['frequency_Hz'] / 1e3:>9.2f}{cap_old:>8.2f}"
              f"{new['frequency_Hz'] / 1e3:>9.2f}{cap_new:>8.2f}"
              f"{new['points']:>5d}{new['points'] * SCAN_POINT_DT * 1e3:>7.1f}{str(new['converged']):>6}")
    print("  The converged flag is the point: a failed acquisition is now visible to the controller.")

    print()
    print("=" * 80)
    print("3. Probe amplitude through the protection limiter")
    print("=" * 80)
    worst_ratio = 0.0
    clipped = 0
    total = 0
    for scenario in scenarios:
        grid = np.arange(M.F_MIN, M.F_MAX + 0.1, 100.0)
        allowed = M.allowed_amplitude(grid, scenario, use_soft_limits=True)
        applied = np.minimum(PROBE_AMPLITUDE, allowed)
        clipped += int(np.sum(applied < PROBE_AMPLITUDE - 1e-12))
        total += applied.size
        worst_ratio = max(worst_ratio, float(np.max(PROBE_AMPLITUDE / allowed)))
    print(f"  probe {PROBE_AMPLITUDE} against the soft limiter over all scenarios and the whole band:")
    print(f"    points where the limiter would clip the probe: {clipped} of {total}")
    print(f"    worst probe-to-allowed ratio: {worst_ratio:.4f}")
    print("  So routing the probe through Protection.apply is a no-op on today's registry.")
    print("  It is worth doing anyway: it turns a margin into an enforced invariant, and the")
    print("  plan's week-3 text already requires every scan sample to pass the same chain.")

    print()
    print("=" * 80)
    print("4. Motional phase as the error signal: uniqueness and monotonicity")
    print("=" * 80)
    grid = np.arange(M.F_MIN, M.F_MAX + 0.1, 10.0)

    def count_zeros(values: np.ndarray) -> int:
        """Sign changes plus exact zeros.

        Counting ``diff(sign(x)) != 0`` double-counts a sample that lands exactly
        on zero, because the sign walks -1, 0, +1 and produces two transitions.
        """
        return int(np.sum(values[:-1] * values[1:] < 0) + np.sum(values == 0.0))

    print(f"  {'case':<22}{'argZin zeros':>13}{'argZm zeros':>12}{'argZm monotone':>16}{'deembed err':>13}")
    non_monotone = []
    for scenario in scenarios:
        q = M.response(grid, scenario, 1.0)
        zin_zeros = count_zeros(q["phase_deg"])
        phase_m = np.angle(q["z_m"], deg=True)
        zm_zeros = count_zeros(phase_m)
        monotone = bool(np.all(np.diff(phase_m) > 0))
        if not monotone:
            non_monotone.append(scenario.case_id)
        check_f = float(grid[len(grid) // 2])
        err = abs(deembed_motional_phase(check_f, scenario, 0.4)
                  - float(np.angle(complex(M.response(check_f, scenario, 0.4)["z_m"][0]), deg=True)))
        print(f"  {scenario.case_id:<22}{zin_zeros:>13d}{zm_zeros:>12d}{str(monotone):>16}{err:>13.2e}")
    print()
    print(f"  scenarios where the motional phase is NOT monotone in frequency: "
          f"{non_monotone if non_monotone else 'none'}")

    # Cross-tabulate the zero count against whether arg(Zin) tracking actually works.
    agree = 0
    for scenario in scenarios:
        power = M.safe_power(grid, scenario)
        i = int(np.argmax(power))
        phase = M.response(grid, scenario, 1.0)["phase_deg"]
        crossings = np.where(phase[:-1] * phase[1:] < 0)[0]
        capture = (100.0 * float(power[int(crossings[int(np.argmin(np.abs(crossings - i)))])])
                   / float(power[i])) if crossings.size else math.nan
        zeros = count_zeros(phase)
        works = capture >= 95.0
        if (zeros >= 3) == works:
            agree += 1
    print(f"  cross-check: 'arg(Zin) has 3 zeros' predicts 'arg(Zin) tracking reaches 95% capture'")
    print(f"  in {agree} of {len(scenarios)} scenarios.  The three-zero case keeps the transducer's")
    print("  own pair of crossings inside the band; the one-zero case has only the network zero left,")
    print("  and that is the one the controller locks to.  The zero count is therefore a cheap")
    print("  online self-check: count the crossings during the acquisition sweep, and if only one")
    print("  is left, do not hand the frequency to a phase controller.")
    print("  A strictly monotone error signal with exactly one zero cannot lock to a wrong point.")
    print("  arg(Zin) carries an extra zero owned by L against C0+Cmatch, which is what attracts")
    print("  the controller to ~904 kHz once the transducer resonance moves away.")
    print()
    print("  Proposed division of labour:")
    print("    acquisition  -> edge-aware power scan, which finds the true constrained maximum")
    print("    holding      -> motional phase driven to the value recorded at that maximum,")
    print("                    which is uniquely reachable because the signal is monotone")
    print("    re-acquire   -> on the existing observable 2-of-4 detector, or on a failed converged flag")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
