"""Combination-disturbance study for the assumed 0.9 MHz BVD model.

The script keeps the source amplitude fixed after calibrating the baseline
matched circuit to 100 Vpp across the transducer at 0.9 MHz. All parameters
and disturbance levels are virtual-study assumptions, not measurements.
"""

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import csv
import json

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


@dataclass(frozen=True)
class BVD:
    c0: float = 1.5e-12
    rm: float = 10.0e3
    lm: float = 100e-3
    cm: float = 0.31272e-12


@dataclass(frozen=True)
class Matching:
    ls: float = 124.73e-6
    cp: float = 247.96e-12
    q_inductor: float = 100.0


@dataclass(frozen=True)
class Scenario:
    case_id: str
    label_zh: str
    complexity: str
    bvd: BVD
    rs: float
    matching: Matching
    description: str


F_MIN = 0.8e6
F_MAX = 1.0e6
F_FIXED = 0.9e6
N_FREQ = 4001
FREQUENCIES = np.linspace(F_MIN, F_MAX, N_FREQ)

VPP_NOMINAL = 100.0
VPP_SOFT = 150.0
VPP_HARD = 160.0
IPEAK_NOMINAL = 5.0e-3
IPEAK_SOFT = 5.5e-3
IPEAK_HARD = 8.0e-3

BASE_BVD = BVD()
BASE_MATCH = Matching()
BASE_RS = 50.0

COLORS = {
    "CASE_000_BASELINE": "#4D4D4D",
    "CASE_400_COMBINED_LOW": "#2C7FB8",
    "CASE_401_COMBINED_MEDIUM": "#F28E2B",
    "CASE_402_COMBINED_HIGH": "#C74343",
}


def shifted_fs(p: BVD, ratio: float) -> BVD:
    fs_new = F_FIXED * ratio
    cm_new = 1.0 / (p.lm * (2.0 * np.pi * fs_new) ** 2)
    return replace(p, cm=cm_new)


def make_scenarios():
    high_bvd = shifted_fs(BASE_BVD, 0.97)
    high_bvd = replace(
        high_bvd,
        c0=BASE_BVD.c0 * 1.20,
        rm=BASE_BVD.rm * 1.30,
    )
    return [
        Scenario(
            "CASE_000_BASELINE",
            "基准",
            "baseline",
            BASE_BVD,
            BASE_RS,
            BASE_MATCH,
            "基准BVD、50 ohm源和基准低通L型匹配",
        ),
        Scenario(
            "CASE_400_COMBINED_LOW",
            "低复杂度：Rm +15%",
            "low",
            replace(BASE_BVD, rm=BASE_BVD.rm * 1.15),
            BASE_RS,
            BASE_MATCH,
            "仅增加运动损耗，用于观察峰高和峰宽变化",
        ),
        Scenario(
            "CASE_401_COMBINED_MEDIUM",
            "中复杂度：C0 +20%，Rm +30%",
            "medium",
            replace(BASE_BVD, c0=BASE_BVD.c0 * 1.20, rm=BASE_BVD.rm * 1.30),
            BASE_RS,
            BASE_MATCH,
            "同时改变静态电容与运动损耗",
        ),
        Scenario(
            "CASE_402_COMBINED_HIGH",
            "高复杂度：fs -3%并叠加失配",
            "high",
            high_bvd,
            BASE_RS * 1.20,
            replace(
                BASE_MATCH,
                ls=BASE_MATCH.ls * 1.05,
                cp=BASE_MATCH.cp * 0.95,
                q_inductor=20.0,
            ),
            "fs -3%、C0 +20%、Rm +30%、Rs +20%、Ls +5%、Cp -5%，电感Q由100降至20",
        ),
    ]


SCENARIOS = make_scenarios()


def zin_bvd(f_hz, p: BVD):
    f = np.asarray(f_hz, dtype=float)
    w = 2.0 * np.pi * f
    zm = p.rm + 1j * w * p.lm + 1.0 / (1j * w * p.cm)
    return 1.0 / (1j * w * p.c0 + 1.0 / zm)


