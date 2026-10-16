#!/usr/bin/env python3
"""对 55fbe6e 审查意见里几条可计算论断的独立复算（只读，不落盘，除非给 --out）。

    python review/review_claims_check_20261016.py --root <main 的 current/unified（原样）>

一、几何缩小不是均匀阻抗缩放：同材料、同长度，端面积缩为 0.6 倍时，用本仓库
    physical_realizability_study.py 的 Mason 模型（血液前负载、空气背衬）重新拟合 BVD，
    看 Q、fs、|Z| 是否按 k = 5/3 均匀缩放（Q、fs 不变，|Z| 乘 5/3）。
二、5 mA 的测点：现有三种设计（5 / 4 / 3 mA，100 Vpp 换能器端）在 0.9 MHz、a=1 时，
    功放输出端（戴维南源支路）电流是多少。用平台模型本身的 response() 计算。
三、两支路电流是相量和：在一只 C0 很大的元件上，反谐振附近端口总电流可以小于 C0 支路电流；
    并检查 2 mm 元件在 0.8–1.0 MHz 带内是否存在 |Z| ≥ 7071 Ω（100 Vpp 且 ≤ 5 mA）的频点。
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
import physical_realizability_study as PR      # noqa: E402
import design_current_study as DC              # noqa: E402

SQ8 = 2.0 * math.sqrt(2.0)


def shrink_case(material='PZT-8', limit='disc', d0=2e-3, area_ratio=0.6, load='blood'):
    d1 = d0 * math.sqrt(area_ratio)
    out = {}
    for tag, d in (('D0', d0), ('D1', d1)):
        el = PR.make_element(material, d, limit)
        zf = lambda f, el=el: PR.element_z(np.atleast_1d(f), el, load)     # noqa: E731
        b = PR.fit_bvd(el, zf)
        z_fs = complex(zf(np.array([b['fs']]))[0])
        z_09 = complex(zf(np.array([0.9e6]))[0])
        out[tag] = dict(D_mm=d * 1e3, L_mm=el['L'] * 1e3, C0_pF=el['C0'] * 1e12, Q=b['q'], fs_kHz=b['fs'] / 1e3,
                        Rm_ohm=b['rm'], keff=b['keff'], absZ_fs_ohm=abs(z_fs), absZ_0p9MHz_ohm=abs(z_09),
                        fit_err_band=b['fit_err_band'])
    a, b = out['D0'], out['D1']
    out['ratios'] = dict(Q=b['Q'] / a['Q'], fs=b['fs_kHz'] / a['fs_kHz'], Rm=b['Rm_ohm'] / a['Rm_ohm'],
                         C0=b['C0_pF'] / a['C0_pF'], absZ_fs=b['absZ_fs_ohm'] / a['absZ_fs_ohm'],
                         absZ_0p9MHz=b['absZ_0p9MHz_ohm'] / a['absZ_0p9MHz_ohm'],
                         uniform_scaling_requires=1.0 / area_ratio)
    return out


def amplifier_current(root):
    """三种设计在 0.9 MHz、a=1 时：换能器端电压/电流与功放输出端（源支路）电流。"""
    sys.path.insert(0, str(root))
    from models import model_v2_1 as model                     # noqa: E402
    base, match, rs = model.BASE_BVD, model.BASE_MATCH, model.BASE_RS
    w0 = 2 * math.pi * base.fs
    q13 = ((1 / (w0 * base.c0)) / base.rm) / (0.45 ** 2 / (1 - 0.45 ** 2))
    rows = []
    saved = model.SOURCE_A1_VRMS
    try:
        for label, bvd, m_k, a1 in [('5 mA（登记，Q=800）', base, match, saved)] + [
                (f'{i:g} mA（合成候选，Q=13.81）', None, None, None) for i in (5.0, 4.0, 3.0)]:
            if bvd is None:
                i_d = float(label.split()[0])
                k = 5.0 / i_d
                b13 = model.changed_qm(base, q13)
                bvd = model.bvd_from_fs_qm(c0=b13.c0 / k, rm=b13.rm * k, fs=b13.fs, qm=b13.qm)
                if i_d == 5.0:
                    m_k, a1 = match, saved
                else:
                    dm = DC.design_matching(bvd, rs, match.ql, match.qc, model.F0)
                    m_k = model.Matching(l_h=dm['l_active_H'], c_f=dm['c_active_F'], ql=match.ql, qc=match.qc)
                    model.SOURCE_A1_VRMS = 1.0
                    probe = model.Scenario('P', 'p', 'p', 'p', '', bvd, m_k, rs)
                    a1 = 100.0 / float(model.response(0.9e6, probe, 1.0)['vport_vpp'][0])
            model.SOURCE_A1_VRMS = a1
            sc = model.Scenario('P', 'p', 'p', 'p', '', bvd, m_k, rs)
            q = model.response(0.9e6, sc, 1.0)
            rows.append(dict(design=label, Qm=bvd.qm, transducer_Vpp=float(q['vport_vpp'][0]),
                             transducer_mArms=float(q['iport_irms_A'][0]) * 1e3,
                             amplifier_output_mArms=float(abs(q['i_source'][0])) * 1e3,
                             amplifier_terminal_Vpp=float(abs(q['v_input'][0])) * SQ8,
                             p_rm_mW=float(q['p_rm_W'][0]) * 1e3, source_Vrms=a1))
    finally:
        model.SOURCE_A1_VRMS = saved
    return rows


def phasor_cancellation():
    """2 mm 元件（血液）：C0 支路电流、端口总电流与 |Z| 在带内的分布。"""
    out = []
    f = np.arange(0.8e6, 1.0e6 + 1, 100.0)
    v = 100.0 / SQ8
    for mat in ('PZT-5H', 'PZT-4', 'PZT-8'):
        for limit in ('rod', 'disc'):
            el = PR.make_element(mat, 2e-3, limit)
            z = PR.element_z(f, el, 'blood')
            i_tot = v / np.abs(z)
            i_c0 = v * 2 * np.pi * f * el['C0']
            k = int(np.argmax(np.abs(z)))
            ok = np.abs(z) >= v / 5e-3
            p100 = v * v * np.real(1 / z)                       # 100 Vpp 时的端口有功功率
            out.append(dict(
                element=f'{mat} 2 mm {limit}', C0_pF=el['C0'] * 1e12,
                I_C0_at_0p9MHz_mA=float(v * 2 * np.pi * 0.9e6 * el['C0'] * 1e3),
                max_absZ_ohm=float(np.abs(z)[k]), at_kHz=float(f[k] / 1e3),
                I_total_there_mA=float(i_tot[k] * 1e3), I_C0_there_mA=float(i_c0[k] * 1e3),
                band_points_100Vpp_le_5mA=int(ok.sum()),
                best_P_at_100Vpp_le_5mA_mW=float(p100[ok].max() * 1e3) if ok.any() else None,
                best_P_at_kHz=float(f[ok][int(np.argmax(p100[ok]))] / 1e3) if ok.any() else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    rep = dict(shrink_pzt8_disc=shrink_case(), shrink_pzt8_rod=shrink_case(limit='rod'),
               amplifier_current=amplifier_current(root), phasor=phasor_cancellation())
    print('== 一、同长度、面积 0.6 倍（PZT-8，血液）')
    for key in ('shrink_pzt8_disc', 'shrink_pzt8_rod'):
        s = rep[key]
        print(f"  {key}: D {s['D0']['D_mm']:.3f}→{s['D1']['D_mm']:.3f} mm，Q {s['D0']['Q']:.2f}→{s['D1']['Q']:.2f}，"
              f"fs {s['D0']['fs_kHz']:.1f}→{s['D1']['fs_kHz']:.1f} kHz，Rm 比 {s['ratios']['Rm']:.3f}，"
              f"|Z(fs)| 比 {s['ratios']['absZ_fs']:.3f}，|Z(0.9 MHz)| 比 {s['ratios']['absZ_0p9MHz']:.3f}"
              f"（均匀缩放应为 {s['ratios']['uniform_scaling_requires']:.3f}、Q 与 fs 不变）")
    print('== 二、0.9 MHz、a=1：换能器端与功放输出端电流')
    for r in rep['amplifier_current']:
        print(f"  {r['design']:22s} 换能器 {r['transducer_Vpp']:.2f} Vpp / {r['transducer_mArms']:.3f} mA；"
              f"功放输出 {r['amplifier_output_mArms']:.2f} mA rms（端子 {r['amplifier_terminal_Vpp']:.2f} Vpp）")
    print('== 三、2 mm 元件（血液）：相量和与带内可行频点')
    for r in rep['phasor']:
        print(f"  {r['element']:18s} C0 {r['C0_pF']:6.2f} pF，0.9 MHz 时 C0 支路 {r['I_C0_at_0p9MHz_mA']:5.2f} mA；"
              f"带内 |Z| 最大 {r['max_absZ_ohm']:7.0f} Ω @ {r['at_kHz']:.1f} kHz（总电流 {r['I_total_there_mA']:.2f} mA、"
              f"C0 支路 {r['I_C0_there_mA']:.2f} mA）；100 Vpp 且 ≤5 mA 的频点 {r['band_points_100Vpp_le_5mA']} 个，"
              f"其中最大有功 {r['best_P_at_100Vpp_le_5mA_mW']} mW @ {r['best_P_at_kHz']} kHz")
    if a.out:
        pathlib.Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
