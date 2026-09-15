"""Relocation checks; do not invoke LTspice or alter original evidence."""
from pathlib import Path
import hashlib, json, os, subprocess, sys, time
from datetime import datetime
from build_handoff import DEST,BUILD,sha

def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

def check_ui(root):
    import tempfile
    temp=BUILD/'ui_test_temp';temp.mkdir(exist_ok=True)
    tempfile.tempdir=str(temp)
    from streamlit.testing.v1 import AppTest
    platform=root/'working_qa/CTO_virtual_drive_platform_v2_1'
    os.chdir(platform)
    sys.path.insert(0,str(platform))
    app=AppTest.from_file(str(platform/'streamlit_app.py')).run(timeout=90)
    errors=[e.message for e in app.exception]
    result={'homepage_exceptions':errors,'homepage_metric_count':len(app.metric)}
    if errors:raise AssertionError(result)
    page=AppTest.from_file(str(platform/'pages/03_LTspice闭环验证.py')).run(timeout=60)
    result['feedback_page_exceptions']=[e.message for e in page.exception]
    assert not result['feedback_page_exceptions']
    button=[b for b in page.button if b.label=='查看历史5轮反馈示例（不启动求解）']
    assert len(button)==1
    button[0].click().run(timeout=60)
    result['five_round_readonly_exceptions']=[e.message for e in page.exception]
    result['five_round_metrics']=[{'label':m.label,'value':m.value} for m in page.metric]
    assert not result['five_round_readonly_exceptions']
    assert any(m['label']=='已完成真实反馈轮数' and m['value']=='5' for m in result['five_round_metrics'])
    result['scope']='Streamlit AppTest script checks only. No browser screenshot, no solver button clicked.'
    print(json.dumps(result,ensure_ascii=False))

def main():
    if len(sys.argv)>1 and sys.argv[1]=='ui':check_ui(DEST);return
    report={'tested_at':datetime.now().astimezone().isoformat(),'status':'IN_PROGRESS','checks':[],
      'limitations':['Not a fresh environment installation','No new LTspice solve','Not full control acceptance','Not PowerPoint GUI or browser screenshot QA','Historical paths retained in metadata']}
    env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',MPLCONFIGDIR=str(BUILD/'matplotlib_qa_cache'))
    def run(label,args,cwd=DEST,timeout=180):
        t=time.perf_counter();r=subprocess.run([sys.executable,'-B','-X','utf8',*map(str,args)],cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
        entry={'name':label,'return_code':r.returncode,'seconds':time.perf_counter()-t,'stdout':r.stdout,'stderr':r.stderr}
        report['checks'].append(entry);dump(DEST/'HANDOFF_CHECKS.json',report)
        print(label,r.returncode,flush=True)
        if r.returncode:raise RuntimeError(entry)
    run('relocated_snapshot_doctor',['handoff.py','doctor'])
    work=DEST/'working_qa'
    if not work.exists():run('working_copy_prepare',['handoff.py','prepare','--name','working_qa','--ltspice-exe','D:/LTspice.exe'])
    run('relocated_working_copy_doctor',['handoff.py','doctor','--name','working_qa'])
    pl=work/'CTO_virtual_drive_platform_v2_1'
    run('six_synthetic_unit_tests',['-m','unittest','discover','-s','tests','-p','test_ltspice_closed_loop.py','-v'],pl)
    run('pipeline_list',['run_all.py','--list'],pl)
    run('pipeline_dry_run_no_solver',['run_all.py','--dry-run','--no-collect'],pl)
    run('relocated_UI_script_readonly',[__file__,'ui'],timeout=180)
    src=DEST/'workspace'
    cl=src/'CTO_virtual_drive_platform_v2_1/results/ltspice_closed_loop/CL_20260914_124949_410d5f9d'
    session=json.loads((cl/'session.json').read_text(encoding='utf-8'))
    for i,r in enumerate(session['records']):
        step=cl/f'step_{i:03d}';ex=json.loads((step/'execution.json').read_text(encoding='utf-8'))
        for ext in ['cir','raw','log']:assert sha(step/f'circuit.{ext}')==ex[ext+'_sha256']
        if i:
            st=json.loads((step/'stimulus.json').read_text(encoding='utf-8'))
            assert st['parent_feedback_sha256']==sha(cl/f'step_{i-1:03d}/feedback.json')
            assert r['command']==session['records'][i-1]['next_command']
    rp=src/'ltspice_transient_replay_20260911_continue'
    ex=json.loads((rp/'PO_FS_M5_REPLAY_DT2NS_execution.json').read_text(encoding='utf-8'))
    for ext in ['cir','raw','log']:assert sha(rp/f'PO_FS_M5_REPLAY_DT2NS.{ext}')==ex[ext]['sha256']
    report['checks'].append({'name':'replay_and_five_round_original_hash_chain','passed':True,
       'scope':'Copied CIR/RAW/LOG match original receipts; causal handoffs match. No new solve.'})
    # Limited credential signature scan; never emit matching contents.
    import re
    pattern=re.compile(rb'(sk-[A-Za-z0-9_-]{24,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')
    hits=[]
    for p in src.rglob('*'):
        if p.is_file() and p.suffix.lower() in ['.py','.js','.mjs','.json','.yaml','.toml','.env'] and p.stat().st_size<2*1024*1024:
            if pattern.search(p.read_bytes()):hits.append(str(p.relative_to(DEST)))
    if hits:raise RuntimeError('Possible credential signature in '+repr(hits))
    report['checks'].append({'name':'limited_credential_signature_scan','matches':0,
       'scope':'Known token/private-key signatures in small code/config files. Not a guarantee of complete de-identification; historical usernames and local paths retained.'})
    report['status']='PASS_WITH_LIMITATIONS'
    dump(DEST/'HANDOFF_CHECKS.json',report)
    print('HANDOFF QA PASSED WITH DECLARED LIMITATIONS',flush=True)

if __name__=='__main__':main()
