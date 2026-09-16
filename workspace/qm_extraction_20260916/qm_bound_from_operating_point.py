"""无需实物换能器，从工作点与材料耦合系数反推 Qm 的可行区间。

背景：用 LTspice 仿真数据「测」Qm 是循环论证——网表里的 BVD 参数就是我们假设的
那套，提取器会精确返回输入值（已验证精度 0.00000%）。仿真不能测量假设本身。

但工作点本身带有一个很强的约束，今天就能用：

    在 BVD 结构下，Zt(fs) = Rm ∥ (1/jwC0)。给定 |Zt(fs)| = |Zop| 与 C0，
    Rm 被唯一确定，于是

        K = Qm x (Cm/C0) = Xc0/Rm = sqrt((Xc0/|Zop|)^2 - 1)

    K 只依赖 C0 与工作点。而材料手册给出的有效机电耦合系数 k_eff 决定 Cm/C0：

        Cm/C0 = k_eff^2 / (1 - k_eff^2)      =>      Qm = K / (Cm/C0)

所以：**查一次材料手册 + 估一个 C0，Qm 就被定死在一个窄区间内。**

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
    print("结论与唯一的出路")
    print("=" * 74)
    print("  在导师给定的工作点下，只要 C0 >= 1 pF 且耦合是正常压电材料，")
    print("  Qm 必然落在 10 量级（约 3–93，中心约 13），不可能是 800。")
    print()
    print("  而 Qm ≈ 13 时，自适应频率跟踪的收益约为 1.00x —— 课题的核心卖点不成立。")
    print()
    print("  唯一能推翻这个推论的，是工作点的前提：")
    print("  上述推导假定 0.9 MHz 的 100 Vpp / 5 mA 就在【串联谐振点】上。")
    print("  若实际是在谐振点【之外】驱动，|Zt| 就不是 Rm ∥ (1/jwC0)，整个族的推导失效。")
    print("  => 这是今天就该向导师确认的一个问题，不需要任何硬件。")

    summary = {
        "operating_point_ohm": ZOP,
        "f0_Hz": F0,
        "invariant": "K = Qm * (Cm/C0) = sqrt((Xc0/|Zop|)^2 - 1)",
        "qm_at_c0_6p858pF": {n: qm_from(6.858e-12, k) for n, k in MATERIALS},
        "c0_required_for_qm800_pF": {
            n: 1 / (2 * math.pi * F0 * ZOP * math.sqrt((800 * ratio_from_k(k)) ** 2 + 1)) * 1e12
            for n, k in MATERIALS[:4]
        },
        "open_question": "0.9 MHz 的 100 Vpp / 5 mA 是否就在串联谐振点上？需向导师确认。",
        "class": "ASSUMED_BASELINE 推论；材料 k_eff 取自公开常见值，非本项目实测。",
    }
    (HERE / "qm_bound_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
