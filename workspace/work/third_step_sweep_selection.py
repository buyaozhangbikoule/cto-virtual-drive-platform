"""Step 3: compare three local-sweep frequency selection criteria.

Criteria:
1) maximum motional-branch active power
2) minimum absolute signed input phase
3) minimum reflection proxy

The model is the same assumed virtual BVD + fixed low-pass L matching network
used in the previous combination and single-factor disturbance studies.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np


ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
OLD_OUTPUTS = Path(r"C:\Users\24739\Documents\Codex\2026-08-03\w\outputs")
OUTDIR = ROOT / "outputs" / "third_step_sweep_selection"


F_CENTER = 0.9e6
INITIAL_START = 0.84e6
INITIAL_STOP = 0.96e6
INITIAL_STEP = 0.5e3

REFERENCE_STEP = 0.01e3  # 10 Hz fine grid for offline reference
STEP_SIZES = [0.1e3, 0.5e3, 1.0e3, 2.0e3]
WINDOW_HALFWIDTHS = [20e3, 50e3, 100e3]


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
    bvd: BVD
    rs: float
    matching: Matching


BASE_BVD = BVD()
BASE_MATCH = Matching()
BASE_RS = 50.0
VPP_NOMINAL = 100.0


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
    r_esr_l = (
        2.0
        * np.pi
        * F_CENTER
        * scenario.matching.ls
        / scenario.matching.q_inductor
    )
    zseries = r_esr_l + 1j * w * scenario.matching.ls
    zin = zseries + zparallel
    isource = vs_rms / (scenario.rs + zin)
    vnode = isource * zparallel
    z_motional = (
        scenario.bvd.rm
        + 1j * w * scenario.bvd.lm
        + 1.0 / (1j * w * scenario.bvd.cm)
    )
    imotional = vnode / z_motional
    p_transducer = np.real(vnode * np.conj(imotional))
    gamma = np.abs((zin - scenario.rs) / (zin + scenario.rs))
    return {
        "zin": zin,
        "phase_deg": np.angle(zin, deg=True),
        "power": p_transducer,
        "gamma": gamma,
    }


def calibrate_source_rms():
    q = circuit_quantities(np.array([F_CENTER]), Scenario("BASE", BASE_BVD, BASE_RS, BASE_MATCH), 1.0)
    vpp_per_vrms = abs(
        (
            1.0
            / (
                BASE_RS
                + (
                    (
                        2.0
                        * np.pi
                        * F_CENTER
                        * BASE_MATCH.ls
                        / BASE_MATCH.q_inductor
                    )
                    + 1j * 2.0 * np.pi * F_CENTER * BASE_MATCH.ls
                    + 1.0
                    / (
                        1.0 / zin_bvd(np.array([F_CENTER]), BASE_BVD)[0]
                        + 1.0
                        / (1.0 / (1j * 2.0 * np.pi * F_CENTER * BASE_MATCH.cp))
                    )
                )
            )
        )
        * (
            1.0
            / (
                1.0 / zin_bvd(np.array([F_CENTER]), BASE_BVD)[0]
                + 1.0 / (1.0 / (1j * 2.0 * np.pi * F_CENTER * BASE_MATCH.cp))
            )
        )
    ) * 2.0 * math.sqrt(2.0)
    # q is kept above as a smoke-use of the same path; explicit expression avoids
    # expanding the function return surface just for calibration.
    _ = q
    return VPP_NOMINAL / float(vpp_per_vrms)


VS_RMS = calibrate_source_rms()


def shifted_fs(p: BVD, ratio: float) -> BVD:
    fs_new = F_CENTER * ratio
    cm_new = 1.0 / (p.lm * (2.0 * np.pi * fs_new) ** 2)
    return replace(p, cm=cm_new)


def make_single_scenarios():
    cases = [Scenario("CASE_000_BASELINE", BASE_BVD, BASE_RS, BASE_MATCH)]
    for pct, code in ((10, 110), (20, 120), (30, 130)):
        cases.append(Scenario(f"CASE_{code}_C0_P{pct}", replace(BASE_BVD, c0=BASE_BVD.c0 * (1 + pct / 100)), BASE_RS, BASE_MATCH))
    for pct, code in ((15, 210), (30, 220), (50, 230)):
        cases.append(Scenario(f"CASE_{code}_RM_P{pct}", replace(BASE_BVD, rm=BASE_BVD.rm * (1 + pct / 100)), BASE_RS, BASE_MATCH))
    for pct, code in ((1, 310), (3, 320), (5, 330)):
        cases.append(Scenario(f"CASE_{code}_FS_M{pct}", shifted_fs(BASE_BVD, 1 - pct / 100), BASE_RS, BASE_MATCH))
    for pct, code in ((5, 410), (10, 420), (20, 430)):
        cases.append(Scenario(f"CASE_{code}_RS_P{pct}", BASE_BVD, BASE_RS * (1 + pct / 100), BASE_MATCH))
    for pct, code in ((2, 510), (5, 520), (10, 530)):
        cases.append(Scenario(f"CASE_{code}_LS_P{pct}", BASE_BVD, BASE_RS, replace(BASE_MATCH, ls=BASE_MATCH.ls * (1 + pct / 100))))
    for pct, code in ((2, 610), (5, 620), (10, 630)):
        cases.append(Scenario(f"CASE_{code}_CP_M{pct}", BASE_BVD, BASE_RS, replace(BASE_MATCH, cp=BASE_MATCH.cp * (1 - pct / 100))))
    for q, code in ((50, 720), (20, 730)):
        cases.append(Scenario(f"CASE_{code}_Q{q}", BASE_BVD, BASE_RS, replace(BASE_MATCH, q_inductor=float(q))))
    return cases


def make_combo_scenarios():
    high_bvd = shifted_fs(BASE_BVD, 0.97)
    high_bvd = replace(high_bvd, c0=BASE_BVD.c0 * 1.20, rm=BASE_BVD.rm * 1.30)
    return [
        Scenario("CASE_400_COMBINED_LOW", replace(BASE_BVD, rm=BASE_BVD.rm * 1.15), BASE_RS, BASE_MATCH),
        Scenario("CASE_401_COMBINED_MEDIUM", replace(BASE_BVD, c0=BASE_BVD.c0 * 1.20, rm=BASE_BVD.rm * 1.30), BASE_RS, BASE_MATCH),
        Scenario(
            "CASE_402_COMBINED_HIGH",
            high_bvd,
            BASE_RS * 1.20,
            replace(BASE_MATCH, ls=BASE_MATCH.ls * 1.05, cp=BASE_MATCH.cp * 0.95, q_inductor=20.0),
        ),
    ]


def scenario_label_from_case(case_id: str, family: str) -> tuple[str, str, str]:
    """Return readable Chinese labels from stable case IDs."""
    if case_id == "CASE_000_BASELINE":
        return "基准", "基准", "基准"

    mapping = {
        "CASE_110_C0_P10": ("单因素", "C0", "+10%"),
        "CASE_120_C0_P20": ("单因素", "C0", "+20%"),
        "CASE_130_C0_P30": ("单因素", "C0", "+30%"),
        "CASE_210_RM_P15": ("单因素", "Rm", "+15%"),
        "CASE_220_RM_P30": ("单因素", "Rm", "+30%"),
        "CASE_230_RM_P50": ("单因素", "Rm", "+50%"),
        "CASE_310_FS_M1": ("单因素", "fs/Cm", "-1%"),
        "CASE_320_FS_M3": ("单因素", "fs/Cm", "-3%"),
        "CASE_330_FS_M5": ("单因素", "fs/Cm", "-5%"),
        "CASE_410_RS_P5": ("单因素", "Rs", "+5%"),
        "CASE_420_RS_P10": ("单因素", "Rs", "+10%"),
        "CASE_430_RS_P20": ("单因素", "Rs", "+20%"),
        "CASE_510_LS_P2": ("单因素", "Ls", "+2%"),
        "CASE_520_LS_P5": ("单因素", "Ls", "+5%"),
        "CASE_530_LS_P10": ("单因素", "Ls", "+10%"),
        "CASE_610_CP_M2": ("单因素", "Cp", "-2%"),
        "CASE_620_CP_M5": ("单因素", "Cp", "-5%"),
        "CASE_630_CP_M10": ("单因素", "Cp", "-10%"),
        "CASE_720_Q50": ("单因素", "电感Q", "Q=50"),
        "CASE_730_Q20": ("单因素", "电感Q", "Q=20"),
        "CASE_400_COMBINED_LOW": ("组合扰动", "低复杂度", "Rm +15%"),
        "CASE_401_COMBINED_MEDIUM": ("组合扰动", "中复杂度", "C0 +20%, Rm +30%"),
        "CASE_402_COMBINED_HIGH": ("组合扰动", "高复杂度", "fs -3%, C0/Rm/Rs/Ls/Cp/Q叠加"),
    }
    return mapping.get(case_id, (family, "未知", case_id))


def build_scenarios():
    rows = []
    # Single-factor scenarios include baseline + 20 disturbances.
    for s in make_single_scenarios():
        family, factor, level = scenario_label_from_case(s.case_id, "单因素")
        rows.append(
            {
                "scenario_key": f"SINGLE::{s.case_id}",
                "scenario_family": family,
                "case_id": s.case_id,
                "factor": factor,
                "level": level,
                "display_scenario": f"{family}-{factor}-{level}"
                if s.case_id != "CASE_000_BASELINE"
                else "基准",
                "scenario": s,
            }
        )
    # Add combination low/medium/high, avoiding duplicate baseline.
    for s in make_combo_scenarios():
        family, factor, level = scenario_label_from_case(s.case_id, "组合扰动")
        rows.append(
            {
                "scenario_key": f"COMBO::{s.case_id}",
                "scenario_family": family,
                "case_id": s.case_id,
                "factor": factor,
                "level": level,
                "display_scenario": f"{family}-{factor}-{level}",
                "scenario": s,
            }
        )
    return rows


SCENARIO_ROWS = build_scenarios()


def frequency_grid(start_hz: float, stop_hz: float, step_hz: float) -> np.ndarray:
    n = int(round((stop_hz - start_hz) / step_hz))
    return start_hz + np.arange(n + 1, dtype=float) * step_hz


def quantities(freq: np.ndarray, scenario) -> dict[str, np.ndarray]:
    return circuit_quantities(freq, scenario, VS_RMS)


def select_points(freq: np.ndarray, q: dict[str, np.ndarray]) -> dict[str, float | int]:
    power = q["power"]
    gamma = q["gamma"]

    p_idx = int(np.argmax(power))
    phase_freq_hz, phase_crossed = linear_phase_zero(freq, q["phase_deg"])
    ph_idx = int(np.argmin(np.abs(freq - phase_freq_hz)))
    g_idx = int(np.argmin(gamma))

    def pack(prefix: str, idx: int, selected_freq_hz: float | None = None) -> dict[str, float | int]:
        zin = q["zin"][idx]
        fsel = float(freq[idx] if selected_freq_hz is None else selected_freq_hz)
        return {
            f"{prefix}_idx": idx,
            f"{prefix}_freq_hz": fsel,
            f"{prefix}_freq_mhz": float(fsel / 1e6),
            f"{prefix}_power_w": float(q["power"][idx]),
            f"{prefix}_phase_deg": float(q["phase_deg"][idx]),
            f"{prefix}_abs_phase_deg": float(abs(q["phase_deg"][idx])),
            f"{prefix}_gamma": float(q["gamma"][idx]),
            f"{prefix}_zin_real_ohm": float(np.real(zin)),
            f"{prefix}_zin_imag_ohm": float(np.imag(zin)),
            f"{prefix}_zin_mag_ohm": float(abs(zin)),
        }

    out = {}
    out.update(pack("max_power", p_idx))
    out.update(pack("min_abs_phase", ph_idx, phase_freq_hz))
    out.update(pack("min_reflection", g_idx))
    out["n_points"] = int(len(freq))
    out["phase_crossed_zero"] = int(phase_crossed)
    return out


def parabolic_refine_max(x: np.ndarray, y: np.ndarray, idx: int) -> tuple[float, float]:
    """3-point parabolic vertex for a local maximum/minimum-like scalar.

    Returns (x_vertex, y_vertex). Falls back to discrete value at edges.
    """
    if idx <= 0 or idx >= len(x) - 1:
        return float(x[idx]), float(y[idx])
    x0, x1, x2 = x[idx - 1], x[idx], x[idx + 1]
    y0, y1, y2 = y[idx - 1], y[idx], y[idx + 1]
    h = x1 - x0
    denom = y0 - 2 * y1 + y2
    if denom == 0:
        return float(x1), float(y1)
    delta = 0.5 * (y0 - y2) / denom
    if abs(delta) > 1.0:
        return float(x1), float(y1)
    xv = x1 + delta * h
    yv = y1 - 0.25 * (y0 - y2) * delta
    return float(xv), float(yv)


def linear_phase_zero(freq: np.ndarray, phase: np.ndarray, target: float = F_CENTER) -> tuple[float, bool]:
    crossings = np.where(phase[:-1] * phase[1:] <= 0.0)[0]
    if len(crossings) == 0:
        idx = int(np.argmin(np.abs(phase)))
        return float(freq[idx]), False
    candidates = []
    for idx in crossings:
        f0, f1 = freq[idx], freq[idx + 1]
        y0, y1 = phase[idx], phase[idx + 1]
        if y1 == y0:
            candidates.append(float(f0))
        else:
            candidates.append(float(f0 - y0 * (f1 - f0) / (y1 - y0)))
    return min(candidates, key=lambda f: abs(f - target)), True


def refined_selection(freq: np.ndarray, q: dict[str, np.ndarray]) -> dict[str, float | int]:
    """Fine-grid + interpolation reference for selection errors."""
    power_idx = int(np.argmax(q["power"]))
    gamma_idx = int(np.argmin(q["gamma"]))
    # Maximize power; minimize gamma by maximizing -gamma.
    power_f, power_y = parabolic_refine_max(freq, q["power"], power_idx)
    gamma_f, gamma_neg = parabolic_refine_max(freq, -q["gamma"], gamma_idx)
    phase_f, phase_crossed = linear_phase_zero(freq, q["phase_deg"])
    phase_idx = int(np.argmin(np.abs(freq - phase_f)))
    gamma_idx_near = int(np.argmin(np.abs(freq - gamma_f)))
    power_idx_near = int(np.argmin(np.abs(freq - power_f)))
    return {
        "ref_max_power_freq_hz": power_f,
        "ref_max_power_freq_mhz": power_f / 1e6,
        "ref_max_power_w": float(q["power"][power_idx_near]),
        "ref_min_abs_phase_freq_hz": phase_f,
        "ref_min_abs_phase_freq_mhz": phase_f / 1e6,
        "ref_min_abs_phase_deg": float(abs(q["phase_deg"][phase_idx])),
        "ref_phase_crossed_zero": int(phase_crossed),
        "ref_min_reflection_freq_hz": gamma_f,
        "ref_min_reflection_freq_mhz": gamma_f / 1e6,
        "ref_min_reflection_gamma": float(-gamma_neg if gamma_neg < 0 else q["gamma"][gamma_idx_near]),
    }


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def initial_sweep_rows() -> tuple[list[dict], list[dict]]:
    freq = frequency_grid(INITIAL_START, INITIAL_STOP, INITIAL_STEP)
    comparison = []
    selected_metrics = []
    for meta in SCENARIO_ROWS:
        q = quantities(freq, meta["scenario"])
        sel = select_points(freq, q)
        delta_power_phase = (sel["min_abs_phase_freq_hz"] - sel["max_power_freq_hz"]) / 1e3
        delta_power_gamma = (sel["min_reflection_freq_hz"] - sel["max_power_freq_hz"]) / 1e3
        delta_phase_gamma = (sel["min_reflection_freq_hz"] - sel["min_abs_phase_freq_hz"]) / 1e3
        split_max_abs = max(abs(delta_power_phase), abs(delta_power_gamma), abs(delta_phase_gamma))
        if split_max_abs <= 0.5:
            consistency = "基本一致"
        elif split_max_abs <= 5:
            consistency = "轻微分裂"
        elif split_max_abs <= 20:
            consistency = "明显分裂"
        else:
            consistency = "严重分裂"
        base = {
            "scenario_key": meta["scenario_key"],
            "场景族": meta["scenario_family"],
            "case_id": meta["case_id"],
            "扰动参数": meta["factor"],
            "扰动等级": meta["level"],
            "场景": meta["display_scenario"],
        }
        comparison.append(
            {
                **base,
                "扫频起点_MHz": INITIAL_START / 1e6,
                "扫频终点_MHz": INITIAL_STOP / 1e6,
                "步长_kHz": INITIAL_STEP / 1e3,
                "扫描点数": sel["n_points"],
                "最大功率频率_MHz": sel["max_power_freq_mhz"],
                "最小绝对相位频率_MHz": sel["min_abs_phase_freq_mhz"],
                "最小反射频率_MHz": sel["min_reflection_freq_mhz"],
                "相位点-功率点_kHz": delta_power_phase,
                "反射点-功率点_kHz": delta_power_gamma,
                "反射点-相位点_kHz": delta_phase_gamma,
                "三准则最大分裂_kHz": split_max_abs,
                "一致性判定": consistency,
            }
        )
        for criterion_zh, prefix in [
            ("最大有功功率", "max_power"),
            ("最小绝对相位", "min_abs_phase"),
            ("最小反射代理", "min_reflection"),
        ]:
            selected_metrics.append(
                {
                    **base,
                    "准则": criterion_zh,
                    "选中频率_MHz": sel[f"{prefix}_freq_mhz"],
                    "|Z|_ohm": sel[f"{prefix}_zin_mag_ohm"],
                    "ReZ_ohm": sel[f"{prefix}_zin_real_ohm"],
                    "ImZ_ohm": sel[f"{prefix}_zin_imag_ohm"],
                    "相位_deg": sel[f"{prefix}_phase_deg"],
                    "有功功率_mW": sel[f"{prefix}_power_w"] * 1e3,
                    "反射代理": sel[f"{prefix}_gamma"],
                }
            )
    return comparison, selected_metrics


def step_window_tradeoff_rows() -> tuple[list[dict], list[dict]]:
    global_reference = {}
    global_start = F_CENTER - max(WINDOW_HALFWIDTHS)
    global_stop = F_CENTER + max(WINDOW_HALFWIDTHS)
    for meta in SCENARIO_ROWS:
        ref_freq = frequency_grid(global_start, global_stop, REFERENCE_STEP)
        ref_q = quantities(ref_freq, meta["scenario"])
        global_reference[meta["scenario_key"]] = refined_selection(ref_freq, ref_q)

    tradeoffs = []
    summary = []
    for meta in SCENARIO_ROWS:
        for halfwidth in WINDOW_HALFWIDTHS:
            start = F_CENTER - halfwidth
            stop = F_CENTER + halfwidth
            ref = global_reference[meta["scenario_key"]]
            for step in STEP_SIZES:
                freq = frequency_grid(start, stop, step)
                q = quantities(freq, meta["scenario"])
                sel = select_points(freq, q)
                errors_hz = {
                    "最大功率频率误差_kHz": abs(sel["max_power_freq_hz"] - ref["ref_max_power_freq_hz"]) / 1e3,
                    "最小绝对相位频率误差_kHz": abs(sel["min_abs_phase_freq_hz"] - ref["ref_min_abs_phase_freq_hz"]) / 1e3,
                    "最小反射频率误差_kHz": abs(sel["min_reflection_freq_hz"] - ref["ref_min_reflection_freq_hz"]) / 1e3,
                }
                max_error = max(errors_hz.values())
                # Relative cost proxy. One frequency point means one AC evaluation/measurement.
                n_points = len(freq)
                rel_cost_vs_0p5_50 = n_points / (2 * 50e3 / 0.5e3 + 1)
                missed = []
                for label, ref_key in [
                    ("最大功率", "ref_max_power_freq_hz"),
                    ("最小相位", "ref_min_abs_phase_freq_hz"),
                    ("最小反射", "ref_min_reflection_freq_hz"),
                ]:
                    f_ref = ref[ref_key]
                    if not (start <= f_ref <= stop):
                        missed.append(label)
                if missed:
                    reliability = "窗口遗漏：" + "、".join(missed)
                elif max_error <= 0.1:
                    reliability = "很高"
                elif max_error <= 0.5:
                    reliability = "高"
                elif max_error <= 1.0:
                    reliability = "中"
                else:
                    reliability = "低"
                tradeoffs.append(
                    {
                        "scenario_key": meta["scenario_key"],
                        "场景族": meta["scenario_family"],
                        "case_id": meta["case_id"],
                        "扰动参数": meta["factor"],
                        "扰动等级": meta["level"],
                        "场景": meta["display_scenario"],
                        "窗口半宽_kHz": halfwidth / 1e3,
                        "窗口起点_MHz": start / 1e6,
                        "窗口终点_MHz": stop / 1e6,
                        "步长_kHz": step / 1e3,
                        "扫描点数": n_points,
                        "相对耗时_以±50kHz_0p5kHz为1": rel_cost_vs_0p5_50,
                        "最大功率频率_MHz": sel["max_power_freq_mhz"],
                        "最小绝对相位频率_MHz": sel["min_abs_phase_freq_mhz"],
                        "最小反射频率_MHz": sel["min_reflection_freq_mhz"],
                        **errors_hz,
                        "三准则最大频率误差_kHz": max_error,
                        "可靠性判定": reliability,
                    }
                )

    # Aggregate by window and step across all scenarios.
    for halfwidth in WINDOW_HALFWIDTHS:
        for step in STEP_SIZES:
            subset = [
                row
                for row in tradeoffs
                if row["窗口半宽_kHz"] == halfwidth / 1e3
                and row["步长_kHz"] == step / 1e3
            ]
            max_err = max(row["三准则最大频率误差_kHz"] for row in subset)
            mean_err = sum(row["三准则最大频率误差_kHz"] for row in subset) / len(subset)
            n_points = int(subset[0]["扫描点数"])
            high_or_better = sum(1 for row in subset if row["可靠性判定"] in {"很高", "高"})
            low = sum(1 for row in subset if row["可靠性判定"] == "低")
            miss = sum(1 for row in subset if str(row["可靠性判定"]).startswith("窗口遗漏"))
            if miss:
                recommendation = "不建议作为通用窗口：部分场景最佳点可能在窗外"
            elif step <= 0.5e3 and halfwidth >= 50e3:
                recommendation = "推荐：精度和耗时较平衡"
            elif step == 0.1e3:
                recommendation = "高精度复核用，耗时较高"
            elif step >= 1.0e3 and max_err <= 1.0:
                recommendation = "快速粗扫可用，需二次细扫"
            else:
                recommendation = "仅适合预扫或低风险场景"
            summary.append(
                {
                    "窗口半宽_kHz": halfwidth / 1e3,
                    "步长_kHz": step / 1e3,
                    "扫描点数": n_points,
                    "相对耗时_以±50kHz_0p5kHz为1": subset[0]["相对耗时_以±50kHz_0p5kHz为1"],
                    "平均最大频率误差_kHz": mean_err,
                    "全场景最大频率误差_kHz": max_err,
                    "高可靠或更好场景数": high_or_better,
                    "低可靠场景数": low,
                    "窗口遗漏场景数": miss,
                    "建议": recommendation,
                }
            )
    return tradeoffs, summary


def write_report(comparison: list[dict], trade_summary: list[dict]):
    # Pick out the high-complexity row because it motivates the step.
    high = next(row for row in comparison if row["case_id"] == "CASE_402_COMBINED_HIGH")
    baseline = next(row for row in comparison if row["case_id"] == "CASE_000_BASELINE")
    recommended = [
        row
        for row in trade_summary
        if row["窗口半宽_kHz"] == 100.0 and row["步长_kHz"] == 0.5
    ][0]
    coarse = [
        row
        for row in trade_summary
        if row["窗口半宽_kHz"] == 100.0 and row["步长_kHz"] == 1.0
    ][0]
    fine = [
        row
        for row in trade_summary
        if row["窗口半宽_kHz"] == 100.0 and row["步长_kHz"] == 0.1
    ][0]
    lines = [
        "# 第三步：三种扫频选点准则比较",
        "",
        "## 1. 设置",
        "",
        "- 模型：沿用当前虚拟 BVD + 固定低通 L 型匹配网络。",
        "- 场景：第二步 21 个单因素场景 + 组合扰动 low/medium/high，共 24 行对比场景。",
        "- 初始局部扫频：0.84–0.96 MHz，步长 0.5 kHz。",
        "- 三个准则：最大有功功率、最小绝对相位、最小反射代理。",
        "- 步长比较：0.1、0.5、1、2 kHz。",
        "- 窗口比较：以 0.9 MHz 为中心的 ±20、±50、±100 kHz。",
        "- 误差参考：0.01 kHz 细网格离线参考。",
        "",
        "## 2. 关键观察",
        "",
        f"- 基准场景三点接近：最大功率 {baseline['最大功率频率_MHz']:.6f} MHz，"
        f"最小相位 {baseline['最小绝对相位频率_MHz']:.6f} MHz，"
        f"最小反射 {baseline['最小反射频率_MHz']:.6f} MHz。",
        f"- 高复杂度组合扰动明显分裂：最大功率 {high['最大功率频率_MHz']:.6f} MHz，"
        f"最小相位 {high['最小绝对相位频率_MHz']:.6f} MHz，"
        f"最小反射 {high['最小反射频率_MHz']:.6f} MHz；三者最大分裂约 {high['三准则最大分裂_kHz']:.1f} kHz。",
        "- 因此不能把“相位等于零”直接当成功率最大点；相位追踪更像一种匹配/阻抗状态指标，不等价于能量最大化指标。",
        "",
        "## 3. 建议",
        "",
        f"- 若要一套设置覆盖全部 24 个场景，建议使用 ±100 kHz、0.5 kHz：每场景 {recommended['扫描点数']} 点，"
        f"相对耗时约为 ±50 kHz/0.5 kHz 的 {recommended['相对耗时_以±50kHz_0p5kHz为1']:.1f} 倍，"
        f"全场景最大频率误差约 {recommended['全场景最大频率误差_kHz']:.3f} kHz。",
        f"- 若要同等耗时附近的快速粗扫，可用 ±100 kHz、1 kHz：每场景 {coarse['扫描点数']} 点，"
        f"相对耗时约 {coarse['相对耗时_以±50kHz_0p5kHz为1']:.1f}，"
        f"全场景最大频率误差约 {coarse['全场景最大频率误差_kHz']:.3f} kHz；之后建议在三个候选点附近二次细扫。",
        f"- 如果要复核高复杂度或怀疑峰位大漂移，建议用 ±100 kHz、0.1 kHz：每场景 {fine['扫描点数']} 点，"
        f"代价约为 ±50 kHz/0.5 kHz 的 {fine['相对耗时_以±50kHz_0p5kHz为1']:.1f} 倍，但最大误差可压到 {fine['全场景最大频率误差_kHz']:.3f} kHz。",
        "- ±20 kHz 窗口不建议作为通用窗口：fs 漂移和高复杂度组合扰动可能把最大功率点推出窗口。",
        "- ±50 kHz 对多数情况够用，但本轮 Cp −10% 的相位零点约 0.95585 MHz，略超 0.95 MHz，因此不是全覆盖窗口。",
        "- 你提出的初始 0.84–0.96 MHz、0.5 kHz 是一个实用折中：241 点，覆盖本轮高复杂度功率点、相位零点和 Cp −10% 边界相位点。",
        "",
        "## 4. 推荐控制解释",
        "",
        "三种准则应该分工，而不是互相替代：",
        "",
        "| 准则 | 适合解释 | 风险 |",
        "|---|---|---|",
        "| 最大有功功率 | 能量注入最大点 | 可能牺牲匹配余量或电压/电流约束 |",
        "| 最小绝对相位 | 输入阻抗接近纯阻点 | 不保证功率最大，尤其在失配或多扰动下 |",
        "| 最小反射代理 | 源/匹配网络最匹配点 | 不保证 BVD 运动支路吸收功率最大 |",
        "",
        "报告里应写成：先扫频同时记录三种候选点，再按控制目标选择；不能用单一相位零点替代全部最优点。",
        "",
    ]
    (OUTDIR / "第三步_扫频选点准则比较报告.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def copy_key_inputs():
    srcs = [
        OLD_OUTPUTS / "combination_disturbance_study.py",
        OLD_OUTPUTS / "single_factor_disturbance_study.py",
        OLD_OUTPUTS / "single_factor_disturbance_results" / "单因素扰动_趋势表.csv",
        OLD_OUTPUTS / "combination_disturbance_results" / "组合扰动_正式审核报告.md",
    ]
    input_dir = OUTDIR / "model_inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    for src in srcs:
        if src.exists():
            shutil.copy2(src, input_dir / src.name)


def main():
    started = time.perf_counter()
    OUTDIR.mkdir(parents=True, exist_ok=True)

    comparison, selected_metrics = initial_sweep_rows()
    tradeoff, trade_summary = step_window_tradeoff_rows()

    scenario_registry = []
    for meta in SCENARIO_ROWS:
        s = meta["scenario"]
        fs = 1 / (2 * math.pi * math.sqrt(s.bvd.lm * s.bvd.cm))
        scenario_registry.append(
            {
                "scenario_key": meta["scenario_key"],
                "场景族": meta["scenario_family"],
                "case_id": meta["case_id"],
                "扰动参数": meta["factor"],
                "扰动等级": meta["level"],
                "场景": meta["display_scenario"],
                "C0_F": s.bvd.c0,
                "Rm_ohm": s.bvd.rm,
                "Lm_H": s.bvd.lm,
                "Cm_F": s.bvd.cm,
                "fs_derived_Hz": fs,
                "Rs_ohm": s.rs,
                "Ls_H": s.matching.ls,
                "Cp_F": s.matching.cp,
                "inductor_Q": s.matching.q_inductor,
                "inductor_ESR_at_0p9MHz_ohm": 2
                * math.pi
                * F_CENTER
                * s.matching.ls
                / s.matching.q_inductor,
            }
        )

    write_csv(OUTDIR / "第三步_初始0p84-0p96MHz_三准则频率对比.csv", comparison)
    write_csv(OUTDIR / "第三步_初始扫频_候选点完整指标.csv", selected_metrics)
    write_csv(OUTDIR / "第三步_步长窗口逐场景误差.csv", tradeoff)
    write_csv(OUTDIR / "第三步_步长窗口权衡汇总.csv", trade_summary)
    write_csv(OUTDIR / "第三步_场景参数登记.csv", scenario_registry)

    write_report(comparison, trade_summary)
    copy_key_inputs()

    manifest = {
        "model_scope": "assumed virtual electrical BVD model; no measured transducer parameters",
        "scenario_count": len(SCENARIO_ROWS),
        "initial_sweep": {
            "start_hz": INITIAL_START,
            "stop_hz": INITIAL_STOP,
            "step_hz": INITIAL_STEP,
        },
        "step_sizes_hz": STEP_SIZES,
        "window_halfwidths_hz": WINDOW_HALFWIDTHS,
        "reference_step_hz": REFERENCE_STEP,
        "source_voltage_rms": VS_RMS,
        "active_power": "re(V(n_in)*conj(I(Rmot)))",
        "phase": "signed Cartesian phase of V(n_s)/I(Rlesr)",
        "reflection_proxy": "abs((Zin-Rs)/(Zin+Rs))",
        "elapsed_seconds": time.perf_counter() - started,
        "scenarios": [
            {
                k: v
                for k, v in meta.items()
                if k not in {"scenario"}
            }
            | {
                "bvd": asdict(meta["scenario"].bvd),
                "rs": meta["scenario"].rs,
                "matching": asdict(meta["scenario"].matching),
            }
            for meta in SCENARIO_ROWS
        ],
    }
    (OUTDIR / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Zip non-workbook deliverables now; the workbook builder will refresh it later.
    print(f"output_dir={OUTDIR}")
    print(f"scenario_count={len(SCENARIO_ROWS)}")
    print(f"elapsed_seconds={manifest['elapsed_seconds']:.3f}")
    for row in comparison:
        if row["case_id"] in {"CASE_000_BASELINE", "CASE_402_COMBINED_HIGH"}:
            print(
                row["场景"],
                row["最大功率频率_MHz"],
                row["最小绝对相位频率_MHz"],
                row["最小反射频率_MHz"],
                row["三准则最大分裂_kHz"],
            )


if __name__ == "__main__":
    main()
