"""Isolated actual LTspice transient validation; not a closed-loop rerun.

Replay historical P&O f/a commands at original dwell times into the frozen
fs-5% BVD plant. No changes to audited project outputs. All model values are
hypothetical; this is not hardware, acoustic, or clinical evidence.
"""
from pathlib import Path
import csv, hashlib, importlib.util, json, math, re, subprocess, sys, time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EXE = Path('D:/LTspice.exe')
MODEL = ROOT / 'outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py'
TIMELINE = ROOT / 'ppt_control_fix_20260906/build/data/stage4_control_timeline.csv'
spec = importlib.util.spec_from_file_location('replay_original_model', MODEL)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def circuit(scenario, drive):
    b, m = scenario.bvd, scenario.matching
    rl = 2*math.pi*model.F0*m.l_h/m.ql
    rc = 1/(2*math.pi*model.F0*m.c_f*m.qc)
    return f'''* Actual LTspice transient; hypothetical linear BVD, not measured.
* Historical command replay is NOT a closed-loop controller implementation.
{drive}
Rsource n_src n_in {scenario.rs:.17g}
Rlesr n_in n_l {rl:.17g}
Lmatch n_l n_port {m.l_h:.17g} Rser=0
Cmatch n_port n_c {m.c_f:.17g}
Rcesr n_c 0 {rc:.17g}
Vprobe n_port n_bvd 0
C0 n_bvd 0 {b.c0:.17g}
Rm n_bvd n_m1 {b.rm:.17g}
Lm n_m1 n_m2 {b.lm:.17g} Rser=0
Cm n_m2 0 {b.cm:.17g}
.options plotwinsize=0 reltol=0.0001 abstol=1p vntol=0.1u
.save V(n_port) I(Vprobe) I(Rm) V(a_cmd) V(f_MHz)
'''

def run(name, net):
    path = HERE / (name+'.cir')
    if path.exists(): raise RuntimeError(f'Refusing to overwrite {path}')
    path.write_text(net, encoding='ascii')
    start=time.perf_counter()
    r=subprocess.run([str(EXE), '-b', str(path)], cwd=HERE, capture_output=True,
                     timeout=240, creationflags=subprocess.CREATE_NO_WINDOW)
    log=path.with_suffix('.log')
    record={'command':[str(EXE),'-b',str(path)],'returncode':r.returncode,
            'wall_seconds':time.perf_counter()-start,
            'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace')}
    (HERE/(name+'_execution.json')).write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record),flush=True)
    if r.returncode or not path.with_suffix('.raw').exists():
        raise RuntimeError(f'LTspice run failed; inspect {log}')
    return path

def read_real_raw(path):
    with path.open('rb') as f: head=f.read(65536)
    marker='Binary:\n'.encode('utf-16-le')
    k=head.index(marker); header=head[:k].decode('utf-16-le')
    nv=int(re.search(r'No\. Variables:\s*(\d+)',header).group(1))
    n=int(re.search(r'No\. Points:\s*(\d+)',header).group(1))
    names=[m.group(2).lower() for m in re.finditer(r'^\s*(\d+)\s+(\S+)\s+\S+',header.split('Variables:\n')[1],re.M)]
    flags=re.search(r'Flags:\s*(.*)',header).group(1)
    assert 'real' in flags and 'fastaccess' not in flags, flags
    offset=k+len(marker)
    dtype=np.dtype([('time','<f8')]+[(str(i),'<f4') for i in range(1,nv)])
    if path.stat().st_size-offset == n*nv*8:
        dtype=np.dtype([('time','<f8')]+[(str(i),'<f8') for i in range(1,nv)])
    assert path.stat().st_size-offset == n*dtype.itemsize
    values=np.memmap(path,dtype=dtype,mode='r',offset=offset,shape=(n,))
    return {name:values['time' if i==0 else str(i)] for i,name in enumerate(names)}

def evaluate(path, scenario, frequency, amplitude, lo, hi):
    d=read_real_raw(path.with_suffix('.raw'))
    t=np.asarray(d['time']); sel=(t>=lo)&(t<=hi)
    t=t[sel]; v=np.asarray(d['v(n_port)'][sel],dtype=float)
    i=np.asarray(d['i(vprobe)'][sel],dtype=float)
    im=np.asarray(d['i(rm)'][sel],dtype=float)
    integrate=getattr(np,'trapezoid',None) or np.trapz
    rms=math.sqrt(integrate(i*i,t)/(t[-1]-t[0]))
    p=integrate(im*im*scenario.bvd.rm,t)/(t[-1]-t[0])
    exact=model.response(frequency,scenario,amplitude)
    actual={'vport_vpp':float(v.max()-v.min()),'iport_irms_A':rms,'p_rm_W':p}
    return {'measurement_window_s':[lo,hi],'frequency_Hz':frequency,'amplitude':amplitude,
            'LTspice_transient':actual,
            'Python_steady_state':{key:float(exact[key][0]) for key in actual},
            'relative_error_percent':{key:100*abs(value-float(exact[key][0]))/abs(float(exact[key][0])) for key,value in actual.items()},
            'raw_points':len(d['time'])}

