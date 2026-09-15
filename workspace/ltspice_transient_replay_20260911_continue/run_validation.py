"""Actual LTspice transient checks and historical-command replay.

Hypothetical linear BVD only. No live controller in LTspice. Original evidence
is read-only. Every circuit and result is stored under this continuation folder.
"""
from pathlib import Path
import argparse,csv,datetime,hashlib,importlib.util,json,math,subprocess,sys,time
import numpy as np

D=Path(__file__).resolve().parent;R=D.parent
helper=R/'ltspice_transient_replay_20260911_side/run_replay.py'
spec=importlib.util.spec_from_file_location('previous_transient_helpers',helper)
old=importlib.util.module_from_spec(spec);sys.modules[spec.name]=old;spec.loader.exec_module(old)
model=old.model;cases=model.scenario_map();EXE=Path('D:/LTspice.exe')
SOURCE=R/'ppt_control_fix_20260906/build/data/stage4_control_timeline.csv'
sha=old.sha

def execute(name,net,timeout=1200):
    p=D/(name+'.cir')
    if p.exists():raise RuntimeError(f'Existing run will not be overwritten: {p}')
    p.write_text(net,encoding='ascii')
    started=datetime.datetime.now().astimezone().isoformat();t0=time.perf_counter()
    print('START '+name,flush=True)
    r=subprocess.run([str(EXE),'-b',str(p)],cwd=D,capture_output=True,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
    receipt={'command':[str(EXE),'-b',str(p)],'started_at':started,'finished_at':datetime.datetime.now().astimezone().isoformat(),'elapsed_seconds':time.perf_counter()-t0,'return_code':r.returncode,'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace')}
    for ext in ['cir','log','raw']:
        f=p.with_suffix('.'+ext)
        if f.is_file():receipt[ext]={'path':str(f),'bytes':f.stat().st_size,'sha256':sha(f)}
    (D/(name+'_execution.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print('FINISHED '+name+' '+json.dumps({'code':r.returncode,'seconds':receipt['elapsed_seconds']}),flush=True)
    if r.returncode or not p.with_suffix('.raw').exists():raise RuntimeError('LTspice run failed')
    return p

def measures(scenario,lo,hi):
    return f'''.meas tran port_vpp PP V(n_port) FROM {lo:.14g} TO {hi:.14g}
.meas tran port_irms RMS I(Vprobe) FROM {lo:.14g} TO {hi:.14g}
.meas tran motional_power AVG (I(Rm)*I(Rm)*{scenario.bvd.rm:.17g}) FROM {lo:.14g} TO {hi:.14g}
'''

def convergence():
    base=cases['CASE_000_BASELINE'];peak=math.sqrt(2)*model.SOURCE_A1_VRMS
    results=[]
    original=R/'ltspice_transient_replay_20260911_side/01_BASELINE_TRANSIENT.cir'
    prev=old.evaluate(original,base,900000,1,.0018,.002)
    results.append({'max_step_ns':50.,'file':str(original),'new_run':False,**prev})
    for ns in [10,5,2]:
        drive=f'Vdrive n_src 0 SINE(0 {peak:.17g} 900k)\nVa a_cmd 0 1\nVf f_MHz 0 0.9'
        net=old.circuit(base,drive)+f'.tran 0 2m 0 {ns}n\n'+measures(base,.0018,.002)+'.end\n'
        path=execute(f'BASELINE_DT_{ns}NS',net)
        metric=old.evaluate(path,base,900000,1,.0018,.002)
        results.append({'max_step_ns':float(ns),'file':str(path),'new_run':True,**metric})
        print(json.dumps(results[-1]),flush=True)
    passed=max(results[-1]['relative_error_percent'].values())<2
    data={'kind':'timestep convergence; actual LTspice transient versus Python sinusoidal steady state','original_failed_run_retained':str(original),'same_circuit_and_tolerances':True,'results':results,'finest_step_passes_2pct':passed,'new_simulation':True}
    (D/'baseline_convergence.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for r in results:
        rows.append({'max_step_ns':r['max_step_ns'],**r['LTspice_transient'],**{'error_'+k+'_percent':v for k,v in r['relative_error_percent'].items()}})
    with (D/'baseline_convergence.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    if not passed:raise RuntimeError('Baseline convergence not acceptable; replay not authorized by numerical gate')

def replay():
    check=json.loads((D/'baseline_convergence.json').read_text(encoding='utf-8'))
    assert check['finest_step_passes_2pct']
    # Full original dwell times retained for a bounded post-disturbance excerpt.
    start=2.838;end=3.059;warmup=.003;slew=1e-9
    with SOURCE.open(encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if r['strategy']=='P_AND_O' and float(r['time_s'])<end and float(r['time_s'])+float(r['duration_s'])>start+1e-10]
    assert rows and all(r['case_id']=='CASE_FS_M5' for r in rows)
    dt_ns=2
    # 2 ns independently passes the 2% analytic steady-state comparison.
    quality=next(x for x in check['results'] if x['max_step_ns']==dt_ns)
    assert max(quality['relative_error_percent'].values())<2
    transitions=[(0.,float(rows[0]['frequency_Hz']),float(rows[0]['amplitude_command']))]
    for r in rows:
        t=float(r['time_s'])-start+warmup
        if t>warmup+1e-10:transitions.append((t,float(r['frequency_Hz']),float(r['amplitude_command'])))
    stop=warmup+end-start;cycles=0.;last_t,last_f,last_a=transitions[0]
    phase=[(0.,0.)];amp=[(0.,last_a)];freq=[(0.,last_f/1e6)]
    for t,f,a in transitions[1:]:
        cycles+=(t-last_t)*last_f;phase.append((t,cycles))
        if a!=last_a:amp.extend([(t-slew,last_a),(t,a)])
        if f!=last_f:freq.extend([(t-slew,last_f/1e6),(t,f/1e6)])
        last_t,last_f,last_a=t,f,a
    phase.append((stop,cycles+(stop-last_t)*last_f));amp.append((stop,last_a));freq.append((stop,last_f/1e6))
    drive='\n'.join([old.pwl('Vphase','cycles',phase),old.pwl('Va','a_cmd',amp),old.pwl('Vf','f_MHz',freq),f'Bdrive n_src 0 V={math.sqrt(2)*model.SOURCE_A1_VRMS:.17g}*V(a_cmd)*sin(2*pi*V(cycles))'])
    dist=cases['CASE_FS_M5'];net=old.circuit(dist,drive)+f'.tran 0 {stop:.14g} 0 {dt_ns}n\n'+measures(dist,stop-.001,stop)+'.end\n'
    with (D/'replayed_original_rows.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    contract={'kind':'OPEN_LOOP_HISTORICAL_COMMAND_REPLAY','strategy':'P_AND_O','scenario':'CASE_FS_M5 fixed for entire run','original_time_range_s':[start,end],'warmup_s':warmup,'simulation_stop_s':stop,'source_phase':'continuous integral of held frequency','command_edge_s':slew,'max_step_ns':dt_ns,'source_sha256':sha(SOURCE),'source_file':str(SOURCE),'sample_rows':len(rows),'no_time_compression':True,'limitations':['Only one strategy excerpt, not all three curves','No live feedback from LTspice to Python controller','No load switch at original 2.4 s','No amplifier or hardware model','Command-edge time is numerical assumption'],'tail_command':{'frequency_Hz':last_f,'amplitude':last_a}}
    (D/'replay_contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
    path=execute('PO_FS_M5_REPLAY_DT2NS',net)
    tail=old.evaluate(path,dist,last_f,last_a,stop-.001,stop)
    (D/'replay_tail_check.json').write_text(json.dumps(tail,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TAIL '+json.dumps(tail),flush=True)

def spotchecks():
    """Independent finer-step checks at the baseline and final disturbed point."""
    out=[]
    for label,key,freq,ns in [('BASELINE','CASE_000_BASELINE',900000,1),('DIST_PEAK','CASE_FS_M5',854800,2),('DIST_PEAK','CASE_FS_M5',854800,1)]:
        scenario=cases[key]
        drive=f'Vdrive n_src 0 SINE(0 {math.sqrt(2)*model.SOURCE_A1_VRMS:.17g} {freq})\nVa a_cmd 0 1\nVf f_MHz 0 {freq/1e6}'
        net=old.circuit(scenario,drive)+f'.tran 0 3m 0 {ns}n\n'+measures(scenario,.0028,.003)+'.end\n'
        path=execute(f'{label}_CHECK_{ns}NS',net)
        metric=old.evaluate(path,scenario,freq,1,.0028,.003)
        out.append({'scenario':key,'max_step_ns':ns,'file':str(path),**metric})
        print(json.dumps(out[-1]),flush=True)
    (D/'finer_step_spotchecks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['convergence','replay','spotchecks']);a=ap.parse_args()
    {'convergence':convergence,'replay':replay,'spotchecks':spotchecks}[a.mode]()