def circuit_quantities(f_hz, scenario: Scenario, vs_rms: float):
    f = np.asarray(f_hz, dtype=float)
    w = 2.0 * np.pi * f
    zt = zin_bvd(f, scenario.bvd)
    zcp = 1.0 / (1j * w * scenario.matching.cp)
    zparallel = 1.0 / (1.0 / zt + 1.0 / zcp)
    # Keep ESR fixed at its 0.9 MHz design value, matching the LTspice netlist.
    r_esr_l = 2.0 * np.pi * F_FIXED * scenario.matching.ls / scenario.matching.q_inductor
    zseries = r_esr_l + 1j * w * scenario.matching.ls
    zin = zseries + zparallel
    isource = vs_rms / (scenario.rs + zin)
    vnode = isource * zparallel
    itransducer = vnode / zt
    z_motional = scenario.bvd.rm + 1j * w * scenario.bvd.lm + 1.0 / (1j * w * scenario.bvd.cm)
    imotional = vnode / z_motional
    # Average active power is defined only on the BVD motional branch.
    p_transducer = np.real(vnode * np.conj(imotional))
    p_match_loss = np.abs(isource) ** 2 * r_esr_l
    gamma = np.abs((zin - scenario.rs) / (zin + scenario.rs))
    return {
        "zt": zt,
        "zin": zin,
        "phase_deg": np.angle(zin, deg=True),
        "vpp": np.abs(vnode) * 2.0 * np.sqrt(2.0),
        "current_peak": np.abs(itransducer) * np.sqrt(2.0),
        "motional_current_peak": np.abs(imotional) * np.sqrt(2.0),
        "source_current_peak": np.abs(isource) * np.sqrt(2.0),
        "power": p_transducer,
        "match_loss": p_match_loss,
        "gamma": gamma,
        "inductor_esr": np.full_like(f, r_esr_l, dtype=float),
    }


def calibrate_source_rms():
    scenario = SCENARIOS[0]
    q = circuit_quantities(np.array([F_FIXED]), scenario, 1.0)
    vpp_per_vrms = float(q["vpp"][0])
    return VPP_NOMINAL / vpp_per_vrms


VS_RMS = calibrate_source_rms()


def unmatched_quantities(f_hz, scenario: Scenario, vs_rms: float):
    f = np.asarray(f_hz, dtype=float)
    zt = zin_bvd(f, scenario.bvd)
    current = vs_rms / (scenario.rs + zt)
    voltage = current * zt
    power = np.real(voltage * np.conj(current))
    gamma = np.abs((zt - scenario.rs) / (zt + scenario.rs))
    return {
        "zt": zt,
        "phase_deg": np.angle(zt, deg=True),
        "vpp": np.abs(voltage) * 2.0 * np.sqrt(2.0),
        "current_peak": np.abs(current) * np.sqrt(2.0),
        "power": power,
        "gamma": gamma,
    }


def calibrate_unmatched_source_rms():
    q = unmatched_quantities(np.array([F_FIXED]), SCENARIOS[0], 1.0)
    return VPP_NOMINAL / float(q["vpp"][0])


VS_UNMATCHED_RMS = calibrate_unmatched_source_rms()


def linear_zero_frequency(freq, values, target=F_FIXED):
    sign_change = np.where(values[:-1] * values[1:] <= 0.0)[0]
    if len(sign_change):
        candidate_freqs = []
        for idx in sign_change:
            f0, f1 = freq[idx], freq[idx + 1]
            y0, y1 = values[idx], values[idx + 1]
            if y1 == y0:
                candidate_freqs.append(float(f0))
            else:
                candidate_freqs.append(float(f0 - y0 * (f1 - f0) / (y1 - y0)))
        return min(candidate_freqs, key=lambda x: abs(x - target)), True
    return float(freq[np.argmin(np.abs(values))]), False


def contiguous_bandwidth(freq, values, threshold_ratio=0.95):
    peak_idx = int(np.argmax(values))
    threshold = threshold_ratio * values[peak_idx]
    left = peak_idx
    right = peak_idx
    while left > 0 and values[left - 1] >= threshold:
        left -= 1
    while right < len(values) - 1 and values[right + 1] >= threshold:
        right += 1
    return float(freq[right] - freq[left]), float(freq[left]), float(freq[right])


