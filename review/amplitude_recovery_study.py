"""Read-only: the three levers neither review/18 nor the 2026-10-13 exploration tested.

Established first (see audit_codex_oct13.py and the segment-7 trace):
  the protection's `f != old_f` branch sets amplitude = min(old_a, wanted) and
  so can never RAISE amplitude, while the phase loop changes frequency three
  times per 20 ms tick (two probes + the control action). Once the soft limit
  clamps the amplitude near the parallel resonance, nothing releases it.

  L1  DEADBAND   widen the deadband: the only existing release valve, because
                 an in-deadband tick skips the probes and holds the frequency.
  L2  HOLD       after a frequency change, stop probing until the amplitude has
                 stopped rising. Observable from consecutive CONTROL samples;
                 unlike recovery-priority gating it ramps at the NEW centre,
                 not at the stale one.
  L3  REFREEZE   scan to capture, refreeze the phase target from a measured
                 point at the locked frequency, then phase-hold -- run on a
                 scan clock that does not interrupt the recovery. The
                 exploration ran this on the ABSOLUTE clock only, whose own
                 action chain shows the rescan cutting full amplitude after
                 20 ms, so that negative result is confounded with the clock.

No variant reads a scenario ID, a segment boundary, the offline optimum table
or the acceptance counter.

Read-only by default. With --out <dir> it additionally writes the per-variant
execution tables, events and metrics into that directory, in the same CSV/JSON
shape run_unified.py uses, so a reviewer can diff them line by line against
their own batches. It never writes into workspace/ or any outputs/ tree.
"""
import argparse
import collections
import csv
import hashlib
import json
import math
import pathlib
import sys

import numpy as np

TRIP = ('HARD_TRIP', 'HOLD', 'FOLDBACK', 'DATA_INVALID', 'PREPARE')


def build(root):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import engine as E
    import controllers as C
    import metrics as M
    import models.model_v2_1 as model
    return E, C, M, model, json.loads((root / 'config.json').read_text())


def probe_update(E, C, io, m, target_phase, trusted, deadband):
    """The formal phase_update with the deadband as a parameter. Nothing else."""
    cfg = io.cfg
    if not C.valid_measurement(m) or m.state != 'NORMAL' or m.frozen:
        return trusted, False
    error = E.wrap_deg(target_phase - m.phase_input_deg)
    if abs(error) <= deadband:
        return trusted, False
    delta = cfg['phase_probe_offset_Hz']
    lo = max(cfg['frequency_min_Hz'], trusted - delta)
    hi = min(cfg['frequency_max_Hz'], trusted + delta)
    t0 = io.time
    left = io.execute(lo, m.amplitude, 'PHASE_PROBE_MINUS', cfg['scan_point_us'])
    ok_l = (io.time - t0 == cfg['scan_point_us'] and C.valid_measurement(left)
            and left.state == 'NORMAL' and not left.frozen
            and abs(left.frequency_Hz - lo) < 1e-7)
    t0 = io.time
    right = (io.execute(hi, m.amplitude, 'PHASE_PROBE_PLUS', cfg['scan_point_us'])
             if ok_l else None)
    ok_r = (io.time - t0 == cfg['scan_point_us'] and C.valid_measurement(right)
            and right.state == 'NORMAL' and not right.frozen
            and abs(right.frequency_Hz - hi) < 1e-7)
    if not ok_l or not ok_r or hi <= lo:
        io.event('PHASE_PROBE_FAILED')
        return trusted, True
    slope = E.wrap_deg(right.phase_input_deg - left.phase_input_deg) / (hi - lo)
    if not E.finite(slope) or abs(slope) < cfg['phase_slope_min_deg_per_Hz']:
        io.event('PHASE_SLOPE_UNRESOLVED')
        return trusted, True
    df = float(np.clip(cfg['phase_gain_Hz_per_deg'] * error * math.copysign(1, slope),
                       -cfg['phase_max_step_Hz'], cfg['phase_max_step_Hz']))
    cand = float(np.clip(trusted + df, cfg['frequency_min_Hz'],
                         cfg['frequency_max_Hz']))
    io.event('PHASE_UPDATE', measured_error_deg=error,
             measured_slope_deg_per_Hz=slope, proposed_frequency_Hz=cand)
    return cand, True


