"""Read-only latency decomposition of the unified 12-segment run.

Replays the formal strategies in memory and splits every segment's wall time
into the phases that actually consume it. Writes nothing. Takes the unified
source directory as argument so the frozen outputs/ are never touched.

Column meanings, which differ by strategy because only PERIODIC_SCAN scans:

  frozen  protection held the drive (HARD_TRIP/HOLD/FOLDBACK/PREPARE/DATA_INVALID)
  rampA   RAMP_UP before this segment's SCAN_SUCCESS. For PERIODIC_SCAN that is
          the ramp at the STALE frequency; for FIXED and PHASE_FEEDBACK, which
          never lock, it is simply all of their RAMP_UP time.
  wait    protection NORMAL, unfrozen, but the sample does not qualify. For
          PERIODIC_SCAN before its scan this is idling at the old frequency; for
          PHASE_FEEDBACK it is mostly converged-but-under-98%, i.e. a wrong
          operating point rather than latency. Read it with that in mind.
  scan    any non-CONTROL action: scan points for PERIODIC_SCAN, the two phase
          probes for PHASE_FEEDBACK.
  rampB   RAMP_UP after SCAN_SUCCESS; always 0 for FIXED and PHASE_FEEDBACK.
  qual    samples meeting the platform's acceptance predicate.

The settled count printed here is a PROXY (total qualifying time >= 200 ms) and
is deliberately looser than the platform's own rule, which needs 10 CONSECUTIVE
samples on the 20 ms lattice. It therefore over-counts PERIODIC_SCAN, whose
qualifying samples are broken apart by the scan itself. Use metrics.evaluate for
the authoritative figure; this proxy exists only to make the row sum legible.
"""
import argparse
import collections
import json
import pathlib
import sys


def load(root: pathlib.Path):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import engine
    import controllers
    cfg = json.loads((root / 'config.json').read_text())
    return engine, controllers, cfg


def replay(engine, controllers, cfg, strategy):
    ids = cfg['historical_schedule']
    eng = engine.Engine(cfg, ids, strategy, 'LATENCY_BUDGET')
    io = controllers.Executor(eng)
    import models.model_v2_1 as model
    target_phase = float(model.response(
        cfg['initial_frequency_Hz'],
        model.scenario_map()['CASE_000_BASELINE'])['phase_deg'][0])
    controllers.run_policy(io, strategy, target_phase)
    return eng.rows, eng.events, target_phase


def refs(engine, controllers, cfg):
    import models.model_v2_1 as model
    return engine.policy_references(cfg) if hasattr(engine, 'policy_references') else None


PHASES = ('frozen_hold', 'ramp_stale_f', 'idle_wait_scan', 'scanning',
          'ramp_after_lock', 'qualified', 'other')


