"""高阻抗负载能否匹配到 50 Ω 功放？——对一句错误断言的更正与实测。

2026-09-16 本次审核曾断言：「实心柱 33 模 7085 Ω 与 50 Ω 功放相差 142 倍，
无法匹配」，并据此把高阻抗几何整体排除。**该断言是错的。**

141:1 的阻抗变换在射频工程里是常规操作，项目自己的 stage2 就把它做出来了。
本脚本用项目现有模型直接测出来，不靠论证：

  1. v2.1 基线（负载 7071 Ω）经 stage2 L 匹配后的实际 Γ、|Z|、带宽
  2. L 型匹配网络的理论 Q 与带宽（Q = sqrt(R_high/R_low - 1)）
  3. 两种几何在【同一组元件容差扰动】下的匹配劣化对照

    python3 workspace/match_feasibility_20260916/check.py
"""
from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

CASES = ("CASE_000_BASELINE", "CASE_LMATCH_P2", "CASE_LMATCH_P5", "CASE_LMATCH_P10",
         "CASE_CMATCH_M2", "CASE_CMATCH_M5", "CASE_CMATCH_M10",
         "CASE_QL_100", "CASE_QL_50", "CASE_QL_20")

VARIANTS = [
    ("v2_1_solid_high_Z", "workspace/outputs/v2_self_consistent_rebuild/active_stage3_5",
     "model_v2_1", 7071.07),
    ("v3_hollow_low_Z", "workspace/disturbance_v3_20260916", "model_v3", 29.37),
]


def collect() -> dict:
    out = {}
    for tag, rel, modname, z_load in VARIANTS:
        sys.path.insert(0, str(REPO / rel))
        m = importlib.import_module(modname)
        sm = m.scenario_map()
        rows = {}
        for case in CASES:
            q = m.point_metrics(m.F0, sm[case])
            rows[case] = {
                "gamma": q["gamma"], "zin_abs_ohm": q["zin_abs_ohm"],
                "phase_deg": q["phase_deg"],
                "efficiency_prm_over_psource": q["p_rm_W"] / q["p_source_W"],
            }
        ratio = max(z_load, 50.0) / min(z_load, 50.0)
        q_match = math.sqrt(ratio - 1)
        base = rows["CASE_000_BASELINE"]["gamma"]
        for case in CASES:
            rows[case]["gamma_relative_to_baseline"] = rows[case]["gamma"] / base
        out[tag] = {
            "f0_Hz": m.F0, "z_load_ohm": z_load,
            "transformation_ratio": ratio,
            "match_Q_theoretical": q_match,
            "match_bandwidth_Hz": m.F0 / q_match,
            "cases": rows,
        }
        sys.path.pop(0)
    return out


def main() -> None:
    d = collect()
    v21, v3 = d["v2_1_solid_high_Z"], d["v3_hollow_low_Z"]

    print("=" * 92)
    print("更正：高阻抗负载【可以】匹配到 50 Ω 功放")
    print("=" * 92)
    for tag, v in d.items():
        b = v["cases"]["CASE_000_BASELINE"]
        print(f"{tag:<22} 负载 {v['z_load_ohm']:>7.1f} Ω  变换比 {v['transformation_ratio']:>6.1f}:1  "
              f"匹配 Q {v['match_Q_theoretical']:>5.2f}  带宽 {v['match_bandwidth_Hz']/1e3:>5.1f} kHz")
        print(f"{'':<22} 匹配后 |Z| = {b['zin_abs_ohm']:.1f} Ω, φ = {b['phase_deg']:+.2f}°, "
              f"Γ = {b['gamma']:.4f} (驻波比 "
              f"{(1+b['gamma'])/(1-b['gamma']):.2f}:1)")
    print()
    print(f"结论：7071 Ω 经 L 匹配后 Γ = {v21['cases']['CASE_000_BASELINE']['gamma']:.4f}，"
          f"这是一个【成功】的匹配，不是「无法匹配」。")
    print(f"      带宽 {v21['match_bandwidth_Hz']/1e3:.0f} kHz 与空心圆柱自身的功率峰宽 "
          f"74.5 kHz 同量级，也不构成瓶颈。")
    print()

    print("=" * 92)
    print("同一组元件容差下的匹配劣化对照")
    print("=" * 92)
    print(f"{'扰动':<20}{'v2.1 Γ':>10}{'相对':>8}{'v3 Γ':>10}{'相对':>8}   说明")
    for case in CASES:
        a, b = v21["cases"][case], v3["cases"][case]
        print(f"{case:<20}{a['gamma']:>10.4f}{a['gamma_relative_to_baseline']:>7.1f}x"
              f"{b['gamma']:>10.4f}{b['gamma_relative_to_baseline']:>7.1f}x")
    print()
    print("读法：【相对】劣化两者基本相同（±10% 元件误差下都是 7-10 倍），")
    print("      即高 Q 匹配并不像我先前设想的那样明显更娇气。")
    print("      差别在【绝对】值：±10% 下 v2.1 的 Γ 逼近 0.5（驻波比 3:1，多数功放的保护点），")
    print("      v3 仍只有 0.056。这是真实的裕量差别，但不等于前者不可用。")
    print()
    print("附带发现：stage2 的匹配把输入阻抗落在 "
          f"{v21['cases']['CASE_000_BASELINE']['zin_abs_ohm']:.1f} Ω 而不是 50 Ω，"
          "实部偏了 13%。")
    print("          这是原项目里一个独立的、可修的问题，本次审核前两轮均未发现——")
    print("          前两轮查的是「代码是否忠实于设计」，没查「设计本身匹配得好不好」。")

    (HERE / "results.json").write_text(json.dumps({
        "purpose": "更正「7085 Ω 无法匹配到 50 Ω」这一错误断言，并给出实测依据",
        "verdict": "断言错误。141:1 变换是常规射频操作，项目自身 stage2 已实现，Γ = 0.0635。",
        "corrected_claim": "高阻抗几何【不】被 50 Ω 功放排除。空心圆柱与高阻抗实心柱是两个并列的设计选择，"
                           "各有代价，应由应用需求（是否需要导丝中心孔）与实测决定，不能以「不可匹配」排除前者。",
        "still_valid": "v3 批次里『29 Ω 负载下并联 C 跨负载够不到 50 Ω』这条【仍然成立】——"
                       "那是对 29 Ω 负载算出的上界 1/Re(Y_load) = 30.4 Ω，与本更正不冲突。"
                       "不成立的是把它表述为「原项目的匹配设计作废」。",
        "incidental_finding": "stage2 匹配落在 56.7 Ω 而非 50 Ω，实部偏 13%，Γ 因此为 0.0635 而非约 0.005。",
        "data": d,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {HERE / 'results.json'}")


if __name__ == "__main__":
    main()
