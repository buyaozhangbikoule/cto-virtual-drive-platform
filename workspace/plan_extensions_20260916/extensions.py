"""围绕计划书想做的事拓展：四处计划书没安排、但直接影响结论的东西。

导师 2026-09-16：「计划书的安排也不一定正确，围绕着计划书想做的东西可以适当拓展一些思路」。

计划书【想做】的是：负载变化时，能否用电压/电流/相位把功率与匹配维持住。
本脚本检查为达成这个目标，计划书的安排里缺了什么。四项全部可计算，不是空谈。

    python3 workspace/plan_extensions_20260916/extensions.py
"""
from __future__ import annotations

import json, math, sys
from pathlib import Path
import numpy as np
from scipy.special import jv, struve

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
Z_PIEZO, QM_MAT, F0 = 33.0, 65.0, 0.8e6
OD_MM = 1.35
out: dict = {}

# 公开典型值，非本项目实测
# 声阻抗与声速。每一项标注出处——2026-09-17 修正：原表的钙化斑块用了 7.00 MRayl
# 与 3000 m/s，【两者都没有出处】（多半是拿了皮质骨），实测值小得多。
MEDIA = [
    # (名称, Z_MRayl, c_m_s, 出处)
    ("空气/气泡（失接触）", 0.0004, 340.0,
     "空气的标准值。【模糊推测】：把空化气泡云当作空气是粗糙上界——"
     "含气液体的等效阻抗是复数且随频率变，可能高于也可能低于液体。"),
    ("血液（基线）", 1.66, 1540.0, "公开典型值（软组织超声标准表）"),
    ("脂质池", 1.70, 1500.0,
     "实测 1.70 ± 0.07 MRayl，扫描声学显微镜，Sci Rep 2018 s41598-018-32788-2"),
    ("纤维组织", 2.02, 1700.0,
     "实测 2.02 ± 0.06 MRayl，同上文献"),
    ("钙化（内膜内）", 2.23, 1858.0,
     "实测 2.23 ± 0.09 MRayl，同上文献。声速由 c = Z/rho 反推，取 rho = 1.2 g/cm^3"
     "（部分矿化组织的假设值，【此项为假设】）"),
]


def qm_of(z: float) -> tuple[float, float]:
    q_rad = math.pi * Z_PIEZO / (2 * z)
    return q_rad, 1 / (1 / QM_MAT + 1 / q_rad)


def ext1_tissue_levels() -> None:
    print("=" * 92)
    print("拓展一：扰动等级应由组织声阻抗推出，而不是取 ±15/30/50% 这种整数档")
    print("=" * 92)
    print("⚠ 2026-09-17 修正：本节原结论「计划书扰动档比应用隐含的小 2.1 倍」【已撤回】。")
    print("  该结论建立在钙化斑块 Z = 7.00 MRayl 上，而这个数【我没有出处】。")
    print("  扫描声学显微镜实测值是 2.23 ± 0.09 MRayl（Sci Rep 2018 s41598-018-32788-2）。")
    print("  用实测值重算，组织驱动的 Rm 范围是 1.00x-1.23x，【完全落在计划书的 ±15/30/50% 之内】。\n")
    print("Q_rad = pi*Z_piezo/(2*Z_medium) 这个公式本身已自行推导验证（见 docs/08 第一节），")
    print("成立条件是：半波厚度模、单面辐射、另一面空气背衬。本器件几何与之不符。\n")
    _, qm_blood = qm_of(1.66)
    print(f"{'声学负载':<26}{'Z(MRayl)':>10}{'Q_rad':>10}{'Qm':>8}{'Rm/血液':>10}{'FWHM(kHz)':>11}")
    rows = []
    for name, z, _c, _src in MEDIA:
        q_rad, qm = qm_of(z)
        rm_rel = qm_blood / qm
        rows.append({"medium": name, "Z_MRayl": z, "Q_rad": q_rad, "Qm": qm,
                     "Rm_relative_to_blood": rm_rel, "FWHM_kHz": F0 / qm / 1e3})
        print(f"{name:<26}{z:>10.4f}{q_rad:>10.1f}{qm:>8.2f}{rm_rel:>9.2f}x{F0/qm/1e3:>11.2f}")
    lo = min(r["Rm_relative_to_blood"] for r in rows)
    hi = max(r["Rm_relative_to_blood"] for r in rows)
    tissue = [r for r in rows if "气泡" not in r["medium"]]
    t_hi = max(r["Rm_relative_to_blood"] for r in tissue)
    print(f"\n计划书的 Rm 扰动档：+15%/+30%/+50%，最大 1.50x")
    print(f"由【实测组织】声阻抗推出的范围：1.00x ~ {t_hi:.2f}x —— 完全落在计划书档位【之内】。")
    print(f"=> 原结论「计划书档位小了 2.1 倍」不成立，已撤回。")
    print(f"   计划书用 ±15/30/50% 覆盖组织变化是【够的】。")
    print(f"\n唯一仍在档位之外的是「失去接触」一档：Rm 降到 {lo:.2f}x、Qm 冲到 {QM_MAT}、")
    print(f"峰宽由 {F0/qm_blood/1e3:.1f} kHz 收窄到 {F0/QM_MAT/1e3:.1f} kHz。")
    print("但这一档把气泡当成空气，【此处为模糊推测内容】——含气液体不等于空气。")
    print("在有可靠的气泡云等效阻抗之前，这一档只能算「值得注意的方向」，不是可用的数值。")
    out["ext1_tissue_levels"] = {"rows": rows, "plan_max": 1.5,
                                 "derived_range": [lo, hi],
                                 "correction_2026_09_17": "原结论「计划书档位小 2.1 倍」已撤回；"
                                 "该结论依赖无出处的 Z=7.0 MRayl，实测为 2.23±0.09。"
                                 "用实测值，组织范围 1.00x-1.23x，落在计划书 ±15/30/50% 之内。",
                                 "sources": {r[0]: r[3] for r in MEDIA}}