def nearest_index(freq, target):
    return int(np.argmin(np.abs(freq - target)))


def extract_features(scenario: Scenario, q, baseline_fixed):
    f = FREQUENCIES
    zmag = np.abs(q["zin"])
    min_idx = int(np.argmin(zmag))
    max_idx = int(np.argmax(zmag))
    power_idx = int(np.argmax(q["power"]))
    gamma_idx = int(np.argmin(q["gamma"]))
    fixed_idx = nearest_index(f, F_FIXED)
    phase_zero_hz, phase_crossed = linear_zero_frequency(f, q["phase_deg"])
    bw95, bw_lo, bw_hi = contiguous_bandwidth(f, q["power"], 0.95)

    p_fixed = float(q["power"][fixed_idx])
    phase_fixed = float(q["phase_deg"][fixed_idx])
    p_drop = 1.0 - p_fixed / baseline_fixed["power"]
    phase_shift = phase_fixed - baseline_fixed["phase_deg"]

    vpp = float(q["vpp"][fixed_idx])
    ipeak = float(q["current_peak"][fixed_idx])
    imot_peak = float(q["motional_current_peak"][fixed_idx])
    isource_peak = float(q["source_current_peak"][fixed_idx])
    p_soft = 1.10 * baseline_fixed["power"]
    p_hard = 1.25 * baseline_fixed["power"]
    soft_trip = vpp > VPP_SOFT or ipeak > IPEAK_SOFT or p_fixed > p_soft
    hard_trip = vpp >= VPP_HARD or ipeak >= IPEAK_HARD or p_fixed >= p_hard

    power_ratio = p_fixed / baseline_fixed["power"]
    gamma_fixed = float(q["gamma"][fixed_idx])
    if gamma_fixed > 0.20 or abs(phase_fixed) > 10.0 or power_ratio < 0.80:
        match_status = "失效"
    elif gamma_fixed > 0.10 or abs(phase_fixed) > 5.0 or power_ratio < 0.90:
        match_status = "明显退化"
    else:
        match_status = "未失效"

    if ipeak >= IPEAK_HARD:
        current_status = "达到8mA峰值硬限"
    elif ipeak > IPEAK_SOFT:
        current_status = "超过5.5mA峰值软限"
    elif ipeak > IPEAK_NOMINAL:
        current_status = "略高于5mA峰值标称值，未触发软限"
    else:
        current_status = "未超过5mA峰值标称值"

    definition_audit = {
        "baseline": "基准场景",
        "low": "符合：仅Rm +15%",
        "medium": "符合：C0 +20%、Rm +30%",
        "high": "符合：fs -3%并叠加源、匹配和ESR偏差",
    }[scenario.complexity]

    return {
        "case_id": scenario.case_id,
        "场景": scenario.label_zh,
        "复杂度": scenario.complexity,
        "固定频率_Hz": F_FIXED,
        "固定频率功率_W": p_fixed,
        "固定频率功率下降率": p_drop,
        "固定频率输入相位_deg": phase_fixed,
        "相位偏离_deg": phase_shift,
        "固定频率换能器电压_Vpp": vpp,
        "固定频率换能器电流_Apeak": ipeak,
        "固定频率运动支路电流_Apeak": imot_peak,
        "固定频率源电流_Apeak": isource_peak,
        "固定频率反射代理_absGamma": float(q["gamma"][fixed_idx]),
        "匹配状态_模型内部判据": match_status,
        "电流限值状态": current_status,
        "源电流口径提示": "若5mA指功放输出电流，则当前匹配网络不满足约束；需确认测量位置",
        "场景定义审核": definition_audit,
        "输入阻抗最低点频率_Hz": float(f[min_idx]),
        "输入阻抗最低值_ohm": float(zmag[min_idx]),
        "输入阻抗最高点频率_Hz": float(f[max_idx]),
        "输入阻抗最高值_ohm": float(zmag[max_idx]),
        "相位零点或最小绝对相位频率_Hz": phase_zero_hz,
        "存在相位过零": int(phase_crossed),
        "有功功率峰值频率_Hz": float(f[power_idx]),
        "有功功率峰值_W": float(q["power"][power_idx]),
        "功率95pct带宽_Hz": bw95,
        "功率95pct带宽下限_Hz": bw_lo,
        "功率95pct带宽上限_Hz": bw_hi,
        "最小反射代理频率_Hz": float(f[gamma_idx]),
        "最小反射代理_absGamma": float(q["gamma"][gamma_idx]),
        "软约束触发": int(soft_trip),
        "硬约束触发": int(hard_trip),
        "说明": scenario.description,
    }


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def configure_plot_style():
    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 3,
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })


