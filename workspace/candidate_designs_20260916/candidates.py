"""候选换能器设计的多组对照。

导师 2026-09-16 指示：可沿用 reference/前视超声治疗.pdf 的结构，也可另行设计；
0.8 MHz 同样是三次谐波；100 Vpp / 5 mA 是按现有仪器选的，可调范围很大，
不必钉死在一两个数上——不确定时就多做几组对照再比。

因此本模块不再指定单一工作点，而是把候选设计并列计算，供选择。

几何与模式
----------
文献器件：径向极化空心圆柱，内外表面电极，沿长度振动 = **31 模**
（电场径向、运动轴向），工作在长度模的三次谐波。
  - 同轴电容：C0 = 2*pi*eps0*eps_r*L / ln(OD/ID)
  - 谐振：f_n = n * N31 / L
  - 耦合：k31（远小于 k33：PZT-5H 的 k31≈0.39 而 k33≈0.75）

公式已用文献数据校验：L=2.5 mm、三次谐波 1.85 MHz 反推 N=1542 Hz·m，
与 PZT-5H 的 31 模频率常数典型值 1400–1500 Hz·m 吻合。

对照还包含一组**实心柱体 33 模**，即本次审核早期假设的结构，用于说明
几何选择会把电学尺度整体搬动两个数量级。

    python3 workspace/candidate_designs_20260916/candidates.py
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
EPS0 = 8.854e-12
C_BLOOD = 1540.0
Z_PIEZO, Z_BLOOD = 33.0, 1.66      # MRayl

# 公开典型值，非本项目实测。31 模用于空心圆柱，33 模用于实心柱。
MATERIALS = {
    "PZT-5H": dict(er=3400, k31=0.39, k33=0.75, N31=1500, N33=1400, qm=65),
    "PZT-5A": dict(er=1800, k31=0.34, k33=0.71, N31=1400, N33=1400, qm=75),
    "PZT-4":  dict(er=1300, k31=0.33, k33=0.70, N31=1650, N33=1500, qm=500),
    "PZT-8":  dict(er=1000, k31=0.30, k33=0.64, N31=1700, N33=1500, qm=1000),
}


@dataclass
class Candidate:
    name: str
    geometry: str          # "hollow_cylinder_31" | "solid_rod_33"
    material: str
    f_target_Hz: float
    harmonic: int
    od_mm: float
    id_mm: float = 0.0


def q_rad() -> float:
    return math.pi * Z_PIEZO / (2 * Z_BLOOD)


def evaluate(c: Candidate) -> dict:
    p = MATERIALS[c.material]
    if c.geometry == "hollow_cylinder_31":
        n_const, k = p["N31"], p["k31"]
        length_m = c.harmonic * n_const / c.f_target_Hz
        c0 = 2 * math.pi * EPS0 * p["er"] * length_m / math.log(c.od_mm / c.id_mm)
        aperture_m = c.od_mm * 1e-3
    else:
        n_const, k = p["N33"], p["k33"]
        length_m = c.harmonic * n_const / c.f_target_Hz
        area = math.pi * (c.od_mm / 2 * 1e-3) ** 2
        c0 = EPS0 * p["er"] * area / length_m
        aperture_m = c.od_mm * 1e-3

    w = 2 * math.pi * c.f_target_Hz
    r = k**2 / (1 - k**2)                      # Cm/C0
    cm = c0 * r
    lm = 1 / (w**2 * cm)
    qm = 1 / (1 / p["qm"] + 1 / q_rad())
    rm = w * lm / qm
    xc0 = 1 / (w * c0)
    z_res = 1 / abs(1 / rm + 1j * w * c0)      # |Z| at series resonance
    lam = C_BLOOD / c.f_target_Hz
    return dict(
        name=c.name, geometry=c.geometry, material=c.material,
        f_MHz=c.f_target_Hz / 1e6, harmonic=c.harmonic,
        length_mm=length_m * 1e3, od_mm=c.od_mm, id_mm=c.id_mm,
        C0_pF=c0 * 1e12, Xc0_ohm=xc0, cm_over_c0=r, k_used=k,
        Qm=qm, Rm_ohm=rm, Z_res_ohm=z_res,
        K_invariant=r * qm,
        V_at_5mA_vpp=5e-3 * z_res * 2 * math.sqrt(2),
        I_at_100vpp_mA=(100 / 2 / math.sqrt(2)) / z_res * 1e3,
        ka=2 * math.pi * (aperture_m / 2) / lam,
        match_ratio_to_50ohm=z_res / 50.0,
    )


CANDIDATES = [
    # A：文献原型（reference/前视超声治疗.pdf）
    Candidate("A_文献原型", "hollow_cylinder_31", "PZT-5H", 1.85e6, 3, 1.35, 0.73),
    # B：同结构、同材料，改到导师给的 0.8 MHz（同为三次谐波）
    Candidate("B_文献结构@0.8MHz", "hollow_cylinder_31", "PZT-5H", 0.8e6, 3, 1.35, 0.73),
    # C/D：0.8 MHz 下换硬性材料
    Candidate("C_PZT-4@0.8MHz", "hollow_cylinder_31", "PZT-4", 0.8e6, 3, 1.35, 0.73),
    Candidate("D_PZT-8@0.8MHz", "hollow_cylinder_31", "PZT-8", 0.8e6, 3, 1.35, 0.73),
    # E/F：改壁厚（内径），看阻抗随壁厚怎么走
    Candidate("E_薄壁@0.8MHz", "hollow_cylinder_31", "PZT-5H", 0.8e6, 3, 1.35, 1.00),
    Candidate("F_厚壁@0.8MHz", "hollow_cylinder_31", "PZT-5H", 0.8e6, 3, 1.35, 0.50),
    # G：缩小外径到 1.0 mm
    Candidate("G_小外径@0.8MHz", "hollow_cylinder_31", "PZT-5H", 0.8e6, 3, 1.00, 0.55),
    # H：基波而非三次谐波（长度短得多）
    Candidate("H_基波@0.8MHz", "hollow_cylinder_31", "PZT-5H", 0.8e6, 1, 1.35, 0.73),
    # I：实心柱 33 模——本次审核早期的假设，作为对照
    Candidate("I_实心柱33模(旧假设)", "solid_rod_33", "PZT-8", 0.8e6, 1, 0.60),
]


def main() -> None:
    rows = [evaluate(c) for c in CANDIDATES]
    print("=" * 112)
    print("候选设计对照（材料常数为公开典型值，非实测；全部为电学估算）")
    print("=" * 112)
    h = (f"{'方案':<20}{'材料':<8}{'f(MHz)':>7}{'次':>3}{'长(mm)':>8}"
         f"{'C0(pF)':>9}{'|Z|(Ω)':>9}{'Qm':>6}{'5mA时V':>9}{'100Vpp时I':>11}{'ka':>6}{'vs50Ω':>8}")
    print(h)
    for r in rows:
        print(f"{r['name']:<20}{r['material']:<8}{r['f_MHz']:>7.2f}{r['harmonic']:>3}"
              f"{r['length_mm']:>8.2f}{r['C0_pF']:>9.1f}{r['Z_res_ohm']:>9.0f}{r['Qm']:>6.1f}"
              f"{r['V_at_5mA_vpp']:>8.1f}V{r['I_at_100vpp_mA']:>10.1f}m{r['ka']:>6.2f}"
              f"{r['match_ratio_to_50ohm']:>8.1f}x")
    print()
    print("说明：")
    print("  |Z| 为串联谐振点的端口阻抗；vs50Ω 为它与 50 Ω 的比值（越接近 1 越好匹配）。")
    print("  ka = 2πa/λ，ka<1 时元件远小于波长、辐射效率显著下降。")
    print("  5mA时V / 100Vpp时I 用于对照导师给的「100 Vpp、5 mA」是否落在该方案的合理区间。")

    with (HERE / "candidates.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (HERE / "candidates.json").write_text(json.dumps({
        "note": "候选设计对照，不指定单一工作点。导师 2026-09-16：数值可调范围大，不必钉死。",
        "reference_device": "reference/前视超声治疗.pdf：PZT-5H 空心圆柱 OD/ID=1.35/0.73mm、"
                            "长 2.5mm、31 模三次谐波 1.85MHz、脉冲 0.1ms/PRF 909Hz（占空比 9.1%）、"
                            "20 Vpp、动态 L-C 匹配到 50Ω±3Ω 与 0°±5°",
        "material_constants_class": "公开典型值，非本项目实测",
        "candidates": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
