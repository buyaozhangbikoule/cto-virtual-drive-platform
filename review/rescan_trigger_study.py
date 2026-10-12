"""Read-only prototype: event-triggered rescan instead of a fixed 500 ms clock.

The formal periodic policy learns its frequency is stale only when the absolute
scan clock fires, so after a disturbance it first ramps 0.25 -> 1.0 at the old
frequency, waits out the rest of the clock, scans, and ramps 0.4 -> 1.0 again.
Two observable triggers are tested, each usable by a controller that sees only
its own commanded values and its own measurements:

  TRIP  the protection itself reported a hold/trip. That state is already in
        the controller-visible Measurement, needs no threshold, and means the
        plant moved under an unchanged command.
  POWER measured p_port/amplitude^2 changed by more than a declared fraction
        between two NORMAL, unfrozen CONTROL samples at the SAME commanded
        frequency and amplitude.

Neither reads a scenario ID, a segment boundary, the offline optimum table or
the acceptance counter. Nothing is written.
"""
import argparse
import json
import pathlib
import sys

TRIP_STATES = ('HARD_TRIP', 'HOLD', 'FOLDBACK', 'DATA_INVALID', 'PREPARE')


def build(root):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import engine as E
    import controllers as C
    import metrics as M
    import models.model_v2_1 as model
    cfg = json.loads((root / 'config.json').read_text())
    return E, C, M, model, cfg


def run(E, C, cfg, ids, use_trip, use_power, drop_fraction,
        min_interval_us, suite):
    eng = E.Engine(cfg, ids, 'PERIODIC_SCAN', suite)
    io = C.Executor(eng)
    target = float(cfg['initial_frequency_Hz'])
    next_scan = cfg['scan_period_us']
    retry = C.ScanBudget(cfg)
    last = None
    failed_episode = False
    pending = False            # an observable trigger is asking for a rescan
    last_event_scan = -10 ** 12
    prev_norm = None           # p_port / amplitude^2 at the last clean sample
    prev_key = None            # (commanded frequency, commanded amplitude)
    while not io.finished:
        if retry.exhausted:
            io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_LATCHED_HOLD')
            continue
        if failed_episode and not retry.can_start(io.time):
            last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_RETRY_WAIT')
            continue
        scan_due = failed_episode or io.time >= next_scan or pending
        ready = (last is not None and C.valid_measurement(last)
                 and last.state == 'NORMAL' and not last.frozen)
        if scan_due and ready and retry.can_start(io.time):
            if pending:
                io.event('EVENT_RESCAN_START', trusted_frequency_Hz=target)
                last_event_scan = io.time
                pending = False
            retry.start(io.time)
            io.event('SCAN_ATTEMPT_START', attempt=retry.attempts,
                     trusted_frequency_Hz=target)
            result = C.scan(io, target)
            if result.ok:
                target = float(result.frequency_Hz)
                io.event('SCAN_SUCCESS', frequency_Hz=target, band_edge=result.band_edge)
                retry.success()
                failed_episode = False
                next_scan = (io.time // cfg['scan_period_us'] + 1) * cfg['scan_period_us']
                prev_norm, prev_key = None, None   # reference is stale after a hop
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
            # While a rescan is pending the frequency is known to be stale, so
            # do not ramp to full at it; that ramp is what blocks `ready`.
            req = cfg['scan_amplitude'] if (failed_episode or pending) else 1.
            req_f, req_a = target, req
            last = io.control(req_f, req_a)
            if not failed_episode and io.time - last_event_scan >= min_interval_us:
                if use_trip and last is not None and last.state in TRIP_STATES:
                    if not pending:
                        io.event('RESCAN_TRIGGER', source='PROTECTION_STATE',
                                 state=last.state)
                    pending = True
                if (use_power and C.valid_measurement(last)
                        and last.state == 'NORMAL' and not last.frozen
                        and last.amplitude > 1e-9):
                    key = (req_f, req_a)
                    norm = last.p_port_W / (last.amplitude ** 2)
                    if prev_key == key and prev_norm is not None and prev_norm > 0:
                        rel = abs(norm - prev_norm) / prev_norm
                        if rel > drop_fraction and not pending:
                            io.event('RESCAN_TRIGGER', source='MEASURED_POWER',
                                     relative_change=rel,
                                     threshold=drop_fraction)
                            pending = True
                    prev_key, prev_norm = key, norm
    return eng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--drop', type=float, default=0.10)
    ap.add_argument('--min-interval-ms', type=float, default=100.0)
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    E, C, M, model, cfg = build(root)
    ids = cfg['historical_schedule']
    ref = M.references(cfg)
    mi = int(a.min_interval_ms * 1000)

    variants = [
        ('A_原样_绝对时钟', False, False),
        ('B_保护状态触发', True, False),
        ('C_功率变化触发', False, True),
        ('D_两者都用', True, True),
    ]
    print('触发器门限：功率相对变化 > %.0f%%；事件重扫最小间隔 %.0f ms（均为本研究设定的策略参数，非器件额定值）\n'
          % (100 * a.drop, a.min_interval_ms))
    out = {}
    for name, ut, up in variants:
        eng = run(E, C, cfg, ids, ut, up, a.drop, mi, 'EVENT_RESCAN')
        per, summary = M.evaluate(eng.rows, eng.events, cfg, ref)
        ramp = sum(r['duration_us'] for r in eng.rows
                   if r['protection_state'] == 'RAMP_UP') / 1000
        scans = sum(1 for e in eng.events if e['event'] == 'SCAN_ATTEMPT_START')
        trig = sum(1 for e in eng.events if e['event'] == 'RESCAN_TRIGGER')
        pv = max(r['pre_guard_vport_Vpp'] for r in eng.rows)
        hv = sum(r['duration_us'] for r in eng.rows
                 if r.get('actual_hard_violation')) / 1000
        print('%-16s 达标段 %2d/12  能量 %6.2f%%  升幅 %5.0f ms  扫描 %2d  触发 %2d  '
              '扫描失败 %d  保护前峰值 %7.3f Vpp  硬越限 %.3f ms'
              % (name, summary['settled_segments'], summary['energy_capture_pct'],
                 ramp, scans, trig, summary['scan_failures'], pv, hv))
        out[name] = per

    print()
    print('每段首个合格样本时刻 (ms):')
    print('%-16s' % '' + ''.join('%7d' % i for i in range(12)))
    for name in out:
        print('%-16s' % name + ''.join(
            '      —' if r['first_qualified_sample_ms'] is None
            else '%7.0f' % r['first_qualified_sample_ms'] for r in out[name]))
    print('%-16s' % '场景' + ''.join('%7s' % c.replace('CASE_', '')[:6] for c in ids))
    print()
    print('每段能量捕获 (%):')
    print('%-16s' % '' + ''.join('%7d' % i for i in range(12)))
    for name in out:
        print('%-16s' % name + ''.join('%7.1f' % r['energy_capture_pct']
                                       for r in out[name]))


if __name__ == '__main__':
    main()