def save_figure(fig, output_stem):
    fig.savefig(output_stem.with_suffix(".png"), dpi=220, bbox_inches="tight")
    fig.savefig(output_stem.with_suffix(".svg"), bbox_inches="tight")
    fig.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def plot_separated(outdir, results, quantity, ylabel, title, filename, scale=1.0):
    fig, axes = plt.subplots(4, 1, figsize=(8.2, 9.2), sharex=True, constrained_layout=True)
    for ax, scenario in zip(axes, SCENARIOS):
        q = results[scenario.case_id]
        ax.plot(FREQUENCIES / 1e6, q[quantity] * scale,
                color=COLORS[scenario.case_id], lw=2.0)
        ax.axvline(F_FIXED / 1e6, color="#777777", ls="--", lw=1.0)
        ax.set_ylabel(ylabel)
        ax.set_title(scenario.label_zh, loc="left", fontsize=10, fontweight="bold")
        ax.grid(axis="both", alpha=0.22)
    axes[-1].set_xlabel("频率 (MHz)")
    fig.suptitle(title, fontsize=14, fontweight="bold")
    save_figure(fig, outdir / filename)


def plot_phase(outdir, results):
    fig, axes = plt.subplots(4, 1, figsize=(8.2, 9.2), sharex=True, constrained_layout=True)
    for ax, scenario in zip(axes, SCENARIOS):
        q = results[scenario.case_id]
        ax.plot(FREQUENCIES / 1e6, q["phase_deg"],
                color=COLORS[scenario.case_id], lw=2.0)
        ax.axhline(0.0, color="#555555", ls=":", lw=1.0)
        ax.axvline(F_FIXED / 1e6, color="#777777", ls="--", lw=1.0)
        ax.set_ylabel("相位 (deg)")
        ax.set_title(scenario.label_zh, loc="left", fontsize=10, fontweight="bold")
        ax.grid(axis="both", alpha=0.22)
    axes[-1].set_xlabel("频率 (MHz)")
    fig.suptitle("组合扰动下的输入阻抗相位：0°线用于识别相位零点", fontsize=14, fontweight="bold")
    save_figure(fig, outdir / "组合扰动_输入相位_分场景")


def plot_summary(outdir, features):
    labels = [row["复杂度"] for row in features]
    colors = [COLORS[row["case_id"]] for row in features]
    x = np.arange(len(labels))
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.7), constrained_layout=True)

    axes[0].bar(x, [100.0 * row["固定频率功率下降率"] for row in features], color=colors)
    axes[0].axhline(0, color="#444444", lw=0.8)
    axes[0].set_ylabel("功率下降率 (%)")
    axes[0].set_title("固定0.9 MHz功率变化")

    axes[1].bar(x, [row["相位偏离_deg"] for row in features], color=colors)
    axes[1].axhline(0, color="#444444", lw=0.8)
    axes[1].set_ylabel("相位偏离 (deg)")
    axes[1].set_title("固定0.9 MHz相位偏离")

    axes[2].bar(x, [row["有功功率峰值频率_Hz"] / 1e6 for row in features], color=colors)
    axes[2].axhline(F_FIXED / 1e6, color="#444444", ls="--", lw=1.0)
    axes[2].set_ylabel("频率 (MHz)")
    axes[2].set_title("有功功率峰值位置")
    axes[2].set_ylim(0.8, 1.0)

    for ax in axes:
        ax.set_xticks(x, ["基准", "低", "中", "高"])
        ax.grid(axis="y", alpha=0.22)
    fig.suptitle("组合扰动摘要：固定频率性能与峰位变化", fontsize=14, fontweight="bold")
    save_figure(fig, outdir / "组合扰动_摘要")


