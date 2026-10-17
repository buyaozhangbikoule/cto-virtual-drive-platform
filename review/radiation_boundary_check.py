#!/usr/bin/env python3
"""Codex 三组物理候选（APC 880 杆 D 0.4/0.5/0.6 mm，即候选 A/B/C）的独立复核，与前端辐射边界的影响（review/29 第七节）。

    python review/radiation_boundary_check.py [--out <目录>]

只读；--out 时另写一份 JSON（拒绝 workspace/ 与 outputs/）。运行期依赖 numpy 与 scipy。
元件、Mason 模型、BVD 提取沿用 codex_baseline_check.py（即 review/24 的独立实现），材料常数取 Codex 报告里的值。

检查项
  1. 三组候选（L 1.8 mm，前端无限障板圆活塞、类血液液体，后端自由）：本实现的 fs、Q、Rm、C0 与 Codex 交付的参数表比较；
     各自把有载 fs 调到 0.9 MHz 需要的长度。
  2. Q 由什么决定：Q 与前端归一化辐射电阻 R1(ka) 的乘积在三组之间是否近似不变（辐射主导时应不变）。
  3. 前端辐射边界的两个极限：
     - 无限刚性障板（Codex 与本仓库现用）；
     - 无法兰端面（导管外径等于杆径）：开口圆管的反射系数模 |R| 与端部修正 l/a 取 Silva、Guillemain、Kergomard、
       Mallaroni、Norris（J. Sound Vib. 322:255–263, 2009）对 Levine & Schwinger 精确解的近似式；系数抄自开源包
       openwind 0.12.4 的 continuous/radiation_silva.py（原文本会话无法访问）。z = j·tan(ka·l/a + ½j·ln|R|)。
       自检：|R| 与 Levine & Schwinger（Phys. Rev. 73:383, 1948）精确积分式逐点比较（scipy 求值）；
       低 ka 极限 R/(ρcA) → (ka)²/4、X/(ρcA) → 0.6133·ka。
       开口管平面波模态的辐射阻抗代替「同径刚性杆端面上的均匀活塞」，低 ka 主项相同，高阶项不同，只作量级。
     导管外径大于杆径时（部分障板）介于两者之间，要用轴对称有限元或边界元算。
     三组候选（L 1.8 mm）与 B 调到 0.9 MHz 的长度在两种边界下：fs、Q、Rm、100 Vpp 时的电流与功率；
     陶瓷端 ≤100 Vpp、换能器端 ≤4.5 mA（用户软限）时的最大功率及其频率，哪一条限值先起作用。
  4. 一维杆近似的横向惯性（Rayleigh）修正：Δf/f ≈ −ν²π²a²/(4L²)，泊松比取 0.3 与 0.4 两个声明值，只估量级。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np
from scipy import integrate, special

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_baseline_check as C   # noqa: E402  元件、Mason 模型与 BVD 提取
PR = C.PR

CANDIDATES = (('A', 0.4e-3), ('B', 0.5e-3), ('C', 0.6e-3))
CODEX_PROFILES = {   # Codex 交付的 bvd_candidate_profiles.json（results/codex_baseline_review_20261016/codex_inputs/）
    'A': dict(c0=4.3197695762618923e-13, rm=10106.549460982515, fs=875520.0280648058, q=81.00410050907966),
    'B': dict(c0=6.778976436547607e-13, rm=9368.265426159336, fs=873695.8099102303, q=55.76277071210622),
    'C': dict(c0=9.81277487583285e-13, rm=8715.303001131726, fs=872444.3583034271, q=41.42497733487115),
}
L_TUNED_B = 1.7467e-3            # review/29 第 3.1 节：B 的有载 fs = 0.9 MHz
I_SOFT, I_HARD, V_NOM = 4.5e-3, 5.0e-3, 100.0
# Silva 等 2009 的无法兰开口管系数（a1, a2, a3, b1, b2, b3, b4, β, η），抄自 openwind 0.12.4 radiation_silva.py
SILVA_UNFLANGED = (0.8, 0.266, 0.0263, 0.0599, 0.238, -0.0153, 0.0015, 0.5, 0.6133)
KA_MAX = 3.0                     # 近似式的拟合范围以内（开口管只有平面波传播的范围是 ka < 3.83）


# ------------------------------------------------------------------ 无法兰端面（开口圆管）
def silva_unflanged(ka):
    """返回 (|R|, l/a)。"""
    a1, a2, a3, b1, b2, b3, b4, beta, eta = SILVA_UNFLANGED
    x = np.asarray(ka, dtype=float) ** 2
    r = (1 + a1 * x) / (1 + (beta + a1) * x + a2 * x ** 2 + a3 * x ** 3)
    la = eta * (1 + b1 * x) / (1 + b2 * x + b3 * x ** 2 + b4 * x ** 3)
    return r, la


def levine_schwinger_r(ka):
    """Levine & Schwinger 的 |R| 精确积分式，只用于自检。积分变量 x = ka·sinθ 消去端点奇异。"""
    def integrand(th):
        x = ka * math.sin(th)
        return math.atan2(special.j1(x), -special.y1(x)) / math.sin(th)
    return math.exp(-(2.0 / math.pi) * integrate.quad(integrand, 0.0, math.pi / 2, limit=400)[0])


def z_unflanged(ka):
    """归一化辐射阻抗 z = j·tan(ka·l/a + ½j·ln|R|)，即 (1+R)/(1−R)、R = −|R|·exp(−2j·ka·l/a)；e^{jωt} 约定，与 piston_z 一致。"""
    ka = np.asarray(ka, dtype=float)
    r, la = silva_unflanged(ka)
    return 1j * np.tan(ka * la + 0.5j * np.log(r))


def piston_unflanged(f, radius, rho0, c0):
    """无法兰端面的辐射阻抗（力/速度，N·s/m）。"""
    ka = 2.0 * np.pi * np.asarray(f, dtype=float) / c0 * radius
    if np.any(ka > KA_MAX):
        raise ValueError('ka 超出近似式范围')
    return rho0 * c0 * np.pi * radius ** 2 * z_unflanged(ka)


def r1_baffled(ka):
    x = 2.0 * ka
    return 1.0 - 2.0 * special.j1(x) / x


def z_baffled(ka):
    x = 2.0 * ka
    return r1_baffled(ka) + 1j * 2.0 * special.struve(1, x) / x


def zfun(el, front):
    if front == 'baffled':
        return C.zfun(el)
    a = el['D'] / 2.0

    def z(f):
        f = np.atleast_1d(np.asarray(f, dtype=float))
        return PR.mason_z(f, el, piston_unflanged(f, a, *C.FLUID), 0.0)
    return z


def case(label, d, length, front):
    el = C.element(d, length)
    z = zfun(el, front)
    s = C.summary(el, z, label)
    ka = 2 * math.pi * s['fs_Hz'] / C.FLUID[1] * d / 2
    s.update(D_mm=d * 1e3, L_mm=length * 1e3, front=front, ka_at_fs=ka,
             Vpp_at_4p5mA=V_NOM * I_SOFT / (s['I_at_fs_100Vpp_mA'] * 1e-3),
             Vpp_at_5mA=V_NOM * I_HARD / (s['I_at_fs_100Vpp_mA'] * 1e-3))
    g = C.drive_grid(z, 0.0, V_NOM, I_SOFT, None)
    s['limited_optimum_100Vpp_4p5mA'] = g
    s['binding_limit'] = 'current' if g['port_mA'] > I_SOFT * 1e3 * 0.999 else 'voltage'
    return s


def self_checks():
    z = complex(z_unflanged(0.01))
    assert abs(z.real / (0.01 ** 2 / 4) - 1) < 2e-3 and abs(z.imag / (0.6133 * 0.01) - 1) < 2e-3, z
    kas = np.linspace(0.05, 2.5, 50)
    diff = np.array([abs(float(silva_unflanged(k)[0]) / levine_schwinger_r(k) - 1) for k in kas])
    assert diff.max() < 1e-2, diff.max()
    return dict(low_ka_z=[z.real, z.imag], max_rel_diff_R_silva_vs_levine_schwinger_ka_0p05_to_2p5=float(diff.max()),
                at_ka=float(kas[int(np.argmax(diff))]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    PR.self_checks()
    res = dict(material=C.APC880, fluid=C.FLUID, codex_profiles=CODEX_PROFILES, self_checks=self_checks())
    sc = res['self_checks']
    print(f"自检：无法兰端面 ka=0.01 时 z = {sc['low_ka_z'][0]:.3e}{sc['low_ka_z'][1]:+.3e}j（低 ka 极限 2.500e-05+6.133e-03j）；"
          f"ka 0.05–2.5 内 Silva 近似式的 |R| 与 Levine–Schwinger 精确积分最大相对差 "
          f"{100*sc['max_rel_diff_R_silva_vs_levine_schwinger_ka_0p05_to_2p5']:.2f}%（ka {sc['at_ka']:.2f}）")

    # 1. 三组候选的独立复核
    rows = []
    print('\n== 1. 三组候选（L 1.8 mm，前端障板活塞、类血液液体，后端自由）：本实现 vs Codex')
    for name, d in CANDIDATES:
        s = case(name, d, C.L_CODEX, 'baffled')
        p = CODEX_PROFILES[name]
        s['rel_diff'] = dict(fs=s['fs_Hz'] / p['fs'] - 1, Rm=s['Rm_ohm'] / p['rm'] - 1, Q=s['Q'] / p['q'] - 1)
        lt = C.length_for(0.9e6, d)
        st = case(f'{name}，有载 fs = 0.9 MHz', d, lt, 'baffled')
        s['tuned_to_0p9MHz'] = st
        rows.append(s)
        print(f"  {name} D {d*1e3:.1f} mm：fs {s['fs_Hz']/1e3:.2f} kHz（{100*s['rel_diff']['fs']:+.3f}%）  "
              f"Q {s['Q']:.1f}（Codex {p['q']:.1f}，{100*s['rel_diff']['Q']:+.1f}%）  Rm {s['Rm_ohm']:.0f} Ω（{100*s['rel_diff']['Rm']:+.1f}%）  "
              f"夹持 C0 {s['C0_clamped_pF']:.3f} pF（Codex {p['c0']*1e12:.3f}）  100 Vpp@fs {s['I_at_fs_100Vpp_mA']:.2f} mA {s['P_at_fs_100Vpp_mW']:.1f} mW")
        print(f"      调到 0.9 MHz：L {lt*1e3:.4f} mm，Q {st['Q']:.1f}，Rm {st['Rm_ohm']:.0f} Ω，100 Vpp@fs {st['I_at_fs_100Vpp_mA']:.2f} mA "
              f"{st['P_at_fs_100Vpp_mW']:.1f} mW，半功率宽度 {st['fwhm_Hz']/1e3:.1f} kHz")
    res['candidates_baffled'] = rows

    # 2. Q 与辐射电阻
    print('\n== 2. Q × R1(ka)：辐射主导时三组应近似相同')
    q_r1 = []
    for s in rows:
        r1 = float(r1_baffled(s['ka_at_fs']))
        q_r1.append(dict(candidate=s['case'], ka=s['ka_at_fs'], R1=r1, Q=s['Q'], Q_times_R1=s['Q'] * r1))
        print(f"  {s['case']}：ka {s['ka_at_fs']:.3f}  R1 {r1:.4f}  Q {s['Q']:.1f}  Q×R1 {s['Q']*r1:.2f}")
    spread = max(r['Q_times_R1'] for r in q_r1) / min(r['Q_times_R1'] for r in q_r1) - 1
    res['q_vs_radiation_resistance'] = dict(rows=q_r1, spread_of_Q_times_R1=spread)
    print(f"  Q×R1 三组相差 {100*spread:.1f}%（Q 本身相差 {100*(rows[0]['Q']/rows[2]['Q']-1):.0f}%）")

    # 3. 前端辐射边界
    print('\n== 3. 前端辐射边界：无限障板 vs 无法兰端面（后端自由）')
    for ka in (0.7, 0.9, 1.05):
        zu, zb = complex(z_unflanged(ka)), complex(z_baffled(ka))
        print(f"  ka {ka:.2f}：障板 z = {zb.real:.4f}{zb.imag:+.4f}j，无法兰 z = {zu.real:.4f}{zu.imag:+.4f}j，"
              f"电阻比 {zu.real/zb.real:.3f}，电抗比 {zu.imag/zb.imag:.3f}")
    bound = []
    for name, d, length in (('A', 0.4e-3, C.L_CODEX), ('B', 0.5e-3, C.L_CODEX), ('C', 0.6e-3, C.L_CODEX),
                            ('B（L 1.7467 mm）', 0.5e-3, L_TUNED_B)):
        pair = {}
        for front, cn in (('baffled', '无限障板'), ('unflanged', '无法兰')):
            s = case(f'{name}，{cn}', d, length, front)
            pair[front] = s
            g = s['limited_optimum_100Vpp_4p5mA']
            print(f"  {s['case']:<18} fs {s['fs_Hz']/1e3:7.2f} kHz  Q {s['Q']:6.1f}  Rm {s['Rm_ohm']:6.0f} Ω  "
                  f"100 Vpp@fs {s['I_at_fs_100Vpp_mA']:5.2f} mA {s['P_at_fs_100Vpp_mW']:6.1f} mW  "
                  f"4.5/5.0 mA 时 {s['Vpp_at_4p5mA']:5.1f}/{s['Vpp_at_5mA']:5.1f} Vpp  "
                  f"≤100 Vpp 且 ≤4.5 mA：{g['f_Hz']/1e3:.2f} kHz {g['port_Vpp']:.1f} Vpp {g['port_mA']:.2f} mA {g['port_P_mW']:.1f} mW"
                  f"（{'电流' if s['binding_limit'] == 'current' else '电压'}先到限）")
        bound.append(pair)
    res['radiation_boundary'] = bound

    # 4. 一维近似的横向惯性修正
    print('\n== 4. 一维杆近似的横向惯性（Rayleigh）修正 Δf/f ≈ −ν²π²a²/(4L²)，L 1.8 mm')
    rayleigh = []
    for name, d in CANDIDATES:
        a_ = d / 2
        est = {f'nu_{nu}': -(nu * math.pi * a_) ** 2 / (4 * C.L_CODEX ** 2) for nu in (0.3, 0.4)}
        rayleigh.append(dict(candidate=name, D_mm=d * 1e3, L_over_D=C.L_CODEX / d, **est))
        print(f"  {name} D {d*1e3:.1f} mm（L/D {C.L_CODEX/d:.1f}）：ν=0.3 时 {100*est['nu_0.3']:.2f}%，ν=0.4 时 {100*est['nu_0.4']:.2f}%")
    res['rayleigh_lateral_inertia'] = rayleigh

    if a.out:
        out = pathlib.Path(a.out).resolve()
        if {'workspace', 'outputs'} & set(out.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out}')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'radiation_boundary_check.json').write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float) + '\n',
                                                           encoding='utf-8')
        print(f'\n已写入 {out / "radiation_boundary_check.json"}')


if __name__ == '__main__':
    main()
