"""Why the observable detector goes blind while the controller retunes, and what fixes it.

Read-only.  Imports the frozen active model, writes nothing into workspace/.

The problem, found while building the fourth ablation: the observable disturbance
detector builds its reference from ten consecutive samples at ONE frequency and
clears the buffer whenever the frequency moves.  A phase controller chasing a
large error moves every control tick, so the reference never completes and the
detector can never fire.  It works while the controller is settled, which is when
it is least needed.  Pure scanning and P&O never show this because their
frequency is constant between updates.

Three candidate fixes are measured here.

1.  Two-point parameter estimation.  De-embed Zm at two frequencies the
    controller visits anyway and solve Im(Zm) = w*Lm - 1/(w*Cm) for Lm and Cm,
    hence fs.  Exact without noise, and it recovers a resonance 78 kHz away from
    the observation point.  The question is whether it survives noise.

2.  Model-referenced residual, the standard answer in the fault-detection
    literature: compare the measurement against what the last identified plant
    predicts AT THE CURRENT FREQUENCY, instead of against a stored measurement
    taken at some earlier frequency.  The reference then moves with the
    controller, so the controller's own retuning cancels out of the residual.

3.  Identifying the plant from the scan grid rather than from the controller's
    own small steps, which decides how good the reference in 2 can be.

Run:

    python3 review/detector_retuning_study.py
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

RNG = np.random.default_rng(20260917)
CONTROL_STEP_HZ = 500.0      # the phase controller's per-tick clip


def edge_aware_scan_grid(scenario, start_hz: float = M.F0) -> np.ndarray:
    """The frequencies the edge-aware scan actually visits for this plant.

    Identification can only use points the scan visited, so the grid has to be
    the real one.  Using the pre-fix grid on CASE_LM_P20 would ask the fit to
    identify a resonance at 821.4 kHz from measurements that stop at 844 kHz,
    which is not an identification failure but a sampling one.
    """
    def sweep(center: float, span: float, step: float) -> tuple[np.ndarray, float, bool]:
        lo, hi = max(M.F_MIN, center - span), min(M.F_MAX, center + span)
        grid = np.arange(lo, hi + 1, step)
        powers = np.array([normalised_port_power(float(f), scenario, 0.40) for f in grid])
        index = int(np.argmax(powers))
        at_band = ((index == 0 and abs(grid[0] - M.F_MIN) < 1.0)
                   or (index == len(grid) - 1 and abs(grid[-1] - M.F_MAX) < 1.0))
        return grid, float(grid[index]), index in (0, len(grid) - 1) and not at_band

    visited: list[np.ndarray] = []
    center, recentres = start_hz, 0
    while True:
        grid, best, on_edge = sweep(center, 50e3, 5e3)
        visited.append(grid)
        if not on_edge or recentres >= 3:
            break
        center, recentres = best, recentres + 1
    grid, best, _ = sweep(best, 5e3, 1e3)
    visited.append(grid)
    grid, best, _ = sweep(best, 1e3, 0.1e3)
    visited.append(grid)
    return np.unique(np.concatenate(visited))


def deembed_zm(frequency_hz: float, scenario, amplitude: float = 1.0) -> complex:
    """arg and magnitude of the motional branch, from input voltage and source current."""
    q = M.response(np.array([frequency_hz]), scenario, amplitude)
    v_input = complex(q["v_input"][0])
    i_source = complex(q["i_source"][0])
    w = 2 * math.pi * frequency_hz
    m = scenario.matching
    r_l = 2 * math.pi * M.F0 * m.l_h / m.ql
    r_c = 1 / (2 * math.pi * M.F0 * m.c_f * m.qc)
    z_c_match = r_c + 1 / (1j * w * m.c_f)
    z_parallel = v_input / i_source - r_l - 1j * w * m.l_h
    v_port = i_source * z_parallel
    i_port = i_source - v_port / z_c_match
    i_motional = i_port - 1j * w * scenario.bvd.c0 * v_port
    return v_port / i_motional


def normalised_port_power(frequency_hz: float, scenario, amplitude: float = 1.0) -> float:
    return float(M.response(np.array([frequency_hz]), scenario, amplitude)["p_port_W"][0]) / amplitude ** 2


def scenario_with_bvd(template, rm: float, lm: float, cm: float):
    """A scenario carrying the template's C0, matching network and Rs, with a new motional branch."""
    fs = 1 / (2 * math.pi * math.sqrt(lm * cm))
    bvd = M.BVD(c0=template.bvd.c0, rm=rm, lm=lm, cm=cm,
                qm=2 * math.pi * fs * lm / rm, fs=fs)
    return M.Scenario("MODEL", "model", "model", "model", "identified model",
                      bvd, template.matching, template.rs)


