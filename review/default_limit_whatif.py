#!/usr/bin/env python3
"""默认配置只改电流限值的假设试算（review/28 第四节；非正式、不登记）。

    python review/default_limit_whatif.py --root <打完 P7 的 current/unified> --batch <P7 默认正式批次目录> --out <目录>

用户确认 5 mA 上限的测点在换能器端（2026-10-16）。默认配置（Qm=800、设计点 5 mA）的软/硬限 5.5/6.0 mA 高于上限。
这里在同一电路上只把软/硬限改成候选的 4.5/5.0 mA，四种策略各跑 35 个日程，与原限值并列：
  · 原限值一组必须与 --batch 的 formal_three_strategy_summary.csv 逐值相同（自证），否则以非零码退出；
  · 捕获率的分母是各组自己的软限可行参考（改限值后参考也变），绝对电能另列，跨组比较以绝对值为准。
只读 --root 与 --batch；只写 --out。
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import pathlib
import sys

VARIANTS = {'limits_5p5_6p0_as_is': {}, 'limits_4p5_5p0': dict(current_soft_Arms=0.0045, current_hard_Arms=0.005)}


def run(root: pathlib.Path, overrides: dict):
    sys.path.insert(0, str(root))
    from controllers import Executor, STRATEGIES, run_policy
    from engine import Engine
    from metrics import evaluate, references
    from models import model_v2_1 as model
    cfg = json.loads((root/'config.json').read_text(encoding='utf-8'))
    cfg.update(overrides)
    model.configure(cfg)
    ref = references(cfg)
    cases = model.scenario_map()
    phase = float(model.response(cfg['initial_frequency_Hz'], cases['CASE_000_BASELINE'])['phase_deg'][0])
    schedules = {'HISTORICAL_12': cfg['historical_schedule']}
    schedules.update({'COVER_'+c: ['CASE_000_BASELINE', c, 'CASE_000_BASELINE'] for c in cases})
    overall, rows = [], []
    for suite, ids in schedules.items():
        for s in STRATEGIES:
            e = Engine(copy.deepcopy(cfg), ids, s, suite)
            run_policy(Executor(e), s, phase)
            per, summary = evaluate(e.rows, e.events, cfg, ref)
            summary['peak_post_guard_current_mArms'] = 1000*max(r['iport_Arms'] for r in e.rows)
            summary['rows_above_5mA'] = sum(r['iport_Arms'] > cfg['user_current_limit_Arms'] for r in e.rows)
            overall.append(summary)
            rows.extend(r for r in per if suite.startswith('COVER_') and r['segment_index'] == 1)
    return STRATEGIES, overall, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', required=True)
    ap.add_argument('--batch', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    root, out = pathlib.Path(a.root).resolve(), pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    formal = {(r['suite'], r['strategy']): r for r in
              csv.DictReader(open(pathlib.Path(a.batch)/'formal_three_strategy_summary.csv', encoding='utf-8-sig'))}
    table, ok = [], True
    for name, overrides in VARIANTS.items():
        strategies, overall, target = run(root, overrides)
        if not overrides:   # self-check against the registered formal batch
            for r in overall:
                f = formal[(r['suite'], r['strategy'])]
                ok &= (str(r['settled_segments']) == f['settled_segments'] and
                       repr(r['energy_capture_pct']) == f['energy_capture_pct'] and repr(r['energy_J']) == f['energy_J'])
        for s in strategies:
            hist = next(r for r in overall if r['suite'] == 'HISTORICAL_12' and r['strategy'] == s)
            mine = [r for r in overall if r['strategy'] == s]
            seg = [r for r in target if r['strategy'] == s]
            table.append(dict(variant=name, strategy=s,
                              historical_settled=hist['settled_segments'], historical_energy_pct=hist['energy_capture_pct'],
                              historical_energy_J=hist['energy_J'],
                              target_settled=sum(r['settled'] for r in seg), target_segments=len(seg),
                              target_energy_pct=100*sum(r['energy_J'] for r in seg)/sum(r['policy_reference_energy_J'] for r in seg),
                              target_energy_J=sum(r['energy_J'] for r in seg),
                              peak_post_guard_current_mArms=max(r['peak_post_guard_current_mArms'] for r in mine),
                              rows_above_5mA=sum(r['rows_above_5mA'] for r in mine)))
    with (out/'default_limit_whatif.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    meta = dict(variants=VARIANTS, root_config_sha256=hashlib.sha256((root/'config.json').read_bytes()).hexdigest(),
                formal_batch=pathlib.Path(a.batch).name,
                self_check_as_is_equals_formal_batch=bool(ok), scope='non-formal what-if; not registered')
    (out/'default_limit_whatif.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for r in table:
        print(f"{r['variant']:22s} {r['strategy']:15s} 12段 {r['historical_settled']:2d}/12 {r['historical_energy_pct']:6.2f}% "
              f"{r['historical_energy_J']:.4f} J | 目标段 {r['target_settled']:2d}/{r['target_segments']} {r['target_energy_pct']:6.2f}% "
              f"{r['target_energy_J']:.4f} J | 峰值 {r['peak_post_guard_current_mArms']:.3f} mA, >5 mA {r['rows_above_5mA']} 行")
    print('自证：' + ('原限值一组与正式批次逐值相同' if ok else '与正式批次不一致'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
