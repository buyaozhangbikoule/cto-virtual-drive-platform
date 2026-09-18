"""One evaluator for all three strategies; no steady-state fallback samples."""
from __future__ import annotations
import math
import numpy as np
from models import model_v2_1 as model


def references(cfg: dict) -> dict:
    fs = np.arange(cfg['frequency_min_Hz'], cfg['frequency_max_Hz']+1,
                   cfg['reference_grid_step_Hz'], dtype=float)
    result = {}
    for case in model.all_scenarios():
        q = model.response(fs, case)
        def feasible(v, i):
            a = np.minimum.reduce([np.ones(len(fs)), v/q['vport_vpp'], i/q['iport_irms_A']])
            power = q['p_rm_W']*a*a
            idx = int(np.argmax(power))
            return dict(frequency_Hz=float(fs[idx]), power_W=float(power[idx]), amplitude=float(a[idx]))
        result[case.case_id] = dict(policy=feasible(cfg['voltage_soft_Vpp'],cfg['current_soft_Arms']),
                                    hard=feasible(cfg['voltage_hard_Vpp'],cfg['current_hard_Arms']))
    return result


def energy(rows: list[dict], start: int, end: int, refs: dict) -> tuple[float,float]:
    actual, optimal = 0., 0.
    for row in rows:
        dt = max(0, min(end,row['end_us'])-max(start,row['start_us']))/1e6
        actual += row['p_rm_W']*dt
        optimal += refs[row['case_id']]['policy']['power_W']*dt
    return actual, optimal


def count_events(events, start, end):
    counts = {}
    for e in events:
        if start <= e['time_us'] < end:
            counts[e['event']] = counts.get(e['event'],0)+1
    return counts


