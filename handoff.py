"""Portable handoff utilities. No solver is started by verify/doctor/prepare."""
from __future__ import annotations
import argparse, hashlib, importlib.metadata, importlib.util, json, math, os
from pathlib import Path
import re, shutil, subprocess, sys

ROOT = Path(__file__).resolve().parent
PLATFORM = 'CTO_virtual_drive_platform_v2_1'
MODEL_REL = 'outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py'
os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
sys.dont_write_bytecode = True

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(4*1024*1024), b''): h.update(b)
    return h.hexdigest()

def safe_rel(name):
    p = (ROOT/name).resolve()
    if not p.is_relative_to(ROOT.resolve()): raise ValueError('Path escapes handoff folder')
    return p

def verify(include_raw=False):
    entries = json.loads((ROOT/'FILE_MANIFEST.json').read_text(encoding='utf-8'))
    bad=[];missing_raw=0;count=0
    for r in entries:
        if r['archive']=='RAW' and not include_raw:
            if not safe_rel(r['path']).is_file():missing_raw+=1
            continue
        p=safe_rel(r['path'])
        if not p.is_file(): bad.append({'path':r['path'],'reason':'MISSING'});continue
        if p.stat().st_size!=r['bytes'] or sha(p)!=r['sha256']:
            bad.append({'path':r['path'],'reason':'HASH_OR_SIZE_MISMATCH'})
        count+=1
    out={'checked_files':count,'failures':bad,'raw_not_present_when_skipped':missing_raw,
         'mode':'ALL' if include_raw else 'MAIN_ONLY',
         'scope':'File integrity only, not scientific acceptance; manifest is unsigned.'}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 1 if bad else 0

def load_model(workspace):
    p=workspace/MODEL_REL
    spec=importlib.util.spec_from_file_location('handoff_verified_model',p)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    return m

def doctor(workspace):
    out={'python':sys.version,'workspace':str(workspace),'errors':[], 'warnings':[], 'packages':{}}
    for pkg in ['numpy','scipy','matplotlib','pandas','streamlit','pillow']:
        try:out['packages'][pkg]=importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:out['errors'].append('Missing '+pkg)
    config=json.loads((workspace/PLATFORM/'config.yaml').read_text(encoding='utf-8'))
    pl=workspace/PLATFORM
    out['pipeline_steps']=len(config['pipeline'])
    for step in config['pipeline']:
        for value in ([step['script']] if 'script' in step else [])+step.get('netlists',[]):
            if not (pl/value).resolve().is_file():out['errors'].append('Missing pipeline input '+value)
    exe=Path(config['runtime']['ltspice_executable'])
    out['configured_ltspice']=str(exe);out['ltspice_found']=exe.is_file()
    if not exe.is_file():out['warnings'].append('LTspice unavailable; analytic UI still usable. Configure a local executable before solver runs.')
    try:
        import numpy as np
        m=load_model(workspace);scenarios=m.all_scenarios();base=m.scenario_map()['CASE_000_BASELINE']
        r=m.response(900000.,base)
        out['analytic_baseline']={k:float(r[k][0]) for k in ['p_rm_W','p_source_W','p_port_W','vport_vpp','iport_irms_A','phase_deg']}
        for key,expected,tol in [('p_rm_W',.170,1e-5),('vport_vpp',100.,.02),('iport_irms_A',.005,2e-6)]:
            if abs(float(r[key][0])-expected)>tol:out['errors'].append('Baseline mismatch '+key)
        max_balance=0.
        for s in scenarios:
            rr=m.response(np.linspace(8e5,1e6,101),s)
            for k in ['p_rm_W','p_port_W','p_source_W','vport_vpp','iport_irms_A','phase_deg']:
                if not np.all(np.isfinite(rr[k])):out['errors'].append('Nonfinite '+s.case_id+' '+k)
            max_balance=max(max_balance,float(np.max(np.abs(rr['power_balance_error_W']))))
        out['scenarios_checked']=len(scenarios);out['max_balance_residual_W']=max_balance
        if max_balance>1e-9:out['errors'].append('Power balance residual exceeds diagnostic tolerance')
    except Exception as e:out['errors'].append(f'{type(e).__name__}: {e}')
    out['scope']='Relocation/environment + analytic smoke checks, NOT new LTspice simulation or control acceptance.'
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 1 if out['errors'] else 0

