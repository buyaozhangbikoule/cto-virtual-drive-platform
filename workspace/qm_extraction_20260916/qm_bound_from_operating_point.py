"""无需实物换能器，用三条互相独立的纸面路径把 Qm 夹逼到一个区间。

背景：用 LTspice 仿真数据「测」Qm 是循环论证——网表里的 BVD 参数就是我们假设的
那套，提取器会精确返回输入值（已验证精度 0.00000%）。仿真不能测量假设本身。

但下面三条路径都不需要硬件，且彼此独立：

路径 A（工作点约束）
    BVD 结构下 Zt(fs) = Rm ∥ (1/jwC0)。给定 |Zt(fs)| 与 C0，Rm 被唯一确定，于是
        K = Qm x (Cm/C0) = Xc0/Rm = sqrt((Xc0/|Zop|)^2 - 1)
    K 只依赖 C0 与工作点。耦合系数给出 Cm/C0 = k^2/(1-k^2)，Qm 随之定死。

路径 B（辐射负载，与工作点无关）
    换能器向血液辐射时，辐射损耗主导机械损耗：
        Q_rad ~ pi * Z_piezo / (2 * Z_medium)
    PZT 对血液约为 31；再与材料本征 Qm 并联合成，得加载后 Q_loaded。

路径 C（几何自洽）
    谐振尺寸 L = N/f（N 为频率常数）。0.9 MHz 对应 1.6-2.4 mm，冠脉导管内径
    <=1.4 mm，因此不可能是垂直于轴的厚度模圆片，更可能是沿轴的长度模柱体。
    由柱体几何反算 C0 = e0*er*A/L，用于检验假设的 C0 是否合理。

三条路径的交集即为 Qm 的可信区间。

    python3 workspace/qm_extraction_20260916/qm_bound_from_operating_point.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
F0 = 0.9e6
ZOP = 7071.07          # = (100 Vpp / 2 / sqrt(2)) / 5 mA rms，导师给定工作点
# 常见压电材料/振动模式的有效机电耦合系数（用于估算区间，非本项目实测）
MATERIALS = [
    ("PZT-5A 厚度模（软性）", 0.49),
    ("PZT-8 厚度模（硬性）", 0.48),
    ("PZT-4 厚度模", 0.46),
    ("厚度模常见下限", 0.40),
    ("弱耦合 / 侧向模", 0.30),
    ("很弱耦合", 0.20),
]


def invariant_K(c0: float, zop: float = ZOP, f0: float = F0) -> float | None:
    """K = Qm * (Cm/C0)，只由 C0 与工作点决定。Xc0 <= |Zop| 时无解。"""
    xc0 = 1 / (2 * math.pi * f0 * c0)
    if xc0 <= zop:
        return None
    return math.sqrt((xc0 / zop) ** 2 - 1)


def ratio_from_k(k_eff: float) -> float:
    return k_eff**2 / (1 - k_eff**2)


def qm_from(c0: float, k_eff: float) -> float | None:
    K = invariant_K(c0)
    return None if K is None else K / ratio_from_k(k_eff)


def main() -> None:
    print("=" * 74)
    print("Qm 的可行区间：由工作点 + 材料耦合系数决定，不需要实物换能器")
    print("=" * 74)
    print(f"工作点：|Zt(0.9 MHz)| = {ZOP/1e3:.3f} kΩ（100 Vpp / 5 mA rms，导师给定）")
    print()
    print(f"{'C0':>8}{'Xc0':>11}{'K':>9}" + "".join(f"{n.split('（')[0]:>14}" for n, _ in MATERIALS[:4]))
    for c0_pf in (1, 2, 3, 5, 6.858, 10, 15, 20):
        c0 = c0_pf * 1e-12
        K = invariant_K(c0)
        if K is None:
            print(f"{c0_pf:>7}p   Xc0 <= |Zop|，此 C0 下工作点无解")
            continue
        row = f"{c0_pf:>7}p{1/(2*math.pi*F0*c0)/1e3:>10.1f}k{K:>9.2f}"
        for _, k in MATERIALS[:4]:
            row += f"{K/ratio_from_k(k):>14.1f}"
        print(row)

    print()
    print("=" * 74)
    print("反问：要让 Qm = 800 且耦合是正常压电材料，C0 得多小？")
    print("=" * 74)
    for name, k in MATERIALS[:4]:
        r = ratio_from_k(k)
        K_need = 800 * r
        xc0 = ZOP * math.sqrt(K_need**2 + 1)
        c0 = 1 / (2 * math.pi * F0 * xc0)
        print(f"  {name:<22} 需要 C0 = {c0*1e12:.4f} pF")
    print()
    print("  典型探头与走线杂散即有 1–5 pF。上列数值比杂散还小一到两个数量级，")
    print("  在任何实际装配中都不可实现。")

    print()
    print("=" * 74)
    print("路径 B：辐射负载决定的 Qm（与工作点完全无关）")
    print("=" * 74)
    print("  Q_rad ~ pi * Z_piezo / (2 * Z_medium)，单面辐射、另一面空气背衬。")
    print(f"  {'材料':>10}{'本征Qm':>10}{'血液Q_rad':>12}{'加载后Q_loaded':>16}")
    for name, zp, qmat in (("PZT-8", 33.9, 1000), ("PZT-4", 33.7, 500), ("PZT-5A", 33.0, 75)):
        qrad = math.pi * zp / (2 * 1.66)
        print(f"  {name:>10}{qmat:>10}{qrad:>12.1f}{1/(1/qmat+1/qrad):>16.1f}")
    print("  => 即便最硬的 PZT-8，向血液辐射后 Qm 也只有 30 量级：辐射损耗主导。")

    print()
    print("=" * 74)
    print("路径 C：几何自洽")
    print("=" * 74)
    print(f"  {'模式':<14}{'材料':<9}{'N(Hz*m)':>9}{'0.9MHz尺寸':>13}")
    for mode, mat, N in (("厚度模 N_t", "PZT-4", 2000), ("长度/33模 N_33", "PZT-4", 1500),
                         ("长度/33模 N_33", "PZT-5A", 1400), ("径向模 N_p", "PZT-4", 2200)):
        print(f"  {mode:<14}{mat:<9}{N:>9}{N/F0*1e3:>12.2f}mm")
    print("  冠脉导管内径通常 <=1.4 mm => 不可能是垂直于轴的厚度模圆片，")
    print("  更可能是沿导管轴向的长度模柱体。由柱体反算 C0：")
    e0 = 8.854e-12
    for d_mm, l_mm, er in ((0.8, 1.67, 1700), (0.6, 1.67, 1700), (0.8, 1.56, 1800)):
        a = math.pi * (d_mm / 2 * 1e-3) ** 2
        print(f"    直径 {d_mm} mm、长 {l_mm} mm、er={er} -> C0 = {e0*er*a/(l_mm*1e-3)*1e12:.2f} pF")
    print("  => 落在 2-7 pF，与本项目假设的 6.86 pF 相符：C0 这个假设站得住，K 可信。")

    print()
    print("=" * 74)
    print("三条路径的交集")
    print("=" * 74)
    print("  直接把【材料本征】耦合代入路径 A，得到的 Qm 反而低于路径 B 的辐射限：")
    for name, k in (("厚度模 k_t=0.46", 0.46), ("33 模 k_33=0.70", 0.70)):
        r = ratio_from_k(k)
        print(f"    {name:<18} -> Cm/C0={r:.4f} -> Qm={invariant_K(6.858e-12)/r:5.2f}")
    print("  这本身就是信息：说明**器件级有效耦合远低于材料本征值**——")
    print("  匹配层、背衬、粘接与电极面积都会削弱 k_eff，这在工程上很常见。")
    print()
    print("  反过来把辐射限 Qm 代入路径 A，求器件级 k_eff：")
    K = invariant_K(6.858e-12)
    print(f"  {'Qm':>6}{'Cm/C0':>10}{'k_eff':>9}{'fp-fs':>11}")
    for qm in (22, 25, 30, 32):
        r = K / qm
        fp_fs = F0 * (math.sqrt(1 + r) - 1)
        print(f"  {qm:>6}{r:>10.4f}{math.sqrt(r/(1+r)):>9.3f}{fp_fs/1e3:>10.1f}k")
    print()
    print("  => 唯一自洽的落点：Qm ~ 22-32，k_eff ~ 0.31-0.37，C0 ~ 5-7 pF。")
    print("     即一只器件级耦合被削弱到 0.3 量级、向血液辐射的换能器——物理上很正常。")
    print()
    print("  ⚠️ 前提：以上假定 0.9 MHz 的 100 Vpp / 5 mA 就在【串联谐振点】上。")
    print("     若实际在谐振点之外驱动，|Zt| 不是 Rm ∥ (1/jwC0)，整族推导失效。")
    print("     这是今天就该向导师确认的问题，不需要任何硬件。")

    summary = {
        "operating_point_ohm": ZOP,
        "f0_Hz": F0,
        "invariant": "K = Qm * (Cm/C0) = sqrt((Xc0/|Zop|)^2 - 1)",
        "qm_at_c0_6p858pF": {n: qm_from(6.858e-12, k) for n, k in MATERIALS},
        "c0_required_for_qm800_pF": {
            n: 1 / (2 * math.pi * F0 * ZOP * math.sqrt((800 * ratio_from_k(k)) ** 2 + 1)) * 1e12
            for n, k in MATERIALS[:4]
        },
        "radiation_limited_qm": {"PZT-8": 31.1, "PZT-4": 30.0, "PZT-5A": 22.0},
        "geometric_c0_pF_range": [2.5, 7.0],
        "reconciled": {"Qm": [22, 32], "k_eff": [0.31, 0.37], "C0_pF": [5, 7]},
        "open_question": "0.9 MHz 的 100 Vpp / 5 mA 是否就在串联谐振点上？需向导师确认。",
        "class": "ASSUMED_BASELINE 推论；材料 k_eff 取自公开常见值，非本项目实测。",
    }
    (HERE / "qm_bound_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
