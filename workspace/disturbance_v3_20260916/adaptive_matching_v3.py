"""固定匹配 vs 自适应匹配：第四种控制策略的可行性与收益。

计划书第 4 周要求对比若干控制策略，现有四种（FIXED / PERIODIC_SCAN /
P_AND_O / PHASE_LOCK）全部只调【频率】，匹配网络始终是 stage2 一次设计定死的。
文献器件 reference/前视超声治疗.pdf 的做法不同：继电器切换 L-C，
每个工作频率各自调谐到 50 Ω±3 Ω 与 0°±5°。

v2.1 里这个差别看不出来，因为负载 7071 Ω 离 50 Ω 有 142 倍，匹配网络必然
存在且被设计好；而 v3 的扰动表显示，固定匹配下 34 个场景里有 8 个的
Γ 超过 0.5（驻波比 3:1）——失谐的代价首先落在功放而不是换能器。
本脚本量化「重新调谐」能把这笔代价收回多少。

对照三种策略：
  A 固定匹配 + 固定频率 f0          —— 什么都不动
  B 固定匹配 + 频率跟踪            —— 现有四种策略的共同能力上限
  C 自适应匹配 + 频率跟踪          —— 文献器件的做法

    python3 workspace/disturbance_v3_20260916/adaptive_matching_v3.py
"""
from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np

import model_v3 as M

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
FINE = np.arange(M.F_MIN, M.F_MAX + 0.1, 25.0)
GAMMA_SOFT = float(M.REG["drive_limits"]["GAMMA_SOFT"]["value"])
GAMMA_HARD = float(M.REG["drive_limits"]["GAMMA_HARD"]["value"])
P_TARGET = M.P_PORT_SOFT


def at(f: float, s: M.Scenario) -> dict:
    """在频率 f 上把端口功率驱到 P_TARGET，返回代价指标。"""
    u = M.response(f, s, amplitude=1.0)
    a = np.sqrt(P_TARGET / float(u["p_port_W"][0]))
    return {
        "f_Hz": f,
        "gamma": float(u["gamma"][0]),
        "zin_abs_ohm": float(abs(u["z_in"][0])),
        "phase_deg": float(u["phase_deg"][0]),
        "amplitude": float(a),
        "vport_vpp": float(u["vport_vpp"][0]) * a,
        "iport_mA": float(u["iport_irms_A"][0]) * a * 1e3,
        # 功放须发出的功率：含 Rs 上的一半与匹配网络 ESR 损耗
        "p_source_W": float(u["p_source_W"][0]) * a**2,
        "p_rm_W": float(u["p_rm_W"][0]) * a**2,
        "efficiency": float(u["p_rm_W"][0]) / float(u["p_source_W"][0]),
    }


def track(s: M.Scenario) -> float:
    """频率跟踪能找到的最优点（窗内单位幅度功率最大处）。"""
    p = M.response(FINE, s, amplitude=1.0)["p_rm_W"]
    return float(FINE[int(np.argmax(p))])