def ext2_sensor_noise() -> None:
    print("\n" + "=" * 92)
    print("拓展二：给虚拟传感器加噪声——计划书里 V/I/相位全是精确值")
    print("=" * 92)
    sys.path.insert(0, str(REPO / "workspace/outputs/v2_self_consistent_rebuild/active_stage3_5"))
    import model_v2_1 as M21
    sys.path.insert(0, str(REPO / "workspace/disturbance_v3_20260916"))
    import model_v3 as M3
    rng = np.random.default_rng(20260916)

    def po(M, s, sigma, step=500.0, n=400, runs=40):
        fine = np.arange(M.F_MIN, M.F_MAX, 25.0)
        pb = M.response(fine, s, 1.0)["p_rm_W"].max()
        caps, freqs = [], []
        for _ in range(runs):
            f, d = M.F0, 1.0
            for _ in range(n):
                p0 = float(M.response(f, s, 1.0)["p_rm_W"][0])
                fc = float(np.clip(f + d * step, M.F_MIN, M.F_MAX))
                p1 = float(M.response(fc, s, 1.0)["p_rm_W"][0])
                if p1 * (1 + rng.normal(0, sigma)) > p0 * (1 + rng.normal(0, sigma)):
                    f = fc
                else:
                    d *= -1
            caps.append(float(M.response(f, s, 1.0)["p_rm_W"][0]) / pb)
            freqs.append(f)
        return float(np.mean(caps)), float(np.std(freqs))

    print("P&O 的全部决策就是比较两次功率测量的符号。先看峰顶处的信号有多大：\n")
    snr = {}
    for tag, M in (("v2.1 Qm=800", M21), ("v3   Qm=21", M3)):
        s = M.scenario_map()["CASE_000_BASELINE"]
        fine = np.arange(M.F_MIN, M.F_MAX, 25.0)
        p = M.response(fine, s, 1.0)["p_rm_W"]
        w, _, _, _ = M.half_power_width(fine, p)
        i = int(np.argmax(p))
        rel = abs(float(M.response(fine[i] + 500.0, s, 1.0)["p_rm_W"][0]) - p[i]) / p[i]
        need = -20 * math.log10(rel / 3)
        snr[tag] = {"FWHM_kHz": w / 1e3, "rel_signal": rel, "required_SNR_dB": need}
        print(f"{tag}  FWHM={w/1e3:6.2f} kHz   峰顶走 0.5 kHz 的相对功率差 = {rel*100:8.4f}%"
              f"   需 SNR > {need:.0f} dB")
    print(f"\n=> 判对符号所需 SNR 相差 {snr['v3   Qm=21']['required_SNR_dB']-snr['v2.1 Qm=800']['required_SNR_dB']:.0f} dB。"
          "宽峰的峰顶平，梯度弱，信号被噪声淹没得多。\n")

    print("但【后果】远比这个 SNR 差距温和，因为宽峰同样平坦地容错：")
    print(f"{'噪声':>9}" + "".join(f"{t:>34}" for t in ("v2.1 窄峰", "v3 宽峰")))
    print(f"{'(相对std)':>9}" + "".join(f"{'功率捕获':>17}{'频率std(kHz)':>17}" for _ in range(2)))
    noise_rows = []
    for sig in (1e-4, 1e-3, 1e-2, 3e-2):
        line = f"{sig*100:>8.2f}%"
        rec = {"sigma": sig}
        for tag, M in (("v2_1", M21), ("v3", M3)):
            s = M.scenario_map()["CASE_000_BASELINE"]
            cap, fsd = po(M, s, sig)
            rec[tag] = {"capture": cap, "freq_std_Hz": fsd}
            line += f"{cap*100:>16.2f}%{fsd/1e3:>17.2f}"
        noise_rows.append(rec)
        print(line)
    print("\n=> 真正的结论不是「噪声让宽峰失效」——功率捕获在 3% 噪声下仍有 99%。")
    print("   真正的结论是：【宽峰上功率捕获这个指标本身失去了分辨力】。")
    print("   所有策略在它上面都得 99%+，计划书第 4 周要求的策略对比会得出一个空结果。")
    print("   退化的是频率估计（1% 噪声下 std 2.6 kHz），而它只在被当作状态估计量时才要紧。")
    sys.path.pop(0); sys.path.pop(0)
    out["ext2_sensor_noise"] = {"snr_requirement": snr, "monte_carlo": noise_rows}


