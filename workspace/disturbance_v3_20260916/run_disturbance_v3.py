"""在 v3 空心圆柱基线上重建 34 场景扰动表。

v2.1 的同名表锚在 |Z(0.9 MHz)| = 7.071 kΩ 上，该工作点由 100 Vpp / 5 mA 反推，
导师澄清后失效，整表随之失效。本脚本【不覆盖】旧结果，另开批次目录。

    python3 workspace/disturbance_v3_20260916/run_disturbance_v3.py
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np

import model_v3 as M

GAMMA_SOFT = float(M.REG["drive_limits"]["GAMMA_SOFT"]["value"])
GAMMA_HARD = float(M.REG["drive_limits"]["GAMMA_HARD"]["value"])

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
FREQ = np.arange(M.F_MIN, M.F_MAX + 0.1, 100.0)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def phase_zero(f: np.ndarray, phase: np.ndarray) -> tuple[float, str]:
    sign = np.sign(phase)
    idx = np.where(sign[:-1] * sign[1:] <= 0)[0]
    if idx.size:
        vals = []
        for i in idx:
            if phase[i + 1] == phase[i]:
                vals.append((f[i] + f[i + 1]) / 2)
            else:
                vals.append(f[i] - phase[i] * (f[i + 1] - f[i]) / (phase[i + 1] - phase[i]))
        return float(min(vals, key=lambda x: abs(x - M.F0))), "ZERO_CROSSING"
    return float(f[int(np.argmin(np.abs(phase)))]), "MIN_ABS_PHASE_ONLY"


def summarise(s: M.Scenario) -> dict:
    q = M.response(FREQ, s)
    p = q["p_rm_W"]
    peak = int(np.argmax(p))
    width, width_status, left, right = M.half_power_width(FREQ, p)
    safe = M.safe_power(FREQ, s)
    si = int(np.argmax(safe))
    zb = np.abs(q["z_bvd"])
    fs_i, fp_i = int(np.argmin(zb)), int(np.argmax(zb))
    zmin, zmax = int(np.argmin(np.abs(q["z_in"]))), int(np.argmax(np.abs(q["z_in"])))
    zero_f, zero_status = phase_zero(FREQ, q["phase_deg"])
    at_f0 = M.point_metrics(M.F0, s)

    # 限幅触发诊断：在 f0 上，哪一条限值先咬住？
    unit = M.response(M.F0, s, amplitude=1.0)
    caps = {
        "source": M.SOURCE_MAX_AMPLITUDE,
        "V": M.VPP_SOFT / float(unit["vport_vpp"][0]),
        "I": M.IRMS_SOFT / float(unit["iport_irms_A"][0]),
        "P": math.sqrt(M.P_PORT_SOFT / float(unit["p_port_W"][0])),
    }
    binding = min(caps, key=caps.get)
    soft_a = float(M.allowed_amplitude(M.F0, s, use_soft_limits=True)[0])
    hard_a = float(M.allowed_amplitude(M.F0, s, use_soft_limits=False)[0])

    return {
        "case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level,
        "description": s.description,
        "C0_F": s.bvd.c0, "Rm_ohm": s.bvd.rm, "Lm_H": s.bvd.lm, "Cm_F": s.bvd.cm,
        "fs_Hz": s.bvd.fs, "Qm": s.bvd.qm, "Rs_ohm": s.rs,
        "Lmatch_H": s.matching.l_h, "Cmatch_F": s.matching.c_f,
        "inductor_Q": s.matching.ql, "capacitor_Q": s.matching.qc,
        "topology": s.matching.topology,
        "power_peak_Hz": float(FREQ[peak]), "power_peak_W": float(p[peak]),
        "power_FWHM_Hz": float(width), "power_FWHM_status": width_status,
        "power_half_left_Hz": float(left), "power_half_right_Hz": float(right),
        "safe_power_peak_Hz": float(FREQ[si]), "safe_power_peak_W": float(safe[si]),
        "zin_abs_min_Hz": float(FREQ[zmin]), "zin_abs_min_ohm": float(abs(q["z_in"][zmin])),
        "zin_abs_max_Hz": float(FREQ[zmax]), "zin_abs_max_ohm": float(abs(q["z_in"][zmax])),
        "fs_measured_Hz": float(FREQ[fs_i]), "zbvd_abs_min_ohm": float(zb[fs_i]),
        "fp_Hz": float(FREQ[fp_i]), "zbvd_abs_max_ohm": float(zb[fp_i]),
        "fp_minus_fs_Hz": float(FREQ[fp_i] - FREQ[fs_i]),
        "fp_theory_Hz": float(s.bvd.fs * math.sqrt(1 + s.bvd.cm / s.bvd.c0)),
        "cm_over_c0": float(s.bvd.cm / s.bvd.c0),
        "k_eff_percent": float(math.sqrt((s.bvd.cm / s.bvd.c0) / (1 + s.bvd.cm / s.bvd.c0)) * 100),
        "K_invariant": float(s.bvd.qm * s.bvd.cm / s.bvd.c0),
        "fs_offset_from_f0_Hz": float(s.bvd.fs - M.F0),
        "phase_zero_or_min_Hz": zero_f, "phase_feature_status": zero_status,
        "source_a1_Vrms": M.SOURCE_A1_VRMS,
        "soft_allowed_amplitude_at_f0": soft_a,
        "hard_allowed_amplitude_at_f0": hard_a,
        "binding_soft_limit_at_f0": binding,
        "cap_source": caps["source"], "cap_V": caps["V"], "cap_I": caps["I"], "cap_P": caps["P"],
        "gamma_at_f0": at_f0["gamma"],
        "vswr_at_f0": float((1 + at_f0["gamma"]) / (1 - at_f0["gamma"])) if at_f0["gamma"] < 1 else float("inf"),
        "vswr_ok_soft": at_f0["gamma"] <= GAMMA_SOFT,
        "vswr_ok_hard": at_f0["gamma"] <= GAMMA_HARD,
        "reflected_power_fraction": float(at_f0["gamma"] ** 2),
        "matched_50ohm_pm3": abs(at_f0["zin_abs_ohm"] - 50.0) <= 3.0,
        "phase_within_pm5deg": abs(at_f0["phase_deg"]) <= 5.0,
        **{f"at_f0_{k}": v for k, v in at_f0.items() if k != "frequency_Hz"},
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    scenarios = M.all_scenarios()
    rows = [summarise(s) for s in scenarios]
    write_csv(OUT / "stage3_disturbance_v3.csv", rows)

    balance = max(
        float(np.max(np.abs(M.response(FREQ, s)["power_balance_error_W"]))) for s in scenarios
    )

    fs_off = [abs(r["fs_offset_from_f0_Hz"]) for r in rows]
    fwhm = [r["power_FWHM_Hz"] for r in rows if r["power_FWHM_status"] == "OK"]
    out_of_window = [r["case_id"] for r in rows if r["power_FWHM_status"] != "OK"]
    binding = {}
    for r in rows:
        binding[r["binding_soft_limit_at_f0"]] = binding.get(r["binding_soft_limit_at_f0"], 0) + 1

    summary = {
        "batch": "disturbance_v3_20260916",
        "scenario_count": len(rows),
        "frequency_window_Hz": [float(M.F_MIN), float(M.F_MAX)],
        "frequency_step_Hz": 100.0,
        "max_power_balance_error_W": balance,
        "baseline": {
            "C0_pF": M.BASE_BVD.c0 * 1e12, "Cm_pF": M.BASE_BVD.cm * 1e12,
            "Lm_uH": M.BASE_BVD.lm * 1e6, "Rm_ohm": M.BASE_BVD.rm,
            "Qm": M.BASE_BVD.qm, "fs_Hz": M.BASE_BVD.fs,
            "z_bvd_at_f0_ohm": [M.z_bvd_at(M.F0, M.BASE_BVD).real, M.z_bvd_at(M.F0, M.BASE_BVD).imag],
            "match_topology": M.BASE_MATCH.topology,
            "Lmatch_uH": M.BASE_MATCH.l_h * 1e6, "Cmatch_nF": M.BASE_MATCH.c_f * 1e9,
            "source_a1_Vrms": M.SOURCE_A1_VRMS,
        },
        "fs_spread": {
            "max_abs_offset_from_f0_Hz": max(fs_off),
            "worst_cases": sorted(rows, key=lambda r: -abs(r["fs_offset_from_f0_Hz"]))[0]["case_id"],
        },
        "fwhm": {
            "min_Hz": min(fwhm), "median_Hz": float(np.median(fwhm)), "max_Hz": max(fwhm),
            "out_of_window_cases": out_of_window,
        },
        "binding_soft_limit_histogram": binding,
        "vswr": {
            "soft_threshold_gamma": GAMMA_SOFT, "hard_threshold_gamma": GAMMA_HARD,
            "cases_within_soft": sum(1 for r in rows if r["vswr_ok_soft"]),
            "cases_within_hard": sum(1 for r in rows if r["vswr_ok_hard"]),
            "cases_exceeding_hard": [r["case_id"] for r in rows if not r["vswr_ok_hard"]],
            "worst": max(rows, key=lambda r: r["gamma_at_f0"])["case_id"],
            "worst_gamma": max(r["gamma_at_f0"] for r in rows),
            "note": "在固定频率 f0 = 800 kHz、固定匹配网络下评估。超限场景全部是 fs 发生漂移的那些——"
                    "说明在 50 Ω 功放下，失谐的代价首先落在功放（反射），而不是换能器（过压过流）。",
        },
        "match_quality": {
            "cases_within_50ohm_pm3": sum(1 for r in rows if r["matched_50ohm_pm3"]),
            "cases_within_phase_pm5deg": sum(1 for r in rows if r["phase_within_pm5deg"]),
            "note": "判据取自 reference/前视超声治疗.pdf 的匹配容差 50 Ω±3 Ω、0°±5°；"
                    "在 f0 = 800 kHz 固定频率上评估，不做重新调谐。",
        },
    }
    (OUT / "summary_v3.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 104)
    print("v3 扰动表（空心圆柱 31 模 PZT-5H，OD/ID 1.35/0.73 mm，三次谐波 @ 0.8 MHz，50 Ω 源）")
    print("=" * 104)
    h = (f"{'场景':<20}{'fs(kHz)':>9}{'Δfs(kHz)':>9}{'Qm':>7}{'FWHM(kHz)':>10}"
         f"{'|Z|f0':>8}{'φ(°)':>7}{'Γ':>7}{'限值':>6}{'Vpp':>7}{'I(mA)':>8}{'P(mW)':>8}")
    print(h)
    for r in rows:
        print(f"{r['case_id']:<20}{r['fs_Hz']/1e3:>9.1f}{r['fs_offset_from_f0_Hz']/1e3:>9.1f}"
              f"{r['Qm']:>7.1f}{r['power_FWHM_Hz']/1e3:>10.2f}"
              f"{r['at_f0_zin_abs_ohm']:>8.1f}{r['at_f0_phase_deg']:>7.1f}{r['gamma_at_f0']:>7.3f}"
              f"{r['binding_soft_limit_at_f0']:>6}"
              f"{r['at_f0_vport_vpp']*r['soft_allowed_amplitude_at_f0']:>7.2f}"
              f"{r['at_f0_iport_irms_A']*r['soft_allowed_amplitude_at_f0']*1e3:>8.1f}"
              f"{r['at_f0_p_rm_W']*r['soft_allowed_amplitude_at_f0']**2*1e3:>8.1f}")
    print()
    print(f"功率平衡最大残差 {balance:.3e} W")
    print(f"fs 最大偏移 {max(fs_off)/1e3:.1f} kHz；FWHM 中位数 {np.median(fwhm)/1e3:.2f} kHz "
          f"（v2.1 基线为 1.74 kHz）")
    print(f"软限触发分布：{binding}")
    print(f"匹配容差内（50 Ω±3 Ω）：{summary['match_quality']['cases_within_50ohm_pm3']}/34；"
          f"相位 0°±5°：{summary['match_quality']['cases_within_phase_pm5deg']}/34")
    v = summary["vswr"]
    print(f"驻波比：Γ<=0.333(VSWR 2:1) {v['cases_within_soft']}/34；"
          f"Γ<=0.5(VSWR 3:1) {v['cases_within_hard']}/34；"
          f"最差 {v['worst']} Γ={v['worst_gamma']:.3f}")
    print(f"超硬阈值场景：{v['cases_exceeding_hard']}")
    if out_of_window:
        print(f"半功率点落在扫描窗外的场景：{out_of_window}")
    print(f"\n已写入 {OUT}")


if __name__ == "__main__":
    main()