# ------------------------------------------------------------------ candidate 1
def estimate_fs_two_point(f1: float, f2: float, scenario, relative_noise: float = 0.0):
    x1 = deembed_zm(f1, scenario).imag
    x2 = deembed_zm(f2, scenario).imag
    if relative_noise:
        x1 *= 1 + RNG.normal(0, relative_noise)
        x2 *= 1 + RNG.normal(0, relative_noise)
    w1, w2 = 2 * math.pi * f1, 2 * math.pi * f2
    matrix = np.array([[w1, -1 / w1], [w2, -1 / w2]])
    lm, inverse_cm = np.linalg.solve(matrix, np.array([x1, x2]))
    if lm <= 0 or inverse_cm <= 0:
        return math.nan
    return 1 / (2 * math.pi * math.sqrt(lm / inverse_cm))


# ------------------------------------------------------------------ candidate 3
def fit_bvd_from_grid(grid: np.ndarray, measured: np.ndarray, template,
                      seed_rm: float = 7352.9, seed_qm: float = 800.0):
    """Least-squares fit of Rm, Lm, Cm to normalised port power over a frequency grid.

    C0, the matching network and Rs are design values the driver already knows.
    Parameters are fitted in log space because they span twenty decades.

    The seed is taken from the data, not from a nominal plant.  A Qm of several
    hundred makes this objective violently non-convex: the peak is about 1 kHz
    wide inside a 100 kHz window, so a gradient fit seeded at the wrong frequency
    sees a flat floor, has no gradient to follow and stays where it started.
    Seeding fs at the grid's measured argmax fixes that, which also means
    identification cannot precede the scan: the scan supplies the seed.
    """
    from scipy.optimize import least_squares

    seed_fs = float(grid[int(np.argmax(measured))])
    seed_lm = seed_qm * seed_rm / (2 * math.pi * seed_fs)
    seed_cm = 1 / ((2 * math.pi * seed_fs) ** 2 * seed_lm)

    def residual(p):
        candidate = scenario_with_bvd(template, *np.exp(p))
        predicted = np.array([normalised_port_power(f, candidate) for f in grid])
        return (predicted - measured) / np.maximum(np.abs(measured), 1e-15)

    result = least_squares(residual, np.log([seed_rm, seed_lm, seed_cm]),
                           xtol=1e-15, ftol=1e-15, gtol=1e-15)
    rm, lm, cm = np.exp(result.x)
    return rm, lm, cm, 1 / (2 * math.pi * math.sqrt(lm * cm))


