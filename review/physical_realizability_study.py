#!/usr/bin/env python3
"""仿真参数能否对应一只真实器件：从压电材料 + 几何 + 声负载推出 BVD，逐条对照原始需求。

只读：不导入、不修改 workspace/；默认不落盘，--out <目录> 时另写一份 JSON
（拒绝写入 workspace/ 或任何 outputs/ 目录）。运行期只依赖 numpy。

    python review/physical_realizability_study.py
    python review/physical_realizability_study.py --root <统一源目录>   # 加做平台基线自证
    python review/physical_realizability_study.py --out <目录>

--root 只用于自证：导入统一源的 models/model_v2_1.py，确认平台基线在 0.9 MHz、a=1 时
确实是 100 Vpp / 5 mA / 170 mW。不给 --root 时，基线由同一条推导链独立复算。

方法（全部是一维近似：量级可信，细节不可信）
  1. 材料：PZT-5H / PZT-4 / PZT-8 的手册典型常数；材料 Qm 用 Zipparo 2010 Table II 的
     实测值（同一牌号不同厂家差几倍，见 MATERIALS 注释）。
  2. 几何：单层、端面电极、轴向极化的实心圆柱，直径 D ≤ 2 mm，长度 L 由空载 fs = 0.9 MHz
     反解。真实器件的 L/D 接近 1，用两种一维极限把它夹在中间：
       rod  细长杆 33 模（L ≫ D 时准确）：v = 1/√(ρ s33^D)，k = k33，C0 = ε33^T(1−k33²)A/L
       disc 薄片厚度模（D ≫ L 时准确）：v = √(c33^D/ρ)，k = kt，C0 = ε33^S A/L
  3. Mason 模型算端口阻抗 Z(f)。前端面：空气 / 血液 / 压在钙化 CTO 上 / λ/4 匹配层后接血液，
     均按刚性障板活塞的辐射阻抗；后端面空气背衬。机械损耗用复刚度 c(1+j/Qm_mat)，
     介电损耗用 tanδ。
  4. 像阻抗分析仪那样从 Z(f) 拟合单支路 BVD：动生导纳峰给 fs 与 Rm，半功率宽度给 Q，
     Cm/C0 由此得到，并报告拟合残差。
  5. 逐条检查原始需求：100 Vpp 下电流与功率；5 mA 上限下最多能加多少电压；
     V ≤ 100/160 Vpp 且 I ≤ 5 mA 时最大有功功率落在哪个频率、是不是串联谐振点。
  6. 导管线缆：1.5 m 微同轴 30–100 pF/m 与 C0 相比，以及能否并进 L 型网络的并联电容。

不做的事：不做有限元，不建横向模态，不建匹配层损耗与粘接层，不建温升；
负载介质参数沿用 research/radiation_load_layer1 的声明值（钙化 1900 kg/m³、3600 m/s
仍是待核实的声明，见参数来源登记 20261006）。所有结果都应被实测阻抗曲线替换。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

EPS0 = 8.8541878128e-12
SQ8 = 2.0 * math.sqrt(2.0)          # Vpp = 2√2·Vrms（正弦稳态）

# ------------------------------------------------------------------ 原始需求
REQ = dict(
    band_Hz=(0.8e6, 1.0e6), f0_Hz=0.9e6, rs_ohm=50.0,
    v_nominal_Vpp=100.0, v_max_Vpp=160.0, i_max_Arms=5e-3, diameter_max_m=2e-3,
)

# ------------------------------------------------------------------ 平台当前基线
# stage2_匹配设计参数.json 的 C0、Rm、fs，加 model_v2_1.py 第 78 行硬编码的 qm=800.0
PLATFORM = dict(c0=6.858064105198409e-12, rm=7352.941176470586, fs=900000.0, qm=800.0)

# ------------------------------------------------------------------ 材料
# 手册典型值（Berlincourt / Morgan 一类常数表；各厂家同牌号差 ±10–20%）。
# qm_measured：Zipparo, Bing, Nightingale, "Imaging arrays with improved transmit power
#   capability", IEEE TUFFC 57(9):2076–2090 (2010), Table II 实测：
#   PZT-5H  CTS 3203HD 63
#   PZT-4   EDO EC64 280；TFT H13 1700
#   PZT-8   EDO EC69 350；TFT H11 1000
# 第一个值用于主表（商用常见牌号），第二个值只用于检查「空气中能否到 800」。
MATERIALS = {
    'PZT-5H': dict(rho=7500., eps33T=3400., eps33S=1470., k33=0.752, kt=0.505,
                   s33E=20.7e-12, c33D=15.7e10, tand=0.02, qm_measured=(63.,)),
    'PZT-4':  dict(rho=7500., eps33T=1300., eps33S=635., k33=0.70, kt=0.513,
                   s33E=15.5e-12, c33D=15.9e10, tand=0.004, qm_measured=(280., 1700.)),
    'PZT-8':  dict(rho=7600., eps33T=1000., eps33S=600., k33=0.64, kt=0.48,
                   s33E=13.5e-12, c33D=16.1e10, tand=0.004, qm_measured=(350., 1000.)),
}

# 介质（ρ kg/m³, c m/s）：与 research/radiation_load_layer1 的声明值相同
MEDIA = {'air': (1.2, 343.0), 'blood': (1060.0, 1570.0), 'calcif': (1900.0, 3600.0)}
# λ/4 匹配层：声明值，氧化铝填充环氧一类，Z = 6.0 MRayl，厚度按 0.9 MHz 取 λ/4
MATCH_LAYER = dict(rho=2000.0, c=3000.0)

LOADS = ('air', 'blood', 'calcif', 'blood+ML')
LOAD_CN = {'air': '空气（台架空载）', 'blood': '血液', 'calcif': '压在钙化CTO上',
           'blood+ML': 'λ/4匹配层+血液'}
DIAMETERS_MM = (1.0, 1.35, 2.0)
CABLE_PF_PER_M = (30.0, 60.0, 100.0)
CABLE_LENGTH_M = 1.5


# ------------------------------------------------------------------ 特殊函数
def bessel_j1(x):
    """J1(x) = (1/2π)∫cos(x sinτ − τ)dτ，整周期梯形公式，指数收敛。"""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    tau = np.linspace(-np.pi, np.pi, 1024, endpoint=False)
    return np.mean(np.cos(np.outer(x, np.sin(tau)) - tau), axis=1)


_GL_X, _GL_W = np.polynomial.legendre.leggauss(200)


def struve_h1(x):
    """H1(x) = (2x/π)∫_0^{π/2} cos²θ·sin(x sinθ)dθ，Gauss–Legendre。"""
    x = np.atleast_1d(np.asarray(x, dtype=float))
    th = (_GL_X + 1.0) * np.pi / 4.0
    w = _GL_W * np.pi / 4.0
    integrand = (np.cos(th) ** 2)[None, :] * np.sin(np.outer(x, np.sin(th)))
    return (2.0 * x / np.pi) * (integrand @ w)


_X_TABLE = np.linspace(1e-6, 120.0, 24001)            # 2ka 的取值表，步长 0.005
_R1_TABLE = 1.0 - 2.0 * bessel_j1(_X_TABLE) / _X_TABLE
_X1_TABLE = 2.0 * struve_h1(_X_TABLE) / _X_TABLE


def piston_z(f, radius, rho0, c0):
    """刚性障板圆活塞辐射阻抗（力/速度，N·s/m）。R1、X1 由预算表线性插值。"""
    x = 2.0 * (2.0 * np.pi * np.asarray(f, dtype=float) / c0) * radius
    if np.any(x > _X_TABLE[-1]):
        raise ValueError('2ka 超出预算表')
    r1 = np.interp(x, _X_TABLE, _R1_TABLE)
    x1 = np.interp(x, _X_TABLE, _X1_TABLE)
    return rho0 * c0 * np.pi * radius ** 2 * (r1 + 1j * x1)


def through_layer(f, z_load, area, rho_l, c_l, thickness):
    """均匀层的阻抗变换（一维平面波）。"""
    zl = rho_l * c_l * area
    t = np.tan(2.0 * np.pi * np.asarray(f, dtype=float) * thickness / c_l)
    return zl * (z_load + 1j * zl * t) / (zl + 1j * z_load * t)


# ------------------------------------------------------------------ 元件与 Mason 模型
def series_root(k):
    """tan(x)/x = 1/k² 在 (0, π/2) 内的根：一维模型的串联谐振。"""
    lo, hi = 1e-9, math.pi / 2 - 1e-12
    target = 1.0 / (k * k)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if math.tan(mid) / mid < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def make_element(material, diameter_m, limit, fs_Hz=REQ['f0_Hz'], qm_target=None):
    m = MATERIALS[material]
    area = math.pi * diameter_m ** 2 / 4.0
    if limit == 'rod':
        s33d = m['s33E'] * (1.0 - m['k33'] ** 2)
        v, k = 1.0 / math.sqrt(m['rho'] * s33d), m['k33']
        eps = m['eps33T'] * (1.0 - m['k33'] ** 2)
    elif limit == 'disc':
        v, k = math.sqrt(m['c33D'] / m['rho']), m['kt']
        eps = m['eps33S']
    else:
        raise ValueError(limit)
    xs = series_root(k)
    length = v * xs / (math.pi * fs_Hz)           # 空载、无损时 fs·L = v·x_s/π
    c0 = eps * EPS0 * area / length
    el = dict(material=material, D=diameter_m, limit=limit, A=area, L=length,
              v=v, k=k, C0=c0, rho=m['rho'], tand=m['tand'],
              qm_target=m['qm_measured'][0] if qm_target is None else qm_target,
              fp_unloaded=v / (2.0 * length))
    el['qm_mat'] = calibrate_loss(el)
    return el


def calibrate_loss(el):
    """损耗加在 c^D 上时，串联谐振处的动生 Q 约为 qm_in·(1−k²)，不等于输入值。
    手册与 Zipparo 的 Qm 是谐振 Q（动生支路），所以反过来标定：
    取 qm_in 使「空气中」拟合出的动生 Q 等于实测材料 Qm。"""
    target = el['qm_target']
    qin = target / (1.0 - el['k'] ** 2)
    for _ in range(6):
        el['qm_mat'] = qin
        b = fit_bvd(el, lambda f: element_z(np.atleast_1d(f), el, 'air'))
        if abs(b['q'] / target - 1.0) < 1e-3:
            break
        qin *= target / b['q']
    return qin


def mason_z(f, el, z_front, z_back, qm_mat=None, tand=None):
    f = np.asarray(f, dtype=float)
    w = 2.0 * np.pi * f
    qm = el['qm_mat'] if qm_mat is None else qm_mat
    td = el['tand'] if tand is None else tand
    vc = el['v'] * np.sqrt(1.0 + 1j / qm)
    zc = el['rho'] * vc * el['A']
    theta = w * el['L'] / vc
    c0 = el['C0']
    n2 = el['k'] ** 2 * el['rho'] * el['v'] ** 2 * el['A'] * c0 / el['L']
    zs = 1j * zc * np.tan(theta / 2.0)
    zsh = zc / (1j * np.sin(theta))
    za, zb = zs + z_front, zs + z_back
    zmech = zsh + za * zb / (za + zb)
    zbranch = -1.0 / (1j * w * c0) + zmech / n2
    y = 1j * w * c0 * (1.0 - 1j * td) + 1.0 / zbranch
    return 1.0 / y


def load_impedance(f, el, load):
    a = el['D'] / 2.0
    if load == 'blood+ML':
        rho0, c0 = MEDIA['blood']
        thickness = MATCH_LAYER['c'] / (4.0 * REQ['f0_Hz'])
        return through_layer(f, piston_z(f, a, rho0, c0), el['A'],
                             MATCH_LAYER['rho'], MATCH_LAYER['c'], thickness)
    rho0, c0 = MEDIA[load]
    return piston_z(f, a, rho0, c0)


def element_z(f, el, load, qm_mat=None):
    return mason_z(f, el, load_impedance(f, el, load),
                   piston_z(f, el['D'] / 2.0, *MEDIA['air']), qm_mat=qm_mat)


# ------------------------------------------------------------------ BVD
def bvd_z(f, b):
    w = 2.0 * np.pi * np.asarray(f, dtype=float)
    zm = b['rm'] + 1j * (w * b['lm'] - 1.0 / (w * b['cm']))
    return 1.0 / (1.0 / zm + 1j * w * b['c0'])


def bvd_from(c0, rm, fs, q):
    w = 2.0 * math.pi * fs
    lm = q * rm / w
    cm = 1.0 / (w * w * lm)
    kappa = cm / c0
    return dict(c0=c0, rm=rm, lm=lm, cm=cm, fs=fs, q=q, kappa=kappa,
                keff=math.sqrt(kappa / (1.0 + kappa)), fp=fs * math.sqrt(1.0 + kappa),
                fwhm=fs / q, M=kappa * q, tau_us=2.0 * q / w * 1e6)


def half_power(f, p, i):
    """|Y_m|² 降到峰值一半的两侧插值频率。"""
    half = 0.5 * p[i]
    j = i
    while j > 0 and p[j] > half:
        j -= 1
    k = i
    while k < len(p) - 1 and p[k] > half:
        k += 1
    if p[j] > half or p[k] > half:
        return None
    f1 = f[j] + (half - p[j]) * (f[j + 1] - f[j]) / (p[j + 1] - p[j])
    f2 = f[k - 1] + (half - p[k - 1]) * (f[k] - f[k - 1]) / (p[k] - p[k - 1])
    return f1, f2


def fit_bvd(el, zfun):
    """从 Z(f) 拟合单支路 BVD：先粗后细找动生导纳峰。"""
    def motional(f):
        z = zfun(f)
        w = 2.0 * np.pi * f
        return 1.0 / z - 1j * w * el['C0'] * (1.0 - 1j * el['tand']), z
    f = np.linspace(0.3e6, 1.8e6, 30001)
    ym, _ = motional(f)
    i = int(np.argmax(np.abs(ym) ** 2))
    hp = half_power(f, np.abs(ym) ** 2, i)
    width = (hp[1] - hp[0]) if hp else 0.2 * f[i]
    span = max(4.0 * width, 2000.0)
    f2 = np.linspace(max(0.2e6, f[i] - span), f[i] + span, 40001)
    ym2, _ = motional(f2)
    p2 = np.abs(ym2) ** 2
    i2 = int(np.argmax(p2))
    hp2 = half_power(f2, p2, i2)
    if hp2 is None:
        return None
    fs = float(f2[i2])
    rm = float(1.0 / ym2[i2].real)
    q = fs / (hp2[1] - hp2[0])
    b = bvd_from(el['C0'], rm, fs, q)
    # 并联谐振：|Z| 极大（在 fs 之上）
    f3 = np.linspace(fs, fs * 1.6, 40001)
    z3 = zfun(f3)
    b['fp_mason'] = float(f3[int(np.argmax(np.abs(z3)))])
    fb = np.linspace(*REQ['band_Hz'], 2001)
    zm, zb = zfun(fb), bvd_z(fb, b)
    b['fit_err_band'] = float(np.max(np.abs(zb - zm) / np.abs(zm)))
    return b


# ------------------------------------------------------------------ 需求检查
def requirement_check(zfun, f_resonance):
    vnom, vmax, imax = REQ['v_nominal_Vpp'] / SQ8, REQ['v_max_Vpp'] / SQ8, REQ['i_max_Arms']
    out = {}
    f = np.arange(REQ['band_Hz'][0], REQ['band_Hz'][1] + 1.0, 50.0)
    z = zfun(f)
    y = 1.0 / z
    g, r = y.real, z.real
    fr = min(max(f_resonance, f[0]), f[-1])
    zr = complex(zfun(np.array([fr]))[0])
    out['f_check_Hz'] = fr
    out['in_band'] = bool(REQ['band_Hz'][0] <= f_resonance <= REQ['band_Hz'][1])
    out['absZ_at_fs_ohm'] = abs(zr)
    out['phase_at_fs_deg'] = math.degrees(math.atan2(zr.imag, zr.real))
    out['I_at_100Vpp_mA'] = vnom / abs(zr) * 1e3
    out['P_at_100Vpp_mW'] = vnom ** 2 * (1.0 / zr).real * 1e3
    out['Vpp_at_5mA'] = imax * abs(zr) * SQ8
    for name, v in (('100', vnom), ('160', vmax)):
        p = np.minimum(v * v * g, imax * imax * r)
        k = int(np.argmax(p))
        vk = min(v, imax * abs(z[k]))
        out[f'opt{name}'] = dict(
            f_Hz=float(f[k]), P_mW=float(p[k] * 1e3), Vpp=float(vk * SQ8),
            I_mA=float(vk / abs(z[k]) * 1e3),
            pf=float(math.cos(math.atan2(z[k].imag, z[k].real))),
            df_from_fs_Hz=float(f[k] - f_resonance),
            binding=('V' if v * v * g[k] <= imax * imax * r[k] else 'I'))
    return out


def cable_check(zfun, f_op):
    """L 型网络（源侧串 L、器件侧并 C）把器件匹配到 50 Ω 时，并联电容还剩多少可容纳线缆。"""
    w = 2.0 * math.pi * f_op
    y = 1.0 / complex(zfun(np.array([f_op]))[0])
    rp = 1.0 / y.real
    if rp <= REQ['rs_ohm']:
        return dict(rp_ohm=rp, c_add_pF=None)
    b_total = math.sqrt(rp / REQ['rs_ohm'] - 1.0) / rp
    c_add = (b_total - y.imag) / w
    return dict(rp_ohm=rp, q_network=math.sqrt(rp / REQ['rs_ohm'] - 1.0), c_add_pF=c_add * 1e12,
                cable_pF={str(c): c * CABLE_LENGTH_M for c in CABLE_PF_PER_M})


# ------------------------------------------------------------------ 自检
def self_checks():
    ref_j1 = {1.0: 0.44005058574493355, 3.0: 0.33905895852593645, 10.0: 0.04347274616886144}
    for x, v in ref_j1.items():
        assert abs(bessel_j1(x)[0] - v) < 1e-12, ('J1', x, bessel_j1(x)[0], v)
    ref_h1 = {1.0: 0.198457, 3.0: 1.020110, 5.0: 0.807812}   # A&S 表 12.1，6 位
    for x, v in ref_h1.items():
        assert abs(struve_h1(x)[0] - v) < 1e-6, ('H1', x, struve_h1(x)[0], v)
    # 无损、两端自由的 Mason 端口阻抗必须等于 (1/jωC0)(1 − k² tanγ/γ)
    el = make_element('PZT-5H', 1e-3, 'rod')
    f = np.array([0.5e6, 0.85e6, 0.95e6, 1.2e6])
    z = mason_z(f, el, 0.0, 0.0, qm_mat=1e15, tand=0.0)
    g = 2 * np.pi * f * el['L'] / (2 * el['v'])
    z_ref = (1 / (1j * 2 * np.pi * f * el['C0'])) * (1 - el['k'] ** 2 * np.tan(g) / g)
    assert np.max(np.abs(z / z_ref - 1)) < 1e-9, 'Mason 闭式不符'
    # 无损自由时串联谐振恰在 0.9 MHz
    y = 1 / mason_z(np.array([0.9e6 * (1 - 1e-7), 0.9e6 * (1 + 1e-7)]), el, 0.0, 0.0,
                    qm_mat=1e15, tand=0.0)
    assert np.sign(y.imag[0]) != np.sign(y.imag[1]) or abs(y.imag).min() > 1, 'fs 未落在 0.9 MHz'


def platform_chain():
    """平台基线的推导链：100 Vpp、170 mW、5 mA → Rm、C0；qm=800 → Lm、Cm。"""
    v = 100.0 / SQ8
    rm = v * v / 0.17
    i_r = v / rm
    i_c = math.sqrt(5e-3 ** 2 - i_r ** 2)
    c0 = i_c / (2 * math.pi * 0.9e6 * v)
    assert abs(rm - PLATFORM['rm']) < 1e-6 and abs(c0 / PLATFORM['c0'] - 1) < 1e-9
    return bvd_from(PLATFORM['c0'], PLATFORM['rm'], PLATFORM['fs'], PLATFORM['qm'])


def platform_selfproof(root):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import models.model_v2_1 as model  # noqa: E402
    base = model.scenario_map()['CASE_000_BASELINE']
    q = model.response(0.9e6, base, 1.0)
    vpp, irms, prm = float(q['vport_vpp'][0]), float(q['iport_irms_A'][0]), float(q['p_rm_W'][0])
    assert abs(vpp - 100.0) < 1e-3 and abs(irms - 5e-3) < 1e-8 and abs(prm - 0.17) < 1e-6, \
        (vpp, irms, prm)
    assert abs(base.bvd.qm - 800.0) < 1e-12 and abs(base.bvd.c0 - PLATFORM['c0']) < 1e-24
    return dict(vport_Vpp=vpp, iport_mArms=irms * 1e3, p_rm_mW=prm * 1e3, qm=base.bvd.qm)


# ------------------------------------------------------------------ 报告
def fmt_opt(o):
    return (f"{o['f_Hz']/1e3:7.1f}kHz {o['P_mW']:6.1f}mW "
            f"{o['Vpp']:5.1f}Vpp {o['I_mA']:4.2f}mA PF{o['pf']:5.2f} 限{o['binding']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=None, help='统一源目录（可选，仅用于平台基线自证）')
    ap.add_argument('--out', default=None, help='可选：JSON 输出目录；拒绝 workspace/ 与 outputs/')
    args = ap.parse_args()
    out_dir = None
    if args.out:
        out_dir = pathlib.Path(args.out).resolve()
        if {'workspace', 'outputs'} & set(out_dir.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out_dir}')
        out_dir.mkdir(parents=True, exist_ok=True)

    self_checks()
    result = dict(requirements=REQ, materials=MATERIALS, media=MEDIA, match_layer=MATCH_LAYER)

    # ---- 1. 平台基线
    pb = platform_chain()
    pz = lambda f: bvd_z(f, pb)                       # noqa: E731
    pchk = requirement_check(pz, pb['fs'])
    result['platform'] = dict(bvd=pb, check=pchk)
    print('== 1. 平台当前基线（假设值，qm=800 硬编码）')
    print(f"  C0={pb['c0']*1e12:.3f} pF  Rm={pb['rm']:.1f} Ω  Lm={pb['lm']:.4f} H  "
          f"Cm={pb['cm']*1e15:.3f} fF  Q={pb['q']:.0f}")
    print(f"  Cm/C0={pb['kappa']:.6f}  k_eff={pb['keff']:.4f}  fp−fs={pb['fp']-pb['fs']:.1f} Hz  "
          f"FWHM={pb['fwhm']:.0f} Hz  M=κQ={pb['M']:.3f}  τ=2Q/ω={pb['tau_us']:.1f} μs")
    print(f"  0.9 MHz: |Z|={pchk['absZ_at_fs_ohm']:.0f} Ω  100 Vpp → "
          f"{pchk['I_at_100Vpp_mA']:.3f} mA, {pchk['P_at_100Vpp_mW']:.1f} mW")
    print(f"  约束最优 V≤100,I≤5: {fmt_opt(pchk['opt100'])}")
    print(f"  约束最优 V≤160,I≤5: {fmt_opt(pchk['opt160'])}")
    if args.root:
        sp = platform_selfproof(pathlib.Path(args.root).resolve())
        result['platform_selfproof'] = sp
        print(f"  自证（统一源 model.response）: {sp['vport_Vpp']:.6f} Vpp, "
              f"{sp['iport_mArms']:.6f} mA, {sp['p_rm_mW']:.6f} mW, qm={sp['qm']}")

    # ---- 1b. 工作点不变、只换谐振形状
    # 在 fs 上 Z_bvd = Rm ∥ C0 与 Q 无关，所以 100 Vpp / 5 mA / 170 mW、匹配网络与源幅度标定
    # 全都不变；M = κQ = X_C0/Rm 由工作点钉死，物理的 k_eff 只能配上对应的 Q = M/κ。
    print('\n== 1b. 保持平台工作点（C0、Rm、fs 不变），只把 k_eff 换成 PZT 的量级')
    print(f"  {'k_eff':>6}{'Cm/C0':>8}{'Q=M/κ':>8}{'FWHM(kHz)':>10}{'fp−fs(kHz)':>11}{'τ(μs)':>8}")
    same_point = []
    for keff in (0.0661, 0.30, 0.45, 0.60, 0.75):
        kap = keff ** 2 / (1.0 - keff ** 2)
        b = bvd_from(pb['c0'], pb['rm'], pb['fs'], pb['M'] / kap)
        same_point.append(b)
        print(f"  {keff:>6.3f}{kap:>8.4f}{b['q']:>8.2f}{b['fwhm']/1e3:>10.2f}"
              f"{(b['fp']-b['fs'])/1e3:>11.1f}{b['tau_us']:>8.2f}")
    result['same_point_family'] = same_point

    # ---- 2. 需求隐含的阻抗
    vnom, vmax, imax = REQ['v_nominal_Vpp'] / SQ8, REQ['v_max_Vpp'] / SQ8, REQ['i_max_Arms']
    print('\n== 2. 需求本身隐含的阻抗与功率上界')
    print(f"  100 Vpp 且 ≤5 mA ⇒ |Z| ≥ {vnom/imax:.0f} Ω；功率 ≤ V·I = {vnom*imax*1e3:.1f} mW")
    print(f"  160 Vpp 且 ≤5 mA ⇒ |Z| ≥ {vmax/imax:.0f} Ω；功率 ≤ V·I = {vmax*imax*1e3:.1f} mW")
    print(f"  C0 单独在 100 Vpp 下就吃掉 5 mA 的条件：C0 = {imax/(2*math.pi*0.9e6*vnom)*1e12:.2f} pF")

    # ---- 3. 材料 Qm 能否到 800
    print('\n== 3. 材料 Qm（Zipparo 2010 实测）与「空气中能否到 800」')
    best = {}
    for mat, m in MATERIALS.items():
        el = make_element(mat, 1e-3, 'rod', qm_target=max(m['qm_measured']))
        qs = {ld: fit_bvd(el, (lambda e, l: (lambda f: element_z(np.atleast_1d(f), e, l)))(el, ld))['q']
              for ld in ('air', 'blood', 'calcif')}
        best[mat] = qs
        print(f"  {mat:<7} 实测 Qm = {', '.join(f'{q:.0f}' for q in m['qm_measured']):<10}"
              f" 取最高牌号、D=1 mm 杆：空气 Q={qs['air']:.0f}  血液 Q={qs['blood']:.1f}"
              f"  钙化接触 Q={qs['calcif']:.1f}")
    result['best_grade_q'] = best

    # ---- 4. 元件扫描
    rows = []
    print('\n== 4. 单层端面电极元件：几何 → Mason → 拟合 BVD → 需求检查')
    head = (f"{'材料':<7}{'D':>5}{'极限':>5}{'L':>6}{'L/D':>5}{'C0':>7}{'负载':<14}{'fs':>8}"
            f"{'Q':>7}{'k_eff':>6}{'fp−fs':>8}{'Rm':>8}{'|Z|fs':>8}{'I@100':>7}"
            f"{'V@5mA':>7}{'拟合差':>7}")
    print('  ' + head)
    print('  ' + ' ' * 16 + '(mm)      (mm)       (pF)              (kHz)            (kHz)    (Ω)'
          '     (Ω)    (mA)  (Vpp)')
    for mat in MATERIALS:
        for dmm in DIAMETERS_MM:
            for limit in ('rod', 'disc'):
                el = make_element(mat, dmm * 1e-3, limit)
                for load in LOADS:
                    zf = (lambda e, ld: (lambda f: element_z(np.atleast_1d(f), e, ld)))(el, load)
                    b = fit_bvd(el, zf)
                    if b is None:
                        continue
                    chk = requirement_check(zf, b['fs'])
                    cab = cable_check(zf, chk['opt100']['f_Hz'])
                    row = dict(material=mat, D_mm=dmm, limit=limit, load=load,
                               L_mm=el['L'] * 1e3, L_over_D=el['L'] / el['D'],
                               C0_pF=el['C0'] * 1e12, qm_loss_input=el['qm_mat'],
                               fp_unloaded_Hz=el['fp_unloaded'], bvd=b, check=chk, cable=cab)
                    rows.append(row)
                    print(f"  {mat:<7}{dmm:>5.2f}{limit:>5}{el['L']*1e3:>6.2f}"
                          f"{el['L']/el['D']:>5.2f}"
                          f"{el['C0']*1e12:>7.2f} {LOAD_CN[load]:<12}{b['fs']/1e3:>8.1f}"
                          f"{b['q']:>7.1f}{b['keff']:>6.3f}{(b['fp']-b['fs'])/1e3:>8.1f}"
                          f"{b['rm']:>8.0f}{chk['absZ_at_fs_ohm']:>8.0f}"
                          f"{chk['I_at_100Vpp_mA']:>7.2f}{chk['Vpp_at_5mA']:>7.1f}"
                          f"{100*b['fit_err_band']:>6.1f}%"
                          f"{'  单支路BVD不适用' if b['fit_err_band'] > 0.25 else ''}")
    result['elements'] = rows

    # ---- 5. 约束最优点不在串联谐振
    print('\n== 5. V≤100 Vpp 且 I≤5 mA 时的最大有功功率（元件端口，0.8–1.0 MHz）')
    print(f"  {'材料':<7}{'D':>5}{'极限':>5} {'负载':<12} {'fs(kHz)':>8}  最优点")
    for r in rows:
        if r['load'] in ('blood', 'blood+ML') and r['D_mm'] in (1.0, 2.0):
            print(f"  {r['material']:<7}{r['D_mm']:>5.2f}{r['limit']:>5} {LOAD_CN[r['load']]:<12}"
                  f"{r['bvd']['fs']/1e3:>8.1f}  {fmt_opt(r['check']['opt100'])}"
                  f"  离fs {r['check']['opt100']['df_from_fs_Hz']/1e3:+.1f} kHz")

    # ---- 6. 线缆
    print(f"\n== 6. 导管线缆 {CABLE_LENGTH_M} m × {CABLE_PF_PER_M} pF/m = "
          f"{[c*CABLE_LENGTH_M for c in CABLE_PF_PER_M]} pF")
    print(f"  {'材料':<7}{'D':>5}{'极限':>5} {'负载':<12}{'C0(pF)':>8}{'Rp(Ω)':>9}"
          f"{'网络Q':>7}{'需并C(pF)':>10}  能否吸收 45/90/150 pF")
    for r in rows:
        if r['load'] == 'blood' and r['limit'] == 'rod':
            c = r['cable']
            if c['c_add_pF'] is None:
                continue
            ok = '/'.join('是' if c['c_add_pF'] >= v else '否' for v in c['cable_pF'].values())
            print(f"  {r['material']:<7}{r['D_mm']:>5.2f}{r['limit']:>5} {LOAD_CN[r['load']]:<12}"
                  f"{r['C0_pF']:>8.2f}{c['rp_ohm']:>9.0f}{c['q_network']:>7.2f}"
                  f"{c['c_add_pF']:>10.1f}  {ok}")

    # ---- 7. 横向（径向）模态位置提示
    print('\n== 7. 薄片径向模估计 f_r ≈ η1·v_p/(πD)（η1≈2.05；只作提示，厚元件会偏）')
    for mat, m in MATERIALS.items():
        s11, s12 = {'PZT-5H': (16.5e-12, -4.78e-12), 'PZT-4': (12.3e-12, -4.05e-12),
                    'PZT-8': (11.5e-12, -3.7e-12)}[mat]
        sigma = -s12 / s11
        vp = 1.0 / math.sqrt(m['rho'] * s11 * (1 - sigma ** 2))
        print(f"  {mat:<7} " + '  '.join(f"D={d:.2f}mm: {2.05*vp/(math.pi*d*1e-3)/1e3:6.0f} kHz"
                                         for d in DIAMETERS_MM))

    if out_dir is not None:
        (out_dir / 'physical_realizability.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=float), encoding='utf-8')
        print(f'\n已写入 {out_dir / "physical_realizability.json"}')


if __name__ == '__main__':
    main()
