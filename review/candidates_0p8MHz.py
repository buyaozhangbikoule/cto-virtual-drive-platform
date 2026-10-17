#!/usr/bin/env python3
"""0.8 MHz 附近的端面电极压电杆：材料与直径怎么选（review/30 第六节）。

    python review/candidates_0p8MHz.py [--out <目录>]

只读；--out 时另写一份 JSON（拒绝 workspace/ 与 outputs/）。运行期依赖 numpy 与 scipy（无法兰边界）。
元件、Mason 模型与 BVD 提取沿用 codex_baseline_check.py（review/24 的实现），无法兰端面沿用
radiation_boundary_check.py。

用户 2026-10-17 的要求：工作频率在 0.8 MHz 附近；源阻抗 50 Ω；约 100 Vpp、不超过 160 Vpp；
电流上限 5 mA RMS，推荐更小；直径最好不超过 2 mm，长度可放宽；材料可选 PZT-5H、PZT-4/8。

做法
  - 材料：APC 880（Codex 报告的常数，材料 Qm 1000）；PZT-8、PZT-4、PZT-5H（review/24 的手册典型常数，
    材料 Qm 取 Zipparo 2010 表 II 的商用常见牌号：350、280、63）。同牌号各厂家差 ±10–20%，Qm 差几倍。
  - 几何：轴向极化实心杆，两端面电极；前端类血液液体（1050 kg/m³、1570 m/s），后端自由（空气背衬）。
    每种材料、每个直径单独解出使有载 fs = 800 kHz 的长度。
  - 前端无限障板为主表；D 0.5 mm 另算无法兰端面（review/29 第 7.4 节）。
  - 正常工作包络取换能器端 ≤100 Vpp、≤4 mA（「电流推荐小一点」，硬限 5 mA 留作保护余量），直接驱动，
    在 fs ± 80 kHz 内求最大有功功率及其频率。
  - 辐射效率 η ≈ 1 − Q/Qm（两种损耗相加）；内耗 = (1 − η)·P。
  - 端面位移单边峰值 x = √2·√(η·P / Re Z_rad) / ω，Re Z_rad 为端面辐射电阻（一维、线性，只作量级）。
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
import codex_baseline_check as C        # noqa: E402
import radiation_boundary_check as RB   # noqa: E402
PR = C.PR

F_TARGET = 0.8e6
V_NOM, I_NORMAL = 100.0, 4e-3
MATERIALS = ('APC880', 'PZT-8', 'PZT-4', 'PZT-5H')
DIAMETERS_MM = (0.4, 0.5, 0.6, 0.8, 1.0)
PR.MATERIALS['APC880'] = C.APC880
PR.REQ['band_Hz'] = (0.7e6, 0.9e6)      # 只影响报告的带内拟合差：频带以 0.8 MHz 为中心


def element(material, d, length):
    m = PR.MATERIALS[material]
    v = 1.0 / math.sqrt(m['rho'] * m['s33E'] * (1.0 - m['k33'] ** 2))
    el = PR.make_element(material, d, 'rod', fs_Hz=v * PR.series_root(m['k33']) / (math.pi * length))
    assert abs(el['L'] / length - 1.0) < 1e-12
    return el


def length_for(material, d, f_target=F_TARGET):
    lo, hi = 1.4e-3, 2.6e-3
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        el = element(material, d, mid)
        fs = PR.fit_bvd(el, C.zfun(el))['fs']
        lo, hi = (mid, hi) if fs > f_target else (lo, mid)
    return 0.5 * (lo + hi)


def operating_point(z, center, v_vpp=V_NOM, i_max=I_NORMAL):
    """换能器端 ≤ v_vpp、≤ i_max 时的最大有功功率（直接驱动，端口电压可调）。
    电流限起作用时最优点移到 fs 之上、两条限值同时到达处，所以窗口向上放宽。"""
    f = np.arange(center - 100e3, center + 250e3 + 0.1, 50.0)
    y = 1.0 / z(f)
    v = np.minimum(v_vpp / C.SQ8, i_max / np.abs(y))
    p = v * v * y.real
    k = int(np.argmax(p))
    assert 0 < k < len(f) - 1, '最优点落在窗口边缘'
    vpp, ma = float(v[k] * C.SQ8), float(v[k] * abs(y[k]) * 1e3)
    v_on, i_on = vpp > v_vpp * 0.99, ma > i_max * 1e3 * 0.99      # 1%：50 Hz 网格的分辨率
    return dict(f_Hz=float(f[k]), port_Vpp=vpp, port_mA=ma, port_P_mW=float(p[k] * 1e3),
                power_factor=float(y.real[k] / abs(y[k])),
                binding='both' if v_on and i_on else ('voltage' if v_on else 'current'))


BINDING_CN = {'voltage': '电压限', 'current': '电流限', 'both': '电压与电流限同时'}


def displacement_um(p_w, eta, f, d, front):
    ka = 2 * math.pi * f / C.FLUID[1] * d / 2
    z = RB.z_baffled(ka) if front == 'baffled' else RB.z_unflanged(ka)
    r_rad = C.FLUID[0] * C.FLUID[1] * math.pi * (d / 2) ** 2 * float(np.real(z))
    return math.sqrt(2.0) * math.sqrt(eta * p_w / r_rad) / (2 * math.pi * f) * 1e6


def case(material, d, length, front):
    el = element(material, d, length)
    z = C.zfun(el) if front == 'baffled' else RB.zfun(el, 'unflanged')
    s = C.summary(el, z, f'{material} D {d*1e3:.1f} mm {front}')
    qm = PR.MATERIALS[material]['qm_measured'][0]
    eta = 1.0 - s['Q'] / qm
    op = operating_point(z, s['fs_Hz'])
    s.update(material=material, D_mm=d * 1e3, L_mm=length * 1e3, front=front, material_Qm=qm, eta=eta,
             operating_point=op, internal_loss_mW=(1 - eta) * op['port_P_mW'],
             displacement_um=displacement_um(op['port_P_mW'] * 1e-3, eta, op['f_Hz'], d, front))
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    PR.self_checks()
    rows, unfl = [], []
    print('== 有载 fs = 800 kHz 的端面电极杆；前端无限障板、类血液液体，后端自由；换能器端 ≤100 Vpp、≤4 mA')
    print('  材料     D     L        Q     Rm       C0      100 Vpp@fs        正常包络内最大功率                    η     内耗   端面位移')
    for mat in MATERIALS:
        for dmm in DIAMETERS_MM:
            d = dmm * 1e-3
            s = case(mat, d, length_for(mat, d), 'baffled')
            rows.append(s)
            op = s['operating_point']
            print(f"  {mat:<7} {dmm:.1f}  {s['L_mm']:.3f} mm  {s['Q']:5.1f}  {s['Rm_ohm']/1e3:5.2f} kΩ  {s['C0_clamped_pF']:5.2f} pF  "
                  f"{s['I_at_fs_100Vpp_mA']:5.2f} mA {s['P_at_fs_100Vpp_mW']:6.1f} mW  "
                  f"{op['f_Hz']/1e3:6.1f} kHz {op['port_Vpp']:5.1f} Vpp {op['port_mA']:4.2f} mA {op['port_P_mW']:6.1f} mW"
                  f"（{BINDING_CN[op['binding']]}）  {s['eta']:.2f}  {s['internal_loss_mW']:5.1f} mW  "
                  f"{s['displacement_um']:.3f} μm")
    print('\n== D 0.5 mm 的无法兰端面（导管与杆同径），同一长度')
    for s0 in [r for r in rows if r['D_mm'] == 0.5]:
        s = case(s0['material'], 0.5e-3, s0['L_mm'] * 1e-3, 'unflanged')
        unfl.append(s)
        op = s['operating_point']
        print(f"  {s['material']:<7} Q {s['Q']:5.1f}  Rm {s['Rm_ohm']/1e3:5.2f} kΩ  100 Vpp@fs {s['I_at_fs_100Vpp_mA']:5.2f} mA  "
              f"最大功率 {op['port_P_mW']:6.1f} mW（{op['f_Hz']/1e3:.1f} kHz、{op['port_Vpp']:5.1f} Vpp、{op['port_mA']:4.2f} mA，"
              f"{BINDING_CN[op['binding']]}）  η {s['eta']:.2f}  位移 {s['displacement_um']:.3f} μm")
    res = dict(target_fs_Hz=F_TARGET, envelope=dict(port_Vpp=V_NOM, port_mA=I_NORMAL * 1e3), fluid=C.FLUID,
               materials={k: PR.MATERIALS[k] for k in MATERIALS}, baffled=rows, unflanged_D0p5=unfl)
    if a.out:
        out = pathlib.Path(a.out).resolve()
        if {'workspace', 'outputs'} & set(out.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out}')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'candidates_0p8MHz.json').write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float) + '\n',
                                                    encoding='utf-8')
        print(f'\n已写入 {out / "candidates_0p8MHz.json"}')


if __name__ == '__main__':
    main()
