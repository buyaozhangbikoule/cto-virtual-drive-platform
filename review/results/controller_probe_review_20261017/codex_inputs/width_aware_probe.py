"""Read-only, direct-drive BVD probe-count study; not a hardware timing model.

The controller sees only feasible-power scores at frequencies it probes.  The
dense optimum is calculated separately for evaluation.  This deliberately omits
cable, matching, amplifier dynamics, protection holds, and acoustic loading
beyond the frozen candidate BVD.  Do not use its probe counts as recovery time.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "cto_candidate_registration/provenance/bvd_candidate_profiles.json"
F_MIN, F_MAX = 800_000.0, 1_000_000.0
SOURCE_R = 50.0
PORT_VPP_NORMAL = 100.0
CURRENT_NORMAL = 0.004  # A rms, at both amplifier output and ceramic terminals


@dataclass(frozen=True)
class BVD:
    c0: float
    rm: float
    lm: float
    cm: float

    @property
    def fs(self) -> float:
        return 1.0 / (2.0 * np.pi * np.sqrt(self.lm * self.cm))


def circuit(f: np.ndarray | float, bvd: BVD, source_vpp: float):
    """50-ohm Thevenin source directly driving a lossless-C0 four-element BVD."""
    w = 2 * np.pi * np.asarray(f, dtype=float)
    zm = bvd.rm + 1j * (w * bvd.lm - 1.0 / (w * bvd.cm))
    y = 1.0 / zm + 1j * w * bvd.c0
    z = 1.0 / y
    source = source_vpp / (2 * np.sqrt(2))
    i_amp = source / (SOURCE_R + z)
    v_port = i_amp * z
    i_port = v_port * y
    p_port = np.real(v_port * np.conj(i_port))
    return 2 * np.sqrt(2) * np.abs(v_port), np.abs(i_amp), np.abs(i_port), p_port


def ceramic_admittance(f: float, bvd: BVD) -> complex:
    w = 2 * np.pi * f
    zm = bvd.rm + 1j * (w * bvd.lm - 1.0 / (w * bvd.cm))
    return 1.0 / zm + 1j * w * bvd.c0


def calibrated_source_vpp(bvd: BVD) -> float:
    """Declared assumed source: 100 Vpp at the *unperturbed* ceramic fs."""
    v, _, _, _ = circuit(bvd.fs, bvd, 100.0)
    return 100.0 * PORT_VPP_NORMAL / float(v)


def feasible_score(f: np.ndarray | float, bvd: BVD, source_vpp: float):
    v, ia, ip, p = circuit(f, bvd, source_vpp)
    a = np.minimum.reduce(np.broadcast_arrays(
        np.ones_like(v), PORT_VPP_NORMAL / v,
        CURRENT_NORMAL / ia, CURRENT_NORMAL / ip,
    ))
    return p * a * a


def estimated_width(samples: dict[float, float], peak_f: float) -> float:
    """FWHM from sampled feasible-power curve, with linear crossing interpolation."""
    fs = np.array(sorted(samples))
    ps = np.array([samples[float(f)] for f in fs])
    i = int(np.where(fs == peak_f)[0][0])
    half = ps[i] / 2
    left = right = None
    for j in range(i - 1, -1, -1):
        if ps[j] <= half:
            left = float(np.interp(half, [ps[j], ps[j + 1]], [fs[j], fs[j + 1]]))
            break
    for j in range(i + 1, len(fs)):
        if ps[j] <= half:
            right = float(np.interp(half, [ps[j], ps[j - 1]], [fs[j], fs[j - 1]]))
            break
    if left is not None and right is not None:
        return right - left
    if left is not None:
        return 2 * (peak_f - left)
    if right is not None:
        return 2 * (right - peak_f)
    raise ValueError("scan did not resolve both sides of the peak")


def startup(bvd: BVD, source_vpp: float):
    """Once per startup: bounded full-band capture, then a 1-kHz local refinement."""
    measured: dict[float, float] = {}

    def score(f):
        f = float(np.clip(f, F_MIN, F_MAX))
        if f not in measured:
            measured[f] = float(feasible_score(f, bvd, source_vpp))
        return measured[f]

    for f in np.arange(F_MIN, F_MAX + 1, 5_000):
        score(f)
    coarse = max(measured, key=measured.get)
    for f in np.arange(max(F_MIN, coarse - 5_000), min(F_MAX, coarse + 5_000) + 1, 1_000):
        score(f)
    peak = max(measured, key=measured.get)
    return peak, estimated_width(measured, peak), len(measured)


def local_reacquire(start_f: float, width: float, bvd: BVD, source_vpp: float):
    """Measured-score bracket expansion followed by bounded local refinement.

    The width sets the initial probe distance. A rising side expands the bracket;
    once neither side improves power by 0.2%, a three-point parabola proposes
    a candidate and golden-section refinement checks the bracket. Probe scores
    are cached; the attempt is bounded at 30 points.
    """
    measured: dict[float, float] = {}

    def score(f):
        f = float(np.clip(f, F_MIN, F_MAX))
        if f not in measured and len(measured) < 30:
            measured[f] = float(feasible_score(f, bvd, source_vpp))
        return measured.get(f, float("-inf"))

    center = float(start_f)
    step = float(np.clip(0.25 * width, 500, 8_000))
    score(center)
    for _ in range(16):
        lo, hi = max(F_MIN, center - step), min(F_MAX, center + step)
        pl, pc, ph = score(lo), score(center), score(hi)
        if pl > pc * 1.002 or ph > pc * 1.002:
            center = lo if pl > ph else hi
            step = min(step * 1.7, max(width, 10_000))
            continue
        # Symmetric parabolic vertex is used only when both sides were measured.
        parabola_score = pc
        if lo < center < hi and pl + ph < 2 * pc:
            delta = 0.5 * step * (pl - ph) / (pl - 2 * pc + ph)
            parabola_score = score(float(np.clip(center + delta, lo, hi)))
        # A load may lower the attainable power without moving its maximizing
        # frequency; do not spend another sweep when the bracket shows that.
        if max(pl, ph) <= pc and parabola_score <= pc * 1.002:
            break
        a, b = lo, hi
        ratio = (np.sqrt(5) - 1) / 2
        x1, x2 = b - ratio * (b - a), a + ratio * (b - a)
        p1, p2 = score(x1), score(x2)
        while b - a > max(100, 0.1 * width) and len(measured) < 29:
            if p1 < p2:
                a, x1, p1 = x1, x2, p2
                x2 = a + ratio * (b - a)
                p2 = score(x2)
            else:
                b, x2, p2 = x2, x1, p1
                x1 = b - ratio * (b - a)
                p1 = score(x1)
        score((a + b) / 2)
        break
    best = max(measured, key=measured.get)
    return best, len(measured), measured[best]


def altered(bvd: BVD, change: str) -> BVD:
    if change == "fs_plus_2pct":
        return replace(bvd, cm=bvd.cm / 1.02**2)
    if change == "fs_minus_2pct":
        return replace(bvd, cm=bvd.cm / 0.98**2)
    if change == "rm_plus_30pct":
        return replace(bvd, rm=bvd.rm * 1.3)
    if change == "c0_plus_20pct":
        return replace(bvd, c0=bvd.c0 * 1.2)
    raise ValueError(change)


def main():
    out = []
    for profile in json.loads(PROFILES.read_text(encoding="utf-8")):
        bvd = BVD(profile["C0_F"], profile["Rm_ohm"], profile["Lm_H"], profile["Cm_F"])
        source = calibrated_source_vpp(bvd)
        start_f, width, startup_points = startup(bvd, source)
        for change in ("fs_plus_2pct", "fs_minus_2pct", "rm_plus_30pct", "c0_plus_20pct"):
            changed = altered(bvd, change)
            fs = np.arange(F_MIN, F_MAX + 1, 100.0)
            scores = feasible_score(fs, changed, source)
            i = int(np.argmax(scores))
            before = float(feasible_score(start_f, changed, source))
            prior = float(feasible_score(start_f, bvd, source))
            y0, y1 = ceramic_admittance(start_f, bvd), ceramic_admittance(start_f, changed)
            power_change = abs(before / prior - 1)
            admittance_change = abs(y1 / y0 - 1)
            # A production monitor must confirm these on consecutive samples.
            trigger = power_change > 0.05 or admittance_change > 0.05
            if trigger:
                f, n, after = local_reacquire(start_f, width, changed, source)
            else:
                f, n, after = start_f, 0, before
            # These are study gates against the separately computed dense-grid
            # reference, never information passed to the search controller.
            if after < 0.98 * float(scores[i]) or n > 30:
                raise AssertionError((profile["id"], change, n, after / float(scores[i])))
            out.append(dict(candidate=profile["id"], change=change,
                            source_vpp=source, start_f_Hz=start_f,
                            estimated_fwhm_Hz=width, startup_points=startup_points,
                            optimum_f_Hz=float(fs[i]), optimum_score_W=float(scores[i]),
                            power_change_pct=100 * power_change,
                            admittance_change_pct=100 * admittance_change,
                            triggered=trigger,
                            before_pct=100 * before / float(scores[i]),
                            after_f_Hz=f, after_pct=100 * after / float(scores[i]),
                            local_points=n))
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
