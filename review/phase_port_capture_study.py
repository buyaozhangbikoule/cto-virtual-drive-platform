#!/usr/bin/env python3
"""相位反馈换判据（换能器端相位＋捕获后重学目标）与第四种策略 CAPTURE_PO 的研究脚本（review/27）。

    python review/phase_port_capture_study.py --root <打了 P1–P6 的 current/unified> --out <目录>
                                              [--batches <正式批次摘要目录>] [--jobs N]

只读 --root：在内存里运行正式引擎、控制器与指标函数（engine / controllers / metrics），不改任何源文件；
只在 --out 写 CSV 与 JSON，拒绝写入 workspace/ 与任何 outputs/ 目录。

四部分，参数与生成规则都在运行前写定：
  1. 消融（两种基线 × 34 个登记场景的基准→场景→基准试验＋原 12 段日程）：
     FIXED、PERIODIC_SCAN、PHASE_FEEDBACK 原定律 gain_v1、newton_v2 × {输入相位, 换能器端相位} × {冻结, 捕获后重学}、
     CAPTURE_PO。配置只改 phase_tracker / phase_signal / phase_target_policy 三项，其余同正式配置。
  2. 自证：给 --batches 时，消融里与正式批次同配置的那几组必须与批次摘要逐值相同（同一引擎、同一指标函数）。
  3. 测量噪声：只加在控制器读到的测量上，不进被控对象与能量积分。P、Vpp、Irms、Zin 实部与虚部各乘
     (1+σ·N(0,1))，输入与端口相位各加 σ 弧度（换算成度）的高斯噪声；σ = 0.5% 与 2%，种子 1–10。
     策略：FIXED、相位原定律、相位端口＋重学、CAPTURE_PO；日程同第 1 部分。
  4. 留出负载：每种基线 40 个随机组合负载（种子 20261016，生成器见 held_out()），各自做基准→负载→基准试验。
     这些负载在开发与排错期间没有用过；它们和登记场景出自同一个电路模型族，不是独立器件。
  5. 段长敏感性：34 个登记场景的基准→场景→基准试验，每段 4 s（正式为 0.8 s），其余配置不变；
     FIXED、相位端口＋重学、CAPTURE_PO。看捕获的一次性代价摊到更长的负载持续时间后是否还在。
     这不是正式口径，正式批次与验收仍按 0.8 s。

结论边界：特定假设 BVD 模型、登记与随机生成的扰动、准稳态电学；无硬件、声学或临床结论。
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import multiprocessing as mp
import pathlib
import sys
import time

import numpy as np

CANDIDATE = 'candidates/synthetic_q13p8_3mA/config.json'
BASELINES = {'default': 'config.json', 'candidate': CANDIDATE}
GAIN_V1 = dict(phase_tracker='gain_v1', phase_signal='input', phase_target_policy='frozen')
VARIANTS = {   # name -> (strategy, phase overrides)
    'FIXED': ('FIXED', GAIN_V1),
    'PERIODIC_SCAN': ('PERIODIC_SCAN', GAIN_V1),
    'PHASE_gain_v1': ('PHASE_FEEDBACK', GAIN_V1),
    'PHASE_input_frozen': ('PHASE_FEEDBACK', dict(phase_tracker='newton_v2', phase_signal='input', phase_target_policy='frozen')),
    'PHASE_input_relearn': ('PHASE_FEEDBACK', dict(phase_tracker='newton_v2', phase_signal='input', phase_target_policy='relearn_after_capture')),
    'PHASE_port_frozen': ('PHASE_FEEDBACK', dict(phase_tracker='newton_v2', phase_signal='port', phase_target_policy='frozen')),
    'PHASE_port_relearn': ('PHASE_FEEDBACK', dict(phase_tracker='newton_v2', phase_signal='port', phase_target_policy='relearn_after_capture')),
    'CAPTURE_PO': ('CAPTURE_PO', GAIN_V1),
}
NOISE_VARIANTS = ('FIXED', 'PHASE_gain_v1', 'PHASE_port_relearn', 'CAPTURE_PO')
HELD_OUT_VARIANTS = ('FIXED', 'PERIODIC_SCAN', 'PHASE_gain_v1', 'PHASE_port_relearn', 'CAPTURE_PO')
LONG_VARIANTS = ('FIXED', 'PHASE_port_relearn', 'CAPTURE_PO')
LONG_SEGMENT_US = 4000000
SIGMAS = (0.005, 0.02)
SEEDS = tuple(range(1, 11))
HELD_OUT_SEED, HELD_OUT_N = 20261016, 40
ALIASES = ('CASE_000_BASELINE', 'CASE_QL_100', 'CASE_QM_800')   # 与基准完全相同的登记项

ROOT = None
_cache = {}


def load(root: pathlib.Path):
    """Import the formal modules from root once per process."""
    if 'mods' not in _cache:
        sys.path.insert(0, str(root))
        import controllers, engine, metrics                 # noqa: E401,E402
        from models import model_v2_1 as model             # noqa: E402
        _cache['mods'] = (controllers, engine, metrics, model)
        _cache['originals'] = (model.all_scenarios, model.scenario_map)
    return _cache['mods']


def held_out(model, n=HELD_OUT_N, seed=HELD_OUT_SEED):
    """Random combined loads around the configured baseline (declared before running).

    fs ×U(0.95,1.02); C0 ×U(0.90,1.30); Rm ×U(1.00,1.50); Qm ×U(0.625,1.25), Lm/Cm re-derived at the new fs;
    Lmatch ×U(0.97,1.08); Cmatch ×U(0.92,1.03); inductor Q U(20,100); Rs ×U(1.00,1.20). Independent draws.
    """
    rng = np.random.default_rng(seed)
    b, m0 = model.BASE_BVD, model.BASE_MATCH
    out = []
    for k in range(n):
        fs, c0, rm, qm, lm, cm, ql, rs = (rng.uniform(.95, 1.02), rng.uniform(.9, 1.3), rng.uniform(1., 1.5),
                                          rng.uniform(.625, 1.25), rng.uniform(.97, 1.08), rng.uniform(.92, 1.03),
                                          rng.uniform(20., 100.), rng.uniform(1., 1.2))
        bvd = model.bvd_from_fs_qm(c0=b.c0*c0, rm=b.rm*rm, fs=b.fs*fs, qm=b.qm*qm)
        matching = dataclasses.replace(m0, l_h=m0.l_h*lm, c_f=m0.c_f*cm, ql=float(ql))
        text = (f'fs x{fs:.4f}, C0 x{c0:.3f}, Rm x{rm:.3f}, Qm x{qm:.3f}, Lmatch x{lm:.4f}, '
                f'Cmatch x{cm:.4f}, QL {ql:.1f}, Rs x{rs:.3f}')
        out.append(model.Scenario(f'HELDOUT_{k:02d}', 'held_out', 'random_combined', f'{k:02d}', text,
                                  bvd, matching, model.BASE_RS*rs))
    return out


def noise_filter(engine_mod, sigma, seed):
    rng = np.random.default_rng(seed)
    phase_sigma = math.degrees(sigma)

    def f(m, kind):
        if not engine_mod.valid_measurement(m):
            return m
        g = rng.standard_normal(7)
        return dataclasses.replace(
            m, p_port_W=m.p_port_W*(1+sigma*g[0]), vpp=m.vpp*(1+sigma*g[1]), irms=m.irms*(1+sigma*g[2]),
            zin_real=m.zin_real*(1+sigma*g[3]), zin_imag=m.zin_imag*(1+sigma*g[4]),
            phase_input_deg=m.phase_input_deg+phase_sigma*g[5],
            phase_port_deg=None if m.phase_port_deg is None else m.phase_port_deg+phase_sigma*g[6])
    return f


def run_job(job):
    """One (baseline, variant, schedule set, noise) job; returns per-suite rows."""
    baseline, variant, part, sigma, seed = job
    controllers, engine_mod, metrics, model = load(ROOT)
    cfg = json.loads((ROOT/BASELINES[baseline]).read_text(encoding='utf-8'))
    strategy, over = VARIANTS[variant]
    cfg.update(over)
    if part == 'long_segments':
        cfg['segment_us'] = LONG_SEGMENT_US
    model.all_scenarios, model.scenario_map = _cache['originals']   # undo the previous job's table
    model.configure(cfg)
    registered = model.all_scenarios()
    extra = held_out(model) if part == 'held_out' else []
    scenarios = registered+extra
    smap = {s.case_id: s for s in scenarios}
    model.all_scenarios = lambda: list(scenarios)          # in memory only, this process
    model.scenario_map = lambda: dict(smap)
    refs = metrics.references(cfg)
    phase = float(model.response(cfg['initial_frequency_Hz'], smap['CASE_000_BASELINE'])['phase_deg'][0])
    schedules = {}
    if part in ('registered', 'noise', 'long_segments'):
        if part != 'long_segments':
            schedules['HISTORICAL_12'] = cfg['historical_schedule']
        for s in registered:
            schedules['COVER_'+s.case_id] = ['CASE_000_BASELINE', s.case_id, 'CASE_000_BASELINE']
    else:
        for s in extra:
            schedules['HELD_'+s.case_id] = ['CASE_000_BASELINE', s.case_id, 'CASE_000_BASELINE']
    rows = []
    for suite, ids in schedules.items():
        e = engine_mod.Engine(cfg, ids, strategy, suite)
        if sigma:
            e.measurement_filter = noise_filter(engine_mod, sigma, seed)
        controllers.run_policy(controllers.Executor(e), strategy, phase)
        per, overall = metrics.evaluate(e.rows, e.events, cfg, refs)
        names = [x['event'] for x in e.events]
        row = dict(baseline=baseline, variant=variant, strategy=strategy, part=part, sigma=sigma, seed=seed,
                   suite=suite, settled_segments=overall['settled_segments'], segments=len(per),
                   energy_J=overall['energy_J'], reference_J=overall['policy_reference_energy_J'],
                   energy_pct=overall['energy_capture_pct'],
                   captures=sum(1 for x in e.events if x['event'] == 'SCAN_ATTEMPT_START'),
                   capture_failures=overall['scan_failures'],
                   memory_recalls=names.count('MEMORY_RECALLED')+sum(
                       1 for x in e.events if x['event'] == 'SCAN_SUCCESS' and x.get('source') == 'MEMORY'),
                   soft_foldbacks=names.count('SOFT_FOLDBACK_ENTER'), hard_trips=names.count('OBSERVED_HARD_TRIP'),
                   peak_post_guard_voltage_Vpp=overall['peak_post_guard_and_hold_voltage_Vpp'],
                   post_guard_hard_violation_ms=overall['actual_hard_violation_duration_ms'])
        if len(per) == 3:
            row.update(case_id=ids[1], target_settled=per[1]['settled'], target_energy_J=per[1]['energy_J'],
                       target_reference_J=per[1]['policy_reference_energy_J'],
                       target_energy_pct=per[1]['energy_capture_pct'], return_energy_pct=per[2]['energy_capture_pct'],
                       target_confirm_ms=per[1]['recovery_confirm_ms'])
        rows.append(row)
    return rows


def write_csv(path, rows):
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def summarise(rows):
    """Per (baseline, variant, part, sigma, seed): 12-segment and cover totals."""
    groups = {}
    for r in rows:
        groups.setdefault((r['baseline'], r['variant'], r['part'], r['sigma'], r['seed']), []).append(r)
    out = []
    for (baseline, variant, part, sigma, seed), rs in groups.items():
        hist = [r for r in rs if r['suite'] == 'HISTORICAL_12']
        cover = [r for r in rs if 'target_settled' in r]
        cover_unique = [r for r in cover if r['case_id'] not in ALIASES[1:]]
        item = dict(baseline=baseline, variant=variant, part=part, sigma=sigma, seed=seed)
        if hist:
            item.update(hist_settled=hist[0]['settled_segments'], hist_energy_pct=hist[0]['energy_pct'])
        if cover:
            item.update(target_settled=sum(r['target_settled'] for r in cover), targets=len(cover),
                        target_energy_pct=100*sum(r['target_energy_J'] for r in cover)/sum(r['target_reference_J'] for r in cover),
                        return_energy_pct_mean=float(np.mean([r['return_energy_pct'] for r in cover])),
                        worst_target_energy_pct=min(r['target_energy_pct'] for r in cover),
                        worst_return_energy_pct=min(r['return_energy_pct'] for r in cover),
                        unique_target_settled=sum(r['target_settled'] for r in cover_unique),
                        captures=sum(r['captures'] for r in rs), capture_failures=sum(r['capture_failures'] for r in rs),
                        soft_foldbacks=sum(r['soft_foldbacks'] for r in rs),
                        max_post_guard_voltage_Vpp=max(r['peak_post_guard_voltage_Vpp'] for r in rs),
                        post_guard_hard_violation_ms=sum(r['post_guard_hard_violation_ms'] for r in rs))
        out.append(item)
    return out


def self_check(rows, batches: pathlib.Path):
    """The study's runs with the formal configuration must equal the saved batch summaries."""
    problems, checked = [], 0
    for meta_path in sorted(batches.glob('*/run_metadata.json')):
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        baseline = 'candidate' if 'candidates/' in meta['config_file'] else 'default'
        mode = meta['phase_feedback']
        with open(meta_path.parent/'formal_three_strategy_summary.csv', encoding='utf-8-sig', newline='') as f:
            summary = list(csv.DictReader(f))
        for s in summary:
            if s['strategy'] == 'PHASE_FEEDBACK':
                variant = 'PHASE_gain_v1' if mode['tracker'] == 'gain_v1' else f"PHASE_{mode['signal']}_{'relearn' if mode['target_policy'] == 'relearn_after_capture' else 'frozen'}"
            else:
                variant = s['strategy']
            match = [r for r in rows if r['part'] == 'registered' and r['baseline'] == baseline
                     and r['variant'] == variant and r['suite'] == s['suite']]
            if len(match) != 1:
                problems.append(f'missing {baseline} {variant} {s["suite"]}')
                continue
            r = match[0]
            checked += 1
            if int(s['settled_segments']) != r['settled_segments'] or abs(float(s['energy_J'])-r['energy_J']) > 1e-12:
                problems.append(f'{meta["batch_id"]} {variant} {s["suite"]}: batch {s["settled_segments"]}/{s["energy_J"]}'
                                f' vs study {r["settled_segments"]}/{r["energy_J"]}')
    return dict(checked=checked, problems=problems, ok=not problems and checked > 0)


