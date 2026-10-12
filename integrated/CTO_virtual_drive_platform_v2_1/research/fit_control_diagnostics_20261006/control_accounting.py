"""Read-only duration/energy ledger for the registered unified batch.

This is NOT a controller change or a new simulation. Stage labels attribute
recorded intervals, not causal counterfactual savings. Detection latency is NA:
the official periodic controller has no separately logged disturbance detector.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, sys
from collections import defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from current.catalog import load_active, read_json, read_rows, sha

STAGES=['保护停机/保持/降额','保护预备降幅','升幅恢复','扫描/邻频试探',
        '失败重试/回退/锁存','连续确认样本','已确认后合格运行','尚未形成确认的合格样本',
        '普通控制未达标/调度等待（不可分辨）']

def typed_rows(path):
    def value(s):
        if s=='True': return True
        if s=='False': return False
        if s=='': return None
        try: return json.loads(s)
        except (ValueError,TypeError): return s
    return [{k:value(v) for k,v in r.items()} for r in read_rows(path)]

def qualified(r, cfg, power):
    return (r['kind']=='CONTROL' and r['protection_state']=='NORMAL'
            and not r['frequency_frozen'] and r['measurement_valid']
            and r['end_us']%cfg['control_tick_us']==0 and r['action_end_us']==r['end_us']
            and r['p_rm_W']/power>=cfg['capture_threshold'] and not r['actual_hard_violation'])

def confirmation(rows,cfg,power):
    run=[]; first=None; max_run=0; confirmed=[]
    for r in rows:
        if qualified(r,cfg,power):
            if run and r['end_us']-run[-1]['end_us']!=cfg['control_tick_us']:
                run=[]
            run.append(r)
            if first is None: first=r['end_us']
            max_run=max(max_run,len(run))
            if len(run)==cfg['continuous_samples'] and not confirmed:
                confirmed=run.copy()
        elif r['kind']=='CONTROL':
            run=[]
    return confirmed,max_run,first

def classify(r,cfg,power,confirmation_ids,confirmation_end):
    state=r['protection_state']; kind=r['kind']
    if state in ('HARD_TRIP','HOLD','FOLDBACK','DATA_INVALID'): return STAGES[0]
    if state=='PREPARE': return STAGES[1]
    if state=='RAMP_UP': return STAGES[2]
    if kind.startswith(('SCAN_','PHASE_PROBE_')): return STAGES[3]
    if kind.startswith('FAILED_SCAN_'): return STAGES[4]
    if kind!='CONTROL' or state!='NORMAL': raise ValueError(f'unclassified {kind}/{state}')
    if r['end_us'] in confirmation_ids: return STAGES[5]
    if qualified(r,cfg,power):
        return STAGES[6] if confirmation_end is not None and r['end_us']>confirmation_end else STAGES[7]
    return STAGES[8]

def empty_ledger():
    return dict(duration_us=0,energy_J=0.,reference_energy_J=0.,signed_deficit_J=0.,
                positive_deficit_J=0.,surplus_J=0.,rows=0)

def accumulate(total,r,ref):
    dt=r['duration_us']/1e6
    energy=r['p_rm_W']*dt; target=ref*dt
    total['duration_us']+=r['duration_us']; total['rows']+=1
    total['energy_J']+=energy; total['reference_energy_J']+=target
    total['signed_deficit_J']+=target-energy
    total['positive_deficit_J']+=max(0.,target-energy)
    total['surplus_J']+=max(0.,energy-target)

def assert_close(a,b,label):
    if not math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12):
        raise ValueError(f'{label}: {a} != {b}')

def analyze(rows, events, cfg, refs, saved_segments, saved_overall):
    if not rows or rows[0]['start_us']!=0: raise ValueError('missing start')
    if any(a['end_us']!=b['start_us'] for a,b in zip(rows,rows[1:])): raise ValueError('gap/overlap')
    for r in rows:
        if r['duration_us']!=r['end_us']-r['start_us'] or r['duration_us']<=0: raise ValueError('duration')
        if not math.isfinite(r['p_rm_W']): raise ValueError('invalid power')
        if r['applied_amplitude']!=r['protection_amplitude']: raise ValueError('amplitude mismatch')
    stages={k:empty_ledger() for k in STAGES}; cross=defaultdict(empty_ledger)
    segments=[]; labelled=[]
    for seg in sorted({r['segment_index'] for r in rows}):
        rs=[r for r in rows if r['segment_index']==seg]
        start=seg*cfg['segment_us']; end=start+cfg['segment_us']
        if rs[0]['start_us']!=start or rs[-1]['end_us']!=end: raise ValueError('segment boundary')
        ref=refs[rs[0]['case_id']]['policy']['power_W']
        confirmed,max_run,first=confirmation(rs,cfg,ref)
        ids={r['end_us'] for r in confirmed}; ce=confirmed[-1]['end_us'] if confirmed else None
        ledger={k:empty_ledger() for k in STAGES}
        for r in rs:
            stage=classify(r,cfg,ref,ids,ce)
            accumulate(ledger[stage],r,ref); accumulate(stages[stage],r,ref)
            accumulate(cross[r['kind']+' | '+r['protection_state']],r,ref)
            labelled.append(dict(segment_index=seg,action_id=r['action_id'],start_us=r['start_us'],end_us=r['end_us'],
                                 duration_us=r['duration_us'],kind=r['kind'],state=r['protection_state'],stage=stage,
                                 p_rm_W=r['p_rm_W'],reference_power_W=ref))
        saved=saved_segments[seg]
        assert bool(confirmed)==saved['settled']
        assert max_run==saved['max_consecutive_qualified_samples']
        assert sum(v['duration_us'] for v in ledger.values())==cfg['segment_us']
        for key in ('energy_J','policy_reference_energy_J'):
            src='reference_energy_J' if key.startswith('policy') else key
            assert_close(sum(v[src] for v in ledger.values()),saved[key],key)
        enter=(confirmed[0]['end_us']-start)/1000 if confirmed else None
        complete=(ce-start)/1000 if ce is not None else None
        assert enter==saved['recovery_enter_ms'] and complete==saved['recovery_confirm_ms']
        starts=[e['time_us'] for e in events if e['event']=='SCAN_ATTEMPT_START' and start<=e['time_us']<end]
        segments.append(dict(segment_index=seg,case_id=rs[0]['case_id'],settled=bool(confirmed),
                             max_consecutive_qualified_samples=max_run,
                             first_qualified_sample_ms=None if first is None else (first-start)/1000,
                             recovery_enter_ms=enter,recovery_confirm_ms=complete,
                             confirmation_sample_span_ms=None if ce is None else (ce-confirmed[0]['end_us'])/1000,
                             detection_wait_ms=None,
                             first_scan_after_segment_start_ms=None if not starts else (starts[0]-start)/1000,
                             stages=ledger))
    totals={key:sum(v[key] for v in stages.values()) for key in empty_ledger()}
    assert totals['duration_us']==rows[-1]['end_us']
    assert_close(totals['energy_J'],saved_overall['energy_J'],'overall energy')
    assert_close(totals['reference_energy_J'],saved_overall['policy_reference_energy_J'],'overall reference')
    assert sum(s['settled'] for s in segments)==saved_overall['settled_segments']
    return dict(suite=rows[0]['suite'],strategy=rows[0]['strategy'],totals=totals,stages=stages,
                cross_by_kind_state=dict(cross),segments=segments),labelled

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--all-suites',action='store_true')
    parser.add_argument('--output',type=Path,default=HERE/'output'/'control')
    args=parser.parse_args()
    ev=load_active(); folder=ev['folder']
    cfg=read_json(folder/'configuration.json'); refs=read_json(folder/'reference_optima.json')
    sm=typed_rows(folder/'per_segment_metrics.csv'); om=typed_rows(folder/'formal_three_strategy_summary.csv')
    args.output.mkdir(parents=True,exist_ok=True)
    manifest_before=sha(folder/'manifest.json')
    output={'batch_id':folder.name,'source_manifest_sha256':manifest_before,
            'method':'sample-hold integration of ALL logged rows; no new simulation',
            'detection_wait':'NA: no explicit detector timestamps; scan-start latency is not detector latency',
            'classification':'protection > prepare > ramp > scan/probe > failed-scan > confirmation/normal',
            'reports':[],'file_hashes':{}}
    for m in om:
        if not args.all_suites and m['suite']!='HISTORICAL_12': continue
        name=m['suite']+'_'+m['strategy']
        raw=folder/'executions'/f'{name}.csv'; event=folder/'events'/f'{name}.json'
        saved={r['segment_index']:r for r in sm if r['suite']==m['suite'] and r['strategy']==m['strategy']}
        report,ledger=analyze(typed_rows(raw),read_json(event),cfg,refs,saved,m)
        output['reports'].append(report)
        output['file_hashes'][str(raw.relative_to(ROOT))]=sha(raw)
        output['file_hashes'][str(event.relative_to(ROOT))]=sha(event)
        if m['suite']=='HISTORICAL_12':
            with (args.output/f'{name}_labelled.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(ledger[0])); w.writeheader(); w.writerows(ledger)
            print(name,report['totals'],flush=True)
    # Revalidate the registered evidence after analysis; output never lives in batch.
    load_active()
    output['source_unchanged']=manifest_before==sha(folder/'manifest.json')
    output['reconciled_timelines']=len(output['reports'])
    output['script_sha256']=sha(Path(__file__))
    (args.output/'results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('reconciled timelines:',len(output['reports']))

if __name__=='__main__': main()