def main() -> None:
    OUT.mkdir(exist_ok=True)
    rows = []
    for s in M.all_scenarios():
        f_track = track(s)
        # C：在该场景自身的工作频率上重新设计 L-C
        s_adapt = replace(s, matching=M.design_lmatch(
            M.z_bvd_at(f_track, s.bvd), s.rs, f_track,
            ql=s.matching.ql, qc=s.matching.qc))
        f_track_c = track(s_adapt)
        s_adapt = replace(s, matching=M.design_lmatch(
            M.z_bvd_at(f_track_c, s.bvd), s.rs, f_track_c,
            ql=s.matching.ql, qc=s.matching.qc))

        a = at(M.F0, s)
        b = at(f_track, s)
        c = at(f_track_c, s_adapt)
        rows.append({
            "case_id": s.case_id, "factor": s.factor, "level": s.level,
            "fs_Hz": s.bvd.fs,
            "A_zin": a["zin_abs_ohm"], "B_zin": b["zin_abs_ohm"], "C_zin": c["zin_abs_ohm"],
            "A_phase": a["phase_deg"], "B_phase": b["phase_deg"], "C_phase": c["phase_deg"],
            "A_f_Hz": a["f_Hz"], "A_gamma": a["gamma"], "A_vpp": a["vport_vpp"],
            "A_p_source_W": a["p_source_W"], "A_efficiency": a["efficiency"],
            "B_f_Hz": b["f_Hz"], "B_gamma": b["gamma"], "B_vpp": b["vport_vpp"],
            "B_p_source_W": b["p_source_W"], "B_efficiency": b["efficiency"],
            "C_f_Hz": c["f_Hz"], "C_gamma": c["gamma"], "C_vpp": c["vport_vpp"],
            "C_p_source_W": c["p_source_W"], "C_efficiency": c["efficiency"],
            "C_Lmatch_uH": s_adapt.matching.l_h * 1e6,
            "C_Cmatch_nF": s_adapt.matching.c_f * 1e9,
            "C_L_change_pct": (s_adapt.matching.l_h / M.BASE_MATCH.l_h - 1) * 100,
            "C_C_change_pct": (s_adapt.matching.c_f / M.BASE_MATCH.c_f - 1) * 100,
            "B_to_C_source_power_saving_pct": (1 - c["p_source_W"] / b["p_source_W"]) * 100,
        })

    with (OUT / "adaptive_matching_v3.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    def stat(key):
        v = np.array([r[key] for r in rows])
        return dict(min=float(v.min()), mean=float(v.mean()), max=float(v.max()))

    summary = {
        "batch": "disturbance_v3_20260916",
        "power_target_W": P_TARGET,
        "strategies": {
            "A": "固定匹配 + 固定频率 f0",
            "B": "固定匹配 + 频率跟踪（现有四种策略的共同能力上限）",
            "C": "自适应匹配 + 频率跟踪（文献器件做法）",
        },
        "gamma": {k: stat(f"{k}_gamma") for k in "ABC"},
        "exceeding_gamma_hard": {
            k: [r["case_id"] for r in rows if r[f"{k}_gamma"] > GAMMA_HARD] for k in "ABC"
        },
        "exceeding_gamma_soft_count": {
            k: int(sum(1 for r in rows if r[f"{k}_gamma"] > GAMMA_SOFT)) for k in "ABC"
        },
        "drive_voltage_vpp": {k: stat(f"{k}_vpp") for k in "ABC"},
        "source_power_W": {k: stat(f"{k}_p_source_W") for k in "ABC"},
        "component_retune_range": {
            "L_change_pct": stat("C_L_change_pct"),
            "C_change_pct": stat("C_C_change_pct"),
        },
        "reference_paper_tolerance": {
            "criterion": "reference/前视超声治疗.pdf 的匹配容差：|Z| = 50 Ω±3 Ω 且相位 0°±5°",
            "cases_meeting": {
                k: int(sum(1 for r in rows
                           if abs(r[f"{k}_zin"] - 50.0) <= 3.0 and abs(r[f"{k}_phase"]) <= 5.0))
                for k in "ABC"
            },
            "failing_cases": {
                k: [r["case_id"] for r in rows
                    if abs(r[f"{k}_zin"] - 50.0) > 3.0 or abs(r[f"{k}_phase"]) > 5.0]
                for k in "ABC"
            },
            "interpretation": {
                "B_failures_are_all_resistance_drift":
                    "B 的 8 个未达标场景没有一个是频率漂移，全部是【电阻】漂移："
                    "Rm +15/30/50%（相位误差至 -21.5°）、Rs +10/20%、以及三个同时含 Rm 与 Rs "
                    "分量的 combined 场景。相对地，纯 fs/Lm/Cm 漂移的 9 个场景 B 全部达标——"
                    "频率跟踪把它们完全修好了。原理上如此：挪频率挪不动负载电阻。"
                    "这是自适应匹配唯一真正不可替代的地方。",
                "C_failures_are_all_Rs_drift":
                    "C 的 4 个未达标场景全部是 Rs 漂移（55 Ω 与 60 Ω，相位近 0°）。此时匹配网络"
                    "正确地匹配到了【漂移后的源阻抗】，Γ 仅 0.005-0.026，是完美匹配；"
                    "不达标的是「50 Ω±3 Ω」这把绝对尺子本身——它默认源就是 50 Ω。"
                    "当 Rs 本身是扫描变量时，只有 Γ 这个判据仍然成立。",
            },
        },
        "median_source_power_saving_B_to_C_pct":
            float(np.median([r["B_to_C_source_power_saving_pct"] for r in rows])),
    }
    (OUT / "adaptive_matching_v3.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 106)
    print(f"固定匹配 vs 自适应匹配（每个场景都驱到端口 {P_TARGET*1e3:.1f} mW）")
    print("=" * 106)
    print(f"{'场景':<20}" + "".join(f"{t:>28}" for t in ("A 固定匹配+固定频率", "B 固定匹配+频率跟踪", "C 自适应匹配+频率跟踪")))
    print(f"{'':<20}" + "".join(f"{'Γ':>7}{'Vpp':>7}{'功放W':>7}{'效率':>7}" for _ in "ABC"))
    for r in rows:
        line = f"{r['case_id']:<20}"
        for k in "ABC":
            line += (f"{r[k+'_gamma']:>7.3f}{r[k+'_vpp']:>7.2f}"
                     f"{r[k+'_p_source_W']:>7.3f}{r[k+'_efficiency']:>7.3f}")
        print(line)

    print()
    for k, label in (("A", "A 固定匹配+固定频率"), ("B", "B 固定匹配+频率跟踪"),
                     ("C", "C 自适应匹配+频率跟踪")):
        ex_h = summary["exceeding_gamma_hard"][k]
        print(f"{label}：Γ 均值 {summary['gamma'][k]['mean']:.3f}、最差 {summary['gamma'][k]['max']:.3f}；"
              f"超 VSWR 3:1 {len(ex_h)}/34；超 2:1 {summary['exceeding_gamma_soft_count'][k]}/34；"
              f"驱动电压 {summary['drive_voltage_vpp'][k]['min']:.1f}-"
              f"{summary['drive_voltage_vpp'][k]['max']:.1f} Vpp")
    rt = summary["reference_paper_tolerance"]["cases_meeting"]
    print(f"\n按文献自身的容差（50 Ω±3 Ω 且 0°±5°）达标数：A {rt['A']}/34、B {rt['B']}/34、C {rt['C']}/34")
    cr = summary["component_retune_range"]
    print(f"\nC 需要的元件调谐范围：L {cr['L_change_pct']['min']:+.1f}% ~ {cr['L_change_pct']['max']:+.1f}%，"
          f"C {cr['C_change_pct']['min']:+.1f}% ~ {cr['C_change_pct']['max']:+.1f}%")
    print(f"B→C 功放输出功率中位数节省 {summary['median_source_power_saving_B_to_C_pct']:.1f}%")
    print(f"\n已写入 {OUT}")


if __name__ == "__main__":
    main()