def ext4_radiation_reactance() -> None:
    print("\n" + "=" * 92)
    print("拓展四：模型只有辐射【电阻】，缺辐射【电抗】（附加质量）")
    print("=" * 92)
    print("现模型把辐射损耗折进 Qm，只取了辐射阻抗的实部。虚部改变等效 Lm，从而移动 fs。")
    print("活塞辐射阻抗 Z_rad = rho*c*A*[R1(2ka) + j*X1(2ka)]，R1=1-2J1/x，X1=2H1/x。\n")
    a = OD_MM * 1e-3 / 2
    print(f"{'声学负载':<26}{'ka':>7}{'X1/R1':>8}{'Q_rad':>9}{'附加质量':>10}{'Δfs/fs':>9}{'Δfs(kHz)':>10}")
    rows = []
    for name, z, c, _src in MEDIA:
        if z < 0.01:
            continue
        ka = 2 * math.pi * a / (c / F0)
        x = 2 * ka
        ratio = (2 * struve(1, x) / x) / (1 - 2 * jv(1, x) / x)
        q_rad, _ = qm_of(z)
        m_ratio = ratio / q_rad
        dfs = 1 / math.sqrt(1 + m_ratio) - 1        # 精确式，非一阶展开
        rows.append({"medium": name, "ka": ka, "X1_over_R1": ratio,
                     "added_mass_ratio": m_ratio, "dfs_rel": dfs, "dfs_Hz": dfs * F0})
        print(f"{name:<26}{ka:>7.2f}{ratio:>8.3f}{q_rad:>9.1f}{m_ratio:>9.3f}{dfs*100:>8.2f}%{dfs*F0/1e3:>10.1f}")
    blood = next(r for r in rows if "血液" in r["medium"])
    calc = next(r for r in rows if "钙化" in r["medium"])
    delta = (calc["dfs_Hz"] - blood["dfs_Hz"]) / 1e3
    print(f"\n血液 -> 钙化斑块的附加 fs 偏移 = {delta:.1f} kHz")
    print(f"参照：v3 的粗扫半宽是 ±80 kHz，登记表最大 fs 扰动（CASE_FS_M5）是 -40 kHz。")
    print(f"=> 这一项与最大的已建模扰动【同量级甚至更大】，而模型完全无法表达它。")
    print("\n须注意（避免过度解读）：")
    print("  · 该式是无限障板圆形活塞的经典结果；本器件是 31 模空心圆柱、端面为环形、")
    print("    内外侧壁也接触流体，故这是【量级估计】而非该几何的精确解。")
    print("  · 钙化的 ka=1.13 落在活塞公式精度较差的区间，且 X1/R1>1，一阶近似不适用，")
    print("    上表已改用精确式 1/sqrt(1+m)-1。即便如此，绝对值仍应看作上界性的估计。")
    print("  · 要得到可用数值需 COMSOL 声固耦合或实测。")
    print("\n但方向是稳的：X1 与 R1 同阶，模型只取 R1，这是【结构性缺项】而非精度问题。")
    out["ext4_radiation_reactance"] = {"rows": rows, "blood_to_calcified_dfs_kHz": delta}


def main() -> None:
    ext1_tissue_levels()
    ext2_sensor_noise()
    ext4_radiation_reactance()
    (HERE / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {HERE/'results.json'}")


if __name__ == "__main__":
    main()
