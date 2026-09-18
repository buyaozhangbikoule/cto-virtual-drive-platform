#!/usr/bin/env python3
"""第一层负载参数化的参考实现与全部数字的复算。

只读：导入冻结的活动模型读取基线 BVD，不写入 `workspace/`，不落盘。

    python3 review/radiation_load_layer1_reference.py
    python3 review/radiation_load_layer1_reference.py --model <含 model_v2_1.py 的目录>

本文件同时是 `review/14_第一层负载参数化_给Codex的实施指导.md` 的参考实现：
文档里出现的每一个数字都由本脚本算出，Codex 实现之后应当逐条对上。

依赖 numpy 与 scipy（scipy 只用于交叉校验 Struve 函数与 J1；正式实现可用纯级数，
见 `struve_h1_series`，两者在 z<=8 上一致到 1e-9）。
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = REPO / 'workspace/outputs/v2_self_consistent_rebuild/active_stage3_5'

# --------------------------------------------------------------------------
# 声明常数。全部是声明值，不是实测值，改动请连同本文件顶部一起改。
# --------------------------------------------------------------------------
RHO_PZT = 7500.0          # kg/m^3，硬 PZT 体密度的典型值
C_D = 4340.0              # m/s，厚度模式声速。半波厚度 L = C_D/(2 fs)
PISTON_RADIUS_M = 0.5e-3  # m，端面半径。**不是可以随手固定的常数**，见第 7b 节

MEDIA = {                 # name -> (rho0 [kg/m^3], c0 [m/s])
    'air':    (1.2, 343.0),
    'blood':  (1060.0, 1570.0),
    'calcif': (1900.0, 3600.0),
}

# A&S 表 12.1 / DLMF 11.5 的 H1 参考值，用于独立于 scipy 的校验
STRUVE_H1_REFERENCE = {1.0: 0.198457, 3.0: 1.020110, 5.0: 0.807812}


# --------------------------------------------------------------------------
# 1. Struve H1
# --------------------------------------------------------------------------
def struve_h1_series(z: float, terms: int = 200) -> float:
    """H1(z) = Σ_k (−1)^k (z/2)^(2k+2) / (Γ(k+3/2)·Γ(k+5/2))

    两个 Gamma 的宗量**不同**（k+3/2 与 k+5/2），且**没有** 2/π 前因子。
    写成 Γ(k+3/2)² 并乘 2/π 是一个会在 z≈4 附近翻号的错误：
    错写法给 H1(3)=0.548、H1(5)=−0.295，正确值是 1.020 与 0.808。
    X1 = 2H1(x)/x 恒正，所以任何算出负附加质量的结果都是公式错，不是物理。
    """
    total = 0.0
    for k in range(terms):
        term = ((-1.0)**k) * (z/2.0)**(2*k+2) / (math.gamma(k+1.5)*math.gamma(k+2.5))
        total += term
        if k > 5 and abs(term) < 1e-18:
            break
    return total


def piston_R1(x: float) -> float:
    """活塞辐射阻函数 R1(x) = 1 − 2 J1(x)/x，x = 2ka。"""
    from scipy.special import j1
    return 1.0 - 2.0*float(j1(x))/x if x > 0 else 0.0


def piston_X1(x: float) -> float:
    """活塞辐射抗函数 X1(x) = 2 H1(x)/x，x = 2ka。恒正。"""
    return 2.0*struve_h1_series(x)/x if x > 0 else 0.0


# --------------------------------------------------------------------------
# 2. 加载后的 BVD
# --------------------------------------------------------------------------
class Layer1:
    """把声负载折算到机械支路，再折算回 BVD。

    一维集总等效（Mason 简化）：机械支路的质量 m、刚度 k、阻尼 c 通过机电变比 φ
    映射到电学量：Lm = m/φ²，Cm = φ²/k，Rm = c/φ²。

    串联一个辐射阻抗 Z_rad = R_rad + jω·m_rad（力/速度，单位 kg/s）后：
        c → c + R_rad      m → m + m_rad      k 不变
    因此：
        Rm' = Rm·(1 + R_rad/c)      Lm' = Lm·(1 + m_rad/m)      Cm' = Cm
        fs' = 1/(2π√(Lm'·Cm))       Qm' = 2π·fs'·Lm'/Rm'

    **φ 在两个比值里约掉了**，所以第一层不需要压电材料常数。
    但 R_rad/c 与 m_rad/m 仍然需要绝对的质量 m 与端面面积 A：
        m = ρ_PZT·A·L/2   （半波厚度模式的集总有效质量，1/2 来自正弦模态）
        R_rad = ρ0·c0·A·R1(2ka)      m_rad = ρ0·c0·A·X1(2ka)/ω
    代进去之后 A 在比值里约掉，只剩下**通过 2ka 的依赖**：
        R_rad/(ω·m) = 2·ρ0·c0·R1(2ka)/(ω·ρ_PZT·L)
        m_rad/m     = 2·ρ0·c0·X1(2ka)/(ω·ρ_PZT·L)
    所以第一层真正需要的绝对量是 **L 与 ρ_PZT**；半径 a 只通过 2ka 进入，
    但那个依赖在 2ka≈1~4 时非常陡，不能当成可以随手固定的常数。
    """

    def __init__(self, bvd, rho_pzt=RHO_PZT, c_d=C_D, radius_m=PISTON_RADIUS_M):
        self.fs, self.qm, self.rm, self.lm, self.cm = bvd.fs, bvd.qm, bvd.rm, bvd.lm, bvd.cm
        self.omega = 2*math.pi*self.fs
        self.rho_pzt, self.c_d, self.radius = rho_pzt, c_d, radius_m
        self.thickness = c_d/(2*self.fs)
        # 自洽性：模型自己的 Qm 必须等于 ω·Lm/Rm
        assert abs(self.omega*self.lm/self.rm - self.qm) < 1e-6*self.qm

    def effective_mass_kg(self) -> float:
        return self.rho_pzt*math.pi*self.radius**2*self.thickness/2

    def ratios(self, medium: str) -> tuple[float, float, float]:
        """返回 (R_rad/(ω·m), m_rad/m, 2ka)。两者都与端面面积 A 无关。"""
        rho0, c0 = MEDIA[medium]
        x = 2.0*(self.omega/c0)*self.radius
        common = 2.0*rho0*c0/(self.omega*self.rho_pzt*self.thickness)
        return common*piston_R1(x), common*piston_X1(x), x

    def load(self, medium: str, contact: float, qm_intrinsic: float | None = None) -> dict:
        """接触比例 contact∈[0,1] 覆盖 medium，其余面积仍看空气。

        线性叠加两种介质的辐射阻抗，是一个**声明的近似**：严格的活塞辐射函数
        假定整个端面均匀加载，部分覆盖不满足这一前提。见文档第六节第 2 条。
        """
        if not 0.0 <= contact <= 1.0:
            raise ValueError('contact 必须在 [0,1]')
        qi = self.qm if qm_intrinsic is None else qm_intrinsic
        rr_m, mr_m, x = self.ratios(medium)
        rr_a, mr_a, _ = self.ratios('air')
        rr = contact*rr_m + (1.0-contact)*rr_a          # R_rad/(ω·m)
        mr = contact*mr_m + (1.0-contact)*mr_a          # m_rad/m

        lm2 = self.lm*(1.0+mr)
        rm_int = self.omega*self.lm/qi                  # 固有 Qm 决定内部阻尼
        rm2 = rm_int*(1.0 + qi*rr)                      # c = ω·m/Qm ⇒ R_rad/c = Qm·rr
        fs2 = 1.0/(2*math.pi*math.sqrt(lm2*self.cm))
        qm2 = 2*math.pi*fs2*lm2/rm2

        q_int_loaded = qi*math.sqrt(1.0+mr)             # ω'm'/c
        q_rad = math.sqrt(1.0+mr)/rr if rr > 0 else float('inf')   # ω'm'/R_rad
        reciprocal = 1.0/(1.0/q_int_loaded + 1.0/q_rad)
        # 倒数分解必须与直接计算逐位相符，否则实现有错
        assert abs(reciprocal-qm2) < 1e-9*qm2, (reciprocal, qm2)
        return dict(medium=medium, contact=contact, two_ka=x,
                    rm=rm2, lm=lm2, cm=self.cm, fs=fs2, qm=qm2,
                    width_Hz=fs2/qm2, q_rad=q_rad, q_int_loaded=q_int_loaded,
                    rm_ratio=rm2/self.rm, fs_shift_pct=100*(fs2/self.fs-1.0))


# --------------------------------------------------------------------------
# 3. 自检与报告
# --------------------------------------------------------------------------
def check_struve() -> None:
    print('== 1. Struve H1 自检')
    from scipy.special import struve
    print(f"{'z':>5}{'级数':>12}{'scipy':>12}{'A&S 参考':>12}")
    for z in (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 8.0):
        ref = STRUVE_H1_REFERENCE.get(z)
        print(f'{z:>5.1f}{struve_h1_series(z):>12.6f}{float(struve(1, z)):>12.6f}'
              f'{("%.6f" % ref) if ref else "-":>12}')
        assert abs(struve_h1_series(z)-float(struve(1, z))) < 1e-9
        if ref is not None:
            assert abs(struve_h1_series(z)-ref) < 1e-5
    print('  级数 == scipy == 参考值（<1e-5）')
    for x in (0.05, 0.1, 0.5, 1, 2, 3.6, 4, 8, 20, 33):
        assert piston_X1(x) > 0, f'X1({x}) 必须为正'
    print('  X1 在 0.05..33 上恒正 ⇒ 附加质量恒正')


def report(bvd, radius_m=PISTON_RADIUS_M) -> None:
    layer = Layer1(bvd, radius_m=radius_m)
    print(f'\n== 2. 基线与导出几何  (a={radius_m*1e3:.2f} mm)')
    print(f'  fs={layer.fs:.1f} Hz  Qm={layer.qm:.1f}  Rm={layer.rm:.3f} Ω  Lm={layer.lm:.6f} H')
    print(f'  L = c_D/(2fs) = {layer.thickness*1e3:.4f} mm    m = ρAL/2 = {layer.effective_mass_kg()*1e6:.3f} mg')
    print(f'  c = ω·m/Qm = {layer.omega*layer.effective_mass_kg()/layer.qm:.4e} kg/s')
    rho0, c0 = MEDIA['air']
    x_air = 2*(layer.omega/c0)*radius_m
    print(f'  空气 R_rad = ρ0c0·A·R1 = {rho0*c0*math.pi*radius_m**2*piston_R1(x_air):.3e} kg/s')

    grid = [('空气 全接触', 'air', 1.0), ('血液 25% 接触', 'blood', 0.25),
            ('血液 50% 接触', 'blood', 0.50), ('血液 全接触', 'blood', 1.0),
            ('钙化 50% 接触', 'calcif', 0.50), ('钙化 全接触', 'calcif', 1.0)]
    print('\n== 3. 负载格点（相对未加载基线）')
    print(f"{'工况':<16}{'2ka':>7}{'Rm(Ω)':>12}{'Rm×':>8}{'fs(Hz)':>11}{'fs偏移':>9}"
          f"{'Qm':>9}{'峰宽Hz':>10}{'Q_rad':>10}")
    rows = {}
    for label, medium, contact in grid:
        r = layer.load(medium, contact)
        rows[label] = r
        print(f'{label:<16}{r["two_ka"]:>7.3f}{r["rm"]:>12.1f}{r["rm_ratio"]:>8.1f}'
              f'{r["fs"]:>11.1f}{r["fs_shift_pct"]:>+8.2f}%{r["qm"]:>9.2f}'
              f'{r["width_Hz"]:>10.0f}{r["q_rad"]:>10.2f}')

    nom = rows['血液 全接触']
    print('\n== 4. 以「血液 全接触」为标称（建议的格点原点）')
    print(f"{'工况':<16}{'ΔRm':>10}{'Δfs':>10}{'Qm':>10}")
    for label, r in rows.items():
        print(f'{label:<16}{100*(r["rm"]/nom["rm"]-1):>+9.1f}%'
              f'{100*(r["fs"]/nom["fs"]-1):>+9.2f}%{r["qm"]:>10.2f}')

    print('\n== 5. 空气中：固有 Qm 决定一切（辐射可忽略）')
    print(f"{'固有Qm':>8}{'Q_total':>10}{'峰宽Hz':>10}{'Q_rad':>12}")
    for q in (500, 800, 1000, 2000):
        r = layer.load('air', 1.0, qm_intrinsic=q)
        print(f'{q:>8}{r["qm"]:>10.2f}{r["width_Hz"]:>10.1f}{r["q_rad"]:>12.0f}')

    print('\n== 6. 半径敏感性：2ka 落在 R1 的陡段，a 不是可随手固定的常数')
    for medium in ('blood', 'calcif'):
        rho0, c0 = MEDIA[medium]
        print(f'  --- {medium}  ρ0c0={rho0*c0/1e6:.3f} MRayl')
        for a_mm in (0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5):
            lay = Layer1(bvd, radius_m=a_mm*1e-3)
            r = lay.load(medium, 1.0)
            print(f'    a={a_mm:4.2f} mm  2ka={r["two_ka"]:6.3f}  R1={piston_R1(r["two_ka"]):.4f}'
                  f'  Qm={r["qm"]:8.2f}  峰宽={r["width_Hz"]:8.0f} Hz  Δfs={r["fs_shift_pct"]:+6.2f}%')

    print('\n== 7. 厚度模式声速敏感性（a=0.5 mm，血液全接触）')
    for cd in (3800.0, 4100.0, 4340.0, 4600.0, 5000.0):
        lay = Layer1(bvd, c_d=cd, radius_m=0.5e-3)
        r = lay.load('blood', 1.0)
        print(f'  c_D={cd:6.0f} m/s  L={lay.thickness*1e3:.4f} mm  Qm={r["qm"]:7.2f}'
              f'  峰宽={r["width_Hz"]:8.0f} Hz')


def report_registry(scenario_map) -> None:
    base = scenario_map['CASE_000_BASELINE'].bvd
    print('\n== 8. 现有登记表覆盖了什么')
    qm = [(k, v.bvd.qm, v.bvd.fs/v.bvd.qm) for k, v in scenario_map.items()
          if k.startswith('CASE_QM_')]
    for k, q, w in qm:
        print(f'  {k:<16} Qm={q:>6.1f}  峰宽={w:>8.1f} Hz')
    rm = [(k, v.bvd.rm/base.rm) for k, v in scenario_map.items() if k.startswith('CASE_RM_')]
    print('  Rm 族：' + '，'.join(f'{k.split("_")[-1]} ×{r:.2f}' for k, r in rm) + '（只增不减）')
    fsf = [(k, v.bvd.fs/base.fs-1) for k, v in scenario_map.items() if k.startswith('CASE_FS_')]
    print('  fs 族：' + '，'.join(f'{k.split("_")[-1]} {100*r:+.1f}%' for k, r in fsf))
    print(f'  登记场景总数 {len(scenario_map)}，其中 BVD 单因子族 '
          f'{sum(1 for k in scenario_map if k.split("_")[1] in ("C0","RM","FS","LM","CM","QM"))} 个')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default=str(DEFAULT_MODEL_DIR),
                    help='含 model_v2_1.py 的目录（默认用本仓库冻结的活动模型）')
    ap.add_argument('--radius-mm', type=float, default=PISTON_RADIUS_M*1e3)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.model).resolve()))
    import model_v2_1 as model            # noqa: E402
    scenarios = model.scenario_map()
    check_struve()
    report(scenarios['CASE_000_BASELINE'].bvd, radius_m=args.radius_mm*1e-3)
    report_registry(scenarios)
    print('\n全部断言通过。本脚本未写入任何目录。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
