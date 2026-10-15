"""Read-only: what the periodic scan itself costs, and whether scanning less helps.

Segment 0 is undisturbed, starts exactly at the optimum and qualifies at 20 ms,
yet captures only 75.0% of its reference energy. The missing quarter is the scan:
every scan runs at scan_amplitude (0.4 -> 16% of the power) and is followed by a
ramp back to full at 2.5/s. So the lever is how OFTEN the policy scans, not how
fast it searches.

Five clock origins are compared, all with the shared scan, budget, guard and
scorer untouched:
  ABSOLUTE      the formal policy: next scan on the absolute 500 ms lattice.
  SCAN_END      500 ms measured from the scan's own return.
  RECOVERY_END  500 ms measured from the first NORMAL, unfrozen sample at the
                newly locked frequency (the pre-registered main candidate of
                research/recovery-scan-handoff-unvalidated-20261012).
  EVENT_ONLY    no periodic clock at all; rescan only when the protection
                reports a hold/trip, which is already controller-visible.
  EVENT_OR_SLOW as EVENT_ONLY plus a slow safety-net clock.

No variant reads a scenario ID, a segment boundary, the offline optimum table
or the acceptance counter. Nothing is written.
"""
import argparse
import json
import pathlib
import sys

TRIP_STATES = ('HARD_TRIP', 'HOLD', 'FOLDBACK', 'DATA_INVALID', 'PREPARE')
MODES = ('ABSOLUTE', 'SCAN_END', 'RECOVERY_END', 'EVENT_ONLY', 'EVENT_OR_SLOW')


def build(root):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import engine as E
    import controllers as C
    import metrics as M
    import models.model_v2_1 as model
    cfg = json.loads((root / 'config.json').read_text())
    return E, C, M, model, cfg


