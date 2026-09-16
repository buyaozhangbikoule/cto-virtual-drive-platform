"""v3 电学模型：空心圆柱 31 模 BVD + 为 50 Ω 功放重新设计的 L 匹配。

与 v2.1 的三处结构性差别
------------------------
1. **BVD 由几何正向推导**，不再由 |Z(fs)| = 7.071 kΩ 反推。
   该工作点来自 100 Vpp ÷ 5 mA，导师 2026-09-16 澄清后已失效。

2. **匹配网络拓扑随负载翻转**。v2.1 是「串联 L + 负载并联 C」，适用于负载阻抗
   【高于】源阻抗的情况（7071 Ω → 50 Ω，降阻），它在那个负载上工作正常。
   空心圆柱在谐振点是 28.4 - j7.5 Ω，【低于】50 Ω，必须升阻。
   对这个新负载，旧拓扑物理上做不到：并联 C 只改虚部，实部上限为
   1/Re(Y_load) = 30.4 Ω < 50 Ω，无论 C 取何值都够不到。因此 v3 改为
   「源侧并联 C + 串联 L」，并联元件跨在阻抗【较大】的一侧。

   **措辞更正 2026-09-16**：本段原写「stage2 匹配设计整体作废」，说过头了。
   作废的只是「同一套拓扑能直接搬到新负载上」，不是原设计本身——
   它在原负载上匹配后 Γ = 0.0635，是成功的。见 workspace/match_feasibility_20260916/。

3. **在本几何下，驱动约束由功率承载**。空心圆柱负载约 29 Ω，5 mA 在它上面
   只对应 0.4 mW，远低于导师意图，因此改用两者之积 176.8 mW。

   **适用范围更正 2026-09-16**：这是【本几何】的性质，不是普遍结论。
   100 Vpp ÷ 5 mA = 7.07 kΩ 是个有效的【下界】（要两者兼得，阻抗须 ≥ 7.07 kΩ），
   高阻抗几何并未被 50 Ω 功放排除；选它时 V/I 仍是有效约束，不必改用功率表述。
   电压上限改由【电场强度 × 壁厚】推导——31 模的电极间距只有 0.31 mm，
   不能沿用 33 模（电极间距 = 长度 5.6 mm）的电压限值。这条与几何绑定，
   与上述更正无关。

所有数值取自 registry_v3.json，不写死在本模块内。
相位按 RMS 等效解释，与 v2.1 一致。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REG = json.loads((HERE / "registry_v3.json").read_text(encoding="utf-8"))

EPS0 = 8.854e-12
F0 = float(REG["operating"]["f0_Hz"]["value"])
F_MIN = float(REG["operating"]["f_scan_min_Hz"]["value"])
F_MAX = float(REG["operating"]["f_scan_max_Hz"]["value"])
BASE_RS = float(REG["driver"]["source_impedance_ohm"]["value"])

P_PORT_SOFT = float(REG["drive_limits"]["P_PORT_SOFT_W"]["value"])
P_PORT_HARD = float(REG["drive_limits"]["P_PORT_HARD_W"]["value"])
VPP_SOFT = float(REG["drive_limits"]["VPP_SOFT"]["value"])
VPP_HARD = float(REG["drive_limits"]["VPP_HARD"]["value"])
IRMS_SOFT = float(REG["drive_limits"]["IRMS_SOFT"]["value"])
IRMS_HARD = float(REG["drive_limits"]["IRMS_HARD"]["value"])
SOURCE_MAX_AMPLITUDE = float(REG["drive_limits"]["source_max_amplitude"]["value"])


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
    topology: str          # "SHUNT_C_AT_SOURCE" | "SHUNT_C_AT_LOAD"


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


# ---------------------------------------------------------------- 几何 -> BVD

def bvd_from_hollow_cylinder(
    *, material: str, od_mm: float, id_mm: float, harmonic: int, f0_hz: float
) -> BVD:
    """径向极化空心圆柱、沿长度振动（31 模）的 BVD 参数。

    L  = n * N31 / f0                              长度模第 n 次谐波
    C0 = 2*pi*eps0*eps_r*L / ln(OD/ID)             同轴电容
    Cm = C0 * k31^2 / (1 - k31^2)
    Lm = 1 / (w0^2 * Cm)
    Qm = 1/(1/Qm_material + 1/Q_radiation)         材料损耗与辐射损耗并联
    Rm = w0 * Lm / Qm
    """
    p = REG["materials"][material]
    length_m = harmonic * float(p["N31_Hz_m"]) / f0_hz
    c0 = 2 * math.pi * EPS0 * float(p["epsilon_r"]) * length_m / math.log(od_mm / id_mm)
    k31 = float(p["k31"])
    cm = c0 * k31**2 / (1 - k31**2)
    w0 = 2 * math.pi * f0_hz
    lm = 1 / (w0**2 * cm)
    qm = 1 / (1 / float(p["Qm_material"]) + 1 / q_radiation())
    return BVD(c0=c0, rm=w0 * lm / qm, lm=lm, cm=cm, qm=qm, fs=f0_hz)


def q_radiation() -> float:
    a = REG["acoustic"]
    return math.pi * float(a["Z_piezo_MRayl"]["value"]) / (2 * float(a["Z_blood_MRayl"]["value"]))


def bvd_from_fs_qm(*, c0: float, rm: float, fs: float, qm: float) -> BVD:
    """保持 Rm 与 Qm，在指定 fs 上重新导出 Lm/Cm（与 v2.1 同名函数同义）。"""
    omega = 2 * math.pi * fs
    lm = qm * rm / omega
    return BVD(c0=c0, rm=rm, lm=lm, cm=1 / (omega * omega * lm), qm=qm, fs=fs)


def z_bvd_at(f: float, p: BVD) -> complex:
    w = 2 * math.pi * f
    zm = p.rm + 1j * (w * p.lm - 1 / (w * p.cm))
    return 1 / (1 / zm + 1j * w * p.c0)


# --------------------------------------------------------------- 匹配网络设计

def design_lmatch(z_load: complex, rs: float, f0_hz: float, *, ql: float, qc: float) -> Matching:
    """为给定负载设计无损 L 型匹配，并联元件跨在阻抗较大的一侧。

    R_load < Rs（本项目）：源侧并联 C + 串联 L，升阻。
    R_load > Rs（v2.1）：串联 L + 负载侧并联 C，降阻。
    两种情况都只用「串联 L + 并联 C」两个元件，元件种类不变，只是接法不同。
    """
    w = 2 * math.pi * f0_hz
    r_l, x_l = z_load.real, z_load.imag
    if r_l <= 0:
        raise ValueError(f"负载实部必须为正，得到 {r_l!r}")
    if r_l < rs:
        # 升阻：Q 由阻抗比决定
        q = math.sqrt(rs / r_l - 1)
        x_series = q * r_l - x_l          # 串联端需补足的电抗（含抵消负载虚部）
        if x_series <= 0:
            raise ValueError("升阻拓扑需要串联感性电抗，本负载不满足")
        l_h = x_series / w
        c_f = q / (w * rs)                # 并联 C 跨在 50 Ω 侧，X = rs/q
        topology = "SHUNT_C_AT_SOURCE"
    else:
        q = math.sqrt(r_l / rs - 1)
        # 降阻：并联 C 跨负载，先把 R_load 拉到 rs，再用串联 L 抵消剩余虚部
        b = q / r_l
        c_f = b / w
        y = 1 / z_load + 1j * b
        z_after = 1 / y
        l_h = -z_after.imag / w
        topology = "SHUNT_C_AT_LOAD"
    if l_h <= 0 or c_f <= 0:
        raise ValueError(f"匹配元件值非正：L={l_h!r}, C={c_f!r}")
    return Matching(l_h=l_h, c_f=c_f, ql=ql, qc=qc, topology=topology)


def max_real_part_with_shunt_c(z_load: complex) -> float:
    """旧拓扑（并联 C 跨负载）在任意 C 下可达的最大输入实部 = 1/Re(Y_load)。

    用于证明 v2.1 拓扑够不到 50 Ω，不是靠试算而是靠上界。
    """
    return 1.0 / (1 / z_load).real


# ------------------------------------------------------------------ 频率响应

def response(
    frequency_hz: np.ndarray | float, scenario: Scenario, amplitude: float = 1.0
) -> dict[str, np.ndarray]:
    f = np.atleast_1d(np.asarray(frequency_hz, dtype=float))
    w = 2 * np.pi * f
    p, m = scenario.bvd, scenario.matching

    z_m = p.rm + 1j * (w * p.lm - 1 / (w * p.cm))
    z_bvd = 1 / (1 / z_m + 1j * w * p.c0)

    # ESR 由 f0 处声明的 Q 导出，视作与频率无关的电阻（与 v2.1 相同约定）
    r_l = 2 * math.pi * F0 * m.l_h / m.ql
    r_c = 1 / (2 * math.pi * F0 * m.c_f * m.qc)
    z_l_branch = r_l + 1j * w * m.l_h
    z_c_shunt = r_c + 1 / (1j * w * m.c_f)

    source_v = SOURCE_A1_VRMS * float(amplitude)

    if m.topology == "SHUNT_C_AT_SOURCE":
        z_series_arm = z_l_branch + z_bvd            # 串联 L 后接换能器
        z_in = 1 / (1 / z_c_shunt + 1 / z_series_arm)
        i_source = source_v / (scenario.rs + z_in)
        v_input = i_source * z_in                    # 并联节点电压
        i_branch = v_input / z_series_arm            # 流过 L 与换能器的电流
        v_port = i_branch * z_bvd
        i_c_match = v_input / z_c_shunt
        p_l = np.abs(i_branch) ** 2 * r_l
        p_c = np.abs(i_c_match) ** 2 * r_c
    else:
        z_parallel = 1 / (1 / z_bvd + 1 / z_c_shunt)
        z_in = z_l_branch + z_parallel
        i_source = source_v / (scenario.rs + z_in)
        v_input = i_source * z_in
        v_port = i_source * z_parallel
        i_c_match = v_port / z_c_shunt
        p_l = np.abs(i_source) ** 2 * r_l
        p_c = np.abs(i_c_match) ** 2 * r_c

    i_m = v_port / z_m
    i_c0 = 1j * w * p.c0 * v_port
    i_port = i_m + i_c0

    s_port = v_port * np.conj(i_port)
    p_rm = np.abs(i_m) ** 2 * p.rm
    p_source = np.real(source_v * np.conj(i_source))
    p_rs = np.abs(i_source) ** 2 * scenario.rs
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
    source_max: float | None = None,
) -> np.ndarray:
    """功放能力与器件限值共同允许的最大驱动幅度。

    与 v2.1 的差别：多了一条【端口功率】上限，且它才是基线下的约束者。
    功率随幅度平方增长，因此幅度上限为 sqrt(P_limit / P_unit)。
    """
    cap = SOURCE_MAX_AMPLITUDE if source_max is None else float(source_max)
    if not (cap > 0) or math.isnan(cap):
        raise ValueError(f"source_max 必须为正，得到 {cap!r}")
    unit = response(frequency_hz, scenario, amplitude=1.0)
    v_limit = VPP_SOFT if use_soft_limits else VPP_HARD
    i_limit = IRMS_SOFT if use_soft_limits else IRMS_HARD
    p_limit = P_PORT_SOFT if use_soft_limits else P_PORT_HARD
    with np.errstate(divide="ignore", invalid="ignore"):
        a = np.minimum.reduce([
            np.full_like(unit["vport_vpp"], cap),
            v_limit / np.maximum(unit["vport_vpp"], 1e-30),
            i_limit / np.maximum(unit["iport_irms_A"], 1e-30),
            np.sqrt(p_limit / np.maximum(unit["p_port_W"], 1e-30)),
        ])
    return np.clip(a, 0.0, cap)


def safe_power(frequency_hz, scenario: Scenario, *, source_max: float | None = None) -> np.ndarray:
    a = allowed_amplitude(frequency_hz, scenario, use_soft_limits=True, source_max=source_max)
    return response(frequency_hz, scenario, amplitude=1.0)["p_rm_W"] * a**2


# ------------------------------------------------------------------ 基线构造

_b = REG["baseline"]
BASE_BVD = bvd_from_hollow_cylinder(
    material=_b["material"]["value"],
    od_mm=float(_b["od_mm"]["value"]),
    id_mm=float(_b["id_mm"]["value"]),
    harmonic=int(_b["harmonic"]["value"]),
    f0_hz=F0,
)
BASE_MATCH = design_lmatch(
    z_bvd_at(F0, BASE_BVD), BASE_RS, F0,
    ql=float(REG["matching"]["inductor_Q_at_f0"]["value"]),
    qc=float(REG["matching"]["capacitor_Q_at_f0"]["value"]),
)

# a1 = 1.0 标定为「基线在 fs 上端口功率恰为 P_PORT_SOFT」。
# v2.1 用的是 stage2 冻结的戴维南幅度；v3 没有 stage2，改用功率目标标定，
# 使 a1 有明确物理含义：a1=1 即导师给的 176.8 mW 工作点。
SOURCE_A1_VRMS = 1.0
_unit_p = float(response(F0, Scenario(
    "CAL", "cal", "cal", "cal", "calibration", BASE_BVD, BASE_MATCH, BASE_RS
), 1.0)["p_port_W"][0])
SOURCE_A1_VRMS = math.sqrt(P_PORT_SOFT / _unit_p)


# ------------------------------------------------------------------ 场景定义

def shifted_fs(base: BVD, ratio: float) -> BVD:
    return bvd_from_fs_qm(c0=base.c0, rm=base.rm, fs=base.fs * ratio, qm=base.qm)


def changed_qm(base: BVD, qm: float) -> BVD:
    return bvd_from_fs_qm(c0=base.c0, rm=base.rm, fs=base.fs, qm=qm)


def changed_rm_only(base: BVD, ratio: float) -> BVD:
    rm = base.rm * ratio
    return replace(base, rm=rm, qm=2 * math.pi * base.fs * base.lm / rm)


def changed_lm_only(base: BVD, ratio: float) -> BVD:
    lm = base.lm * ratio
    fs = 1 / (2 * math.pi * math.sqrt(lm * base.cm))
    return replace(base, lm=lm, fs=fs, qm=2 * math.pi * fs * lm / base.rm)


def changed_cm_only(base: BVD, ratio: float) -> BVD:
    cm = base.cm * ratio
    fs = 1 / (2 * math.pi * math.sqrt(base.lm * cm))
    return replace(base, cm=cm, fs=fs, qm=2 * math.pi * fs * base.lm / base.rm)


def _case(case_id, factor, level, *, bvd=None, matching=None, rs=BASE_RS,
          family="single_factor",
          description="仅所列扫描变量变化，其余冻结。") -> Scenario:
    return Scenario(case_id, family, factor, level, description,
                    BASE_BVD if bvd is None else bvd,
                    BASE_MATCH if matching is None else matching, rs)


# Qm 档位不再是 500/800/1000——基线 Qm 已是 21 量级，旧档位物理上不可达。
# 改为基线的 0.5x / 1x / 2x：材料 Qm（典型 65）与辐射 Qm（平面波近似 31.2）
# 各自都有约 2 倍的不确定度，该区间覆盖「换硬性材料」「空气背衬台架测试」两端。
QM_LEVELS = [round(BASE_BVD.qm * r, 2) for r in (0.5, 1.0, 2.0)]


def single_factor_scenarios() -> list[Scenario]:
    cases = [_case("CASE_000_BASELINE", "baseline", "baseline", family="baseline")]
    for pct in (10, 20, 30):
        cases.append(_case(f"CASE_C0_P{pct}", "C0", f"+{pct}%",
                           bvd=replace(BASE_BVD, c0=BASE_BVD.c0 * (1 + pct / 100))))
    for pct in (15, 30, 50):
        cases.append(_case(f"CASE_RM_P{pct}", "Rm", f"+{pct}%",
                           bvd=changed_rm_only(BASE_BVD, 1 + pct / 100),
                           description="仅 Rm 变化；C0/Lm/Cm/fs 冻结，Qm 由 Rm 导出。"))
    for pct in (1, 3, 5):
        cases.append(_case(f"CASE_FS_M{pct}", "fs", f"-{pct}%",
                           bvd=shifted_fs(BASE_BVD, 1 - pct / 100),
                           description="fs 变化而 Rm 与 Qm 固定，Lm 与 Cm 一同重新导出。"))
    for pct in (5, 10, 20):
        cases.append(_case(f"CASE_LM_P{pct}", "Lm", f"+{pct}%",
                           bvd=changed_lm_only(BASE_BVD, 1 + pct / 100),
                           description="仅 Lm 变化；C0/Rm/Cm 冻结，fs 与 Qm 为导出量。"))
    for pct in (5, 10, 20):
        cases.append(_case(f"CASE_CM_P{pct}", "Cm", f"+{pct}%",
                           bvd=changed_cm_only(BASE_BVD, 1 + pct / 100),
                           description="仅 Cm 变化；C0/Rm/Lm 冻结，fs 与 Qm 为导出量。"))
    for pct in (5, 10, 20):
        cases.append(_case(f"CASE_RS_P{pct}", "Rs", f"+{pct}%", rs=BASE_RS * (1 + pct / 100)))
    for pct in (2, 5, 10):
        cases.append(_case(f"CASE_LMATCH_P{pct}", "Lmatch", f"+{pct}%",
                           matching=replace(BASE_MATCH, l_h=BASE_MATCH.l_h * (1 + pct / 100))))
    for pct in (2, 5, 10):
        cases.append(_case(f"CASE_CMATCH_M{pct}", "Cmatch", f"-{pct}%",
                           matching=replace(BASE_MATCH, c_f=BASE_MATCH.c_f * (1 - pct / 100))))
    for ql in (100, 50, 20):
        cases.append(_case(f"CASE_QL_{ql}", "inductor_Q", f"Q={ql}",
                           matching=replace(BASE_MATCH, ql=float(ql)),
                           description=f"电感 ESR 通过 {F0/1e6:.1f} MHz 处声明的 Q 变化。"))
    for qm in QM_LEVELS:
        cases.append(_case(f"CASE_QM_{qm:g}".replace(".", "P"), "Qm", f"Qm={qm:g}",
                           bvd=changed_qm(BASE_BVD, float(qm)),
                           description="Qm 灵敏度：fs、Rm、C0 固定，Lm/Cm 重新导出。"))
    return cases


def combination_scenarios() -> list[Scenario]:
    levels = [("LOW", 10, 15, 1, 5, 2, 2, 100),
              ("MEDIUM", 20, 30, 3, 10, 5, 5, 50),
              ("HIGH", 30, 50, 5, 20, 10, 10, 20)]
    cases: list[Scenario] = []
    for name, c0p, rmp, fsm, rsp, lp, cmp_, ql in levels:
        bvd = shifted_fs(BASE_BVD, 1 - fsm / 100)
        bvd = replace(bvd, c0=BASE_BVD.c0 * (1 + c0p / 100), rm=BASE_BVD.rm * (1 + rmp / 100))
        bvd = bvd_from_fs_qm(c0=bvd.c0, rm=bvd.rm, fs=bvd.fs, qm=BASE_BVD.qm)
        matching = replace(BASE_MATCH, l_h=BASE_MATCH.l_h * (1 + lp / 100),
                           c_f=BASE_MATCH.c_f * (1 - cmp_ / 100), ql=float(ql))
        cases.append(_case(f"CASE_COMBINED_{name}", "combined", name.lower(),
                           bvd=bvd, matching=matching, rs=BASE_RS * (1 + rsp / 100),
                           family="combined",
                           description=(f"C0 +{c0p}%, Rm +{rmp}%, fs -{fsm}%, Rs +{rsp}%, "
                                        f"Lmatch +{lp}%, Cmatch -{cmp_}%, 电感 Q={ql}。")))
    return cases


def all_scenarios() -> list[Scenario]:
    return single_factor_scenarios() + combination_scenarios()


def scenario_map() -> dict[str, Scenario]:
    return {s.case_id: s for s in all_scenarios()}


def half_power_width(frequency_hz, power_w) -> tuple[float, str, float, float]:
    f = np.asarray(frequency_hz, dtype=float)
    p = np.asarray(power_w, dtype=float)
    peak = int(np.argmax(p))
    half = p[peak] / 2
    left = np.where(p[: peak + 1] <= half)[0]
    right = np.where(p[peak:] <= half)[0]
    if left.size == 0 or right.size == 0:
        return math.nan, "OUT_OF_WINDOW", math.nan, math.nan
    li, ri = int(left[-1]), int(peak + right[0])
    if li >= peak or ri <= peak:
        return math.nan, "DEGENERATE", math.nan, math.nan

    def crossing(i0, i1):
        if p[i1] == p[i0]:
            return float((f[i0] + f[i1]) / 2)
        return float(f[i0] + (half - p[i0]) * (f[i1] - f[i0]) / (p[i1] - p[i0]))

    lo, hi = crossing(li, li + 1), crossing(ri - 1, ri)
    return hi - lo, "OK", lo, hi


def point_metrics(frequency_hz: float, scenario: Scenario, amplitude: float = 1.0) -> dict[str, float]:
    q = response(frequency_hz, scenario, amplitude)
    z = complex(q["z_in"][0])
    return {
        "frequency_Hz": float(frequency_hz),
        "zin_real_ohm": float(z.real), "zin_imag_ohm": float(z.imag),
        "zin_abs_ohm": float(abs(z)), "phase_deg": float(q["phase_deg"][0]),
        "gamma": float(q["gamma"][0]), "vport_vpp": float(q["vport_vpp"][0]),
        "iport_irms_A": float(q["iport_irms_A"][0]), "p_rm_W": float(q["p_rm_W"][0]),
        "p_port_W": float(q["p_port_W"][0]), "q_port_var": float(q["q_port_var"][0]),
        "s_port_VA": float(q["s_port_VA"][0]), "p_source_W": float(q["p_source_W"][0]),
        "p_rs_W": float(q["p_rs_W"][0]), "p_l_esr_W": float(q["p_l_esr_W"][0]),
        "p_c_esr_W": float(q["p_c_esr_W"][0]),
    }
