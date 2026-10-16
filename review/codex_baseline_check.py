#!/usr/bin/env python3
"""审核 Codex 的物理候选基线（APC 880 杆，D 0.5 mm × L 1.8 mm）：独立模型复核与补充检查（review/29）。

    python review/codex_baseline_check.py [--codex <Codex 交付目录>] [--out <目录>]

只读；--out 时另写一份 JSON（拒绝 workspace/ 与 outputs/）。运行期只依赖 numpy。
--codex：目录里有 derive_candidates.py、assumptions_20261016.json、bvd_candidate_profiles.json 时，
在临时目录里原样运行 Codex 的脚本（python -I），把结果与它交付的参数表逐项比对（第 0 项）。
Codex 没有交付 assumptions_20261016.json；仓库里那份按其报告的数值重建，见文件内 purpose。

独立性：不调用 Codex 的 derive_candidates.py。元件、Mason 模型、圆活塞辐射阻抗与 BVD 提取
全部用本仓库 review/24 的 physical_realizability_study.py（另一套实现：损耗加在波速上、
BVD 用动生导纳峰与半功率宽度提取、C0 取夹持电容）。材料常数、几何、流体参数取 Codex 报告里的值，
对照值是 Codex 交付的 bvd_candidate_profiles.json（下面 CODEX_B）。

检查项
  1. 同一边界（前端无限障板圆活塞、类血液液体 1050 kg/m³ / 1570 m/s，后端自由）下，两套实现的
     fs、Rm、Q 是否一致；本模型的阻抗曲线与 Codex 的四元件 BVD（加回介电电导）差多少。
  2. Codex 没算的安装与接触：后端平面波背衬 1.5 / 3 MRayl（声明值，类聚合物/环氧；相当于与杆同截面的长背衬柱，
     是背衬加载的上限）；后端贴在大块环氧上（1200 kg/m³、2500 m/s，按圆活塞向半空间辐射，是较轻的一端）；
     前端压在钙化斑块上（沿用仓库声明 1900 kg/m³、3600 m/s，按流体活塞公式，只作量级）。
  3. 把有载 fs 调到 0.9 MHz 需要的长度，以及该长度下的 BVD。
  4. 驱动与线缆：用户已确认 5 mA 上限的测点在换能器端（review/28）。
     a. 复现 Codex 的「功放端与陶瓷端同时 ≤ 限值」表（直接驱动、并联线缆电容）；
     b. 只限换能器端时同样的线缆电容下陶瓷端功率、功放电流与所需源电压；
     c. 换成把负载匹配到 50 Ω 的无损网络时，所需源电压与功放电流。
  5. 线缆对测量的影响：近端（功放侧）导纳相位在谐振附近的摆幅，与换能器端口相比。
  6. 平台用的峰宽：直接驱动、恒定源幅度时端口功率的半功率宽度。
  7. 〔补充，review/29 第六节〕前端 λ/4 匹配层（Liu 等的导管用了环氧匹配层）：环氧 1150 kg/m³、2500 m/s
     （声明值，约 2.9 MRayl）与 review/24 的 6 MRayl 层，层厚为 0.9 MHz 的 λ/4，按一维平面波变换后接圆活塞辐射。
  8. 〔补充〕电极方式与阻抗量级：端面电极细杆（Codex）与内外壁电极的径向极化管（Liu 等：PZT-5H、
     外径/内径 1.35/0.73 mm、长 2.5 mm）的夹持电容、0.9 MHz 容抗，以及 100 Vpp 时仅 C0 支路的电流。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import physical_realizability_study as PR   # noqa: E402  review/24 的独立实现

SQ8 = PR.SQ8
FLUID = (1050.0, 1570.0)          # Codex 报告的类血液液体（Kim 等 2017 的标称值）
L_CODEX = 1.8e-3
# Codex 报告与 bvd_candidate_profiles.json 里的值（材料表典型值；本会话无法访问厂家网页核对）
APC880 = dict(rho=7600.0, eps33T=1050.0, eps33S=None, k33=0.62, kt=None, s33E=1.0 / 72e9,
              c33D=None, tand=0.004, qm_measured=(1000.0,))
CODEX_B = dict(c0=6.778976436547607e-13, rm=9368.265426159336, lm=0.0951619669770087,
               cm=3.4870353270187705e-13, fs=873695.8099102303, q=55.76277071210622)
CABLE_PF = (0.0, 5.0, 10.0, 30.0, 100.0, 150.0)
BACKING_RAYL = (1.5e6, 3.0e6)
EPOXY_BLOCK = (1200.0, 2500.0)    # 声明值：大块环氧背衬，ρc = 3.0 MRayl
EPOXY_LAYER = (1150.0, 2500.0)    # 声明值：未填充环氧匹配层，约 2.9 MRayl
PZT5H_EPS = dict(eps33T=3400.0, eps33S=1470.0)   # review/24 MATERIALS['PZT-5H']
CALCIF = PR.MEDIA['calcif']


def reproduce_codex(codex_dir):
    """在临时目录里原样运行 Codex 的 derive_candidates.py，与它交付的 bvd_candidate_profiles.json 比对。"""
    import shutil
    import subprocess
    import tempfile
    src = pathlib.Path(codex_dir).resolve()
    profiles = json.loads((src / 'bvd_candidate_profiles.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory() as tmp:
        for name in ('derive_candidates.py', 'assumptions_20261016.json'):
            shutil.copy2(src / name, pathlib.Path(tmp) / name)
        run = subprocess.run([sys.executable, '-I', 'derive_candidates.py'], cwd=tmp, capture_output=True, text=True)
        if run.returncode:
            raise SystemExit('Codex 脚本运行失败：\n' + run.stderr[-2000:])
        out = json.loads((pathlib.Path(tmp) / 'candidate_parameters.json').read_text(encoding='utf-8'))
    rows = []
    for c, p in zip(out['candidates'], profiles):
        b = c['bvd']
        diffs = {k: abs(b[a] / p[r] - 1.0) for k, a, r in (('C0', 'c0', 'C0_F'), ('Rm', 'rm', 'Rm_ohm'), ('Lm', 'lm', 'Lm_H'),
                                                       ('Cm', 'cm', 'Cm_F'), ('fs', 'fs', 'fs_Hz'), ('Q', 'q', 'Q_loaded'))}
        normal = c['constrained_optima']['V100_I4mA']
        rows.append(dict(id=c['id'], max_rel_diff_vs_profile=max(diffs.values()), fit_err=b['fit']['max_relative_Z_error'],
                         normal_f_Hz=normal['f_Hz'], normal_P_mW=normal['port_P_W'] * 1e3, normal_I_mA=normal['ceramic_Arms'] * 1e3,
                         P_900kHz_100Vpp_mW=c['points']['at_900k_100Vpp']['port_P_W'] * 1e3,
                         load_sensitivity=[dict(scale=s['scale'], Q=s['bvd']['q'], fit_ok=s['bvd']['fit']['passes_5percent_gate'])
                                           for s in c['load_sensitivity']]))
    return dict(rows=rows, primary_sensitivity=[dict(name=s['name'], Q=s['bvd']['q'], fs_Hz=s['bvd']['fs'],
                                                     fit_err=s['bvd']['fit']['max_relative_Z_error'])
                                                for s in out['primary_sensitivity']])


def element(d, length=L_CODEX):
    PR.MATERIALS['APC880'] = APC880
    m = APC880
    v = 1.0 / math.sqrt(m['rho'] * m['s33E'] * (1.0 - m['k33'] ** 2))
    fs_free = v * PR.series_root(m['k33']) / (math.pi * length)      # make_element 由 fs 反解 L
    el = PR.make_element('APC880', d, 'rod', fs_Hz=fs_free)
    assert abs(el['L'] / length - 1.0) < 1e-12
    return el


def zfun(el, front='fluid', back_rayl=0.0, back_block=None, layer=None):
    a = el['D'] / 2.0

    def z(f):
        f = np.atleast_1d(np.asarray(f, dtype=float))
        rho0, c0 = FLUID if front == 'fluid' else CALCIF
        zb = back_rayl * el['A'] if back_block is None else PR.piston_z(f, a, *back_block)
        zf = PR.piston_z(f, a, rho0, c0)
        if layer is not None:                  # λ/4 层（按 0.9 MHz 定厚），一维平面波变换
            rho_l, c_l = layer
            zf = PR.through_layer(f, zf, el['A'], rho_l, c_l, c_l / (4.0 * 0.9e6))
        return PR.mason_z(f, el, zf, zb)
    return z


def bvd_y(f, b, gd_c=0.0, tand=0.0):
    w = 2.0 * np.pi * np.asarray(f, dtype=float)
    return 1j * w * b['c0'] + 1.0 / (b['rm'] + 1j * (w * b['lm'] - 1.0 / (w * b['cm']))) + w * gd_c * tand


def summary(el, z, label):
    b = PR.fit_bvd(el, z)
    zs = complex(z(np.array([b['fs']]))[0])
    v = 100.0 / SQ8
    return dict(case=label, fs_Hz=b['fs'], Q=b['q'], Rm_ohm=b['rm'], C0_clamped_pF=el['C0'] * 1e12,
                keff=b['keff'], fwhm_Hz=b['fwhm'], fit_err_band=b['fit_err_band'],
                I_at_fs_100Vpp_mA=v / abs(zs) * 1e3, P_at_fs_100Vpp_mW=v * v * (1.0 / zs).real * 1e3)


def drive_grid(z, c_pF, v_max_vpp, i_port_max=None, i_amp_max=None, step=25.0):
    """直接驱动：50 Ω 戴维南源串联，陶瓷端并联线缆电容。逐频点取最大允许的陶瓷端电压，再取功率最大点。"""
    f = np.arange(0.8e6, 1.0e6 + 0.1, step)
    w = 2.0 * np.pi * f
    y = 1.0 / z(f)
    y_amp = y + 1j * w * c_pF * 1e-12
    v = np.full(len(f), v_max_vpp / SQ8)
    if i_port_max is not None:
        v = np.minimum(v, i_port_max / np.abs(y))
    if i_amp_max is not None:
        v = np.minimum(v, i_amp_max / np.abs(y_amp))
    p = v * v * y.real
    k = int(np.argmax(p))
    i_amp = v[k] * y_amp[k]
    vs = v[k] + PR.REQ['rs_ohm'] * i_amp
    return dict(f_Hz=float(f[k]), port_Vpp=float(v[k] * SQ8), port_mA=float(v[k] * abs(y[k]) * 1e3),
                amp_mA=float(abs(i_amp) * 1e3), port_P_mW=float(p[k] * 1e3), source_open_Vpp=float(abs(vs) * SQ8))


def proximal_phase(z, b, c_pF):
    """近端（并联线缆电容之后）导纳相位，在 fs ± 2·fs/Q 内的摆幅；与陶瓷端口相比。"""
    f = np.linspace(b['fs'] - 2 * b['fwhm'], b['fs'] + 2 * b['fwhm'], 2001)
    y = 1.0 / z(f)
    yp = y + 1j * 2 * np.pi * f * c_pF * 1e-12
    ph_port, ph_prox = np.degrees(np.angle(y)), np.degrees(np.angle(yp))
    return dict(cable_pF=c_pF, port_swing_deg=float(ph_port.max() - ph_port.min()),
                proximal_swing_deg=float(ph_prox.max() - ph_prox.min()),
                proximal_phase_at_fs_deg=float(np.degrees(np.angle(1.0 / complex(z(np.array([b['fs']]))[0])
                                                                   + 1j * 2 * np.pi * b['fs'] * c_pF * 1e-12))))


def half_power_width(z, center, span=60e3):
    f = np.linspace(center - span, center + span, 24001)
    p = (1.0 / z(f)).real                     # 恒定端口电压（直接驱动、源内阻可忽略）时 P ∝ G
    i = int(np.argmax(p))
    hp = PR.half_power(f, p, i)
    return None if hp is None else float(hp[1] - hp[0])


def length_for(fs_target, d=0.5e-3):
    lo, hi = 1.6e-3, 1.9e-3
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        el = element(d, mid)
        fs = PR.fit_bvd(el, zfun(el))['fs']
        lo, hi = (mid, hi) if fs > fs_target else (lo, mid)
    return 0.5 * (lo + hi)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--codex', default=None, help='Codex 交付目录（可选）')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    PR.self_checks()
    res = dict(material=APC880, fluid=FLUID, codex_reference=CODEX_B)

    if a.codex:
        rep = reproduce_codex(a.codex)
        res['codex_reproduction'] = rep
        print('== 0. 原样运行 Codex 的脚本（重建的假设文件），与它交付的参数表比对')
        for r in rep['rows']:
            print(f"  {r['id']}: 六个 BVD 量最大相对差 {r['max_rel_diff_vs_profile']:.1e}；拟合差 {100*r['fit_err']:.2f}%；"
                  f"100 Vpp/4 mA 最优 {r['normal_f_Hz']/1e3:.2f} kHz {r['normal_P_mW']:.2f} mW {r['normal_I_mA']:.3f} mA；"
                  f"0.9 MHz {r['P_900kHz_100Vpp_mW']:.2f} mW；负载 " +
                  '，'.join(f"×{s['scale']:g} Q {s['Q']:.1f}{'' if s['fit_ok'] else '（拟合未过 5%）'}" for s in r['load_sensitivity']))
        print()

    # 1. 同一边界下两套实现对照
    el = element(0.5e-3)
    z = zfun(el)
    s = summary(el, z, 'B, 同一边界')
    f = np.linspace(0.8e6, 1.0e6, 1601)
    y_model = 1.0 / z(f)
    y_codex = bvd_y(f, CODEX_B, el['C0'], APC880['tand'])
    s['codex_bvd_vs_this_model_max_rel_Z_err'] = float(np.max(np.abs(1 / y_codex - 1 / y_model) / np.abs(1 / y_model)))
    s['rel_diff_fs'] = s['fs_Hz'] / CODEX_B['fs'] - 1
    s['rel_diff_Rm'] = s['Rm_ohm'] / CODEX_B['rm'] - 1
    s['rel_diff_Q'] = s['Q'] / CODEX_B['q'] - 1
    p900 = (1.0 / complex(z(np.array([0.9e6]))[0])).real * (100 / SQ8) ** 2
    s['P_at_900kHz_100Vpp_mW'] = p900 * 1e3
    res['cross_check'] = s
    print('== 1. 同一边界（前端障板活塞、类血液液体，后端自由），review/24 的独立实现 vs Codex')
    print(f"  fs {s['fs_Hz']/1e3:.3f} kHz（{100*s['rel_diff_fs']:+.3f}%）  Rm {s['Rm_ohm']:.1f} Ω（{100*s['rel_diff_Rm']:+.2f}%）"
          f"  Q {s['Q']:.2f}（{100*s['rel_diff_Q']:+.2f}%）  夹持 C0 {s['C0_clamped_pF']:.4f} pF")
    print(f"  Codex 的四元件 BVD（+介电电导）对本模型 0.8–1 MHz 最大复阻抗相对差 {100*s['codex_bvd_vs_this_model_max_rel_Z_err']:.2f}%")
    print(f"  fs 处 100 Vpp：{s['I_at_fs_100Vpp_mA']:.3f} mA、{s['P_at_fs_100Vpp_mW']:.2f} mW；0.9 MHz 处 100 Vpp：{p900*1e3:.2f} mW")

    # 2. 安装与接触
    cases = [summary(el, zfun(el), '前端液体，后端自由（Codex）')]
    for zb in BACKING_RAYL:
        cases.append(summary(el, zfun(el, back_rayl=zb), f'前端液体，后端背衬 {zb/1e6:g} MRayl'))
    cases.append(summary(el, zfun(el, back_block=EPOXY_BLOCK), '前端液体，后端贴大块环氧'))
    cases.append(summary(el, zfun(el, front='calcif'), '前端压在钙化斑块上，后端自由'))
    cases.append(summary(el, zfun(el, front='calcif', back_rayl=3.0e6), '钙化接触＋背衬 3 MRayl'))
    res['mounting_and_contact'] = cases
    print('\n== 2. 安装与接触（D 0.5 mm、L 1.8 mm）')
    for c in cases:
        print(f"  {c['case']:<22} fs {c['fs_Hz']/1e3:7.2f} kHz  Q {c['Q']:6.1f}  Rm {c['Rm_ohm']:7.0f} Ω"
              f"  100 Vpp@fs {c['I_at_fs_100Vpp_mA']:5.2f} mA {c['P_at_fs_100Vpp_mW']:6.1f} mW  拟合差 {100*c['fit_err_band']:.1f}%")

    # 3. 有载 fs = 0.9 MHz 的长度
    l9 = length_for(0.9e6)
    el9 = element(0.5e-3, l9)
    s9 = summary(el9, zfun(el9), f'L = {l9*1e3:.4f} mm')
    s9['L_mm'] = l9 * 1e3
    res['tuned_to_0p9MHz'] = s9
    print(f"\n== 3. 有载 fs 调到 0.9 MHz：L = {l9*1e3:.4f} mm（原 1.8 mm）")
    print(f"  fs {s9['fs_Hz']/1e3:.3f} kHz  Q {s9['Q']:.2f}  Rm {s9['Rm_ohm']:.1f} Ω  C0(夹持) {s9['C0_clamped_pF']:.4f} pF"
          f"  100 Vpp@fs {s9['I_at_fs_100Vpp_mA']:.3f} mA {s9['P_at_fs_100Vpp_mW']:.1f} mW")

    # 4. 驱动与线缆
    drive = []
    for c in CABLE_PF:
        row = dict(cable_pF=c)
        for ilim in (4e-3, 5e-3):
            row[f'codex_both_ends_{int(ilim*1e3)}mA'] = drive_grid(z, c, 100.0, ilim, ilim)
        row['port_only_4p5mA'] = drive_grid(z, c, 100.0, 4.5e-3, None)
        p = row['port_only_4p5mA']['port_P_mW'] * 1e-3
        row['matched_50ohm'] = dict(port_P_mW=p * 1e3, amp_mA=math.sqrt(p / 50.0) * 1e3,
                                    source_open_Vpp=2.0 * math.sqrt(50.0 * p) * SQ8)
        drive.append(row)
    res['drive_and_cable'] = drive
    print('\n== 4. 驱动与线缆（D 0.5 mm、L 1.8 mm；陶瓷端 ≤ 100 Vpp）')
    print('  电容   Codex口径(两端≤5 mA)          只限换能器端 ≤4.5 mA（用户口径）                   匹配到 50 Ω')
    for r in drive:
        cb, po, mt = r['codex_both_ends_5mA'], r['port_only_4p5mA'], r['matched_50ohm']
        print(f"  {r['cable_pF']:5.0f}pF  {cb['port_Vpp']:6.1f}Vpp {cb['port_P_mW']:6.1f}mW  |  "
              f"{po['port_Vpp']:6.1f}Vpp {po['port_mA']:4.2f}mA {po['port_P_mW']:6.1f}mW 功放{po['amp_mA']:5.1f}mA 源{po['source_open_Vpp']:6.1f}Vpp  |  "
              f"功放{mt['amp_mA']:5.1f}mA 源{mt['source_open_Vpp']:5.1f}Vpp")

    # 5. 近端测量
    b = PR.fit_bvd(el, z)
    prox = [proximal_phase(z, b, c) for c in (0.0, 30.0, 100.0, 150.0)]
    res['proximal_phase'] = prox
    print('\n== 5. 近端测量：fs ± 2 个半功率宽度内的导纳相位摆幅')
    for p in prox:
        print(f"  线缆 {p['cable_pF']:5.0f} pF：端口摆幅 {p['port_swing_deg']:5.1f}°，近端摆幅 {p['proximal_swing_deg']:5.1f}°，"
              f"近端 fs 处相位 {p['proximal_phase_at_fs_deg']:5.1f}°")

    # 6. 峰宽
    widths = dict(B_L1p8=half_power_width(z, b['fs']), B_tuned=half_power_width(zfun(el9), s9['fs_Hz']),
                  platform_default_nominal_peak_width_Hz=2142, synthetic_candidate_nominal_peak_width_Hz=86872)
    res['half_power_width_Hz'] = widths
    print(f"\n== 6. 端口功率半功率宽度（恒定端口电压）：B {widths['B_L1p8']:.0f} Hz，调到 0.9 MHz 后 {widths['B_tuned']:.0f} Hz；"
          f"平台默认 2142 Hz、合成候选 86872 Hz")

    # 7. 前端匹配层
    layers = []
    for lab, e in (('L 1.8 mm', el), (f'L {l9*1e3:.3f} mm', el9)):
        layers.append(summary(e, zfun(e), f'{lab}，无匹配层'))
        for name, lay in (('环氧层 2.9 MRayl', EPOXY_LAYER), ('6 MRayl 层', (PR.MATCH_LAYER['rho'], PR.MATCH_LAYER['c']))):
            layers.append(summary(e, zfun(e, layer=lay), f'{lab}，λ/4 {name}'))
    res['front_matching_layer'] = layers
    print('\n== 7. 前端 λ/4 匹配层（层厚按 0.9 MHz；后端自由）')
    for c in layers:
        print(f"  {c['case']:<26} fs {c['fs_Hz']/1e3:7.2f} kHz  Q {c['Q']:6.1f}  Rm {c['Rm_ohm']:7.0f} Ω"
              f"  100 Vpp@fs {c['I_at_fs_100Vpp_mA']:5.2f} mA {c['P_at_fs_100Vpp_mW']:6.1f} mW")

    # 8. 电极方式与阻抗量级
    eps0, v = PR.EPS0, 100.0 / SQ8
    ro, ri, lt = 1.35e-3 / 2, 0.73e-3 / 2, 2.5e-3
    tube = {k: 2 * math.pi * e * eps0 * lt / math.log(ro / ri) for k, e in (('clamped', PZT5H_EPS['eps33S']), ('free', PZT5H_EPS['eps33T']))}
    w9 = 2 * math.pi * 0.9e6
    elec = dict(rod_end_electrodes_C0_pF=el9['C0'] * 1e12, rod_Xc0_ohm=1 / (w9 * el9['C0']),
                tube_lateral_C_clamped_pF=tube['clamped'] * 1e12, tube_lateral_C_free_pF=tube['free'] * 1e12,
                tube_Xc0_clamped_ohm=1 / (w9 * tube['clamped']), tube_Xc0_free_ohm=1 / (w9 * tube['free']),
                tube_C0_branch_current_at_100Vpp_mA=(v * w9 * tube['clamped'] * 1e3, v * w9 * tube['free'] * 1e3),
                min_abs_Z_for_100Vpp_within_5mA_ohm=v / 5e-3)
    res['electrode_configuration'] = elec
    print('\n== 8. 电极方式与阻抗量级（0.9 MHz）')
    print(f"  端面电极杆（L {l9*1e3:.3f} mm）：C0 {elec['rod_end_electrodes_C0_pF']:.3f} pF，容抗 {elec['rod_Xc0_ohm']/1e3:.0f} kΩ")
    print(f"  内外壁电极管（Liu 等尺寸，PZT-5H）：C 夹持 {elec['tube_lateral_C_clamped_pF']:.0f} pF / 自由 {elec['tube_lateral_C_free_pF']:.0f} pF，"
          f"容抗 {elec['tube_Xc0_clamped_ohm']:.0f} / {elec['tube_Xc0_free_ohm']:.0f} Ω；100 Vpp 时仅 C0 支路 "
          f"{elec['tube_C0_branch_current_at_100Vpp_mA'][0]:.0f}–{elec['tube_C0_branch_current_at_100Vpp_mA'][1]:.0f} mA")
    print(f"  100 Vpp 且 ≤ 5 mA 要求端口 |Z| ≥ {elec['min_abs_Z_for_100Vpp_within_5mA_ohm']:.0f} Ω")

    if a.out:
        out = pathlib.Path(a.out).resolve()
        if {'workspace', 'outputs'} & set(out.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out}')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'codex_baseline_check.json').write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float) + '\n',
                                                        encoding='utf-8')
        print(f'\n已写入 {out / "codex_baseline_check.json"}')


if __name__ == '__main__':
    main()