def decompose(rows, events, cfg, reference):
    """Split each segment into phases. Classification uses only logged state."""
    seg_us = cfg['segment_us']
    tick = cfg['control_tick_us']
    by_seg = collections.defaultdict(list)
    for r in rows:
        by_seg[r['segment_index']].append(r)
    ev_by_seg = collections.defaultdict(list)
    for e in events:
        ev_by_seg[e['time_us'] // seg_us].append(e)

    out = []
    for seg in sorted(by_seg):
        rs = by_seg[seg]
        start = seg * seg_us
        ref = reference[rs[0]['case_id']]
        evs = ev_by_seg[seg]
        scan_start = next((e['time_us'] for e in evs
                           if e['event'] == 'SCAN_ATTEMPT_START'), None)
        scan_lock = next((e['time_us'] for e in evs
                          if e['event'] == 'SCAN_SUCCESS'), None)
        bucket = dict.fromkeys(PHASES, 0)
        first_q = None
        for r in rs:
            d = r['duration_us']
            q = (r['kind'] == 'CONTROL' and r['protection_state'] == 'NORMAL'
                 and not r['frequency_frozen'] and r['measurement_valid']
                 and r['end_us'] % tick == 0
                 and r['action_end_us'] == r['end_us']
                 and r['p_rm_W'] / ref >= cfg['capture_threshold']
                 and not r['actual_hard_violation'])
            if q and first_q is None:
                first_q = r['end_us']
            st = r['protection_state']
            if q:
                bucket['qualified'] += d
            elif r['kind'] != 'CONTROL':
                bucket['scanning'] += d
            elif st in ('HARD_TRIP', 'HOLD', 'FOLDBACK', 'DATA_INVALID', 'PREPARE'):
                bucket['frozen_hold'] += d
            elif st == 'RAMP_UP':
                after = scan_lock is not None and r['start_us'] >= scan_lock
                bucket['ramp_after_lock' if after else 'ramp_stale_f'] += d
            elif st == 'NORMAL':
                bucket['idle_wait_scan'] += d
            else:
                bucket['other'] += d
        out.append(dict(
            segment=seg, case=rs[0]['case_id'],
            first_qualified_ms=None if first_q is None else (first_q - start) / 1000,
            scan_start_ms=None if scan_start is None else (scan_start - start) / 1000,
            scan_lock_ms=None if scan_lock is None else (scan_lock - start) / 1000,
            **{k: bucket[k] / 1000 for k in PHASES}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--strategies', default='PERIODIC_SCAN,PHASE_FEEDBACK,FIXED')
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    engine, controllers, cfg = load(root)
    import models.model_v2_1 as model
    ref = {c: float(model.response(cfg['initial_frequency_Hz'], s)['p_rm_W'][0])
           for c, s in model.scenario_map().items()}
    # Policy reference = best power on the reference grid for that scenario.
    ref = {}
    lo, hi, step = cfg['frequency_min_Hz'], cfg['frequency_max_Hz'], cfg['reference_grid_step_Hz']
    import numpy as np
    gridf = np.arange(lo, hi + step / 2, step, dtype=float)
    for c, s in model.scenario_map().items():
        ref[c] = max(float(model.response(f, s)['p_rm_W'][0]) for f in gridf)

    print(f'config: segment={cfg["segment_us"]/1000:.0f} ms  tick={cfg["control_tick_us"]/1000:.0f} ms  '
          f'scan_period={cfg["scan_period_us"]/1000:.0f} ms')
    print(f'        ramp={cfg["ramp_amplitude_per_s"]}/s  scan_amp={cfg["scan_amplitude"]}  '
          f'recovery_amp={cfg["recovery_amplitude"]}')
    print(f'        hard_hold={cfg["hard_hold_us"]/1000:.0f} ms  recovery_hold={cfg["recovery_hold_us"]/1000:.0f} ms')
    print(f'        acceptance = {cfg["continuous_samples"]} x {cfg["control_tick_us"]/1000:.0f} ms '
          f'= {cfg["continuous_samples"]*cfg["control_tick_us"]/1000:.0f} ms at >= {cfg["capture_threshold"]:.0%}')
    print()
    for strategy in a.strategies.split(','):
        rows, events, tp = replay(engine, controllers, cfg, strategy)
        tbl = decompose(rows, events, cfg, ref)
        print(f'===== {strategy}  (phase target {tp:.7f} deg)')
        hdr = ('seg case                 firstQ  scanS  lockT | frozen  rampA   wait   scan  rampB   qual')
        print(hdr)
        for r in tbl:
            f = lambda v: '    -' if v is None else f'{v:5.0f}'
            print(f'{r["segment"]:3d} {r["case"]:<20s} {f(r["first_qualified_ms"])} '
                  f'{f(r["scan_start_ms"])} {f(r["scan_lock_ms"])} |'
                  f'{r["frozen_hold"]:7.0f}{r["ramp_stale_f"]:7.0f}{r["idle_wait_scan"]:7.0f}'
                  f'{r["scanning"]:7.0f}{r["ramp_after_lock"]:7.0f}{r["qualified"]:7.0f}')
        tot = {k: sum(r[k] for r in tbl) for k in PHASES}
        n = len(tbl)
        print(f'    合计 (12 段 = {n*cfg["segment_us"]/1000:.0f} ms)        |'
              + ''.join(f'{tot[k]:7.0f}' for k in
                        ('frozen_hold', 'ramp_stale_f', 'idle_wait_scan',
                         'scanning', 'ramp_after_lock', 'qualified')))
        print(f'    占比                            |'
              + ''.join(f'{100*tot[k]/(n*cfg["segment_us"]/1000):6.1f}%' for k in
                        ('frozen_hold', 'ramp_stale_f', 'idle_wait_scan',
                         'scanning', 'ramp_after_lock', 'qualified')))
        acc = [r for r in tbl if r['qualified'] >= cfg['continuous_samples']*cfg['control_tick_us']/1000]
        print(f'    达标段(合格时间>=200ms): {len(acc)}/{n}')
        print()


if __name__ == '__main__':
    main()