def evaluate(rows: list[dict], events: list[dict], cfg: dict, refs: dict) -> tuple[list[dict],dict]:
    if not rows:
        raise ValueError('No executed data')
    assert rows[0]['start_us'] == 0
    assert all(a['end_us']==b['start_us'] for a,b in zip(rows,rows[1:])), 'time gap/overlap'
    assert all(r['end_us']>r['start_us'] for r in rows)
    assert all(r['applied_amplitude']==r['protection_amplitude'] for r in rows)
    assert all(math.isfinite(r['p_rm_W']) for r in rows)
    full_end = rows[-1]['end_us']
    segment_metrics = []
    for segment in sorted({r['segment_index'] for r in rows}):
        rs = [r for r in rows if r['segment_index']==segment]
        start, end = segment*cfg['segment_us'], (segment+1)*cfg['segment_us']
        assert sum(r['duration_us'] for r in rs)==cfg['segment_us']
        ref = refs[rs[0]['case_id']]['policy']['power_W']
        run, max_run, confirmed, first_qualified = [], 0, None, None
        actual_violations = 0
        in_violation = False
        for r in rs:
            qualified = (r['kind']=='CONTROL' and r['protection_state']=='NORMAL' and
                         not r['frequency_frozen'] and r['measurement_valid'] and
                         r['end_us'] % cfg['control_tick_us']==0 and
                         r['action_end_us']==r['end_us'] and
                         r['p_rm_W']/ref>=cfg['capture_threshold'] and not r['actual_hard_violation'])
            if qualified:
                # Consecutive CONTROL samples on the common 20 ms lattice.
                # Short probes are not counted as extra samples; a missed tick
                # during a longer scan breaks the sequence. Sample acceptance
                # does not assert high power throughout the between-sample path.
                if run and r['end_us']-run[-1]['end_us'] != cfg['control_tick_us']:
                    run = []
                if first_qualified is None:
                    first_qualified = r['end_us']
                run.append(r)
                max_run = max(max_run,len(run))
                if len(run)==cfg['continuous_samples'] and confirmed is None:
                    confirmed = list(run)
            elif r['kind']=='CONTROL':
                run = []
            if r['actual_hard_violation'] and not in_violation:
                actual_violations += 1
            in_violation = r['actual_hard_violation']
        actual, optimal = energy(rs,start,end,refs)
        ta, to = energy(rs,max(start,end-cfg['tail_window_us']),end,refs)
        power_mean = actual/((end-start)/1e6)
        std = math.sqrt(sum((r['p_rm_W']-power_mean)**2*r['duration_us'] for r in rs)/(end-start))
        counts = count_events(events,start,end+1 if end==full_end else end)
        pre = [r for r in rs if r.get('pre_guard_sample_here',r['start_us']==r['action_start_us'])]
        pre_v = max([r['pre_guard_vport_Vpp'] for r in pre]+[0.])
        pre_i = max([r['pre_guard_iport_Arms'] for r in pre]+[0.])
        segment_metrics.append(dict(suite=rs[0]['suite'],strategy=rs[0]['strategy'],
            segment_index=segment,case_id=rs[0]['case_id'],start_s=start/1e6,end_s=end/1e6,
            settled=confirmed is not None, max_consecutive_qualified_samples=max_run,
            first_qualified_sample_ms=None if first_qualified is None else (first_qualified-start)/1000,
            recovery_enter_ms=None if confirmed is None else (confirmed[0]['end_us']-start)/1000,
            recovery_confirm_ms=None if confirmed is None else (confirmed[-1]['end_us']-start)/1000,
            steady_error_pct=None if confirmed is None else
                100*sum(abs(r['p_rm_W']/ref-1) for r in confirmed)/len(confirmed),
            steady_sample_source='NA_NOT_ACCEPTED' if confirmed is None else 'FIRST_CONFIRMED_10_CONTROL_SAMPLES',
            fixed_tail_error_pct=100*(1-ta/to), fixed_tail_duration_ms=min(end-start,cfg['tail_window_us'])/1000,
            energy_J=actual,policy_reference_energy_J=optimal,energy_capture_pct=100*actual/optimal,
            whole_segment_power_std_W=std,whole_segment_power_cv_pct=None if power_mean==0 else 100*std/power_mean,
            peak_power_overshoot_pct=max(0.,100*(max([r['p_rm_W'] for r in rs]+
                [r['pre_guard_p_rm_W'] for r in pre])/ref-1)),
            peak_voltage_Vpp=max(pre_v,max(r['vport_Vpp'] for r in rs)),
            peak_current_mArms=1000*max(pre_i,max(r['iport_Arms'] for r in rs)),
            peak_post_guard_and_hold_voltage_Vpp=max(r['vport_Vpp'] for r in rs),
            peak_post_guard_and_hold_current_mArms=1000*max(r['iport_Arms'] for r in rs),
            peak_pre_guard_voltage_Vpp=pre_v,peak_pre_guard_current_mArms=pre_i*1000,
            pre_guard_hard_observations=sum(r['observed_hold_hard'] for r in pre),
            max_gamma_proxy=max(r['gamma_proxy'] for r in rs),
            actual_hard_violation_episodes=actual_violations,
            actual_hard_violation_duration_ms=sum(r['duration_us'] for r in rs if r['actual_hard_violation'])/1000,
            protection_trigger_events=sum(counts.get(k,0) for k in ('OBSERVED_HARD_TRIP','SOFT_FOLDBACK_ENTER')),
            candidate_limit_enter_events=counts.get('CANDIDATE_LIMIT_ENTER',0),
            rejected_hard_candidate_actions=len({r['action_id'] for r in rs if r['candidate_hard_rejected']}),
            scan_attempts=counts.get('SCAN_ATTEMPT_START',0),scan_successes=counts.get('SCAN_SUCCESS',0),
            scan_failures=counts.get('SCAN_FAILURE',0),scan_exhaustions=counts.get('SCAN_RETRIES_EXHAUSTED',0),
            frequency_saturation_events=counts.get('FREQUENCY_SATURATION',0),
            phase_probe_failures=counts.get('PHASE_PROBE_FAILED',0),
            noncontrol_duration_ms=sum(r['duration_us'] for r in rs if r['kind']!='CONTROL')/1000))
    actual, optimal = energy(rows,0,full_end,refs)
    counts = count_events(events,0,full_end+1)  # include a scan truncated at final endpoint
    comparable = energy(rows,800000,min(full_end,6400000),refs) if full_end>=6400000 else (None,None)
    overall = dict(suite=rows[0]['suite'],strategy=rows[0]['strategy'],
                   duration_s=full_end/1e6,segments=len(segment_metrics),
                   settled_segments=sum(r['settled'] for r in segment_metrics),
                   energy_J=actual,policy_reference_energy_J=optimal,energy_capture_pct=100*actual/optimal,
                   energy_0p8_to_6p4_J=comparable[0],
                   energy_0p8_to_6p4_capture_pct=None if comparable[1] is None else 100*comparable[0]/comparable[1],
                   peak_voltage_Vpp=max(r['peak_voltage_Vpp'] for r in segment_metrics),
                   peak_current_mArms=max(r['peak_current_mArms'] for r in segment_metrics),
                   peak_post_guard_and_hold_voltage_Vpp=max(r['vport_Vpp'] for r in rows),
                   peak_post_guard_and_hold_current_mArms=max(r['iport_Arms'] for r in rows)*1000,
                   peak_pre_guard_voltage_Vpp=max(r['peak_pre_guard_voltage_Vpp'] for r in segment_metrics),
                   pre_guard_hard_observations=sum(r['pre_guard_hard_observations'] for r in segment_metrics),
                   actual_hard_violation_duration_ms=sum(r['duration_us'] for r in rows if r['actual_hard_violation'])/1000,
                   protection_trigger_events=sum(counts.get(k,0) for k in ('OBSERVED_HARD_TRIP','SOFT_FOLDBACK_ENTER')),
                   scan_attempts=counts.get('SCAN_ATTEMPT_START',0),scan_failures=counts.get('SCAN_FAILURE',0),
                   scan_exhaustions=counts.get('SCAN_RETRIES_EXHAUSTED',0),
                   frequency_saturation_events=counts.get('FREQUENCY_SATURATION',0),
                   total_executed_actions=len({r['action_id'] for r in rows}),
                   logged_duration_s=sum(r['duration_us'] for r in rows)/1e6,
                   steady_error_aggregation='not_averaged_over_unaccepted_segments')
    return segment_metrics, overall
