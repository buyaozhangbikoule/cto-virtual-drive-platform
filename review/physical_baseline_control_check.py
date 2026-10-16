#!/usr/bin/env python3
"""只读：把正式三策略放到「谐振形状物理化」的基线上原样重跑，看哪些结论留得住。

〔已改正 2026-10-16，见 review/26：这里的「物理化」「物理的 k_eff」是指让谐振形状落进本仓库简化模型算出的量级；
Q = M/κ 是保留原工作点、指定 k_eff 反算出的合成参数，Lm、Cm、k_eff 一起改变，不是任何确定器件的拟合结果，
也不是同一器件只增加阻尼。计算本身不受影响。〕

为什么只改 Q：在 fs 上 Z_m = Rm 与 Lm/Cm 怎么分无关，所以 C0、Rm、fs 不动时
100 Vpp / 5 mA / 170 mW 的工作点、匹配网络、源幅度标定、冻结相位目标 arg(Zin)=−1.078°
全部不变；唯一改变的是谐振形状。M = κQ = X_C0/Rm = 3.507 被工作点钉死，所以
物理的 k_eff 只能配 Q = M/κ（见 physical_realizability_study.py 第 1b 节）：

    k_eff 0.0661 → Q 800（已登记基线）   0.30 → 35.46   0.45 → 13.81   0.60 → 6.23

34 条登记场景用 model_v2_1 自己的配方、以新基线为基准重建（C0/Rm/fs/Lm/Cm/Rs/Lmatch/
Cmatch/QL 的相对扰动全部照搬）。唯一的改写：QM_500/800/1000 读作 Q_base×{500,800,1000}/800；
这三条不在 12 段日程里，只进参考表，不影响打分。

自证条件（任何一条不满足就退出）：
  1. Q=800 时重建的 34 条场景与 model.scenario_map() 逐字段完全相等；
  2. Q=800 时三策略复现已登记批次 UNIFIED_20260923T013352_476445Z_f442bcda：
     FIXED 7/12、73.778340%；PERIODIC_SCAN 1/12、41.958642%；PHASE_FEEDBACK 6/12、57.337359%。

    python review/physical_baseline_control_check.py --root <统一源目录> [--out <目录>]

只读：运行期在内存里替换 model.scenario_map / model.all_scenarios，不改任何文件；
--out 只写到给定目录，拒绝 workspace/ 与任何 outputs/ 目录。
"""
from __future__ import annotations

import argparse
import collections
import csv
import dataclasses
import json
import math
import pathlib
import sys

REGISTERED = {'FIXED': (7, 73.77834015632311),
              'PERIODIC_SCAN': (1, 41.958641853267814),
              'PHASE_FEEDBACK': (6, 57.337358679119646)}
M_FIXED = 3.507                       # 由工作点钉死的 κQ，下面按精确值重算
KEFFS = (0.0661, 0.30, 0.45, 0.60)


def build(root):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import engine as E                    # noqa: E402
    import controllers as C               # noqa: E402
    import metrics as Mx                  # noqa: E402
    import models.model_v2_1 as model     # noqa: E402
    cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    return E, C, Mx, model, cfg