def plot_matched_unmatched(outdir, matched_features, unmatched_rows):
    labels = ["基准", "低", "中", "高"]
    x = np.arange(4)
    width = 0.36
    matched_capture = [100.0 * (1.0 - row["固定频率功率下降率"]) for row in matched_features]
    unmatched_capture = [100.0 * float(row["功率捕获率"]) for row in unmatched_rows]
    fig, ax = plt.subplots(figsize=(7.6, 4.3), constrained_layout=True)
    ax.bar(x - width / 2, unmatched_capture, width, label="未匹配BVD", color="#8DA0CB")
    ax.bar(x + width / 2, matched_capture, width, label="固定基准L型网络", color="#E78AC3")
    ax.set_xticks(x, labels)
    ax.set_ylabel("固定0.9 MHz功率捕获率 (%)")
    ax.set_ylim(0, 110)
    ax.set_title("组合扰动：未匹配与固定匹配网络的功率保持能力")
    ax.grid(axis="y", alpha=0.22)
    ax.legend()
    save_figure(fig, outdir / "组合扰动_匹配与未匹配_功率对照")


def make_parameter_rows():
    rows = [
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "voltage_nominal_vpp", "数值": VPP_NOMINAL, "参数身份": "假设基线值", "说明": "换能器端名义峰峰值电压"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "voltage_hard_limit_vpp", "数值": VPP_HARD, "参数身份": "假设基线值", "说明": "模型内部硬上限"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "current_nominal_a_peak", "数值": IPEAK_NOMINAL, "参数身份": "假设基线值", "说明": "BVD换能器端总电流名义值"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "current_soft_limit_a_peak", "数值": IPEAK_SOFT, "参数身份": "假设基线值", "说明": "BVD换能器端总电流建议软限值"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "current_hard_limit_a_peak", "数值": IPEAK_HARD, "参数身份": "假设基线值", "说明": "BVD换能器端总电流暂定硬限值"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "current_measurement_expression", "数值": "mag(I(Rmot)+I(Cstatic))*sqrt(2)", "参数身份": "假设基线值", "说明": "5 mA约束测量位置；AC RMS相量换算为峰值"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "source_current_policy", "数值": "mag(I(Rlesr))*sqrt(2)", "参数身份": "假设基线值", "说明": "源侧电流另行记录，不套用5 mA约束"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "active_power_expression", "数值": "re(V(n_in)*conj(I(Rmot)))", "参数身份": "假设基线值", "说明": "运动支路有功功率"},
        {"case_id": "GLOBAL_MODEL_CONVENTION", "场景": "统一模型口径", "参数": "signed_phase_expression", "数值": "ph(V(n_s)/I(Rlesr))", "参数身份": "假设基线值", "说明": "使用Cartesian输出保留正负号"},
    ]
    for scenario in SCENARIOS:
        fs = 1.0 / (2.0 * np.pi * np.sqrt(scenario.bvd.lm * scenario.bvd.cm))
        values = {
            "C0_F": scenario.bvd.c0,
            "Rm_ohm": scenario.bvd.rm,
            "Lm_H": scenario.bvd.lm,
            "Cm_F": scenario.bvd.cm,
            "fs_derived_Hz": fs,
            "Rs_ohm": scenario.rs,
            "Ls_H": scenario.matching.ls,
            "Cp_F": scenario.matching.cp,
            "inductor_Q": scenario.matching.q_inductor,
            "inductor_ESR_at_0p9MHz_ohm": 2.0 * np.pi * F_FIXED * scenario.matching.ls / scenario.matching.q_inductor,
        }
        for name, value in values.items():
            rows.append({
                "case_id": scenario.case_id,
                "场景": scenario.label_zh,
                "参数": name,
                "数值": value,
                "参数身份": "假设基线值" if scenario.case_id == "CASE_000_BASELINE" else "扫描变量",
                "说明": scenario.description,
            })
    return rows