def main():
    global ROOT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--batches', default=None, help='保存的正式批次摘要（每个子目录含 run_metadata.json 与 formal_three_strategy_summary.csv）')
    ap.add_argument('--jobs', type=int, default=max(1, mp.cpu_count()-1))
    a = ap.parse_args()
    ROOT = pathlib.Path(a.root).resolve()
    out = pathlib.Path(a.out).resolve()
    if {'workspace', 'outputs'} & set(out.parts):
        raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out}')
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(b, v, 'registered', 0., 0) for b in BASELINES for v in VARIANTS]
    jobs += [(b, v, 'noise', s, k) for b in BASELINES for v in NOISE_VARIANTS for s in SIGMAS for k in SEEDS]
    jobs += [(b, v, 'held_out', 0., 0) for b in BASELINES for v in HELD_OUT_VARIANTS]
    jobs += [(b, v, 'long_segments', 0., 0) for b in BASELINES for v in LONG_VARIANTS]
    t0 = time.time()
    with mp.Pool(a.jobs, initializer=_init, initargs=(str(ROOT),)) as pool:
        rows = [r for part in pool.imap_unordered(run_job, jobs, chunksize=1) for r in part]
    rows.sort(key=lambda r: (r['part'], r['baseline'], r['variant'], r['sigma'], r['seed'], r['suite']))
    summary = summarise(rows)
    summary.sort(key=lambda r: (r['part'], r['baseline'], r['variant'], r['sigma'], r['seed']))
    write_csv(out/'per_suite.csv', rows)
    write_csv(out/'summary_by_run.csv', summary)
    noise = []
    for b in BASELINES:
        for v in NOISE_VARIANTS:
            for s in SIGMAS:
                runs = [r for r in summary if r['part'] == 'noise' and r['baseline'] == b and r['variant'] == v and r['sigma'] == s]
                noise.append(dict(baseline=b, variant=v, sigma=s, seeds=len(runs),
                                  **{f'{k}_mean': float(np.mean([r[k] for r in runs])) for k in
                                     ('hist_settled', 'hist_energy_pct', 'target_settled', 'target_energy_pct', 'return_energy_pct_mean', 'captures')},
                                  **{f'{k}_sd': float(np.std([r[k] for r in runs], ddof=1)) for k in
                                     ('hist_settled', 'hist_energy_pct', 'target_settled', 'target_energy_pct')},
                                  **{f'{k}_min': float(min(r[k] for r in runs)) for k in ('hist_energy_pct', 'target_energy_pct')}))
    write_csv(out/'noise_summary.csv', noise)
    check = self_check(rows, pathlib.Path(a.batches)) if a.batches else dict(ok=None, note='no --batches given')
    meta = dict(script='review/phase_port_capture_study.py', root=str(ROOT), jobs=len(jobs), suites=len(rows),
                seconds=round(time.time()-t0, 1), held_out=dict(seed=HELD_OUT_SEED, n=HELD_OUT_N, generator=held_out.__doc__.strip()),
                long_segments=dict(segment_us=LONG_SEGMENT_US, variants=LONG_VARIANTS),
                noise=dict(sigmas=SIGMAS, seeds=SEEDS, model='P, Vpp, Irms, Re Zin, Im Zin x (1+sigma N); input and port phase + sigma rad N'),
                self_check=check, python=sys.version, numpy=np.__version__)
    (out/'run_metadata.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    for r in summary:
        if r['part'] != 'noise':
            print(r['part'], r['baseline'], r['variant'],
                  f"hist {r.get('hist_settled', '-')}/12 {r.get('hist_energy_pct', float('nan')):.3f}%" if 'hist_settled' in r else '',
                  f"target {r['target_settled']}/{r['targets']} {r['target_energy_pct']:.3f}% return {r['return_energy_pct_mean']:.2f}%"
                  f" worst {r['worst_target_energy_pct']:.1f}/{r['worst_return_energy_pct']:.1f}% captures {r['captures']} foldbacks {r['soft_foldbacks']}")
    for r in noise:
        print('noise', r['baseline'], r['variant'], r['sigma'],
              f"hist {r['hist_settled_mean']:.1f}±{r['hist_settled_sd']:.1f}/12 {r['hist_energy_pct_mean']:.2f}±{r['hist_energy_pct_sd']:.2f}%",
              f"target {r['target_settled_mean']:.1f}±{r['target_settled_sd']:.1f}/34 {r['target_energy_pct_mean']:.2f}±{r['target_energy_pct_sd']:.2f}%")
    print('self-check', json.dumps(check, ensure_ascii=False))
    return 0 if check.get('ok') in (True, None) else 1


def _init(root):
    global ROOT
    ROOT = pathlib.Path(root)


if __name__ == '__main__':
    raise SystemExit(main())
