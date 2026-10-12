"""Read-only prototype: does scanning BEFORE the amplitude ramp help?

The formal periodic policy commands full amplitude whenever it is not scanning.
After a disturbance the protection therefore ramps 0.25 -> 1.0 at the STALE
frequency (the scan cannot start, because the `ready` gate requires NORMAL and
RAMP_UP is frozen), then the scan drops to 0.4, then a second ramp 0.4 -> 1.0
runs. Variant B commands scan amplitude while a scan is pending, so the ramp to
full happens once, after the frequency is known.

Only the policy's requested amplitude while a scan is pending changes. The
protection object, the scan, the budget, the thresholds, the ramp rate, the
hold times, the segment length and the scorer are untouched. No variant reads a
scenario ID, a segment boundary or the offline optimum. Nothing is written.
"""
import argparse
import json
import math
import pathlib
import sys


def build(root):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import engine as E
    import controllers as C
    import metrics as M
    import models.model_v2_1 as model
    cfg = json.loads((root / 'config.json').read_text())
    return E, C, M, model, cfg


def run(E, C, cfg, ids, hold_low_while_pending: bool, suite: str):
    """Verbatim periodic policy, except for the pending-scan request amplitude."""
    eng = E.Engine(cfg, ids, 'PERIODIC_SCAN', suite)
    io = C.Executor(eng)
    target = float(cfg['initial_frequency_Hz'])
    next_scan = cfg['scan_period_us']
    retry = C.ScanBudget(cfg)
    last = None
    failed_episode = False
    while not io.finished:
        if retry.exhausted:
            io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_LATCHED_HOLD')
            continue
        if failed_episode and not retry.can_start(io.time):
            last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_RETRY_WAIT')
            continue
        scan_due = failed_episode or io.time >= next_scan
        ready = (last is not None and C.valid_measurement(last)
                 and last.state == 'NORMAL' and not last.frozen)
        if scan_due and ready and retry.can_start(io.time):
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
            if failed_episode:
                req = cfg['scan_amplitude']
            elif hold_low_while_pending and io.time >= next_scan:
                # A scan is already due but the guard has not released control.
                # Requesting full amplitude here would ramp at the stale
                # frequency and keep `ready` false for the whole ramp.
                req = cfg['scan_amplitude']
            else:
                req = 1.
            last = io.control(target, req)
    return eng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    E, C, M, model, cfg = build(root)
    ids = cfg['historical_schedule']
    ref = M.references(cfg)

    out = {}
    for name, low in (('A_原样', False), ('B_待扫描时保持低幅', True)):
        eng = run(E, C, cfg, ids, low, 'RAMP_ORDER')
        per, summary = M.evaluate(eng.rows, eng.events, cfg, ref)
        ramp_ms = sum(r['duration_us'] for r in eng.rows
                      if r['protection_state'] == 'RAMP_UP') / 1000
        trips = sum(1 for e in eng.events if e['event'] == 'OBSERVED_HARD_TRIP')
        scans = sum(1 for e in eng.events if e['event'] == 'SCAN_ATTEMPT_START')
        okscan = sum(1 for e in eng.events if e['event'] == 'SCAN_SUCCESS')
        print('%-16s 达标段 %2d/12  能量 %6.2f%%  升幅总时长 %6.0f ms  '
              '扫描 %2d(成功 %2d)  扫描失败 %d  硬跳闸 %2d'
              % (name, summary['settled_segments'], summary['energy_capture_pct'],
                 ramp_ms, scans, okscan, summary['scan_failures'], trips))
        out[name] = (per, eng)

    print()
    print('每段首个合格样本时刻 (ms):')
    print('%-16s' % '' + ''.join('%7d' % i for i in range(12)))
    for name in out:
        print('%-16s' % name + ''.join(
            '      —' if r['first_qualified_sample_ms'] is None
            else '%7.0f' % r['first_qualified_sample_ms'] for r in out[name][0]))
    print('%-16s' % '场景' + ''.join('%7s' % c.replace('CASE_', '')[:6] for c in ids))
    print()
    print('每段能量捕获 (%):')
    print('%-16s' % '' + ''.join('%7d' % i for i in range(12)))
    for name in out:
        print('%-16s' % name + ''.join('%7.1f' % r['energy_capture_pct']
                                       for r in out[name][0]))
    print()
    print('安全核对（必须不退步）：')
    for name in out:
        per, eng = out[name]
        pv = max(r['pre_guard_vport_Vpp'] for r in eng.rows)
        pi = max(r['pre_guard_iport_Arms'] for r in eng.rows)
        hv = sum(r['duration_us'] for r in eng.rows
                 if r.get('actual_hard_violation')) / 1000
        print('  %-16s 保护前预测峰值 %8.3f Vpp / %7.4f Arms；实际硬越限时长 %.3f ms'
              % (name, pv, pi, hv))


if __name__ == '__main__':
    main()