def run_phase(E, C, cfg, ids, deadband, hold, suite):
    """L1 / L2. hold=True suspends probing until the amplitude stops rising."""
    eng = E.Engine(cfg, ids, 'PHASE_FEEDBACK', suite)
    io = C.Executor(eng)
    tp = TARGET[0]
    target, last = float(cfg['initial_frequency_Hz']), None
    settling, a_prev = False, -1.0
    while not io.finished:
        if last is not None:
            may_probe = True
            if hold and settling:
                if (C.valid_measurement(last) and last.state == 'NORMAL'
                        and not last.frozen):
                    if last.amplitude > a_prev + 1e-12:
                        a_prev = last.amplitude      # still rising: keep holding
                        may_probe = False
                    else:
                        settling = False             # ramp finished
                        io.event('AMPLITUDE_SETTLED', applied_amplitude=last.amplitude)
                else:
                    may_probe = False                # guard busy: do not probe
            if may_probe:
                new, probed = probe_update(E, C, io, last, tp, target, deadband)
                if hold and probed and new != target:
                    settling, a_prev = True, -1.0
                target = new
        if not io.finished:
            last = io.control(target, 1.)
    return eng


def run_hybrid(E, C, cfg, ids, mode, hold, suite):
    """L3. Periodic scan for capture + phase hold on a refrozen target."""
    eng = E.Engine(cfg, ids, 'PHASE_FEEDBACK', suite)
    io = C.Executor(eng)
    period = cfg['scan_period_us']
    target = float(cfg['initial_frequency_Hz'])
    next_scan = period
    retry = C.ScanBudget(cfg)
    tp = None                      # no phase loop before the first capture
    last, failed = None, False
    settling, a_prev = False, -1.0
    while not io.finished:
        if retry.exhausted:
            io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_LATCHED_HOLD')
            continue
        if failed and not retry.can_start(io.time):
            last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_RETRY_WAIT')
            continue
        due = failed or (next_scan is not None and io.time >= next_scan)
        ready = (last is not None and C.valid_measurement(last)
                 and last.state == 'NORMAL' and not last.frozen)
        if due and ready and retry.can_start(io.time):
            retry.start(io.time)
            io.event('SCAN_ATTEMPT_START', attempt=retry.attempts,
                     trusted_frequency_Hz=target)
            res = C.scan(io, target)
            if res.ok:
                target = float(res.frequency_Hz)
                io.event('SCAN_SUCCESS', frequency_Hz=target, band_edge=res.band_edge)
                retry.success()
                failed = False
                # Refreeze the target from a measured point at the locked
                # frequency. One extra low-amplitude point, logged like any other.
                pt = io.point(target, cfg['scan_amplitude'], 'PHASE_TARGET_CAPTURE')
                if pt.ok:
                    tp = float(pt.measurement.phase_input_deg)
                    io.event('PHASE_TARGET_REFROZEN', target_deg=tp,
                             reference_frequency_Hz=target)
                settling, a_prev = True, -1.0
                next_scan = ((io.time // period + 1) * period if mode == 'ABSOLUTE'
                             else io.time + period)
            else:
                bc = retry.classify(res.status)
                if bc is None:
                    io.event('SCAN_TRUNCATED_BY_RUN_END', status=res.status)
                    continue
                retry.fail(bc, io.time)
                failed = True
                io.event('SCAN_FAILURE', status=res.status, budget_class=bc,
                         reason=res.reason, total_failures=retry.total_failures)
                if retry.exhausted:
                    io.event('SCAN_RETRIES_EXHAUSTED', budget_class=retry.exhausted_class)
                if not io.finished:
                    last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_ROLLBACK')
                continue
        if tp is not None and last is not None and not failed:
            may_probe = True
            if hold and settling:
                if (C.valid_measurement(last) and last.state == 'NORMAL'
                        and not last.frozen):
                    if last.amplitude > a_prev + 1e-12:
                        a_prev, may_probe = last.amplitude, False
                    else:
                        settling = False
                        io.event('AMPLITUDE_SETTLED', applied_amplitude=last.amplitude)
                else:
                    may_probe = False
            if may_probe:
                new, probed = probe_update(E, C, io, last, tp, target,
                                           cfg['phase_deadband_deg'])
                if hold and probed and new != target:
                    settling, a_prev = True, -1.0
                target = new
        if not io.finished:
            last = io.control(target, cfg['scan_amplitude'] if failed else 1.)
    return eng


TARGET = [None]      # the frozen phase target, set once in main()


SAFE_SLUG = str.maketrans({c: '_' for c in ' /\\:*?"<>|°+'})


def dump(out: pathlib.Path, name: str, eng, per, summary):
    """Same CSV/JSON shape as run_unified.py, for line-by-line comparison."""
    slug = name.translate(SAFE_SLUG)
    if eng.rows:
        with (out / f'{slug}_executions.csv').open(
                'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(eng.rows[0]))
            w.writeheader()
            w.writerows(eng.rows)
    (out / f'{slug}_events.json').write_text(
        json.dumps(eng.events, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8')
    return slug


def source_hashes(root: pathlib.Path) -> dict:
    """Prove which baseline was run: compare against the batch's run_metadata."""
    names = ('config.json', 'controllers.py', 'engine.py', 'metrics.py',
             'models/model_v2_1.py')
    out = {}
    for n in names:
        p = root / n
        if p.is_file():
            out[n] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def report(M, cfg, name, eng, ref, out=None, collected=None):
    per, s = M.evaluate(eng.rows, eng.events, cfg, ref)
    c = collections.Counter(e['event'] for e in eng.events)
    low = sum(r['duration_us'] for r in eng.rows
              if r['applied_amplitude'] < 0.999) / 1000
    pv = max(r['pre_guard_vport_Vpp'] for r in eng.rows)
    hv = sum(r['duration_us'] for r in eng.rows
             if r.get('actual_hard_violation')) / 1000
    print('%-26s 达标 %2d/12  能量 %6.2f%%  更新 %3d  探针失败 %2d  扫描 %2d  '
          '非满幅 %5.0f ms  峰值 %7.3f Vpp  硬越限 %.3f ms'
          % (name, s['settled_segments'], s['energy_capture_pct'],
             c['PHASE_UPDATE'], c['PHASE_PROBE_FAILED'],
             c['SCAN_ATTEMPT_START'], low, pv, hv))
    if out is not None:
        slug = dump(out, name, eng, per, s)
        row = dict(variant=name, variant_slug=slug,
                   settled_segments=s['settled_segments'],
                   energy_capture_pct=s['energy_capture_pct'],
                   phase_updates=c['PHASE_UPDATE'],
                   phase_probe_failed=c['PHASE_PROBE_FAILED'],
                   phase_slope_unresolved=c['PHASE_SLOPE_UNRESOLVED'],
                   scan_attempts=c['SCAN_ATTEMPT_START'],
                   scan_failures=s['scan_failures'],
                   below_full_amplitude_ms=low,
                   max_applied_amplitude=max(r['applied_amplitude']
                                             for r in eng.rows),
                   pre_guard_peak_vport_Vpp=pv,
                   actual_hard_violation_ms=hv)
        collected['overall'].append(row)
        for r in per:
            collected['per_segment'].append(dict(variant=name, **r))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', default=None,
                    help='optional directory for execution tables, events and '
                         'metrics; never workspace/ or an outputs/ tree')
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    out = None
    if a.out:
        out = pathlib.Path(a.out).resolve()
        parts = set(out.parts)
        if 'workspace' in parts or 'outputs' in parts:
            raise SystemExit('refusing to write into workspace/ or outputs/: %s' % out)
        out.mkdir(parents=True, exist_ok=True)
    collected = dict(overall=[], per_segment=[])
    E, C, M, model, cfg = build(root)
    ids = cfg['historical_schedule']
    ref = M.references(cfg)
    base = model.scenario_map()['CASE_000_BASELINE']
    TARGET[0] = float(model.response(cfg['initial_frequency_Hz'], base)['phase_deg'][0])

    print('基线死区 %.2f deg。第 7 段末尾可达相位误差 0.128361 deg，恰在死区外。\n'
          % cfg['phase_deadband_deg'])
    tables = {}
    tables['A 原样'] = report(M, cfg, 'A 原样 (死区 0.10°)',
                              run_phase(E, C, cfg, ids, 0.1, False, 'L0'), ref, out, collected)
    for db in (0.3, 1.0, 3.0):
        tables['死区 %.1f°' % db] = report(
            M, cfg, 'L1 死区 %.1f°' % db,
            run_phase(E, C, cfg, ids, db, False, 'L1'), ref, out, collected)
    tables['L2 升幅优先'] = report(
        M, cfg, 'L2 改频后等升幅停止', run_phase(E, C, cfg, ids, 0.1, True, 'L2'), ref, out, collected)
    tables['L2+死区1.0'] = report(
        M, cfg, 'L2 + 死区 1.0°', run_phase(E, C, cfg, ids, 1.0, True, 'L2b'), ref, out, collected)
    print()
    for mode in ('ABSOLUTE', 'SCAN_END'):
        for hold in (False, True):
            nm = 'L3 重冻结 %s%s' % (mode, ' + 等升幅' if hold else '')
            tables[nm] = report(M, cfg, nm,
                                run_hybrid(E, C, cfg, ids, mode, hold, 'L3'), ref, out, collected)
    print()
    print('每段能量捕获 (%):')
    print('%-26s' % '' + ''.join('%7d' % i for i in range(12)))
    for k, per in tables.items():
        print('%-26s' % k + ''.join('%7.1f' % r['energy_capture_pct'] for r in per))
    print('%-26s' % '场景' + ''.join('%7s' % c.replace('CASE_', '')[:6] for c in ids))
    print()
    print('第 7 段首个合格样本时刻 (ms) 与该段能量:')
    for k, per in tables.items():
        r = per[7]
        v = r['first_qualified_sample_ms']
        print('  %-26s %s  能量 %5.1f%%'
              % (k, '  未合格' if v is None else '%5.0f ms' % v,
                 r['energy_capture_pct']))


    if out is not None:
        for nm, rows in (('overall_metrics.csv', collected['overall']),
                         ('per_segment_metrics.csv', collected['per_segment'])):
            if rows:
                with (out / nm).open('w', encoding='utf-8-sig', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
        (out / 'configuration.json').write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2, allow_nan=False),
            encoding='utf-8')
        (out / 'provenance.json').write_text(json.dumps(dict(
            source_root=str(root),
            source_hashes=source_hashes(root),
            registered_batch_compared_against=
                'UNIFIED_20260923T013352_476445Z_f442bcda',
            registered_source_tree_sha256=
                'f442bcda10396bb29748a562b3c2a1953d0b6288a5972a8acdeb39317fef972b',
            schedule=ids,
            scorer='metrics.evaluate with metrics.references(cfg)',
            frozen_phase_target_deg=TARGET[0],
            reference_definition=
                'max over reference_grid_step_Hz of p_rm_W*a^2, '
                'a = min(1, voltage_soft_Vpp/vport_vpp, current_soft_Arms/iport_irms_A)',
            note='A variant must reproduce 6/12 and 57.34% or nothing here is evidence',
            python=sys.version, numpy=np.__version__,
        ), ensure_ascii=False, indent=2), encoding='utf-8')
        print()
        print('已写入 %s' % out)


if __name__ == '__main__':
    main()