def work_path(name):
    if not re.fullmatch(r'working[A-Za-z0-9_-]*',name):raise ValueError('Use a name such as working or working_02')
    return ROOT/name

def prepare(name,exe):
    dest=work_path(name)
    if dest.exists():raise SystemExit('Refusing overwrite. Choose --name working_02 or use the existing copy.')
    if exe:
        exe=str(Path(exe).resolve())
        if not Path(exe).is_file():raise SystemExit('LTspice executable does not exist: '+exe)
    def ignore(folder,names):
        return [n for n in names if n in ['__pycache__','node_modules','.git'] or n.lower().endswith('.raw')]
    dest.mkdir()
    for rel in [PLATFORM,'outputs/v2_self_consistent_rebuild']:
        shutil.copytree(ROOT/'workspace'/rel,dest/rel,ignore=ignore)
    changes=[]
    if exe:
        p=dest/PLATFORM/'config.yaml';old=sha(p);cfg=json.loads(p.read_text(encoding='utf-8'))
        cfg['runtime']['ltspice_executable']=exe;p.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
        changes.append({'file':str(p.relative_to(dest)),'before_sha256':old,'after_sha256':sha(p),'reason':'Local LTspice executable only'})
        p=dest/'outputs/v2_self_consistent_rebuild/active_stage3_5/run_stage3_disturbance.py'
        old=sha(p);text=p.read_text(encoding='utf-8')
        lines=text.splitlines();matches=[i for i,l in enumerate(lines) if l.startswith('LTSPICE = Path(')]
        if len(matches)!=1:raise RuntimeError('Unexpected stage3 executable declaration; no silent rewrite')
        lines[matches[0]]='LTSPICE = Path('+repr(exe)+')'
        p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        changes.append({'file':str(p.relative_to(dest)),'before_sha256':old,'after_sha256':sha(p),'reason':'Replace historical D-drive executable only'})
        p=dest/PLATFORM/'pages/03_LTspice闭环验证.py';old=sha(p);text=p.read_text(encoding='utf-8')
        needle="value='D:/LTspice.exe'"
        if text.count(needle)!=1:raise RuntimeError('Unexpected UI executable default; no silent rewrite')
        p.write_text(text.replace(needle,'value='+repr(exe)),encoding='utf-8')
        changes.append({'file':str(p.relative_to(dest)),'before_sha256':old,'after_sha256':sha(p),'reason':'Local UI default only'})
    (dest/'PORTABILITY_CHANGES.json').write_text(json.dumps({'changes':changes,'raw_files_copied':False,
        'source_snapshot':'../workspace','note':'Original snapshot unchanged. Historical session metadata remains unchanged; do not resume old sessions.'},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Working copy ready:',dest)
    print('No solver started. Launch: python handoff.py launch --name '+name)

def launch(name,port):
    w=work_path(name);app=w/PLATFORM/'streamlit_app.py'
    if not app.is_file():raise SystemExit('First run: python handoff.py prepare [--ltspice-exe PATH]')
    cmd=[sys.executable,'-m','streamlit','run',str(app),'--server.address','127.0.0.1','--server.port',str(port),'--browser.gatherUsageStats','false']
    print('Open http://127.0.0.1:'+str(port)+' ; Ctrl+C to stop. No LTspice starts until you explicitly press its run button.',flush=True)
    return subprocess.call(cmd,cwd=app.parent)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    v=sub.add_parser('verify');v.add_argument('--include-raw',action='store_true')
    d=sub.add_parser('doctor');d.add_argument('--name',default=None)
    prep=sub.add_parser('prepare');prep.add_argument('--name',default='working');prep.add_argument('--ltspice-exe')
    l=sub.add_parser('launch');l.add_argument('--name',default='working');l.add_argument('--port',type=int,default=8501)
    a=p.parse_args()
    if a.command=='verify':return verify(a.include_raw)
    if a.command=='doctor':return doctor(work_path(a.name) if a.name else ROOT/'workspace')
    if a.command=='prepare':prepare(a.name,a.ltspice_exe);return 0
    if a.command=='launch':return launch(a.name,a.port)
if __name__=='__main__':raise SystemExit(main())