def write_ltspice_netlists(outdir):
    netdir = outdir / "ltspice_cases"
    netdir.mkdir(exist_ok=True)
    for s in SCENARIOS:
        q_esr = 2.0 * np.pi * F_FIXED * s.matching.ls / s.matching.q_inductor
        text = f"""* {s.case_id}: assumed 0.9 MHz BVD combination-disturbance case
* Complexity level: {s.complexity}
* AC amplitudes are interpreted as RMS phasors in this study.
V1 src 0 AC {VS_RMS:.9g}
Rsrc src n_s {s.rs:.9g}
Rlesr n_s n_l {q_esr:.9g}
Lmatch n_l n_in {s.matching.ls:.9g}
Cmatch n_in 0 {s.matching.cp:.9g}
Cstatic n_in 0 {s.bvd.c0:.9g}
Rmot n_in n_m1 {s.bvd.rm:.9g}
Lmot n_m1 n_m2 {s.bvd.lm:.9g}
Cmot n_m2 0 {s.bvd.cm:.9g}
.ac lin {N_FREQ} {F_MIN:.9g} {F_MAX:.9g}
* Total matching-network input impedance: V(n_s)/I(Rlesr)
* Transducer voltage: V(n_in)
* Transducer total terminal current: I(Rmot)+I(Cstatic)
* Transducer motional-branch current: I(Rmot)
* Transducer active power: re(V(n_in)*conj(I(Rmot)))
.options meascplxfmt=cartesian
.meas ac Zin_mag_fixed FIND mag(V(n_s)/I(Rlesr)) AT={F_FIXED:.9g}
.meas ac Zin_real_fixed FIND re(V(n_s)/I(Rlesr)) AT={F_FIXED:.9g}
.meas ac Zin_imag_fixed FIND im(V(n_s)/I(Rlesr)) AT={F_FIXED:.9g}
.meas ac Phase_fixed FIND ph(V(n_s)/I(Rlesr)) AT={F_FIXED:.9g}
.meas ac Vpp_fixed FIND mag(V(n_in))*2*sqrt(2) AT={F_FIXED:.9g}
.meas ac Itrans_peak_fixed FIND mag(I(Rmot)+I(Cstatic))*sqrt(2) AT={F_FIXED:.9g}
.meas ac Imot_peak_fixed FIND mag(I(Rmot))*sqrt(2) AT={F_FIXED:.9g}
.meas ac Isource_peak_fixed FIND mag(I(Rlesr))*sqrt(2) AT={F_FIXED:.9g}
.meas ac P_fixed FIND re(V(n_in)*conj(I(Rmot))) AT={F_FIXED:.9g}
.meas ac Gamma_fixed FIND mag((V(n_s)/I(Rlesr)-{s.rs:.9g})/(V(n_s)/I(Rlesr)+{s.rs:.9g})) AT={F_FIXED:.9g}
.meas ac Pmax MAX re(V(n_in)*conj(I(Rmot)))
.end
"""
        (netdir / f"{s.case_id}.cir").write_text(text, encoding="ascii")