def pwl(name, node, pairs):
    # Continuations keep the generated netlist readable and reproducible.
    return f'{name} {node} 0 PWL(\n'+'\n'.join(f'+ {t:.14g} {v:.14g}' for t,v in pairs)+'\n+ )'

def main():
    scenarios=model.scenario_map()
    base=scenarios['CASE_000_BASELINE']; dist=scenarios['CASE_FS_M5']
    peak=math.sqrt(2)*model.SOURCE_A1_VRMS
    baseline=run('01_BASELINE_TRANSIENT',circuit(base,f'Vdrive n_src 0 SINE(0 {peak:.17g} 900k)\nVa a_cmd 0 1\nVf f_MHz 0 0.9')+'''.tran 0 2m 0 50n
.meas tran port_vpp PP V(n_port) FROM 1.8m TO 2m
.meas tran port_irms RMS I(Vprobe) FROM 1.8m TO 2m
.meas tran motional_power AVG (I(Rm)*I(Rm)*7352.941176470586) FROM 1.8m TO 2m
.end
''')
    baseline_metrics=evaluate(baseline,base,900000,1,.0018,.002)
    print('BASELINE_CHECK '+json.dumps(baseline_metrics),flush=True)
    if max(baseline_metrics['relative_error_percent'].values())>2:
        raise RuntimeError('Baseline transient did not pass 2% check; do not continue replay.')
    start=2.838; end=3.059; warmup=.003; slew=1e-9
    with TIMELINE.open(encoding='utf-8-sig',newline='') as f:
        all_rows=[r for r in csv.DictReader(f) if r['strategy']=='P_AND_O']
    rows=[r for r in all_rows if float(r['time_s'])<end and float(r['time_s'])+float(r['duration_s'])>start+1e-10]
    assert rows and all(r['case_id']=='CASE_FS_M5' for r in rows)
    transitions=[(0.,float(rows[0]['frequency_Hz']),float(rows[0]['amplitude_command']))]
    for r in rows:
        dt=float(r['time_s'])-start+warmup
        if dt>warmup+1e-10: transitions.append((dt,float(r['frequency_Hz']),float(r['amplitude_command'])))
    stop=warmup+end-start
    phase=[(0.,0.)]; amp=[(0.,transitions[0][2])]; freq=[(0.,transitions[0][1]/1e6)]
    cycles=0.; last_t,last_f,last_a=transitions[0]
    for t,f,a in transitions[1:]:
        cycles+=(t-last_t)*last_f; phase.append((t,cycles))
        if a!=last_a: amp.extend([(t-slew,last_a),(t,a)])
        if f!=last_f: freq.extend([(t-slew,last_f/1e6),(t,f/1e6)])
        last_t,last_f,last_a=t,f,a
    phase.append((stop,cycles+(stop-last_t)*last_f)); amp.append((stop,last_a)); freq.append((stop,last_f/1e6))
    drive='\n'.join([pwl('Vphase','cycles',phase),pwl('Va','a_cmd',amp),pwl('Vf','f_MHz',freq),
                     f'Bdrive n_src 0 V={peak:.17g}*V(a_cmd)*sin(2*pi*V(cycles))'])
    # Source phase is continuous; only its slope (frequency) changes.
    replay=run('02_PO_FS_M5_COMMAND_REPLAY',circuit(dist,drive)+f'''.tran 0 {stop:.14g} 0 50n
.meas tran tail_vpp PP V(n_port) FROM {stop-.001:.14g} TO {stop:.14g}
.meas tran tail_irms RMS I(Vprobe) FROM {stop-.001:.14g} TO {stop:.14g}
.meas tran tail_motional_power AVG (I(Rm)*I(Rm)*{dist.bvd.rm:.17g}) FROM {stop-.001:.14g} TO {stop:.14g}
.end
''')
    tail=evaluate(replay,dist,last_f,last_a,stop-.001,stop)
    with (HERE/'replayed_original_rows.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    audit={'scope':'Actual LTspice transient OPEN-LOOP command replay; NOT closed-loop validation',
           'model_values':'hypothetical, non-measured','strategy':'historical P_AND_O',
           'scenario':'CASE_FS_M5 held constant for the entire transient',
           'original_time_range_s':[start,end],'warmup_s':warmup,
           'time_mapping':'original_time_s = LTspice_time_s - 0.003 + 2.838 (after warmup)',
           'source_phase':'continuous; exact integral of held frequency commands',
           'amplitude_transition_s':slew,'amplitude_transition_source':'assumed numerical command edge; no amplifier model',
           'maximum_timestep_s':50e-9,'limits_not_tested':'No full strategy comparison, disturbance jump, feedback delay or hardware safety guarantee',
           'baseline':baseline_metrics,'replay_tail':tail,
           'inputs':{str(TIMELINE):sha(TIMELINE),str(MODEL):sha(MODEL)},
           'artifacts':{p.name:sha(p) for p in HERE.iterdir() if p.suffix in ('.cir','.raw','.log','.csv','.py')}}
    (HERE/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REPLAY_CHECK '+json.dumps(tail),flush=True)

if __name__=='__main__':main()
