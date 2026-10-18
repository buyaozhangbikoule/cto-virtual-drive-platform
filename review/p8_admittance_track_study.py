#!/usr/bin/env python3
"""P8 的平台内对比（review/32）：ADMITTANCE_TRACK 与四种正式策略，在打过 P8 的平台上跑同一日程。

    python -B review/p8_admittance_track_study.py --unified <打过 P8 的 current/unified> --out <新目录> [--seeds 10] [--jobs 4]

只读 --unified，只写 --out（须不存在）。4 核约 5 分钟。

三套配置：默认（Qm=800、L 型匹配）、合成候选（Q 13.8、L 型匹配）、物理候选（APC 880 D 0.5 mm、L 1.7467 mm、直接驱动）。
日程：
  · 历史 12 段；
  · 34 个登记场景各一条「基准 → 场景 → 基准」；
  · 另加 6 条按峰宽归一的 fs 移动（±0.25、±1、±2 个标称峰宽，Rm、Q 不变），同样「基准 → 移动 → 基准」。
    标称峰宽取各配置的 nominal_peak_width_Hz；这 6 个场景不进平台登记表，只在本研究里注入。
变体：
  · 无噪声，五种策略；
  · 测量噪声 0.5%、2%（vpp、irms、p_port、zin、功放端电流按相对值，两个相位按弧度），--seeds 个种子，
    只跑会用测量的三种（PHASE_FEEDBACK、CAPTURE_PO、ADMITTANCE_TRACK）；
  · 渐升斜率 25/s、250/s（平台为 2.5/s），无噪声，五种策略；
  · 物理候选的捕获幅度 0.65（L 型匹配的规则；候选配置为 1），无噪声，五种策略。
每段的指标都取自平台 metrics.evaluate：是否通过（98% × 10 个控制样本）、持续达到 95% 的时间、电能捕获率。

预登记判据（运行前写定，见 ACCEPTANCE；判的是 ADMITTANCE_TRACK 对 CAPTURE_PO）：
  A1 目标段（34 个登记场景 + 6 个峰宽归一移动）通过数不少于 CAPTURE_PO；
  A2 「需要控制」的目标段（无噪声 FIXED 守在 0.9 MHz 达不到参考 95% 的段，由各配置自己的 FIXED 结果定）中，
     两者都持续达到 95% 的那些段上，持续达到时间的中位数不超过 CAPTURE_PO 的一半；
  A3 保护后没有任何一行超过硬限（两处电流都算）；
  A4 历史 12 段电能捕获率不低于 CAPTURE_PO 减 1 个百分点。
有噪声时 A1、A2、A4 按种子取中位数；每个配置、每档噪声分别判。
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import json
import math
from multiprocessing import Pool
import os
from pathlib import Path
import statistics
import sys

ALL = ('FIXED', 'PERIODIC_SCAN', 'PHASE_FEEDBACK', 'CAPTURE_PO', 'ADMITTANCE_TRACK')
MEASURING = ('PHASE_FEEDBACK', 'CAPTURE_PO', 'ADMITTANCE_TRACK')
CONFIGS = {'default': 'config.json',
           'synthetic': 'candidates/synthetic_q13p8_3mA/config.json',
           'physical': 'candidates/physical_apc880_d05_L1747/config.json'}
WIDTH_SHIFTS = (-2., -1., -.25, .25, 1., 2.)
ACCEPTANCE = dict(A1='target settled >= CAPTURE_PO',
                  A2=('median sustained-95% time <= 0.5 x CAPTURE_PO, on the target segments that need control '
                      '(noise-free FIXED never reaches 95%) and that both reach'),
                  A3='no post-guard row above a hard limit', A4='HISTORICAL_12 energy >= CAPTURE_PO - 1 percentage point')
BASE = 'CASE_000_BASELINE'
_mods = {}


def load(unified):
    if 'model' not in _mods:
        sys.dont_write_bytecode = True
        sys.path.insert(0, unified)
        os.chdir(unified)
        for name in ('models.model_v2_1', 'engine', 'controllers', 'metrics'):
            _mods[name.split('.')[-1]] = importlib.import_module(name)
        _mods['original_scenarios'] = _mods['model_v2_1'].all_scenarios
    return _mods['model_v2_1'], _mods['engine'], _mods['controllers'], _mods['metrics']


def width_case(model, k, width):
    base = model.BASE_BVD
    return model.Scenario(f'WIDTH_SHIFT_{k:+g}', 'width_shift', 'fs', f'{k:+g} w',
                          f'fs moved by {k:+g} nominal widths ({width:.0f} Hz) with Rm and Qm held (study only, not registered)',
                          model.shifted_fs(base, 1+k*width/base.fs), model.BASE_MATCH, model.BASE_RS)


def configure(unified, config_name, over):
    model, engine, controllers, metrics = load(unified)
    cfg = json.loads(Path(CONFIGS[config_name]).read_text(encoding='utf-8'))
    cfg.update(over)
    model.all_scenarios = _mods['original_scenarios']
    model.configure(cfg)
    extra = [width_case(model, k, cfg['nominal_peak_width_Hz']) for k in WIDTH_SHIFTS]
    original = _mods['original_scenarios']
    model.all_scenarios = lambda: original()+extra
    return cfg, model, engine, controllers, metrics


def noise_filter(engine, sigma, seed):
    import numpy as np
    rng = np.random.default_rng(seed)
    phase = math.degrees(sigma)

    def f(m, kind):
        if not engine.valid_measurement(m):
            return m
        g = rng.standard_normal(8)
        return dataclasses.replace(
            m, p_port_W=m.p_port_W*(1+sigma*g[0]), vpp=m.vpp*(1+sigma*g[1]), irms=m.irms*(1+sigma*g[2]),
            zin_real=m.zin_real*(1+sigma*g[3]), zin_imag=m.zin_imag*(1+sigma*g[4]),
            phase_input_deg=m.phase_input_deg+phase*g[5],
            phase_port_deg=None if m.phase_port_deg is None else m.phase_port_deg+phase*g[6],
            irms_source=None if m.irms_source is None else m.irms_source*(1+sigma*g[7]))
    return f


def schedules(cfg, model):
    out = {'HISTORICAL_12': list(cfg['historical_schedule'])}
    for case in model.all_scenarios():
        if case.case_id != BASE:
            out['COVER_'+case.case_id] = [BASE, case.case_id, BASE]
    return out


def run_job(job):
    unified, config_name, variant, over, sigma, seed, strategies = job
    cfg, model, engine, controllers, metrics = configure(unified, config_name, over)
    refs = metrics.references(cfg)
    cases = model.scenario_map()
    phase = float(model.response(cfg['initial_frequency_Hz'], cases[BASE])['phase_deg'][0])
    rows = []
    for suite, ids in schedules(cfg, model).items():
        for s in strategies:
            e = engine.Engine(cfg, ids, s, suite)
            if sigma:
                stream = int(hashlib.sha256(f'{suite}/{s}'.encode()).hexdigest()[:8], 16)   # not hash(): salted per process
                e.measurement_filter = noise_filter(engine, sigma, seed*2**32 + stream)
            controllers.run_policy(controllers.Executor(e), s, phase)
            per, overall = metrics.evaluate(e.rows, e.events, cfg, refs)
            hard = sum(r['duration_us'] for r in e.rows if r['actual_hard_violation'])
            events = [x['event'] for x in e.events]
            target = per if suite == 'HISTORICAL_12' else [per[1]]
            for p in target:
                rows.append(dict(config=config_name, variant=variant, sigma=sigma, seed=seed, suite=suite, strategy=s,
                                 segment=p['segment_index'], case_id=p['case_id'], settled=p['settled'],
                                 sustained_95_ms=p['sustained_recovery_level_ms'], first_95_ms=p['first_recovery_level_ms'],
                                 recovery_confirm_ms=p['recovery_confirm_ms'], energy_pct=p['energy_capture_pct'],
                                 hard_violation_ms=hard/1000 if p is target[0] else 0., captures=events.count('SCAN_ATTEMPT_START'),
                                 protection_events=overall['protection_trigger_events'],
                                 schedule_energy_pct=overall['energy_capture_pct'] if suite == 'HISTORICAL_12' else None))
    return rows


def jobs(unified, seeds):
    out = []
    for name in CONFIGS:
        out.append((unified, name, 'noise_free', {}, 0., 0, ALL))
        for sigma in (.005, .02):
            for seed in range(seeds):
                out.append((unified, name, f'noise_{sigma:g}', {}, sigma, seed, MEASURING))
        for ramp in (25., 250.):
            out.append((unified, name, f'ramp_{ramp:g}', dict(ramp_amplitude_per_s=ramp), 0., 0, ALL))
    out.append((unified, 'physical', 'capture_amplitude_0.65', dict(capture_scan_amplitude=.65), 0., 0, ALL))
    return out


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def needs_control(rows):
    """Per config: the target suites where noise-free FIXED (0.9 MHz held, a=1) never reaches 95 %."""
    return {c: {r['suite'] for r in rows if r['config'] == c and r['variant'] == 'noise_free'
                and r['strategy'] == 'FIXED' and r['suite'] != 'HISTORICAL_12' and r['first_95_ms'] is None}
            for c in {r['config'] for r in rows}}


def summarise(rows):
    """Per (config, variant, strategy): target settled count, median/max sustained-95 time (on the
    segments that need control), HISTORICAL energy."""
    hard = needs_control(rows)
    table = {}
    for r in rows:
        key = (r['config'], r['variant'], r['strategy'])
        t = table.setdefault(key, dict(by_seed={}))
        s = t['by_seed'].setdefault(r['seed'], dict(target=0, target_settled=0, sustained={}, hist_energy=None, hard_ms=0.))
        s['hard_ms'] += r['hard_violation_ms']
        if r['suite'] == 'HISTORICAL_12':
            s['hist_energy'] = r['schedule_energy_pct']
        else:
            s['target'] += 1
            s['target_settled'] += r['settled']
            if r['suite'] in hard[r['config']]:
                s['sustained'][r['suite']] = r['sustained_95_ms']
    out = []
    for (config, variant, strategy), t in sorted(table.items()):
        seeds = t['by_seed'].values()
        all_sus = [x for s in seeds for x in s['sustained'].values()]
        out.append(dict(config=config, variant=variant, strategy=strategy, seeds=len(t['by_seed']),
                        target_segments=next(iter(seeds))['target'], needs_control=len(hard[config]),
                        target_settled_median=median([s['target_settled'] for s in seeds]),
                        target_settled_min=min(s['target_settled'] for s in seeds),
                        sustained_95_median_ms=median(all_sus),
                        sustained_95_max_ms=max([x for x in all_sus if x is not None], default=None),
                        sustained_95_missing=sum(x is None for x in all_sus),
                        historical_energy_median_pct=median([s['hist_energy'] for s in seeds]),
                        hard_violation_ms_total=sum(s['hard_ms'] for s in seeds)))
    return out, table


def verdicts(table):
    """The pre-registered criteria, ADMITTANCE_TRACK against CAPTURE_PO, per config and variant."""
    out = []
    for (config, variant, strategy), t in sorted(table.items()):
        if strategy != 'ADMITTANCE_TRACK' or (config, variant, 'CAPTURE_PO') not in table:
            continue
        a, c = t['by_seed'], table[(config, variant, 'CAPTURE_PO')]['by_seed']
        a1 = median([a[k]['target_settled'] for k in a]) >= median([c[k]['target_settled'] for k in c])
        ratios = []
        for k in a:
            both = [(a[k]['sustained'][s], c[k]['sustained'][s]) for s in a[k]['sustained']
                    if a[k]['sustained'][s] is not None and c[k]['sustained'].get(s) is not None]
            ma, mc = median([x for x, _ in both]), median([y for _, y in both])
            ratios.append(None if not both or not mc else ma/mc)
        ratio = median(ratios)
        a2 = ratio is not None and ratio <= .5
        a3 = all(a[k]['hard_ms'] == 0 for k in a)
        ea, ec = median([a[k]['hist_energy'] for k in a]), median([c[k]['hist_energy'] for k in c])
        a4 = ea >= ec-1.
        out.append(dict(config=config, variant=variant, A1=a1, A2=a2, A3=a3, A4=a4,
                        sustained_ratio_median=ratio, historical_energy_pct=(ea, ec),
                        all_pass=a1 and a2 and a3 and a4))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--unified', required=True)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--seeds', type=int, default=10)
    ap.add_argument('--jobs', type=int, default=os.cpu_count())
    a = ap.parse_args()
    unified = str(Path(a.unified).resolve())
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    work = jobs(unified, a.seeds)
    with Pool(a.jobs) as pool:
        rows = [r for part in pool.imap_unordered(run_job, work) for r in part]
    rows.sort(key=lambda r: (r['config'], r['variant'], r['seed'], r['suite'], r['strategy'], r['segment']))
    summary, table = summarise(rows)
    result = dict(acceptance=ACCEPTANCE, verdicts=verdicts(table), summary=summary,
                  needs_control={c: sorted(v) for c, v in needs_control(rows).items()},
                  width_shifts=WIDTH_SHIFTS, seeds=a.seeds,
                  platform_sources={p: hashlib.sha256((Path(unified)/p).read_bytes()).hexdigest()
                                    for p in ('admittance.py', 'controllers.py', 'engine.py', 'metrics.py',
                                              'models/model_v2_1.py', *CONFIGS.values())})
    (out/'p8_study.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, allow_nan=False), encoding='utf-8')
    import csv
    with (out/'segments.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for v in result['verdicts']:
        print(json.dumps(v, ensure_ascii=False))
    for s in summary:
        print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
