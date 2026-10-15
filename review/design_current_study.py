#!/usr/bin/env python3
"""设计点电流降到 4 / 3 mA：电流软限压幅带与 P&O 回程代价是否随之消失。

只读：运行期在内存里替换场景表、匹配网络与源幅度标定，不改任何文件；
--out 只写到给定目录，拒绝 workspace/ 与任何 outputs/ 目录。

    python review/design_current_study.py --root <unified 源目录> --candidate <candidate.py 所在目录> [--out <目录>]

做法（运行前声明）
  · 元件：review/24 第八节的同工作点物理基线（k_eff 0.45、Q 13.81），按 k = 5 mA / I_d 均匀缩放阻抗：
    C0/k、Cm/k、Lm·k、Rm·k；Q、fs、k_eff 不变。物理上是同材料、同长度、端面积缩为 1/k 的元件
    （直径缩为 1/√k）：同一电压下端面振速不变，总电流与功率按 1/k 变小。
  · 匹配网络：按 stage2 原规则（integrated/outputs/v2_self_consistent_rebuild/stage2_matching/
    design_stage2.py 的 design_values）重新设计——理想 L 型网络作初值，再在有损模型（QL=100、QC=1000、
    ESR 取 0.9 MHz 值）上用 Nelder–Mead 最大化 0.9 MHz 处 P_Rm，容差同原脚本。
  · 源幅度：标定到 0.9 MHz、a=1 时端口 100 Vpp（同 stage2 规则）。
  · 34 条登记场景以新基线按 model_v2_1 的配方重建（相对扰动全部照搬）。
  · 限值两套：登记（电流软 5.5 / 硬 6.0 mA）与按需求（软 4.5 / 硬 5.0 mA，5 mA 为硬上限）；电压限值不变。
  · 控制器：固定频率、v2、功率 P&O（参数与 review/24 第十四节相同，不重调）。

自证：I_d = 5 mA 用已登记的匹配网络与源标定（不重新设计），在登记限值下必须逐位复现
review/results/power_tracking_20261015 的 12 段与覆盖日程结果；另报告重设计程序在 5 mA 上
与登记匹配值的相对偏差，作为该程序本身的自检。
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import pathlib
import sys

import numpy as np
from scipy.optimize import minimize

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import physical_baseline_control_check as PB    # noqa: E402
import power_tracking_prototype as PT           # noqa: E402

DESIGNS_mA = (5.0, 4.0, 3.0)
LIMITS = (('登记 5.5/6.0 mA', 0.0055, 0.006), ('按需求 4.5/5.0 mA', 0.0045, 0.005))
KEFF = 0.45
REFERENCE_RESULTS = HERE / 'results' / 'power_tracking_20261015' / 'power_tracking_comparison.json'


def lossy_p_rm(bvd, rs, l_h, c_f, ql, qc, f0):
    """design_stage2.network_response 的 active_lossy 分支在 f0 处、1 Vrms 源时的 P_Rm。"""
    w = 2 * math.pi * f0
    z_m = bvd.rm + 1j * (w * bvd.lm - 1 / (w * bvd.cm))
    z_load = 1 / (1 / z_m + 1j * w * bvd.c0)
    r_l = w * l_h / ql
    r_c = 1 / (w * c_f * qc)
    z_cap = r_c + 1 / (1j * w * c_f)
    z_par = 1 / (1 / z_load + 1 / z_cap)
    z_in = r_l + 1j * w * l_h + z_par
    i_s = 1.0 / (rs + z_in)
    v_port = i_s * z_par
    return abs(v_port / z_m) ** 2 * bvd.rm


def design_matching(bvd, rs, ql, qc, f0):
    """design_stage2.design_values 的同一算法，BVD 作参数。"""
    w = 2 * math.pi * f0
    z_m = bvd.rm + 1j * (w * bvd.lm - 1 / (w * bvd.cm))
    y = 1 / (1 / (1 / z_m + 1j * w * bvd.c0))
    g, b = y.real, y.imag
    total_b = math.sqrt(g / rs - g * g)
    c_ideal = (total_b - b) / w
    l_ideal = -(1 / (g + 1j * total_b)).imag / w
    fit = minimize(lambda x: -lossy_p_rm(bvd, rs, x[0] * 1e-6, x[1] * 1e-12, ql, qc, f0),
                   np.array([l_ideal * 1e6, c_ideal * 1e12]), method='Nelder-Mead',
                   options={'xatol': 1e-11, 'fatol': 1e-16, 'maxiter': 10000})
    if not fit.success:
        raise RuntimeError(f'匹配优化失败：{fit.message}')
    return dict(l_ideal_H=l_ideal, c_ideal_F=c_ideal, l_active_H=float(fit.x[0] * 1e-6),
                c_active_F=float(fit.x[1] * 1e-12), iterations=int(fit.nit),
                network_q=math.sqrt((1 / g) / rs - 1))


def band(model, cfg_l, scen, f0):
    """基线被控对象、a=1 时 0.8–1.0 MHz 上软限可施加幅度 a(f) < 0.999 的频段。"""
    g = np.arange(cfg_l['frequency_min_Hz'], cfg_l['frequency_max_Hz'] + 1, 100.0)
    u = model.response(g, scen, 1.0)
    av = cfg_l['voltage_soft_Vpp'] / u['vport_vpp']
    ai = cfg_l['current_soft_Arms'] / u['iport_irms_A']
    a = np.minimum.reduce([np.ones_like(g), av, ai])
    lim = a < 0.999
    k_i = int(np.argmax(u['iport_irms_A']))
    i0 = int(np.argmin(np.abs(g - f0)))
    out = dict(max_I_mA=float(u['iport_irms_A'][k_i] * 1e3), max_I_at_kHz=float(g[k_i] / 1e3),
               max_V_Vpp=float(u['vport_vpp'].max()), max_V_at_kHz=float(g[int(np.argmax(u['vport_vpp']))] / 1e3),
               a_at_f0=float(a[i0]), I_at_f0_mA=float(u['iport_irms_A'][i0] * 1e3),
               V_at_f0_Vpp=float(u['vport_vpp'][i0]), limited_points=int(lim.sum()), intervals=[])
    j = 0
    while j < len(g):                                   # 连续受限频段逐段报告
        if not lim[j]:
            j += 1
            continue
        k0 = j
        while j + 1 < len(g) and lim[j + 1]:
            j += 1
        seg = slice(k0, j + 1)
        km = k0 + int(np.argmin(a[seg]))
        out['intervals'].append(dict(from_kHz=float(g[k0] / 1e3), to_kHz=float(g[j] / 1e3),
                                     min_a=float(a[km]), min_a_at_kHz=float(g[km] / 1e3),
                                     binding='电流' if ai[km] <= av[km] else '电压'))
        j += 1
    return out


def cover_runs(E, C, Mx, cfg_l, smap, refs, strategies):
    """覆盖日程，另记目标段与返回段里非 NORMAL 的控制时间。"""
    out = {}
    for cid in smap:
        sched = ['CASE_000_BASELINE', cid, 'CASE_000_BASELINE']
        row = {}
        for name, label, fn in strategies:
            eng = E.Engine(cfg_l, sched, label, 'COVER_' + cid)
            fn(C.Executor(eng))
            per, s = Mx.evaluate(eng.rows, eng.events, cfg_l, refs)
            busy = [sum(r['duration_us'] for r in eng.rows
                        if r['segment_index'] == k and r['kind'] == 'CONTROL'
                        and r['protection_state'] != 'NORMAL') / 1000 for k in (1, 2)]
            row[name] = dict(target_settled=bool(per[1]['settled']),
                             target_energy=per[1]['energy_capture_pct'],
                             return_settled=bool(per[2]['settled']),
                             return_energy=per[2]['energy_capture_pct'],
                             total_energy=s['energy_capture_pct'],
                             target_busy_ms=busy[0], return_busy_ms=busy[1])
        out[cid] = row
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, help='统一源目录（current/unified 的副本）')
    ap.add_argument('--candidate', required=True, help='candidate.py 所在目录（v2）')
    ap.add_argument('--out', default=None, help='可选输出目录；拒绝 workspace/ 与 outputs/')
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve()
    out_dir = None
    if args.out:
        out_dir = pathlib.Path(args.out).resolve()
        if {'workspace', 'outputs'} & set(out_dir.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out_dir}')
        out_dir.mkdir(parents=True, exist_ok=True)

    E, C, Mx, model, cfg = PB.build(root)
    sys.path.insert(0, str(pathlib.Path(args.candidate).resolve()))
    import candidate as CAND                                       # noqa: E402
    original = model.scenario_map()
    a1_registered = model.SOURCE_A1_VRMS
    base, match, rs = model.BASE_BVD, model.BASE_MATCH, model.BASE_RS
    f0 = cfg['initial_frequency_Hz']
    w0 = 2 * math.pi * base.fs
    q13 = ((1 / (w0 * base.c0)) / base.rm) / (KEFF ** 2 / (1 - KEFF ** 2))
    base13 = model.changed_qm(base, q13)
    ids = cfg['historical_schedule']
    params = PT.POParams()

    # 重设计程序的自检：用它重算 5 mA（Q=800 原基线）的匹配，与登记值比较
    chk = design_matching(base, rs, match.ql, match.qc, model.F0)
    dev_l = chk['l_active_H'] / match.l_h - 1
    dev_c = chk['c_active_F'] / match.c_f - 1
    print(f'重设计程序自检（5 mA 原基线）：L 相对偏差 {dev_l:+.2e}，C 相对偏差 {dev_c:+.2e}，'
          f'迭代 {chk["iterations"]} 次')

    designs, results = {}, {}
    for i_d in DESIGNS_mA:
        k = 5.0 / i_d
        bvd = model.bvd_from_fs_qm(c0=base13.c0 / k, rm=base13.rm * k, fs=base13.fs, qm=base13.qm)
        if i_d == 5.0:
            m_k, a1, dm = match, a1_registered, dict(network_q=math.sqrt(base13.rm / rs - 1),
                                                    l_active_H=match.l_h, c_active_F=match.c_f,
                                                    source='登记值')
        else:
            dm = design_matching(bvd, rs, match.ql, match.qc, model.F0)
            dm['source'] = '按 stage2 规则重新设计'
            m_k = model.Matching(l_h=dm['l_active_H'], c_f=dm['c_active_F'], ql=match.ql, qc=match.qc)
            probe = model.Scenario('PROBE', 'probe', 'probe', 'probe', '', bvd, m_k, rs)
            model.SOURCE_A1_VRMS = 1.0
            vpp_unit = float(model.response(f0, probe, 1.0)['vport_vpp'][0])
            a1 = 100.0 / vpp_unit
        model.SOURCE_A1_VRMS = a1
        cases = PB.registry(model, bvd, m_k, rs, qm_scale=q13 / 800.0)
        smap = {c.case_id: c for c in cases}
        model.scenario_map = lambda sm=smap: dict(sm)
        model.all_scenarios = lambda cs=cases: list(cs)
        u0 = model.response(f0, smap['CASE_000_BASELINE'], 1.0)
        designs[i_d] = dict(k=k, area_scale=1 / k, diameter_scale=1 / math.sqrt(k),
                            C0_pF=bvd.c0 * 1e12, Rm_ohm=bvd.rm, Lm_mH=bvd.lm * 1e3, Cm_pF=bvd.cm * 1e12,
                            Q=bvd.qm, a1_source_Vrms=a1, matching=dm,
                            V_f0_Vpp=float(u0['vport_vpp'][0]), I_f0_mA=float(u0['iport_irms_A'][0] * 1e3),
                            P_f0_mW=float(u0['p_rm_W'][0] * 1e3))
        tp = float(u0['phase_deg'][0])
        for lname, i_soft, i_hard in LIMITS:
            cfg_l = dict(cfg, current_soft_Arms=i_soft, current_hard_Arms=i_hard)
            refs = Mx.references(cfg_l)
            res = dict(band=band(model, cfg_l, smap['CASE_000_BASELINE'], f0),
                       ref_amplitude_lt1=[c for c in dict.fromkeys(smap)
                                          if refs[c]['policy']['amplitude'] < 0.999])
            twelve = {}
            for name, label, fn in (
                    ('固定频率', 'FIXED', lambda io: C.run_policy(io, 'FIXED', tp)),
                    ('v2', 'PHASE_FEEDBACK', lambda io: CAND.run_phase_recovery(io, tp)),
                    ('功率 P&O', 'POWER_PO', lambda io: PT.run_power_po(io, E, C, params))):
                eng = E.Engine(cfg_l, ids, label, 'DESIGN_CURRENT')
                fn(C.Executor(eng))
                twelve[name] = PT.summarize(Mx, cfg_l, eng, refs)
            res['twelve'] = twelve
            if lname == LIMITS[0][0]:                  # 登记限值下：P&O 的多种子测量噪声
                res['noise'] = {}
                for sigma in (0.005, 0.02):
                    vals = []
                    for seed in PT.NOISE_SEEDS:
                        eng = E.Engine(cfg_l, ids, 'POWER_PO', 'DESIGN_CURRENT_NOISE')
                        eng.measurement_filter = PT.noise_filter(C, sigma, seed)
                        PT.run_power_po(C.Executor(eng), E, C, params)
                        _, s = Mx.evaluate(eng.rows, eng.events, cfg_l, refs)
                        vals.append((s['settled_segments'], s['energy_capture_pct']))
                    e = np.array([v[1] for v in vals])
                    res['noise'][f'{sigma*100:.1f}%'] = dict(
                        energy_pct=e.tolist(), energy_mean=float(e.mean()), energy_std=float(e.std(ddof=1)),
                        energy_min=float(e.min()), energy_max=float(e.max()),
                        settled_mean=float(np.mean([v[0] for v in vals])))
            strategies = [('固定频率', 'FIXED', lambda io: C.run_policy(io, 'FIXED', tp)),
                          ('v2', 'PHASE_FEEDBACK', lambda io: CAND.run_phase_recovery(io, tp)),
                          ('功率 P&O', 'POWER_PO', lambda io: PT.run_power_po(io, E, C, params))]
            res['cover'] = cover_runs(E, C, Mx, cfg_l, smap, refs, strategies)
            results[(i_d, lname)] = res

    model.scenario_map = lambda: dict(original)
    model.all_scenarios = lambda: list(original.values())
    model.SOURCE_A1_VRMS = a1_registered

    # 自证：5 mA、登记限值必须逐位复现 review/24 第十四节
    ref = json.loads(REFERENCE_RESULTS.read_text(encoding='utf-8'))
    mine = results[(5.0, LIMITS[0][0])]
    for name in ('固定频率', 'v2', '功率 P&O'):
        a, b = mine['twelve'][name], ref['results']['k_eff 0.45']['strategies'][name]
        assert a['settled'] == b['settled'] and a['energy_pct'] == b['energy_pct'], (name, a['energy_pct'], b['energy_pct'])
    for cid, row in ref['cover']['k_eff 0.45'].items():
        for name in ('固定频率', 'v2', '功率 P&O'):
            for key in ('target_settled', 'target_energy', 'return_settled', 'return_energy', 'total_energy'):
                assert mine['cover'][cid][name][key] == row[name][key], (cid, name, key)
    for key, d in ref['noise_multi_seed'].items():
        assert mine['noise'][key]['energy_pct'] == d['energy_pct'], key
    print('自证通过：5 mA、登记限值逐位复现 review/24 第十四节（12 段、34 条覆盖日程、两档噪声各 10 个种子）\n')

    print('== 一、三种设计点（Q=13.81、k_eff 0.45；按 k=5 mA/I_d 均匀缩放阻抗）')
    print(f"  {'设计电流':<8}{'面积':>6}{'直径':>6}{'C0 pF':>8}{'Rm Ω':>8}{'匹配 L µH':>10}{'匹配 C pF':>10}"
          f"{'网络Q':>7}{'源 Vrms':>9}{'0.9MHz: V':>11}{'I mA':>7}{'P_Rm mW':>9}  匹配来源")
    for i_d, d in designs.items():
        m = d['matching']
        print(f"  {i_d:<8.1f}{d['area_scale']:>6.3f}{d['diameter_scale']:>6.3f}{d['C0_pF']:>8.3f}{d['Rm_ohm']:>8.0f}"
              f"{m['l_active_H']*1e6:>10.3f}{m['c_active_F']*1e12:>10.2f}{m['network_q']:>7.2f}"
              f"{d['a1_source_Vrms']:>9.4f}{d['V_f0_Vpp']:>9.3f}Vpp{d['I_f0_mA']:>7.3f}{d['P_f0_mW']:>9.2f}  {m['source']}")

    print('\n== 二、基线被控对象上的压幅频段（a=1 驱动；a<0.999 的连续频段逐段列出）')
    print(f"  {'设计':<6}{'限值':<16}{'0.9MHz处a':>9}{'最大电流':>17}{'最大电压':>17}  压幅频段（最低 a，受限于）"
          f"   参考最优点本身被压幅的场景数")
    for (i_d, lname), r in results.items():
        b = r['band']
        segs = '；'.join(f"{s['from_kHz']:.1f}–{s['to_kHz']:.1f} kHz（{s['min_a']:.3f}@{s['min_a_at_kHz']:.0f}k，{s['binding']}）"
                        for s in b['intervals']) or '无'
        n_lim = len([c for c in r['ref_amplitude_lt1'] if c not in PT.COVER_ALIASES])
        print(f"  {i_d:<6.1f}{lname:<16}{b['a_at_f0']:>9.3f}{b['max_I_mA']:>10.3f}mA@{b['max_I_at_kHz']:.0f}k"
              f"{b['max_V_Vpp']:>9.1f}Vpp@{b['max_V_at_kHz']:.0f}k  {segs}   {n_lim}/31")

    print('\n== 三、12 段日程（达标 / 能量）')
    print(f"  {'设计':<6}{'限值':<16}" + ''.join(f'{n:>18}' for n in ('固定频率', 'v2', '功率 P&O')))
    for (i_d, lname), r in results.items():
        print(f"  {i_d:<6.1f}{lname:<16}" + ''.join(
            f"{r['twelve'][n]['settled']:>9}/12 {r['twelve'][n]['energy_pct']:6.2f}%" for n in ('固定频率', 'v2', '功率 P&O')))

    print('\n   P&O 测量噪声（登记限值，10 个种子；固定频率无噪声可比）：')
    for (i_d, lname), r in results.items():
        if 'noise' not in r:
            continue
        fx = r['twelve']['固定频率']['energy_pct']
        print(f"   设计 {i_d:.0f} mA：" + '；'.join(
            f"σ={k} 均值 {d['energy_mean']:.2f}% ± {d['energy_std']:.2f}（{d['energy_min']:.2f}–{d['energy_max']:.2f}），"
            f"比固定 {d['energy_mean']-fx:+.2f}"
            for k, d in r['noise'].items()) + f"；固定频率 {fx:.2f}%")

    print('\n== 四、31 个去重扰动的覆盖日程')
    uniq = [c for c in results[(5.0, LIMITS[0][0])]['cover'] if c not in PT.COVER_ALIASES]
    for (i_d, lname), r in results.items():
        cv = r['cover']
        print(f"  设计 {i_d:.0f} mA，{lname}")
        print(f"    {'策略':<10}{'扰动段达标':>10}{'扰动段能量':>11}{'返回段达标':>10}{'返回段能量':>11}"
              f"{'三段总能量':>11}{'返回段非NORMAL':>15}{'扰动段胜/负固定':>14}")
        for n in ('固定频率', 'v2', '功率 P&O'):
            t_ok = sum(cv[c][n]['target_settled'] for c in uniq)
            r_ok = sum(cv[c][n]['return_settled'] for c in uniq)
            t_e = np.mean([cv[c][n]['target_energy'] for c in uniq])
            r_e = np.mean([cv[c][n]['return_energy'] for c in uniq])
            tot = np.mean([cv[c][n]['total_energy'] for c in uniq])
            busy = sum(cv[c][n]['return_busy_ms'] for c in uniq)
            win = sum(cv[c][n]['target_energy'] > cv[c]['固定频率']['target_energy'] + 0.5 for c in uniq)
            lose = sum(cv[c][n]['target_energy'] < cv[c]['固定频率']['target_energy'] - 0.5 for c in uniq)
            print(f"    {n:<10}{t_ok:>7}/{len(uniq)}{t_e:>10.2f}%{r_ok:>7}/{len(uniq)}{r_e:>10.2f}%"
                  f"{tot:>10.2f}%{busy:>12.0f} ms{win:>9}/{lose}")

    if out_dir is not None:
        flat = []
        for (i_d, lname), r in results.items():
            for n, s in r['twelve'].items():
                flat.append(dict(design_mA=i_d, limits=lname, schedule='HISTORICAL_12', strategy=n,
                                 settled=s['settled'], energy_pct=s['energy_pct']))
            for n in ('固定频率', 'v2', '功率 P&O'):
                cv = r['cover']
                flat.append(dict(design_mA=i_d, limits=lname, schedule='COVER_31_unique', strategy=n,
                                 settled=sum(cv[c][n]['target_settled'] for c in uniq),
                                 energy_pct=float(np.mean([cv[c][n]['total_energy'] for c in uniq]))))
        with (out_dir / 'design_current_summary.csv').open('w', encoding='utf-8-sig', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(flat[0]))
            wr.writeheader()
            wr.writerows(flat)
        (out_dir / 'design_current_study.json').write_text(json.dumps(dict(
            designs={str(k): v for k, v in designs.items()},
            results={f'{k[0]:.0f}mA | {k[1]}': v for k, v in results.items()},
            redesign_selfcheck=dict(l_rel_dev=dev_l, c_rel_dev=dev_c, iterations=chk['iterations']),
            po_params=PT.dataclasses.asdict(params), cover_aliases=PT.COVER_ALIASES,
            registered_batch='UNIFIED_20260923T013352_476445Z_f442bcda'),
            ensure_ascii=False, indent=2, default=float), encoding='utf-8')
        print(f'\n已写入 {out_dir}')


if __name__ == '__main__':
    main()