def registry(model, base_bvd, base_match, base_rs, qm_scale=1.0):
    """model_v2_1.single_factor_scenarios + combination_scenarios 的逐行镜像，基线作参数。"""
    rep = dataclasses.replace
    S = model.Scenario
    default = 'Only the named scan variable changes; all others remain frozen.'

    def case(cid, factor, level, bvd=base_bvd, matching=base_match, rs=base_rs,
             family='single_factor', description=default):
        return S(cid, family, factor, level, description, bvd, matching, rs)

    cases = [case('CASE_000_BASELINE', 'baseline', 'baseline', family='baseline')]
    for pct in (10, 20, 30):
        cases.append(case(f'CASE_C0_P{pct}', 'C0', f'+{pct}%',
                          bvd=rep(base_bvd, c0=base_bvd.c0 * (1 + pct / 100))))
    for pct in (15, 30, 50):
        cases.append(case(f'CASE_RM_P{pct}', 'Rm', f'+{pct}%',
                          bvd=model.changed_rm_only(base_bvd, 1 + pct / 100),
                          description='Rm-only scan: C0/Lm/Cm/fs remain frozen; Qm is derived '
                                      'from the changed Rm.'))
    for pct in (1, 3, 5):
        cases.append(case(f'CASE_FS_M{pct}', 'fs', f'-{pct}%',
                          bvd=model.shifted_fs(base_bvd, 1 - pct / 100),
                          description='fs changes while Rm and Qm remain fixed; Lm and Cm are '
                                      're-derived together.'))
    for pct in (5, 10, 20):
        cases.append(case(f'CASE_LM_P{pct}', 'Lm', f'+{pct}%',
                          bvd=model.changed_lm_only(base_bvd, 1 + pct / 100),
                          description=('Lm-only scan: Lm changes while C0, Rm and Cm remain frozen; '
                                       'the resulting fs and Qm are derived, not independently '
                                       'held fixed.')))
    for pct in (5, 10, 20):
        cases.append(case(f'CASE_CM_P{pct}', 'Cm', f'+{pct}%',
                          bvd=model.changed_cm_only(base_bvd, 1 + pct / 100),
                          description=('Cm-only scan: Cm changes while C0, Rm and Lm remain frozen; '
                                       'the resulting fs and Qm are derived, not independently '
                                       'held fixed.')))
    for pct in (5, 10, 20):
        cases.append(case(f'CASE_RS_P{pct}', 'Rs', f'+{pct}%', rs=base_rs * (1 + pct / 100)))
    for pct in (2, 5, 10):
        cases.append(case(f'CASE_LMATCH_P{pct}', 'Lmatch', f'+{pct}%',
                          matching=rep(base_match, l_h=base_match.l_h * (1 + pct / 100))))
    for pct in (2, 5, 10):
        cases.append(case(f'CASE_CMATCH_M{pct}', 'Cmatch', f'-{pct}%',
                          matching=rep(base_match, c_f=base_match.c_f * (1 - pct / 100))))
    for ql in (100, 50, 20):
        cases.append(case(f'CASE_QL_{ql}', 'inductor_Q', f'Q={ql}',
                          matching=rep(base_match, ql=float(ql)),
                          description='Inductor ESR changes through the declared Q at 0.9 MHz.'))
    for qm in (500, 800, 1000):
        cases.append(case(f'CASE_QM_{qm}', 'Qm', f'Qm={qm}',
                          bvd=model.changed_qm(base_bvd, float(qm) * qm_scale),
                          description='Qm sensitivity: fs, Rm and C0 remain fixed; Lm/Cm are '
                                      're-derived.'))
    levels = [('LOW', 10, 15, 1, 5, 2, 2, 100), ('MEDIUM', 20, 30, 3, 10, 5, 5, 50),
              ('HIGH', 30, 50, 5, 20, 10, 10, 20)]
    for name, c0p, rmp, fsm, rsp, lp, cm, ql in levels:
        bvd = model.shifted_fs(base_bvd, 1 - fsm / 100)
        bvd = rep(bvd, c0=base_bvd.c0 * (1 + c0p / 100), rm=base_bvd.rm * (1 + rmp / 100))
        bvd = model.bvd_from_fs_qm(c0=bvd.c0, rm=bvd.rm, fs=bvd.fs, qm=base_bvd.qm)
        matching = rep(base_match, l_h=base_match.l_h * (1 + lp / 100),
                       c_f=base_match.c_f * (1 - cm / 100), ql=float(ql))
        cases.append(case(f'CASE_COMBINED_{name}', 'combined', name.lower(), bvd=bvd,
                          matching=matching, rs=base_rs * (1 + rsp / 100), family='combined',
                          description=(f'C0 +{c0p}%, Rm +{rmp}%, fs -{fsm}%, Rs +{rsp}%, '
                                       f'Lmatch +{lp}%, Cmatch -{cm}%, inductor Q={ql}.')))
    return cases


