"""按导师澄清后的前提重算设计空间。说明见同目录 README.md。

澄清后的前提（2026-09-16）：
  - 0.8 MHz 附近才是合适振动条件（原模型标称 0.9 MHz）
  - 100 Vpp 是推荐值、与振幅成正比、越高越好（不是标称工作点）
  - 5 mA 是上限且推荐更小（不是标称电流）
  - 材料可选（曾用 PZT-5H，PZT-4/8 亦可），直径 <= 2 mm，长度可放宽

关键后果：|Z(fs)| = 7.071 kΩ 不再是约束——它原本由 100 Vpp / 5 mA 反推而来。
设计问题从「反推工作点」变成「选材料与尺寸」。

    python3 workspace/design_space_20260916/design_space.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
E0 = 8.854e-12
F0 = 0.8e6
W0 = 2 * math.pi * F0
C_BLOOD = 1540.0          # 血液声速 m/s
Z_PIEZO_MRAYL = 33.0      # PZT 声阻抗
Z_BLOOD_MRAYL = 1.66
I_LIMIT = 5.0e-3          # 端口电流上限（导师给定为上限，非标称）
V_LIMIT_VRMS = 160 / 2 / math.sqrt(2)

# 公开典型材料常数，非本项目实测
MATERIALS = {
    "PZT-5H": dict(er=3400, k33=0.75, qm_material=65, N33=1400),
    "PZT-5A": dict(er=1800, k33=0.71, qm_material=75, N33=1400),
    "PZT-4": dict(er=1300, k33=0.70, qm_material=500, N33=1500),
    "PZT-8": dict(er=1000, k33=0.64, qm_material=1000, N33=1500),
}
DIAMETERS_MM = (2.0, 1.0, 0.5, 0.3)


def q_radiation() -> float:
    """向血液辐射的机械 Q。空气背衬平板的平面波近似。"""
    return math.pi * Z_PIEZO_MRAYL / (2 * Z_BLOOD_MRAYL)


def design(material: str, diameter_mm: float) -> dict:
    p = MATERIALS[material]
    length_m = p["N33"] / F0
    area_m2 = math.pi * (diameter_mm / 2 * 1e-3) ** 2
    c0 = E0 * p["er"] * area_m2 / length_m
    xc0 = 1 / (W0 * c0)
    r = p["k33"] ** 2 / (1 - p["k33"] ** 2)          # Cm/C0
    qm = 1 / (1 / p["qm_material"] + 1 / q_radiation())
    k_invariant = r * qm                              # i_m / i_C0
    rm = xc0 / k_invariant                            # |Z(fs)| ≈ Rm，因为 K >> 1
    i_allowed_by_voltage = V_LIMIT_VRMS / rm
    current_bound = I_LIMIT < i_allowed_by_voltage
    i = min(I_LIMIT, i_allowed_by_voltage)
    ka = 2 * math.pi * (diameter_mm / 2 * 1e-3) / (C_BLOOD / F0)
    return dict(
        material=material, diameter_mm=diameter_mm, length_mm=length_m * 1e3,
        C0_pF=c0 * 1e12, Xc0_kohm=xc0 / 1e3, cm_over_c0=r, Qm_loaded=qm,
        K=k_invariant, Rm_ohm=rm,
        V_vpp=i * rm * 2 * math.sqrt(2), I_mA=i * 1e3,
        limited_by="电流" if current_bound else "电压",
        P_mech_mW=i * i * rm * 1e3, ka=ka,
        radiation_model_valid=ka > 2.0,
    )


def main() -> None:
    lam = C_BLOOD / F0
    print(f"0.8 MHz、血液中波长 {lam*1e3:.2f} mm、Q_rad ≈ {q_radiation():.1f}")
    print(f"约束：端口电流 <= {I_LIMIT*1e3:.1f} mA（上限），电压 <= 160 Vpp\n")

    rows = [design(m, d) for d in DIAMETERS_MM for m in MATERIALS]
    hdr = f"{'材料':<9}{'直径mm':>8}{'C0(pF)':>9}{'Rm(ohm)':>10}{'V(Vpp)':>9}{'受限于':>8}{'P(mW)':>9}{'ka':>7}{'辐射模型':>10}"
    print(hdr)
    for d in DIAMETERS_MM:
        for m in MATERIALS:
            r = design(m, d)
            print(f"{r['material']:<9}{r['diameter_mm']:>8.1f}{r['C0_pF']:>9.1f}"
                  f"{r['Rm_ohm']:>10.0f}{r['V_vpp']:>9.1f}{r['limited_by']:>8}"
                  f"{r['P_mech_mW']:>9.1f}{r['ka']:>7.2f}"
                  f"{'适用' if r['radiation_model_valid'] else ('边缘' if r['ka'] > 1 else '不适用'):>10}")
        print()

    valid = [r for r in rows if r["ka"] > 1.0]        # 辐射模型至少在边缘内
    best = max(valid, key=lambda r: r["P_mech_mW"])
    print(f"辐射模型仍适用（ka > 1）范围内的最优：{best['material']} ⌀{best['diameter_mm']} mm")
    print(f"  {best['V_vpp']:.1f} Vpp、{best['I_mA']:.2f} mA、{best['P_mech_mW']:.1f} mW、"
          f"受限于{best['limited_by']}、ka={best['ka']:.2f}")
    print()
    print("⚠️ 电学最优（忽略辐射效率）为 PZT-8 ⌀0.5 mm / 257 mW，但 ka=0.82，")
    print("   元件已远小于波长，声输出会明显低于电学功率所暗示的值。")

    (HERE / "design_space.json").write_text(json.dumps({
        "premises_updated_by_supervisor_2026-09-16": {
            "f0_Hz": F0, "voltage_100vpp": "推荐值，与振幅成正比",
            "current_5mA": "上限，推荐更小",
            "diameter_max_mm": 2.0, "length": "可放宽",
            "materials_allowed": list(MATERIALS),
        },
        "invalidated": "|Z(fs)| = 7.071 kΩ 不再是约束；它由 100 Vpp / 5 mA 反推而来。",
        "material_constants_class": "公开典型值，非本项目实测",
        "rows": rows,
        "open_question": "5 mA 上限针对端口总电流还是机械支路电流？两者物理含义不同。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
