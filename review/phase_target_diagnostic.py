#!/usr/bin/env python3
"""冻结的输入相位目标是不是最大功率判据：两种基线上逐场景对照（只读诊断）。

    python review/phase_target_diagnostic.py --root <current/unified> [--config <配置>] [--batch <该源码产出的批次>] [--out <CSV>]

对每个登记场景，在 0.8–1.0 MHz、10 Hz 网格上求：
  · 软限可行最大功率所在频率（策略可行参考，同 metrics.references 的口径，只是网格更细）；
  · arg(Zin) 回到冻结目标（基准 0.9 MHz 标定值）的频率中离 0.9 MHz 最近的一个——
    即相位环“无限快、无限准”时会停的地方；
  · 停在那里与停在 0.9 MHz（固定频率）各能拿到参考功率的多少。
给了 --batch 时，再从该批次的覆盖试验里读相位反馈在目标段实际走了多远、做了几次更新。
--root 指向的源码树用它的默认配置；拆分补丁之后（review/26）可用 --config 选候选配置，
例如 candidates/synthetic_q13p8_3mA/config.json（相对 --root）。
〔已改正 2026-10-16〕原文称补丁后为「3 mA 物理基线」；它是合成候选基线，不是物理基线，见 review/26。
只读源码与批次；只在 --out 写一个 CSV。
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

import numpy as np

CASES = ('CASE_FS_M1', 'CASE_FS_M3', 'CASE_FS_M5', 'CASE_LM_P5', 'CASE_LM_P10', 'CASE_LM_P20',
         'CASE_CM_P5', 'CASE_CM_P10', 'CASE_CM_P20', 'CASE_LMATCH_P5', 'CASE_LMATCH_P10',
         'CASE_CMATCH_M10', 'CASE_COMBINED_LOW', 'CASE_COMBINED_MEDIUM', 'CASE_COMBINED_HIGH')


def read_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--config', default=None, help='可选：运行配置（相对 --root），需要拆分补丁后的模型')
    ap.add_argument('--batch', default=None)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    sys.path.insert(0, str(root))
    from models import model_v2_1 as model                   # noqa: E402
    cfg = json.loads((root / (a.config or 'config.json')).read_text(encoding='utf-8'))
    if a.config:
        model.configure(cfg)
    cases = model.scenario_map()
    grid = np.arange(cfg['frequency_min_Hz'], cfg['frequency_max_Hz'] + 0.5, 10.0)
    target = float(model.response(cfg['initial_frequency_Hz'], cases['CASE_000_BASELINE'])['phase_deg'][0])
    base = model.response(np.array([899900.0, 900100.0]), cases['CASE_000_BASELINE'])
    slope = float(base['phase_deg'][1] - base['phase_deg'][0]) / 200.0
    print(f"基线 {getattr(model, 'BASELINE_ID', 'MODEL_V2_1_HYPOTHETICAL')}，Qm={model.BASE_BVD.qm:.6g}；"
          f"冻结相位目标 {target:.6f}°；0.9 MHz 处 d arg(Zin)/df = {slope:+.3e} °/Hz，"
          f"增益 {cfg['phase_gain_Hz_per_deg']} Hz/° 时每次更新修正误差的 {abs(slope) * cfg['phase_gain_Hz_per_deg']:.2%}")
    out = []
    for cid in CASES:
        q = model.response(grid, cases[cid])
        amp = np.minimum.reduce([np.ones(len(grid)), cfg['voltage_soft_Vpp'] / q['vport_vpp'],
                                 cfg['current_soft_Arms'] / q['iport_irms_A']])
        p = q['p_rm_W'] * amp * amp
        best = float(p.max())
        cross = np.where(np.diff(np.sign(q['phase_deg'] - target)) != 0)[0]
        i900 = int(np.argmin(abs(grid - cfg['initial_frequency_Hz'])))
        row = dict(case_id=cid, optimum_kHz=float(grid[int(np.argmax(p))]) / 1e3,
                   phase_target_crossings=int(len(cross)),
                   phase_target_kHz=None, capture_at_phase_target_pct=None,
                   capture_at_0p9MHz_pct=100 * float(p[i900]) / best)
        if len(cross):
            j = int(cross[np.argmin(abs(grid[cross] - cfg['initial_frequency_Hz']))])
            row.update(phase_target_kHz=float(grid[j]) / 1e3, capture_at_phase_target_pct=100 * float(p[j]) / best)
        if a.batch:
            batch = pathlib.Path(a.batch)
            ex = [r for r in read_rows(batch / 'executions' / f'COVER_{cid}_PHASE_FEEDBACK.csv')
                  if r['segment_index'] == '1' and r['kind'] == 'CONTROL']
            ev = json.loads((batch / 'events' / f'COVER_{cid}_PHASE_FEEDBACK.json').read_text(encoding='utf-8'))
            seg = cfg['segment_us']
            row.update(phase_loop_end_kHz=float(ex[-1]['frequency_Hz']) / 1e3,
                       phase_loop_moved_Hz=float(ex[-1]['frequency_Hz']) - float(ex[0]['frequency_Hz']),
                       phase_updates=sum(e['event'] == 'PHASE_UPDATE' and seg <= e['time_us'] < 2 * seg for e in ev),
                       phase_probe_failures=sum(e['event'] == 'PHASE_PROBE_FAILED' and seg <= e['time_us'] < 2 * seg
                                                for e in ev))
        out.append(row)
    keys = list(out[0])
    print(' | '.join(keys))
    for r in out:
        print(' | '.join('' if r[k] is None else (f'{r[k]:.2f}' if isinstance(r[k], float) else str(r[k])) for k in keys))
    worse = [r['case_id'] for r in out if r['capture_at_phase_target_pct'] is not None
             and r['capture_at_phase_target_pct'] < r['capture_at_0p9MHz_pct']]
    print(f'相位目标处捕获率低于固定 0.9 MHz 的场景：{len(worse)}/{len(out)}')
    if a.out:
        with open(a.out, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