def write_readme(outdir, features):
    lines = [
        "# 组合扰动实验结果说明",
        "",
        "本目录只描述假设BVD电学模型。所有参数、扰动等级、匹配元件和安全限值均不是实测值。",
        "",
        "## 固定0.9 MHz结果",
        "",
        "| 场景 | 功率 (mW) | 功率下降率 | 输入相位 (deg) | 相位偏离 (deg) | 电压 (Vpp) | BVD总电流 (mA peak) | 源电流 (mA peak) | |Gamma| | 匹配状态 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in features:
        lines.append(
            f"| {row['场景']} | {1000*row['固定频率功率_W']:.3f} | "
            f"{100*row['固定频率功率下降率']:.2f}% | {row['固定频率输入相位_deg']:.3f} | "
            f"{row['相位偏离_deg']:.3f} | {row['固定频率换能器电压_Vpp']:.3f} | "
            f"{1000*row['固定频率换能器电流_Apeak']:.3f} | "
            f"{1000*row['固定频率源电流_Apeak']:.3f} | "
            f"{row['固定频率反射代理_absGamma']:.4f} | {row['匹配状态_模型内部判据']} |"
        )
    lines.extend([
        "",
        "## 审核顺序",
        "",
        "1. 在参数登记CSV中确认每个case只包含计划内的参数变化。",
        "2. 抽查固定0.9 MHz行，手算功率下降率和相位偏离。",
        "3. 查看分场景曲线，确认频率漂移主要移动峰位，Rm增加主要改变峰高/峰宽。",
        "4. 用ltspice_cases中的网表复核任意一个场景。",
        "5. 报告中始终使用‘虚拟电学扰动’，不写成患者特异CTO负载。",
        "",
        "## 匹配状态的模型内部判据",
        "",
        "- 失效：固定0.9 MHz处|Gamma|>0.20，或|相位|>10 deg，或功率低于基准的80%。",
        "- 明显退化：未达到失效条件，但|Gamma|>0.10，或|相位|>5 deg，或功率低于基准的90%。",
        "- 其余记为未失效。该阈值仅用于虚拟模型内部比较，不是器件或临床标准。",
        "",
        "## 电流口径警告",
        "",
        "当前5/5.5/8 mA判断应用于BVD端总电流。匹配网络输入侧源电流约70-79 mA峰值，包含并联匹配电容的无功电流。源侧电流只单独记录，不套用5 mA约束。",
    ])
    (outdir / "README_组合扰动结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    configure_plot_style()
    outdir = Path(__file__).resolve().parent / "combination_disturbance_results"
    outdir.mkdir(exist_ok=True)

    results = {
        scenario.case_id: circuit_quantities(FREQUENCIES, scenario, VS_RMS)
        for scenario in SCENARIOS
    }
    base_q = results[SCENARIOS[0].case_id]
    fixed_idx = nearest_index(FREQUENCIES, F_FIXED)
    baseline_fixed = {
        "power": float(base_q["power"][fixed_idx]),
        "phase_deg": float(base_q["phase_deg"][fixed_idx]),
    }

    features = [
        extract_features(s, results[s.case_id], baseline_fixed)
        for s in SCENARIOS
    ]
    parameter_rows = make_parameter_rows()

    unmatched_results = {
        scenario.case_id: unmatched_quantities(FREQUENCIES, scenario, VS_UNMATCHED_RMS)
        for scenario in SCENARIOS
    }
    unmatched_base_power = float(unmatched_results[SCENARIOS[0].case_id]["power"][fixed_idx])
    unmatched_base_phase = float(unmatched_results[SCENARIOS[0].case_id]["phase_deg"][fixed_idx])
    unmatched_rows = []
    for scenario in SCENARIOS:
        q_unmatched = unmatched_results[scenario.case_id]
        p_fixed_unmatched = float(q_unmatched["power"][fixed_idx])
        unmatched_rows.append({
            "case_id": scenario.case_id,
            "场景": scenario.label_zh,
            "源电压_Vrms": VS_UNMATCHED_RMS,
            "固定频率_Hz": F_FIXED,
            "固定频率功率_W": p_fixed_unmatched,
            "功率下降率": 1.0 - p_fixed_unmatched / unmatched_base_power,
            "功率捕获率": p_fixed_unmatched / unmatched_base_power,
            "换能器阻抗相位_deg": float(q_unmatched["phase_deg"][fixed_idx]),
            "相位偏离_deg": float(q_unmatched["phase_deg"][fixed_idx]) - unmatched_base_phase,
            "换能器电压_Vpp": float(q_unmatched["vpp"][fixed_idx]),
            "换能器总电流_Apeak": float(q_unmatched["current_peak"][fixed_idx]),
            "反射代理_absGamma": float(q_unmatched["gamma"][fixed_idx]),
            "说明": "未加入L型匹配网络；各场景使用同一未匹配基准源幅值",
        })

    sweep_rows = []
    for scenario in SCENARIOS:
        q = results[scenario.case_id]
        for idx, freq in enumerate(FREQUENCIES):
            sweep_rows.append({
                "case_id": scenario.case_id,
                "场景": scenario.label_zh,
                "frequency_hz": float(freq),
                "zin_real_ohm": float(np.real(q["zin"][idx])),
                "zin_imag_ohm": float(np.imag(q["zin"][idx])),
                "zin_mag_ohm": float(abs(q["zin"][idx])),
                "phase_deg": float(q["phase_deg"][idx]),
                "transducer_vpp": float(q["vpp"][idx]),
                "transducer_current_a_peak": float(q["current_peak"][idx]),
                "motional_current_a_peak": float(q["motional_current_peak"][idx]),
                "source_current_a_peak": float(q["source_current_peak"][idx]),
                "active_power_w": float(q["power"][idx]),
                "matching_loss_w": float(q["match_loss"][idx]),
                "reflection_proxy_absGamma": float(q["gamma"][idx]),
            })

    write_csv(outdir / "组合扰动_参数登记.csv", parameter_rows)
    write_csv(outdir / "组合扰动_逐频数据.csv", sweep_rows)
    write_csv(outdir / "组合扰动_特征汇总.csv", features)
    write_csv(outdir / "组合扰动_未匹配对照.csv", unmatched_rows)

    manifest = {
        "model_scope": "assumed virtual electrical BVD model",
        "script": Path(__file__).name,
        "source_voltage_rms": VS_RMS,
        "unmatched_source_voltage_rms": VS_UNMATCHED_RMS,
        "baseline_target_vpp_at_0p9MHz": VPP_NOMINAL,
        "frequency_start_hz": F_MIN,
        "frequency_stop_hz": F_MAX,
        "frequency_points": N_FREQ,
        "frequency_step_hz": float(FREQUENCIES[1] - FREQUENCIES[0]),
        "constraints": {
            "voltage_nominal_vpp": VPP_NOMINAL,
            "voltage_soft_vpp": VPP_SOFT,
            "voltage_hard_vpp": VPP_HARD,
            "current_nominal_a_peak": IPEAK_NOMINAL,
            "current_soft_a_peak": IPEAK_SOFT,
            "current_hard_a_peak": IPEAK_HARD,
            "current_measurement_location": "BVD total terminal current: I(Rmot)+I(Cstatic)",
            "source_current_policy": "record separately; do not apply the 5 mA transducer constraint",
            "active_power_definition": "re(V(n_in)*conj(I(Rmot)))",
            "phase_definition": "signed Cartesian phase of V(n_s)/I(Rlesr)",
            "power_soft_ratio_to_baseline_fixed": 1.10,
            "power_hard_ratio_to_baseline_fixed": 1.25,
        },
        "scenarios": [
            {
                **asdict(s),
                "bvd": asdict(s.bvd),
                "matching": asdict(s.matching),
            }
            for s in SCENARIOS
        ],
    }
    (outdir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    magnitude_results = {
        key: {**value, "zin_mag": np.abs(value["zin"])}
        for key, value in results.items()
    }
    plot_separated(
        outdir,
        magnitude_results,
        "zin_mag",
        "|Zin| (ohm)",
        "组合扰动下的输入阻抗幅值：虚线为固定0.9 MHz",
        "组合扰动_输入阻抗_分场景",
    )
    plot_phase(outdir, results)
    plot_separated(
        outdir,
        results,
        "power",
        "有功功率 (mW)",
        "组合扰动下的换能器有功功率：峰位与峰高均可能变化",
        "组合扰动_有功功率_分场景",
        scale=1000.0,
    )
    plot_summary(outdir, features)
    plot_matched_unmatched(outdir, features, unmatched_rows)
    write_ltspice_netlists(outdir)
    write_readme(outdir, features)

    print(f"output_dir={outdir}")
    print(f"source_voltage_rms={VS_RMS:.9g}")
    for row in features:
        print(
            row["case_id"],
            f"P_fixed_mW={1000*row['固定频率功率_W']:.6f}",
            f"drop_pct={100*row['固定频率功率下降率']:.3f}",
            f"phase_shift_deg={row['相位偏离_deg']:.3f}",
        )


if __name__ == "__main__":
    main()