def run(E, C, cfg, ids, mode, slow_us, suite):
    assert mode in MODES
    eng = E.Engine(cfg, ids, 'PERIODIC_SCAN', suite)
    io = C.Executor(eng)
    period = cfg['scan_period_us']
    target = float(cfg['initial_frequency_Hz'])
    next_scan = period if mode not in ('EVENT_ONLY', 'EVENT_OR_SLOW') else period
    awaiting_recovery = False
    retry = C.ScanBudget(cfg)
    last = None
    failed_episode = False
    pending = False
    while not io.finished:
        if retry.exhausted:
            io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_LATCHED_HOLD')
            continue
        if failed_episode and not retry.can_start(io.time):
            last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_RETRY_WAIT')
            continue
        clock_due = next_scan is not None and io.time >= next_scan
        scan_due = failed_episode or pending or clock_due
        ready = (last is not None and C.valid_measurement(last)
                 and last.state == 'NORMAL' and not last.frozen)
        if scan_due and ready and retry.can_start(io.time):
            why = 'EVENT' if (pending and not clock_due) else 'CLOCK'
            pending = False
            retry.start(io.time)
            io.event('SCAN_ATTEMPT_START', attempt=retry.attempts,
                     trusted_frequency_Hz=target, trigger=why)
            result = C.scan(io, target)
            if result.ok:
                target = float(result.frequency_Hz)
                io.event('SCAN_SUCCESS', frequency_Hz=target, band_edge=result.band_edge)
                retry.success()
                failed_episode = False
                if mode == 'ABSOLUTE':
                    next_scan = (io.time // period + 1) * period
                elif mode == 'SCAN_END':
                    next_scan = io.time + period
                elif mode == 'RECOVERY_END':
                    next_scan, awaiting_recovery = None, True
                elif mode == 'EVENT_ONLY':
                    next_scan = None
                else:
                    next_scan = io.time + slow_us
            else:
                bc = retry.classify(result.status)
                if bc is None:
                    io.event('SCAN_TRUNCATED_BY_RUN_END', reason=result.reason,
                             status=result.status, trusted_frequency_unchanged_Hz=target)
                    continue
                retry.fail(bc, io.time)
                failed_episode = True
                io.event('SCAN_FAILURE', reason=result.reason, status=result.status,
                         budget_class=bc, trusted_frequency_unchanged_Hz=target,
                         total_failures=retry.total_failures)
                if retry.exhausted:
                    io.event('SCAN_RETRIES_EXHAUSTED', budget_class=retry.exhausted_class)
                if not io.finished:
                    last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_ROLLBACK')
                continue
        if not io.finished:
            req = cfg['scan_amplitude'] if (failed_episode or pending) else 1.
            last = io.control(target, req)
            if awaiting_recovery and C.valid_measurement(last) \
                    and last.state == 'NORMAL' and not last.frozen \
                    and abs(last.frequency_Hz - target) < 1e-7:
                next_scan, awaiting_recovery = io.time + period, False
                io.event('RECOVERY_TIMER_REARM', next_scan_us=next_scan)
            if mode in ('EVENT_ONLY', 'EVENT_OR_SLOW') and not failed_episode \
                    and last is not None and last.state in TRIP_STATES and not pending:
                io.event('RESCAN_TRIGGER', source='PROTECTION_STATE', state=last.state)
                pending = True
    return eng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--slow-ms', type=float, default=2000.0)
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    E, C, M, model, cfg = build(root)
    ids = cfg['historical_schedule']
    ref = M.references(cfg)

    print('扫描一次的代价：扫描期间幅度 %.2f（功率约为满幅的 %.0f%%），返回后按 %.1f/s 升幅，'
          '即 %.0f ms 才回到满幅。'
          % (cfg['scan_amplitude'], 100 * cfg['scan_amplitude'] ** 2,
             cfg['ramp_amplitude_per_s'],
             1000 * (1 - cfg['scan_amplitude']) / cfg['ramp_amplitude_per_s']))
    print('EVENT_OR_SLOW 的兜底周期 = %.0f ms（本研究设定的策略参数）\n' % a.slow_ms)

    out = {}
    for mode in MODES:
        eng = run(E, C, cfg, ids, mode, int(a.slow_ms * 1000), 'SCAN_COST')
        per, summary = M.evaluate(eng.rows, eng.events, cfg, ref)
        ramp = sum(r['duration_us'] for r in eng.rows
                   if r['protection_state'] == 'RAMP_UP') / 1000
        low = sum(r['duration_us'] for r in eng.rows
                  if r['applied_amplitude'] < 0.999) / 1000
        scans = sum(1 for e in eng.events if e['event'] == 'SCAN_ATTEMPT_START')
        ev = sum(1 for e in eng.events
                 if e['event'] == 'SCAN_ATTEMPT_START' and e.get('trigger') == 'EVENT')
        pv = max(r['pre_guard_vport_Vpp'] for r in eng.rows)
        hv = sum(r['duration_us'] for r in eng.rows
                 if r.get('actual_hard_violation')) / 1000
        print('%-14s 达标段 %2d/12  能量 %6.2f%%  扫描 %2d(事件 %2d)  失败 %d  '
              '非满幅 %5.0f ms(%4.1f%%)  升幅 %5.0f ms  峰值 %7.3f Vpp  硬越限 %.3f ms'
              % (mode, summary['settled_segments'], summary['energy_capture_pct'],
                 scans, ev, summary['scan_failures'], low,
                 100 * low / (len(ids) * cfg['segment_us'] / 1000), ramp, pv, hv))
        out[mode] = per

    print()
    print('每段能量捕获 (%):')
    print('%-14s' % '' + ''.join('%7d' % i for i in range(12)))
    for m in out:
        print('%-14s' % m + ''.join('%7.1f' % r['energy_capture_pct'] for r in out[m]))
    print('%-14s' % '场景' + ''.join('%7s' % c.replace('CASE_', '')[:6] for c in ids))
    print()
    print('每段首个合格样本时刻 (ms):')
    print('%-14s' % '' + ''.join('%7d' % i for i in range(12)))
    for m in out:
        print('%-14s' % m + ''.join(
            '      —' if r['first_qualified_sample_ms'] is None
            else '%7.0f' % r['first_qualified_sample_ms'] for r in out[m]))


if __name__ == '__main__':
    main()
