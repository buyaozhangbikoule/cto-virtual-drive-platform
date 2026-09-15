"""Active v2.1 BVD + lossy L-match model used by stages 3-5.

All parameters are hypothetical baselines, derived values, or scan variables.
No value in this module is a measured transducer or a hardware safety rating.
AC phasors are interpreted as RMS-equivalent values for power calculations.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
F0 = 0.9e6
F_MIN = 0.8e6
F_MAX = 1.0e6
VPP_SOFT = 130.0
VPP_HARD = 160.0
IRMS_SOFT = 5.5e-3
IRMS_HARD = 6.0e-3


@dataclass(frozen=True)
class BVD:
    c0: float
    rm: float
    lm: float
    cm: float
    qm: float
    fs: float


@dataclass(frozen=True)
class Matching:
    l_h: float
    c_f: float
    ql: float
    qc: float


@dataclass(frozen=True)
class Scenario:
    case_id: str
    family: str
    factor: str
    level: str
    description: str
    bvd: BVD
    matching: Matching
    rs: float


def bvd_from_fs_qm(*, c0: float, rm: float, fs: float, qm: float) -> BVD:
    """Hold Rm and Qm while deriving Lm/Cm at the requested fs."""
    omega = 2 * math.pi * fs
    lm = qm * rm / omega
    cm = 1 / (omega * omega * lm)
    return BVD(c0=c0, rm=rm, lm=lm, cm=cm, qm=qm, fs=fs)


_design = json.loads(
    (ROOT / "stage2_matching" / "stage2_匹配设计参数.json").read_text(encoding="utf-8")
)
_cal = json.loads(
    (ROOT / "stage2_matching" / "stage2_控制源幅度校准.json").read_text(encoding="utf-8")
)

BASE_BVD = bvd_from_fs_qm(
    c0=float(_design["bvd"]["C0_F"]),
    rm=float(_design["bvd"]["Rm_ohm"]),
    fs=float(_design["bvd"]["fs_Hz"]),
    qm=800.0,
)
BASE_MATCH = Matching(
    l_h=float(_design["design"]["l_active_H"]),
    c_f=float(_design["design"]["c_active_F"]),
    ql=float(_design["matching_loss_assumptions"]["inductor_Q_at_f0"]),
    qc=float(_design["matching_loss_assumptions"]["capacitor_Q_at_f0"]),
)
BASE_RS = 50.0
SOURCE_A1_VRMS = float(_cal["source_Vrms_for_a1"])


def response(
    frequency_hz: np.ndarray | float,
    scenario: Scenario,
    amplitude: float = 1.0,
) -> dict[str, np.ndarray]:
    f = np.atleast_1d(np.asarray(frequency_hz, dtype=float))
    w = 2 * np.pi * f
    p = scenario.bvd
    m = scenario.matching

    z_m = p.rm + 1j * (w * p.lm - 1 / (w * p.cm))
    z_bvd = 1 / (1 / z_m + 1j * w * p.c0)

    # ESR is a frequency-independent resistor derived from the declared Q at f0.
    r_l = 2 * math.pi * F0 * m.l_h / m.ql
    r_c = 1 / (2 * math.pi * F0 * m.c_f * m.qc)
    z_c_match = r_c + 1 / (1j * w * m.c_f)
    z_parallel = 1 / (1 / z_bvd + 1 / z_c_match)
    z_in = r_l + 1j * w * m.l_h + z_parallel

    source_v = SOURCE_A1_VRMS * float(amplitude)
    i_source = source_v / (scenario.rs + z_in)
    v_input = i_source * z_in
    v_port = i_source * z_parallel
    i_m = v_port / z_m
    i_c0 = 1j * w * p.c0 * v_port
    i_port = i_m + i_c0
    i_c_match = v_port / z_c_match

    s_port = v_port * np.conj(i_port)
    p_rm = np.abs(i_m) ** 2 * p.rm
    p_source = np.real(source_v * np.conj(i_source))
    p_rs = np.abs(i_source) ** 2 * scenario.rs
    p_l = np.abs(i_source) ** 2 * r_l
    p_c = np.abs(i_c_match) ** 2 * r_c
    gamma = np.abs((z_in - scenario.rs) / (z_in + scenario.rs))

    return {
        "frequency_Hz": f,
        "z_bvd": z_bvd,
        "z_m": z_m,
        "z_in": z_in,
        "v_input": v_input,
        "v_port": v_port,
        "i_source": i_source,
        "i_motional": i_m,
        "i_port": i_port,
        "p_rm_W": p_rm,
        "p_port_W": np.real(s_port),
        "q_port_var": np.imag(s_port),
        "s_port_VA": np.abs(s_port),
        "p_source_W": p_source,
        "p_rs_W": p_rs,
        "p_l_esr_W": p_l,
        "p_c_esr_W": p_c,
        "power_balance_error_W": p_source - (p_rs + p_rm + p_l + p_c),
        "gamma": gamma,
        "vport_vpp": np.abs(v_port) * 2 * math.sqrt(2),
        "iport_irms_A": np.abs(i_port),
        "phase_deg": np.angle(z_in, deg=True),
        "r_l_ohm": np.full(f.shape, r_l),
        "r_c_ohm": np.full(f.shape, r_c),
    }


def allowed_amplitude(
    frequency_hz: np.ndarray | float,
    scenario: Scenario,
    *,
    use_soft_limits: bool,
) -> np.ndarray:
    unit = response(frequency_hz, scenario, amplitude=1.0)
    v_limit = VPP_SOFT if use_soft_limits else VPP_HARD
    i_limit = IRMS_SOFT if use_soft_limits else IRMS_HARD
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.minimum.reduce(
            [
                np.ones_like(unit["vport_vpp"]),
                v_limit / np.maximum(unit["vport_vpp"], 1e-30),
                i_limit / np.maximum(unit["iport_irms_A"], 1e-30),
            ]
        )
    return np.clip(a, 0.0, 1.0)


def safe_power(frequency_hz: np.ndarray | float, scenario: Scenario) -> np.ndarray:
    a = allowed_amplitude(frequency_hz, scenario, use_soft_limits=True)
    unit = response(frequency_hz, scenario, amplitude=1.0)
    return unit["p_rm_W"] * a**2


def shifted_fs(base: BVD, ratio: float) -> BVD:
    return bvd_from_fs_qm(c0=base.c0, rm=base.rm, fs=base.fs * ratio, qm=base.qm)


def changed_qm(base: BVD, qm: float) -> BVD:
    return bvd_from_fs_qm(c0=base.c0, rm=base.rm, fs=base.fs, qm=qm)


def changed_lm_only(base: BVD, ratio: float) -> BVD:
    """Change Lm only; derive the resulting fs and Qm with Rm/Cm fixed."""
    lm = base.lm * ratio
    fs = 1 / (2 * math.pi * math.sqrt(lm * base.cm))
    qm = 2 * math.pi * fs * lm / base.rm
    return replace(base, lm=lm, fs=fs, qm=qm)


def changed_cm_only(base: BVD, ratio: float) -> BVD:
    """Change Cm only; derive the resulting fs and Qm with Rm/Lm fixed."""
    cm = base.cm * ratio
    fs = 1 / (2 * math.pi * math.sqrt(base.lm * cm))
    qm = 2 * math.pi * fs * base.lm / base.rm
    return replace(base, cm=cm, fs=fs, qm=qm)


def _case(
    case_id: str,
    factor: str,
    level: str,
    *,
    bvd: BVD = BASE_BVD,
    matching: Matching = BASE_MATCH,
    rs: float = BASE_RS,
    family: str = "single_factor",
    description: str = "Only the named scan variable changes; all others remain frozen.",
) -> Scenario:
    return Scenario(case_id, family, factor, level, description, bvd, matching, rs)


def single_factor_scenarios() -> list[Scenario]:
    cases = [_case("CASE_000_BASELINE", "baseline", "baseline", family="baseline")]
    for pct in (10, 20, 30):
        cases.append(_case(
            f"CASE_C0_P{pct}", "C0", f"+{pct}%",
            bvd=replace(BASE_BVD, c0=BASE_BVD.c0 * (1 + pct / 100)),
        ))
    for pct in (15, 30, 50):
        cases.append(_case(
            f"CASE_RM_P{pct}", "Rm", f"+{pct}%",
            bvd=replace(BASE_BVD, rm=BASE_BVD.rm * (1 + pct / 100)),
        ))
    for pct in (1, 3, 5):
        cases.append(_case(
            f"CASE_FS_M{pct}", "fs", f"-{pct}%",
            bvd=shifted_fs(BASE_BVD, 1 - pct / 100),
            description="fs changes while Rm and Qm remain fixed; Lm and Cm are re-derived together.",
        ))
    for pct in (5, 10, 20):
        cases.append(_case(
            f"CASE_LM_P{pct}", "Lm", f"+{pct}%",
            bvd=changed_lm_only(BASE_BVD, 1 + pct / 100),
            description=(
                "Lm-only scan: Lm changes while C0, Rm and Cm remain frozen; "
                "the resulting fs and Qm are derived, not independently held fixed."
            ),
        ))
    for pct in (5, 10, 20):
        cases.append(_case(
            f"CASE_CM_P{pct}", "Cm", f"+{pct}%",
            bvd=changed_cm_only(BASE_BVD, 1 + pct / 100),
            description=(
                "Cm-only scan: Cm changes while C0, Rm and Lm remain frozen; "
                "the resulting fs and Qm are derived, not independently held fixed."
            ),
        ))
    for pct in (5, 10, 20):
        cases.append(_case(f"CASE_RS_P{pct}", "Rs", f"+{pct}%", rs=BASE_RS * (1 + pct / 100)))
    for pct in (2, 5, 10):
        cases.append(_case(
            f"CASE_LMATCH_P{pct}", "Lmatch", f"+{pct}%",
            matching=replace(BASE_MATCH, l_h=BASE_MATCH.l_h * (1 + pct / 100)),
        ))
    for pct in (2, 5, 10):
        cases.append(_case(
            f"CASE_CMATCH_M{pct}", "Cmatch", f"-{pct}%",
            matching=replace(BASE_MATCH, c_f=BASE_MATCH.c_f * (1 - pct / 100)),
        ))
    for ql in (100, 50, 20):
        cases.append(_case(
            f"CASE_QL_{ql}", "inductor_Q", f"Q={ql}",
            matching=replace(BASE_MATCH, ql=float(ql)),
            description="Inductor ESR changes through the declared Q at 0.9 MHz.",
        ))
    for qm in (500, 800, 1000):
        cases.append(_case(
            f"CASE_QM_{qm}", "Qm", f"Qm={qm}",
            bvd=changed_qm(BASE_BVD, float(qm)),
            description="Qm sensitivity: fs, Rm and C0 remain fixed; Lm/Cm are re-derived.",
        ))
    return cases


def combination_scenarios() -> list[Scenario]:
    levels = [
        ("LOW", 10, 15, 1, 5, 2, 2, 100),
        ("MEDIUM", 20, 30, 3, 10, 5, 5, 50),
        ("HIGH", 30, 50, 5, 20, 10, 10, 20),
    ]
    cases: list[Scenario] = []
    for name, c0p, rmp, fsm, rsp, lp, cm, ql in levels:
        bvd = shifted_fs(BASE_BVD, 1 - fsm / 100)
        bvd = replace(bvd, c0=BASE_BVD.c0 * (1 + c0p / 100), rm=BASE_BVD.rm * (1 + rmp / 100))
        # Re-derive Lm/Cm after Rm changes so the declared fs and Qm remain exact.
        bvd = bvd_from_fs_qm(c0=bvd.c0, rm=bvd.rm, fs=bvd.fs, qm=BASE_BVD.qm)
        matching = replace(
            BASE_MATCH,
            l_h=BASE_MATCH.l_h * (1 + lp / 100),
            c_f=BASE_MATCH.c_f * (1 - cm / 100),
            ql=float(ql),
        )
        cases.append(_case(
            f"CASE_COMBINED_{name}", "combined", name.lower(),
            bvd=bvd, matching=matching, rs=BASE_RS * (1 + rsp / 100), family="combined",
            description=(
                f"C0 +{c0p}%, Rm +{rmp}%, fs -{fsm}%, Rs +{rsp}%, "
                f"Lmatch +{lp}%, Cmatch -{cm}%, inductor Q={ql}."
            ),
        ))
    return cases


def all_scenarios() -> list[Scenario]:
    return single_factor_scenarios() + combination_scenarios()


def scenario_map() -> dict[str, Scenario]:
    return {s.case_id: s for s in all_scenarios()}


def half_power_width(frequency_hz: np.ndarray, power_w: np.ndarray) -> tuple[float, str, float, float]:
    """Linear-interpolated full width at half maximum."""
    f = np.asarray(frequency_hz, dtype=float)
    p = np.asarray(power_w, dtype=float)
    peak = int(np.argmax(p))
    half = p[peak] / 2
    left_candidates = np.where(p[: peak + 1] <= half)[0]
    right_candidates = np.where(p[peak:] <= half)[0]
    if left_candidates.size == 0 or right_candidates.size == 0:
        return math.nan, "OUT_OF_WINDOW", math.nan, math.nan
    li = int(left_candidates[-1])
    ri = int(peak + right_candidates[0])
    if li >= peak or ri <= peak:
        return math.nan, "DEGENERATE", math.nan, math.nan

    def crossing(i0: int, i1: int) -> float:
        if p[i1] == p[i0]:
            return float((f[i0] + f[i1]) / 2)
        return float(f[i0] + (half - p[i0]) * (f[i1] - f[i0]) / (p[i1] - p[i0]))

    left = crossing(li, li + 1)
    right = crossing(ri - 1, ri)
    return right - left, "OK", left, right


def point_metrics(frequency_hz: float, scenario: Scenario, amplitude: float = 1.0) -> dict[str, float]:
    q = response(frequency_hz, scenario, amplitude)
    z = complex(q["z_in"][0])
    return {
        "frequency_Hz": float(frequency_hz),
        "zin_real_ohm": float(z.real),
        "zin_imag_ohm": float(z.imag),
        "zin_abs_ohm": float(abs(z)),
        "phase_deg": float(q["phase_deg"][0]),
        "gamma": float(q["gamma"][0]),
        "vport_vpp": float(q["vport_vpp"][0]),
        "iport_irms_A": float(q["iport_irms_A"][0]),
        "p_rm_W": float(q["p_rm_W"][0]),
        "p_port_W": float(q["p_port_W"][0]),
        "q_port_var": float(q["q_port_var"][0]),
        "s_port_VA": float(q["s_port_VA"][0]),
        "p_source_W": float(q["p_source_W"][0]),
        "p_rs_W": float(q["p_rs_W"][0]),
        "p_l_esr_W": float(q["p_l_esr_W"][0]),
        "p_c_esr_W": float(q["p_c_esr_W"][0]),
    }