def run_all(E, C, Mx, model, cfg, cases, label):
    """在内存里替换场景表，跑三策略，按正式口径打分。"""
    smap = {c.case_id: c for c in cases}
    model.scenario_map = lambda: dict(smap)
    model.all_scenarios = lambda: list(cases)
    ids = cfg['historical_schedule']
    refs = Mx.references(cfg)
    phase = float(model.response(cfg['initial_frequency_Hz'],
                                 smap['CASE_000_BASELINE'])['phase_deg'][0])
    out = {}
    for strategy in C.STRATEGIES:
        eng = E.Engine(cfg, ids, strategy, label)
        C.run_policy(C.Executor(eng), strategy, phase)
        per, s = Mx.evaluate(eng.rows, eng.events, cfg, refs)
        ev = collections.Counter(e['event'] for e in eng.events)
        out[strategy] = dict(settled=s['settled_segments'], energy_pct=s['energy_capture_pct'],
                             per_segment=[r['energy_capture_pct'] for r in per],
                             settled_flags=[bool(r['settled']) for r in per],
                             scan_attempts=ev['SCAN_ATTEMPT_START'],
                             phase_updates=ev['PHASE_UPDATE'])
    ref_f = {cid: refs[cid]['policy']['frequency_Hz'] for cid in dict.fromkeys(ids)}
    ref_a = {cid: refs[cid]['policy']['amplitude'] for cid in dict.fromkeys(ids)}
    return out, phase, ref_f, ref_a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, help='统一源目录（current/unified 的副本）')
    ap.add_argument('--out', default=None, help='可选输出目录；拒绝 workspace/ 与 outputs/')
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve()
    out_dir = None
    if args.out:
        out_dir = pathlib.Path(args.out).resolve()
        if {'workspace', 'outputs'} & set(out_dir.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out_dir}')
        out_dir.mkdir(parents=True, exist_ok=True)

    E, C, Mx, model, cfg = build(root)
    original_map = model.scenario_map()
    base, match, rs = model.BASE_BVD, model.BASE_MATCH, model.BASE_RS
    w = 2 * math.pi * base.fs
    m_point = (1 / (w * base.c0)) / base.rm                 # κQ = X_C0/Rm

    # 自证 1：Q=800 时重建场景与模块自己的场景表逐字段相等
    rebuilt = registry(model, base, match, rs)
    assert [c.case_id for c in rebuilt] == list(original_map), '场景顺序不同'
    for c in rebuilt:
        assert c == original_map[c.case_id], ('重建场景不等', c.case_id)
    print(f'自证 1 通过：34 条重建场景与 model.scenario_map() 逐字段相等；κQ = {m_point:.6f}')

    rows, results = [], {}
    for keff in KEFFS:
        kappa = keff ** 2 / (1 - keff ** 2)
        q = 800.0 if keff == 0.0661 else m_point / kappa
        b = model.changed_qm(base, q)
        cases = registry(model, b, match, rs, qm_scale=q / 800.0)
        label = f'Q={q:.2f}'
        res, phase, ref_f, ref_a = run_all(E, C, Mx, model, cfg, cases, label)
        results[label] = dict(keff=keff, q=q, fwhm_Hz=base.fs / q,
                              fp_minus_fs_Hz=base.fs * (math.sqrt(1 + b.cm / b.c0) - 1),
                              phase_target_deg=phase, strategies=res,
                              reference_frequency_Hz=ref_f, reference_amplitude=ref_a)
        if q == 800.0:      # 自证 2
            for s, (n, e) in REGISTERED.items():
                got = res[s]
                assert got['settled'] == n and abs(got['energy_pct'] - e) < 1e-6, (s, got, n, e)
            print('自证 2 通过：Q=800 三策略逐位复现已登记批次 '
                  '(7/12 73.778340%, 1/12 41.958642%, 6/12 57.337359%)')
        for s, r in res.items():
            rows.append(dict(k_eff=keff, Q=q, strategy=s, settled=r['settled'],
                             energy_pct=r['energy_pct'], scan_attempts=r['scan_attempts'],
                             phase_updates=r['phase_updates'],
                             **{f'seg{i:02d}': v for i, v in enumerate(r['per_segment'])}))

    ids = cfg['historical_schedule']
    print('\n三策略在 12 段日程上的成绩（达标段 / 全程电能捕获）')
    print(f"{'k_eff':>6}{'Q':>8}{'FWHM':>9}{'fp−fs':>9}   "
          + ''.join(f'{s:>22}' for s in C.STRATEGIES))
    for label, r in results.items():
        cells = ''.join(f"{r['strategies'][s]['settled']:>12d}/12 {r['strategies'][s]['energy_pct']:6.2f}%"
                        for s in C.STRATEGIES)
        print(f"{r['keff']:>6.3f}{r['q']:>8.2f}{r['fwhm_Hz']/1e3:>7.2f}k{r['fp_minus_fs_Hz']/1e3:>8.1f}k   {cells}")

    print('\n逐段能量捕获 (%)：')
    short = [c.replace('CASE_', '')[:9] for c in ids]
    print(f"{'':>24}" + ''.join(f'{s:>10}' for s in short))
    for label, r in results.items():
        for s in C.STRATEGIES:
            print(f"{label + ' ' + s:>24}" + ''.join(f'{v:>10.1f}' for v in r['strategies'][s]['per_segment']))

    print('\n参考最优频率（软限、a≤1，100 Hz 栅格）随 Q 的变化 (kHz)：')
    uniq = list(dict.fromkeys(ids))
    print(f"{'':>12}" + ''.join(f"{c.replace('CASE_', '')[:9]:>11}" for c in uniq))
    for label, r in results.items():
        print(f"{label:>12}" + ''.join(f"{r['reference_frequency_Hz'][c]/1e3:>11.1f}" for c in uniq))
    print(f"{'':>12}  （同表的参考幅度 a）")
    for label, r in results.items():
        print(f"{label:>12}" + ''.join(f"{r['reference_amplitude'][c]:>11.3f}" for c in uniq))

    model.scenario_map = lambda: dict(original_map)          # 还原，免得被同进程误用
    model.all_scenarios = lambda: list(original_map.values())

    if out_dir is not None:
        with (out_dir / 'physical_baseline_control.csv').open('w', encoding='utf-8-sig',
                                                              newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        (out_dir / 'physical_baseline_control.json').write_text(
            json.dumps(dict(results=results, schedule=ids, kappa_q=m_point,
                            registered_batch='UNIFIED_20260923T013352_476445Z_f442bcda'),
                       ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n已写入 {out_dir}')


if __name__ == '__main__':
    main()
