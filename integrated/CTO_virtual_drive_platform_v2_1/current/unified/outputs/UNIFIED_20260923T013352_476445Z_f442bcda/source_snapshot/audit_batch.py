"""Read-only independent recomputation of saved execution logs (no metrics.evaluate).

Writes a NEW audit receipt outside the immutable batch. Model reconstruction is
the same analytic model, not an independent circuit solver / LTspice validation.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from models import model_v2_1 as model

ROOT = Path(__file__).resolve().parent


def read_csv(p):
    with p.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def audit(folder: Path):
    config = json.loads((folder/'configuration.json').read_text(encoding='utf-8'))
    refs = json.loads((folder/'reference_optima.json').read_text(encoding='utf-8'))
    schedules = json.loads((folder/'schedules.json').read_text(encoding='utf-8'))
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    problems = []
    for rel,h in manifest['files'].items():
        if hashlib.sha256((folder/rel).read_bytes()).hexdigest()!=h:
            problems.append('hash:'+rel)
    summaries = {(r['suite'],r['strategy']):r for r in read_csv(folder/'formal_three_strategy_summary.csv')}
    per = {(r['suite'],r['strategy'],int(r['segment_index'])):r for r in read_csv(folder/'per_segment_metrics.csv')}
    total_rows = total_actions = total_violating_rows = pre_guard_hard_observations = 0
    max_pre_guard_voltage = max_post_guard_voltage = 0.
    max_energy_error = max_voltage_error = max_current_error = max_power_error = 0.
    details = []
    for path in sorted((folder/'executions').glob('*.csv')):
        rows = read_csv(path)
        key = rows[0]['suite'],rows[0]['strategy']
        summary = summaries[key]
        total_rows += len(rows)
        total_actions += len({r['action_id'] for r in rows})
        total_violating_rows += sum(r['actual_hard_violation']=='True' for r in rows)
        pre_guard_hard_observations += sum(r['observed_hold_hard']=='True' and
            r['start_us']==r['action_start_us'] for r in rows)
        max_pre_guard_voltage=max(max_pre_guard_voltage,max(float(r['pre_guard_vport_Vpp']) for r in rows))
        max_post_guard_voltage=max(max_post_guard_voltage,max(float(r['vport_Vpp']) for r in rows))
        max_all_v=max(float(r['vport_Vpp']) for r in rows)
        max_all_v=max(max_all_v,max(float(r['pre_guard_vport_Vpp']) for r in rows))
        if abs(max_all_v-float(summary['peak_voltage_Vpp']))>1e-9:
            problems.append('peak_omits_pre_guard:'+path.name)
        durations = [int(r['end_us'])-int(r['start_us']) for r in rows]
        if any(d<=0 for d in durations) or int(rows[0]['start_us'])!=0:
            problems.append('duration:'+path.name)
        if any(a['end_us']!=b['start_us'] for a,b in zip(rows,rows[1:])):
            problems.append('gap:'+path.name)
        actual = sum(float(r['p_rm_W'])*d/1e6 for r,d in zip(rows,durations))
        max_energy_error = max(max_energy_error,abs(actual-float(summary['energy_J'])))
        if abs(actual-float(summary['energy_J']))>1e-12:
            problems.append('energy:'+path.name)
        for seg in schedules[key[0]]:
            sr = [r for r in rows if int(r['segment_index'])==seg['index']]
            if sum(int(r['duration_us']) for r in sr)!=seg['end_us']-seg['start_us']:
                problems.append('segment_duration:'+path.name)
            ref = refs[seg['case_id']]['policy']['power_W']
            control = [r for r in sr if r['kind']=='CONTROL' and r['end_us']==r['action_end_us']]
            sequence, previous, first_confirm = 0,None,None
            max_sequence = 0
            for r in control:
                t = int(r['end_us'])
                ok = (r['protection_state']=='NORMAL' and r['frequency_frozen']=='False' and
                      r['measurement_valid']=='True' and r['actual_hard_violation']=='False' and
                      t % config['control_tick_us']==0 and float(r['p_rm_W'])>=config['capture_threshold']*ref)
                sequence = (sequence+1 if previous is not None and t-previous==config['control_tick_us'] else 1) if ok else 0
                previous=t
                max_sequence=max(max_sequence,sequence)
                if sequence>=config['continuous_samples'] and first_confirm is None:
                    first_confirm=(t-seg['start_us'])/1000
            recorded = per[(key[0],key[1],seg['index'])]
            if (recorded['settled']=='True') != (first_confirm is not None) or int(recorded['max_consecutive_qualified_samples'])!=max_sequence:
                problems.append('settled:'+path.name+':'+str(seg['index']))
            if first_confirm is None and recorded['steady_error_pct']!='':
                problems.append('fallback:'+path.name+':'+str(seg['index']))
            if first_confirm is not None and abs(float(recorded['recovery_confirm_ms'])-first_confirm)>1e-9:
                problems.append('confirmation:'+path.name+':'+str(seg['index']))
        for case_id in {r['case_id'] for r in rows}:
            cr = [r for r in rows if r['case_id']==case_id]
            f = np.array([float(r['frequency_Hz']) for r in cr])
            a = np.array([float(r['applied_amplitude']) for r in cr])
            q = model.response(f,model.scenario_map()[case_id])
            for name,pred in [('vport_Vpp',q['vport_vpp']*a),('iport_Arms',q['iport_irms_A']*a),('p_rm_W',q['p_rm_W']*a*a)]:
                err = float(np.max(abs(np.array([float(r[name]) for r in cr])-pred)))
                if name=='vport_Vpp': max_voltage_error=max(max_voltage_error,err)
                elif name=='iport_Arms': max_current_error=max(max_current_error,err)
                else: max_power_error=max(max_power_error,err)
                if err>1e-9:
                    problems.append('response:'+path.name+':'+name)
            if any(r['applied_amplitude']!=r['protection_amplitude'] for r in cr):
                problems.append('actuator_state:'+path.name)
        details.append(dict(suite=key[0],strategy=key[1],rows=len(rows),energy_J_recomputed=actual))
    # Reference-grid discretization diagnostic only. Does NOT replace frozen
    # denominators or reclassify passes; 10 Hz is also a grid, not an exact bound.
    fine_check = []
    frequencies = np.arange(config['frequency_min_Hz'],config['frequency_max_Hz']+1,10.)
    for case in model.all_scenarios():
        q=model.response(frequencies,case)
        a=np.minimum.reduce([np.ones(len(frequencies)),config['voltage_soft_Vpp']/q['vport_vpp'],config['current_soft_Arms']/q['iport_irms_A']])
        p=q['p_rm_W']*a*a
        k=int(np.argmax(p))
        coarse=refs[case.case_id]['policy']['power_W']
        fine_check.append(dict(case_id=case.case_id,grid_100Hz_power_W=coarse,
            grid_10Hz_power_W=float(p[k]),grid_10Hz_frequency_Hz=float(frequencies[k]),
            relative_increase_pct=float(100*(p[k]/coarse-1))))
    receipt=dict(batch_id=folder.name,audit_pass=not problems,problems=problems,
        manifest_files_verified=len(manifest['files']),timelines=len(details),executed_rows=total_rows,
        executed_actions=total_actions,post_guard_hold_violation_rows=total_violating_rows,
        pre_guard_hard_observations=pre_guard_hard_observations,
        max_pre_guard_voltage_Vpp=max_pre_guard_voltage,max_post_guard_hold_voltage_Vpp=max_post_guard_voltage,
        max_energy_recompute_error_J=max_energy_error,max_voltage_recompute_error_Vpp=max_voltage_error,
        max_current_recompute_error_Arms=max_current_error,max_power_recompute_error_W=max_power_error,
        grid_reference_diagnostic_only=fine_check,timeline_recomputations=details,
        scope='saved-log, analytic-model and statistics audit; not independent LTspice/hardware proof')
    out=ROOT/'audits'
    out.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    dest=out/(folder.name+'_'+stamp+'.json')
    dest.write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('grid_reference_diagnostic_only','timeline_recomputations')},ensure_ascii=False,indent=2))
    print('AUDIT',dest)
    return not problems


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('batch',type=Path)
    raise SystemExit(0 if audit(p.parse_args().batch) else 1)