def main() -> int:
    scenarios = M.scenario_map()

    print("=" * 84)
    print("1. Two-point estimation from the frequencies the controller visits anyway")
    print("=" * 84)
    print("   Without noise it is exact, and it sees a resonance far outside the observed span.")
    print(f"   {'case':<22}{'true fs kHz':>13}{'estimated kHz':>15}{'error Hz':>12}")
    for case_id in ("CASE_000_BASELINE", "CASE_FS_M5", "CASE_LM_P20", "CASE_COMBINED_HIGH"):
        s = scenarios[case_id]
        estimate = estimate_fs_two_point(900e3, 900e3 + CONTROL_STEP_HZ, s)
        print(f"   {case_id:<22}{s.bvd.fs / 1e3:>13.2f}{estimate / 1e3:>15.2f}{estimate - s.bvd.fs:>12.4f}")

    print()
    print("   With noise on the de-embedded reactance it collapses.  Median |error| over 400 draws,")
    print("   observing CASE_LM_P20 from 900 kHz, whose true fs is 821.58 kHz:")
    print(f"   {'separation Hz':>15}{'noise 0.1%':>14}{'noise 1%':>14}{'usable?':>10}")
    target = scenarios["CASE_LM_P20"]
    peak_width_hz = 1133.0        # narrowest registered FWHM, the accuracy the controller needs
    for separation in (100.0, 500.0, 2000.0, 10000.0, 50000.0):
        medians = []
        for noise in (1e-3, 1e-2):
            draws = [estimate_fs_two_point(900e3, 900e3 + separation, target, noise) for _ in range(400)]
            errors = [abs(d - target.bvd.fs) for d in draws if np.isfinite(d)]
            medians.append(np.median(errors) if errors else math.nan)
        usable = "yes" if medians[0] < peak_width_hz / 2 else "no"
        print(f"   {separation:>15.0f}{medians[0]:>14.0f}{medians[1]:>14.0f}{usable:>10}")
    print(f"   The controller's own step is {CONTROL_STEP_HZ:.0f} Hz, which is the second row.")
    print("   So estimation from the controller's retuning is not viable once noise exists.")

    print()
    print("=" * 84)
    print("2. Model-referenced residual: reference moves with the controller")
    print("=" * 84)
    print("   The controller sweeps 900 -> 850 kHz.  Plant is unchanged for the first half and")
    print("   switches to CASE_LM_P20 at 875 kHz.  Two references are compared:")
    print("     frozen      the stored measurement at 900 kHz, which is what the detector uses")
    print("     model       the identified plant's prediction at the CURRENT frequency")
    before = scenarios["CASE_000_BASELINE"]
    after = scenarios["CASE_LM_P20"]
    identified = before                     # a perfect identification, isolated on purpose
    frozen_reference = normalised_port_power(900e3, before)

    print()
    print(f"   {'f kHz':>9}{'plant':<20}{'frozen resid':>15}{'model resid':>14}")
    for frequency in (900e3, 890e3, 880e3, 875e3, 874e3, 870e3, 860e3, 850e3):
        plant = before if frequency > 875e3 else after
        measured = normalised_port_power(frequency, plant)
        predicted = normalised_port_power(frequency, identified)
        frozen = abs(frozen_reference - measured) / max(abs(frozen_reference), 1e-30)
        model = abs(predicted - measured) / max(abs(predicted), 1e-30)
        label = "baseline" if plant is before else "LM_P20 (changed)"
        print(f"   {frequency / 1e3:>9.1f}{label:<20}{frozen:>15.4f}{model:>14.4f}")
    print()
    print("   The frozen residual is already above the detector's 0.10 power-drop threshold at")
    print("   890 kHz with nothing wrong, because the controller moved off the peak.  That is a")
    print("   false alarm, and it is also why the detector must freeze its reference and rebuild")
    print("   it, which is the behaviour that blinds it.  The model residual stays at zero while")
    print("   the plant is unchanged no matter where the controller goes, then jumps when it is not.")

    print()
    print("=" * 84)
    print("3. How well the scan grid identifies the plant, which sets the model reference quality")
    print("=" * 84)
    print("   The grid is the one the edge-aware scan actually visits for each plant.")
    print(f"   {'case':<20}{'pts':>5}{'span kHz':>10}{'true fs kHz':>13}{'clean Hz':>11}{'0.1% Hz':>10}{'1% Hz':>10}")
    for case_id in ("CASE_000_BASELINE", "CASE_FS_M5", "CASE_LM_P20", "CASE_COMBINED_HIGH"):
        s = scenarios[case_id]
        grid = edge_aware_scan_grid(s)
        clean = np.array([normalised_port_power(f, s) for f in grid])
        row = []
        for noise in (0.0, 1e-3, 1e-2):
            errors = []
            for _ in range(1 if noise == 0 else 5):
                measured = clean * (1 + RNG.normal(0, noise, clean.shape)) if noise else clean
                try:
                    *_, fs_estimate = fit_bvd_from_grid(grid, measured, s)
                    errors.append(abs(fs_estimate - s.bvd.fs))
                except Exception:
                    errors.append(math.nan)
            row.append(np.median(errors))
        span = (grid.max() - grid.min()) / 1e3
        print(f"   {case_id:<20}{len(grid):>5}{span:>10.0f}{s.bvd.fs / 1e3:>13.2f}"
              f"{row[0]:>11.3f}{row[1]:>10.1f}{row[2]:>10.1f}")
    print()
    print("   A wide grid is well conditioned where two nearby points are not, so the plant should")
    print("   be identified from the scan and the model reference refreshed at every scan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
