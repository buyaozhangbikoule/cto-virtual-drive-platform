"""由材料与几何【正向推导】BVD 参数，取代 v2.1 的「由工作点反推」。

v2.1 的做法：给定 |Z(fs)| = 7.071 kΩ（由 100 Vpp ÷ 5 mA 得来）反推 C0 与 Rm，
于是模型被一个反推出来的量锁死，34 个场景全部锚在它上面。导师 2026-09-16 澄清
100 Vpp 只是推荐值、5 mA 只是上限之后，那个工作点不再是约束，反推链条失效。

本模块改为正向推导，每一步都有物理出处：

    L  = N33 / f0                       谐振长度，N33 为材料频率常数
    A  = pi * (d/2)^2                   截面积，d 为设计选择
    C0 = eps0 * eps_r * A / L           静态电容
    Cm = C0 * k33^2 / (1 - k33^2)       机电耦合决定动态电容
    Lm = 1 / (w0^2 * Cm)
    Qm = 1/(1/Qm_material + 1/Q_rad)    材料损耗与辐射损耗并联
    Rm = w0 * Lm / Qm

`build()` 保留 cable_pF 参数，但【基线不含任何连接导线】：
导管电缆是 HANDOFF.md 第 4 节的推测，计划书与项目文档均未提及，长度与类型无依据，
且其影响取决于尚未确定的电流口径。详见 operating_point.json 的 not_modelled 段。

所有参数来自 operating_point.json，不写死在代码里。

    python3 workspace/operating_point_v3_20260916/bvd_from_geometry.py
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REG = json.loads((HERE / "operating_point.json").read_text(encoding="utf-8"))
EPS0 = 8.854e-12

F0 = float(REG["supervisor_given"]["f0_Hz"]["value"])
W0 = 2 * math.pi * F0
V_HARD_VRMS = float(REG["supervisor_given"]["voltage_hard_vpp"]["value"]) / 2 / math.sqrt(2)
I_LIMIT = float(REG["supervisor_given"]["current_limit_mA"]["value"]) * 1e-3
MATERIALS = {k: v for k, v in REG["materials"].items() if not k.startswith("_")}
AC = REG["acoustic"]
LAMBDA = float(AC["c_blood_m_s"]["value"]) / F0


@dataclass(frozen=True)
class Transducer:
    material: str
    diameter_mm: float
    cable_pF: float
    length_mm: float
    c0_F: float          # 换能器本体静态电容（不含电缆）
    cable_F: float
    cm_F: float
    lm_H: float
    rm_ohm: float
    qm: float
    ka: float

    @property
    def c_total_F(self) -> float:
        """端口看到的静态电容 = C0 + C_cable。"""
        return self.c0_F + self.cable_F

    @property
    def fs_Hz(self) -> float:
        return 1 / (2 * math.pi * math.sqrt(self.lm_H * self.cm_F))

    @property
    def radiation_model(self) -> str:
        return "适用" if self.ka > 2 else ("边缘" if self.ka > 1 else "不适用")


def q_radiation() -> float:
    return math.pi * float(AC["Z_piezo_MRayl"]["value"]) / (2 * float(AC["Z_blood_MRayl"]["value"]))


def build(material: str, diameter_mm: float, cable_pF: float = 0.0) -> Transducer:
    p = MATERIALS[material]
    length_m = p["N33_Hz_m"] / F0
    area_m2 = math.pi * (diameter_mm / 2 * 1e-3) ** 2
    c0 = EPS0 * p["epsilon_r"] * area_m2 / length_m
    cm = c0 * p["k33"] ** 2 / (1 - p["k33"] ** 2)
    lm = 1 / (W0**2 * cm)
    qm = 1 / (1 / p["Qm_material"] + 1 / q_radiation())
    return Transducer(
        material=material, diameter_mm=diameter_mm, cable_pF=cable_pF,
        length_mm=length_m * 1e3, c0_F=c0, cable_F=cable_pF * 1e-12,
        cm_F=cm, lm_H=lm, rm_ohm=W0 * lm / qm, qm=qm,
        ka=2 * math.pi * (diameter_mm / 2 * 1e-3) / LAMBDA,
    )


def impedance(f, t: Transducer) -> np.ndarray:
    """端口阻抗，含电缆电容。"""
    w = 2 * math.pi * np.atleast_1d(np.asarray(f, dtype=float))
    zm = t.rm_ohm + 1j * (w * t.lm_H - 1 / (w * t.cm_F))
    return 1 / (1 / zm + 1j * w * t.c_total_F)


def operating_point(t: Transducer, i_limit: float = I_LIMIT,
                    count_cable_current: bool = False) -> dict:
    """谐振点上，在电流/电压两条上限下能达到的工作状态。

    `count_cable_current` 决定电流上限的口径：

    False（默认，口径 B）——限值只约束【流入换能器本体】的电流。
        5 mA 是保护器件（发热、机械应力）的限值，而导管电缆的电容电流不流经
        压电体。此口径下电缆完全不影响换能器工作点，只是功放要多供电流。

    True（口径 A）——限值约束端口总电流，含电缆。
        若 5 mA 其实来自功放输出能力而非器件保护，应取此口径。此时电缆会严重
        压低可达电压（125 pF 下 100.2 -> 21.7 Vpp）。交接文档「150 pF 衰减 41 倍」
        用的正是这一口径。

    无电缆时两者在谐振点仅差 0.11%（K = i_m/i_C0 ≈ 21-29）；有电缆时差别巨大。
    """
    w = 2 * math.pi * t.fs_Hz
    zm = t.rm_ohm + 1j * (w * t.lm_H - 1 / (w * t.cm_F))
    y_transducer = 1 / zm + 1j * w * t.c0_F          # 换能器本体（含自身 C0）
    y_cable = 1j * w * t.cable_F
    y_limited = y_transducer + y_cable if count_cable_current else y_transducer
    v = min(i_limit / abs(y_limited), V_HARD_VRMS)
    current_bound = i_limit / abs(y_limited) < V_HARD_VRMS
    return dict(
        Z_ohm=1 / abs(y_transducer + y_cable),
        V_vpp=v * 2 * math.sqrt(2),
        I_transducer_mA=abs(v * y_transducer) * 1e3,
        I_cable_mA=abs(v * y_cable) * 1e3,
        I_source_mA=abs(v * (y_transducer + y_cable)) * 1e3,
        limited_by="电流" if current_bound else "电压",
        P_mech_mW=abs(v / zm) ** 2 * t.rm_ohm * 1e3,
        reaches_100vpp=v * 2 * math.sqrt(2) >= 100.0,
        current_convention="A_总电流" if count_cable_current else "B_仅换能器",
    )


def main() -> None:
    b = REG["baseline_choice"]
    tr = build(b["material"]["value"], b["diameter_mm"]["value"])
    op = operating_point(tr)
    print("=" * 74)
    print(f"v3 基线：{tr.material} ⌀{tr.diameter_mm} mm @ {F0/1e6} MHz（正向推导，无反推）")
    print("=" * 74)
    print(f"  谐振长度 {tr.length_mm:.2f} mm    ka = {tr.ka:.2f}（{tr.radiation_model}）")
    print(f"  C0 = {tr.c0_F*1e12:.3f} pF   Cm = {tr.cm_F*1e15:.2f} fF   Lm = {tr.lm_H*1e3:.2f} mH")
    print(f"  Qm = {tr.qm:.1f}（材料 {MATERIALS[tr.material]['Qm_material']} 与辐射 "
          f"{q_radiation():.1f} 并联）")
    print(f"  Rm = {tr.rm_ohm:.0f} Ω   fs = {tr.fs_Hz/1e6:.5f} MHz   Cm/C0 = {tr.cm_F/tr.c0_F:.4f}")
    print(f"  工作点：{op['V_vpp']:.1f} Vpp、换能器电流 {op['I_transducer_mA']:.2f} mA、"
          f"{op['P_mech_mW']:.1f} mW，受限于{op['limited_by']}")

    print()
    print("=" * 74)
    print("设计空间扫描（口径 B，无电缆；数值为 5 mA 下可达电压 Vpp）")
    print("=" * 74)
    diams = REG["scan_variables"]["diameters_mm"]
    print(f"{'材料':<9}" + "".join(f"{'⌀'+str(d):>9}" for d in diams))
    for m in MATERIALS:
        row = f"{m:<9}"
        for d in diams:
            row += f"{operating_point(build(m, d))['V_vpp']:>9.1f}"
        print(row)
    print(f"{'ka':<9}" + "".join(f"{build('PZT-8', d).ka:>9.2f}" for d in diams))
    print("  （ka<=1 时元件远小于波长，辐射效率显著下降，该列电学数值偏乐观）")


if __name__ == "__main__":
    main()
