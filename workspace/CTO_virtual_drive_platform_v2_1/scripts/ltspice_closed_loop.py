"""Offline causal feedback via real LTspice transient solves; no analytic oracle.

Each iteration recomputes and saves the complete command prefix from the same
initial state. Only the latest interval drives feedback. No .loadbias approximation.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
import hashlib, importlib.util, json, math, os, re, shutil, subprocess, sys, time, uuid
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/ltspice_closed_loop'
MODEL = ROOT.parent / 'outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py'
LIMITS = dict(f_min=800000., f_max=1000000., v_soft=130., v_hard=160., i_soft=.0055, i_hard=.006)
trap = getattr(np, 'trapezoid', None) or np.trapz

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def dump(path, obj):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(tmp,path)

def load(path): return json.loads(Path(path).read_text(encoding='utf-8'))

def plant(case_id):
    spec=importlib.util.spec_from_file_location('closed_loop_plant_registry',MODEL)
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
    case=mod.scenario_map()[case_id]
    return dict(case=asdict(case), source_vrms=mod.SOURCE_A1_VRMS, reference_hz=mod.F0,
                registry_sha256=sha(MODEL), source_type='假设基线值 / 扫描变量；非实测')

def create_session(*, case_id='CASE_000_BASELINE', frequency_hz=899000., amplitude=.4,
                   amplitude_target=.4, period_s=.002, step_hz=500., executable='D:/LTspice.exe',
                   max_steps=12, output_root=OUT):
    vals=[frequency_hz,amplitude,amplitude_target,period_s,step_hz,max_steps]
    if not all(math.isfinite(float(v)) for v in vals):raise ValueError('参数必须是有限数')
    if not 8e5<=frequency_hz<=1e6 or not 0<=amplitude<=amplitude_target<=1:raise ValueError('频率/幅度超范围')
    if not .001<=period_s<=.02 or not 100<=step_hz<=2000 or not 1<=max_steps<=30:raise ValueError('周期/步长/轮数超范围')
    exe=Path(executable).resolve()
    if not exe.is_file() or exe.name.lower()!='ltspice.exe':raise ValueError('请选择本机LTspice.exe')
    p=Path(output_root)/('CL_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]);p.mkdir(parents=True)
    cfg=dict(schema=1,mode='OFFLINE_CAUSAL_LTSPICE_FEEDBACK',plant=plant(case_id),executable=str(exe),
             period_s=period_s,tail_window_s=.0002,protection_window_s=.00005,warmup_s=.003,
             max_step_s=2e-9,command_edge_s=1e-9,step_hz=step_hz,amplitude_target=amplitude_target,
             amplitude_increment=.05,hold_steps=2,power_deadband=.002,max_steps=int(max_steps),limits=LIMITS,
             state_continuity='full-prefix recomputation from the same zero operating point',
             controller_source_sha256=sha(__file__),assumptions='所有新增控制参数为假设值；离线、固定负载、非原20ms正式验收',
             limitations=['No real-time hardware','No dynamic load switch','No intersample safety guarantee',
                          'Local power search is not guaranteed to find global optimum','No formal three-strategy ranking'])
    dump(p/'config.json',cfg)
    dump(p/'session.json',dict(status='READY',next_command=dict(frequency_hz=frequency_hz,amplitude=amplitude),
         controller=dict(direction=1,previous=None,hold_left=0,trip=False),records=[]))
    return p

def netlist(cfg, commands):
    p=cfg['plant'];c=p['case'];b=c['bvd'];m=c['matching'];period=cfg['period_s'];warm=cfg['warmup_s']
    stop=warm+len(commands)*period;save_start=warm+(len(commands)-1)*period
    phases=[(0.,0.)];amps=[(0.,commands[0]['amplitude'])];freqs=[(0.,commands[0]['frequency_hz']/1e6)]
    last_t=0.;cycles=0.;last_f=commands[0]['frequency_hz'];last_a=commands[0]['amplitude']
    for k,cmd in enumerate(commands[1:],1):
        t=warm+k*period;cycles+=(t-last_t)*last_f;phases.append((t,cycles))
        if cmd['amplitude']!=last_a:amps.extend([(t,last_a),(t+cfg['command_edge_s'],cmd['amplitude'])])
        if cmd['frequency_hz']!=last_f:freqs.extend([(t-cfg['command_edge_s'],last_f/1e6),(t,cmd['frequency_hz']/1e6)])
        last_t=t;last_f=cmd['frequency_hz'];last_a=cmd['amplitude']
    phases.append((stop,cycles+(stop-last_t)*last_f));amps.append((stop,last_a));freqs.append((stop,last_f/1e6))
    def pwl(name,node,points):return f'{name} {node} 0 PWL(\n'+'\n'.join(f'+ {t:.16g} {v:.16g}' for t,v in points)+'\n+ )\n'
    net='* OFFLINE CAUSAL FEEDBACK; hypothetical BVD, not hardware.\n'
    net+=pwl('Vphase','cycles',phases)+pwl('Va','a_cmd',amps)+pwl('Vf','f_mhz',freqs)
    rl=2*math.pi*p['reference_hz']*m['l_h']/m['ql'];rc=1/(2*math.pi*p['reference_hz']*m['c_f']*m['qc'])
    net+=f'''Bdrive n_src 0 V={math.sqrt(2)*p['source_vrms']:.17g}*V(a_cmd)*sin(2*pi*V(cycles))
Rsource n_src n_in {c['rs']:.17g}
Rlesr n_in n_l {rl:.17g}
Lmatch n_l n_port {m['l_h']:.17g} Rser=0
Cmatch n_port n_c {m['c_f']:.17g}
Rcesr n_c 0 {rc:.17g}
Vprobe n_port n_bvd 0
C0 n_bvd 0 {b['c0']:.17g}
Rm n_bvd n_m1 {b['rm']:.17g}
Lm n_m1 n_m2 {b['lm']:.17g} Rser=0
Cm n_m2 0 {b['cm']:.17g}
.options plotwinsize=0 reltol=0.0001 abstol=1p vntol=0.1u
.save V(n_port) I(Vprobe) I(Rm) V(a_cmd) V(f_mhz)
.tran 0 {stop:.16g} 0 {cfg['max_step_s']:.16g}
.meas tran tail_vpp PP V(n_port) FROM {stop-cfg['tail_window_s']:.16g} TO {stop:.16g}
.meas tran tail_irms RMS I(Vprobe) FROM {stop-cfg['tail_window_s']:.16g} TO {stop:.16g}
.meas tran tail_port_power AVG (V(n_port)*I(Vprobe)) FROM {stop-cfg['tail_window_s']:.16g} TO {stop:.16g}
.end
'''
    return net,save_start,stop

def read_raw(path):
    with Path(path).open('rb') as f:head=f.read(65536)
    mark='Binary:\n'.encode('utf-16-le');pos=head.index(mark);header=head[:pos].decode('utf-16-le')
    nv=int(re.search(r'No\. Variables:\s*(\d+)',header)[1]);n=int(re.search(r'No\. Points:\s*(\d+)',header)[1])
    flags=re.search(r'Flags:\s*(.*)',header)[1]
    if 'real' not in flags or 'fastaccess' in flags:raise ValueError('需要未转换的real瞬态RAW')
    names=[m[2].lower() for m in re.finditer(r'^\s*(\d+)\s+(\S+)\s+\S+',header.split('Variables:\n')[1],re.M)]
    off=pos+len(mark);size=Path(path).stat().st_size-off
    dtype=np.dtype([('time','<f8')]+[(str(i),'<f8' if size==n*nv*8 else '<f4') for i in range(1,nv)])
    if n<10 or size!=n*dtype.itemsize:raise ValueError('RAW不完整')
    mm=np.memmap(path,dtype=dtype,mode='r',offset=off,shape=(n,))
    result={name:mm['time' if i==0 else str(i)] for i,name in enumerate(names)}
    offset_match=re.search(r'^Offset:\s*(\S+)',header,re.M)
    time_offset=float(offset_match[1]) if offset_match else 0.
    if time_offset:result['time']=np.asarray(result['time'])+time_offset
    return result

def measure(raw_path,cfg,cmd,start,stop):
    raw=read_raw(raw_path);t=raw['time']
    if t[-1]<stop-cfg['max_step_s']*4 or t[0]>start+cfg['max_step_s']*4:raise ValueError('RAW未覆盖要求区间')
    def segment(lo,hi):
        a=max(0,np.searchsorted(t,lo)-1);z=min(len(t),np.searchsorted(t,hi,side='right')+1)
        tx=np.asarray(t[a:z]);lo=max(lo,float(tx[0]));hi=min(hi,float(tx[-1]));inside=(tx>lo)&(tx<hi)
        tt=np.r_[lo,tx[inside],hi]
        data={}
        for name in ['v(n_port)','i(vprobe)','i(rm)']:
            v=np.asarray(raw[name][a:z],dtype=float);data[name]=np.r_[np.interp(lo,tx,v),v[inside],np.interp(hi,tx,v)]
        return tt,data
    def stats(tt,d):
        v=d['v(n_port)'];i=d['i(vprobe)'];dt=tt[-1]-tt[0]
        return float(np.ptp(v)),math.sqrt(float(trap(i*i,tt)/dt)),float(trap(v*i,tt)/dt)
    tt,d=segment(stop-cfg['tail_window_s'],stop);vpp,irms,power=stats(tt,d)
    v=d['v(n_port)'];i=d['i(vprobe)'];x=2*np.pi*cmd['frequency_hz']*(tt-tt[0])
    basis=np.column_stack([np.cos(x),np.sin(x),np.ones_like(x)])
    vc=np.linalg.lstsq(basis,v,rcond=None)[0];ic=np.linalg.lstsq(basis,i,rcond=None)[0]
    vp=complex(vc[0],-vc[1]);ip=complex(ic[0],-ic[1])
    phase=float(np.angle(vp/ip,deg=True)) if abs(ip)>1e-12 and abs(vp)>1e-9 else None
    windows=[];edges=np.linspace(start,stop,int(round((stop-start)/cfg['protection_window_s']))+1)
    for lo,hi in zip(edges[:-1],edges[1:]):
        wt,wd=segment(lo,hi);vv,ii,pp=stats(wt,wd)
        windows.append(dict(time_s=float((lo+hi)/2),vpp=vv,irms_A=ii,p_port_W=pp))
    result=dict(vpp=vpp,irms_A=irms,p_port_W=power,phase_port_deg=phase,
        p_rm_W=float(trap(d['i(rm)']**2*cfg['plant']['case']['bvd']['rm'],tt)/(tt[-1]-tt[0])),
        max_window_vpp=max(r['vpp'] for r in windows),max_window_irms_A=max(r['irms_A'] for r in windows),
        tail_window_s=cfg['tail_window_s'],protection_window_s=cfg['protection_window_s'],raw_points=len(t))
    if not all(math.isfinite(result[k]) for k in ['vpp','irms_A','p_port_W','max_window_vpp','max_window_irms_A']):raise ValueError('测量含非有限数')
    return result,windows

def decide(cfg,state,cmd,m):
    """Only measured feedback and past controller state; no plant/optimum inputs."""
    s=dict(state);n=dict(cmd);lim=cfg['limits'];v=m['max_window_vpp'];i=m['max_window_irms_A']
    if s['trip']:
        n['amplitude']=0.;return n,s,'HALTED','已执行零幅指令；硬停机锁存',False
    if v>=lim['v_hard'] or i>=lim['i_hard']:
        n['amplitude']=0.;s.update(trip=True,previous=None)
        return n,s,'TRIP_TO_ZERO','本轮已检测越限，下一轮执行零幅；不能撤销此前越限',False
    if v>lim['v_soft'] or i>lim['i_soft']:
        n['amplitude']=cmd['amplitude']*min(.9,.95*lim['v_soft']/max(v,1e-12),.95*lim['i_soft']/max(i,1e-12))
        s.update(previous=None,hold_left=cfg['hold_steps'])
        return n,s,'FOLDBACK','软阈值触发：冻结频率，只降幅',False
    if s['hold_left']>0:
        s['hold_left']-=1;return n,s,'HOLD','保持当前频率及降额幅度，确认安全',False
    if cmd['amplitude']<cfg['amplitude_target']-1e-9:
        n['amplitude']=min(cfg['amplitude_target'],cmd['amplitude']+cfg['amplitude_increment']);s['previous']=None
        return n,s,'RAMP_UP','冻结频率，只逐步恢复幅度',False
    if cmd['amplitude']<=1e-6:return n,s,'HOLD','幅度为零，不进行功率搜索',False
    normalized=m['p_port_W']/cmd['amplitude']**2;prev=s['previous']
    reason='建立RAW虚拟测量功率参考，试探下一频点'
    if prev is not None and normalized<prev*(1-cfg['power_deadband']):
        s['direction']*=-1;reason='RAW测得归一化端口功率下降：反转搜索方向'
    elif prev is not None:reason='RAW测得功率未显著下降：保持搜索方向'
    proposed=cmd['frequency_hz']+s['direction']*cfg['step_hz']
    saturated=not lim['f_min']<=proposed<=lim['f_max']
    if saturated:
        s['direction']*=-1;proposed=cmd['frequency_hz']+s['direction']*cfg['step_hz'];reason+='；边界反向'
    n['frequency_hz']=float(np.clip(proposed,lim['f_min'],lim['f_max']));s['previous']=normalized
    return n,s,'TRACK',reason,saturated

def run_step(directory,timeout_s=300):
    p=Path(directory);lock=p/'running.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('该会话已有计算或残留锁；请检查进程，勿重复提交')
    os.close(fd)
    try:
        cfg=load(p/'config.json');s=load(p/'session.json')
        if s['status'] in ['ERROR','HALTED','COMPLETE']:raise RuntimeError('会话已终止，请新建会话')
        records=s['records'];k=len(records);cmd=s['next_command'];pending=records and records[-1]['state']=='TRIP_TO_ZERO'
        if k>=cfg['max_steps'] and not pending:raise RuntimeError('已达轮数上限')
        commands=[r['command'] for r in records]+[cmd];net,start,stop=netlist(cfg,commands)
        step=p/f'step_{k:03d}';step.mkdir(exist_ok=False)
        cir=step/'circuit.cir';cir.write_text(net,encoding='ascii')
        parent=sha(p/f'step_{k-1:03d}/feedback.json') if k else None
        dump(step/'stimulus.json',dict(commands=commands,parent_feedback_sha256=parent,save_interval_s=[start,stop]))
        receipt=dict(started_at=datetime.now().astimezone().isoformat(),command=[cfg['executable'],'-b',str(cir)],cir_sha256=sha(cir))
        t0=time.perf_counter()
        try:
            estimated=math.ceil(stop/cfg['max_step_s'])*28
            if shutil.disk_usage(p).free<estimated+1024**3:raise RuntimeError('可用磁盘空间不足以保存本轮完整RAW及1GB余量')
            proc=subprocess.run(receipt['command'],cwd=step,capture_output=True,timeout=timeout_s,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            receipt.update(return_code=proc.returncode,wall_seconds=time.perf_counter()-t0,
                           stdout=proc.stdout.decode(errors='replace'),stderr=proc.stderr.decode(errors='replace'))
            dump(step/'execution.json',receipt)
            if proc.returncode!=0:raise RuntimeError(f'LTspice返回码{proc.returncode}')
            raw=cir.with_suffix('.raw');m,windows=measure(raw,cfg,cmd,start,stop)
            receipt.update(raw_sha256=sha(raw),raw_bytes=raw.stat().st_size,log_sha256=sha(cir.with_suffix('.log')))
            dump(step/'execution.json',receipt);dump(step/'windows.json',windows)
            next_cmd,cs,status,why,sat=decide(cfg,s['controller'],cmd,m)
            assert next_cmd['amplitude']==cmd['amplitude'] or next_cmd['frequency_hz']==cmd['frequency_hz']
            r=dict(iteration=k,time_s=stop-cfg['warmup_s'],command=cmd,measurement=m,next_command=next_cmd,
                state=status,reason=why,frequency_saturated=sat,raw_sha256=receipt['raw_sha256'],wall_seconds=receipt['wall_seconds'])
            dump(step/'feedback.json',r);records.append(r)
            s.update(records=records,next_command=next_cmd,controller=cs,
                status='HALTED' if status=='HALTED' else ('COMPLETE' if len(records)>=cfg['max_steps'] and status!='TRIP_TO_ZERO' else 'READY'))
            dump(p/'session.json',s);return r
        except Exception as e:
            receipt.update(error=f'{type(e).__name__}: {e}',wall_seconds=time.perf_counter()-t0);dump(step/'execution.json',receipt)
            s.update(status='ERROR',error=str(e));dump(p/'session.json',s);raise
    finally:lock.unlink(missing_ok=True)
