"""Build a traceable, portable handoff; never modify original research files."""
from __future__ import annotations
import argparse, csv, hashlib, importlib.metadata, json, os, platform, re, shutil, sys, time, zipfile
from datetime import datetime
from pathlib import Path

BUILD=Path(__file__).resolve().parent
SRC=BUILD.parent
OUT=BUILD/'delivery'
NAME='CTO_Handoff_20260915'
DEST=OUT/NAME
T=BUILD/'templates'
SKIP_DIRS={'node_modules','__pycache__','.git','.venv','venv','pydeps','.pytest_cache','.mypy_cache',
           'tmp','temp','qa_temp','temp2','temp_montage','docx_temp','runtime_temp',
           'closed_loop_readiness_tmp','closed_loop_page_test_tmp','slides_test_temp'}
SKIP_SUFFIX={'.pyc','.pyo','.zip','.7z','.rar','.exe','.dll','.msi','.lock'}
RAW_CUTOFF=16*1024*1024

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def reparse(p):
    try:return p.is_symlink() or bool(getattr(p.lstat(),'st_file_attributes',0)&0x400)
    except OSError:return True

def stage():
    if (DEST/'SOURCE_MAP.json').exists():raise SystemExit('Refusing to overwrite completed staged handoff')
    DEST.mkdir(parents=True,exist_ok=True)
    exclusions=[];source_rows=[];count=0;start=time.time()
    def copy(p,rel):
        nonlocal count
        q=DEST/rel;q.parent.mkdir(parents=True,exist_ok=True)
        st=p.stat();h=hashlib.sha256()
        if q.exists():
            with p.open('rb') as f:
                for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
            if q.stat().st_size!=st.st_size or sha(q)!=h.hexdigest():raise RuntimeError('Interrupted staging copy differs: '+str(q))
        else:
            with p.open('rb') as f,q.open('xb') as g:
                for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b);g.write(b)
        if p.stat().st_size!=st.st_size or p.stat().st_mtime_ns!=st.st_mtime_ns:
            raise RuntimeError('Source changed during packaging: '+str(p))
        shutil.copystat(p,q)
        source_rows.append({'path':q.relative_to(DEST).as_posix(),'source':str(p),'bytes':st.st_size,
             'sha256':h.hexdigest(),'archive':'RAW' if p.suffix.lower()=='.raw' and st.st_size>RAW_CUTOFF else 'MAIN'})
        count+=1
        if count%300==0:print(f'Staged {count} files in {time.time()-start:.1f}s',flush=True)
    for top in sorted(SRC.iterdir()):
        if top==BUILD or top.name in ['tmp','.git','.codex','.agents'] or top.name.startswith('handoff_'):
            exclusions.append({'path':str(top.relative_to(SRC)),'reason':'packaging output / temp / tooling metadata'});continue
        if top.is_file():
            if top.suffix.lower() in ['.md','.pptx','.docx']:copy(top,Path('workspace')/top.name)
            else:exclusions.append({'path':top.name,'reason':'root duplicate archive / non-project executable'})
            continue
        if reparse(top):exclusions.append({'path':top.name,'reason':'external linked runtime'});continue
        def walk_error(e):raise e
        for folder,dirs,files in os.walk(top,topdown=True,followlinks=False,onerror=walk_error):
            here=Path(folder);keep=[]
            for n in dirs:
                p=here/n
                if n.lower() in SKIP_DIRS or n.lower().startswith(('soffice_','montage_convert_')) or reparse(p):
                    exclusions.append({'path':str(p.relative_to(SRC)),'reason':'cache / temporary directory / linked runtime'})
                else:keep.append(n)
            dirs[:]=keep
            for n in sorted(files):
                p=here/n;rel=p.relative_to(SRC)
                if p.suffix.lower() in SKIP_SUFFIX or n in ['.env','secrets.toml','Thumbs.db','.DS_Store'] or n.startswith('~$') or reparse(p):
                    exclusions.append({'path':str(rel),'reason':'duplicate archive / temporary / credential config / external link'})
                else:copy(p,Path('workspace')/rel)
    # User-provided plan and reference PDFs; byte-preserving copies, not edited.
    refroot=Path('D:/微信文件/WeChat Files/wxid_f86c1kdajuft12/FileStorage/File/2026-08')
    for n in ['CTO超声换能器虚拟阻抗建模与自适应驱动控制_第一月计划书.docx',
              'CTO超声换能器虚拟阻抗建模与自适应驱动控制_第一月计划书(1).docx',
              '前视超声治疗.pdf','High intensity focused ultrasound  Physical principles and devices.pdf']:
        p=refroot/n
        if not p.is_file():raise FileNotFoundError(p)
        copy(p,Path('reference')/n)
    report=SRC/'ppt_progress_complete_20260915/output'
    for n in ['CTO组会汇报_成果补全32页_2026-09-15.pptx','逐页讲稿_成果补全_2026-09-15.txt','汇报顺序与截图说明.md']:
        copy(report/n,Path('reports')/n)
    for p in T.iterdir():
        rel=Path('docs')/p.name if p.name.startswith(('01_','02_','03_')) else Path(p.name)
        copy(p,rel)
    env={'captured_at':datetime.now().astimezone().isoformat(),'python':sys.version,'executable':sys.executable,
         'platform':platform.platform(),'direct_dependencies':{p:importlib.metadata.version(p) for p in ['numpy','scipy','matplotlib','pandas','streamlit','pillow']},
         'license_transfer':False,'new_solver_runs_for_handoff':False,'not_included':['Python and Node runtimes','LTspice executable','ANSYS/COMSOL','accounts/licenses','caches and nested duplicate ZIPs'],
         'privacy':'Historical absolute paths retained for internal handoff; no secret credentials intentionally included.'}
    dump(DEST/'ENVIRONMENT_SOURCE.json',env)
    dump(DEST/'SOURCE_MAP.json',source_rows)
    dump(DEST/'EXCLUSIONS.json',exclusions)
    dump(BUILD/'stage_receipt.json',{'files':count,'bytes':sum(r['bytes'] for r in source_rows),
         'raw_archive_bytes':sum(r['bytes'] for r in source_rows if r['archive']=='RAW'),
         'raw_archive_files':sum(r['archive']=='RAW' for r in source_rows),'seconds':time.time()-start})
    print(json.dumps(json.loads((BUILD/'stage_receipt.json').read_text()),indent=2),flush=True)

def pack():
    if not (DEST/'HANDOFF_CHECKS.json').is_file():raise SystemExit('Run QA before packaging')
    checks=json.loads((DEST/'HANDOFF_CHECKS.json').read_text(encoding='utf-8'))
    if checks['status']!='PASS_WITH_LIMITATIONS':raise SystemExit('Handoff checks not passed')
    sources={r['path']:r for r in json.loads((DEST/'SOURCE_MAP.json').read_text(encoding='utf-8'))}
    rows=[]
    for p in sorted(DEST.rglob('*')):
        if not p.is_file() or p.name=='FILE_MANIFEST.json' or any(x.startswith('working') for x in p.relative_to(DEST).parts):continue
        rel=p.relative_to(DEST).as_posix()
        h=sha(p);src=sources.get(rel)
        if src and (h!=src['sha256'] or p.stat().st_size!=src['bytes']):raise RuntimeError('Snapshot changed: '+rel)
        rows.append({'path':rel,'bytes':p.stat().st_size,'sha256':h,'archive':src['archive'] if src else 'MAIN'})
    dump(DEST/'FILE_MANIFEST.json',rows)
    archives=[]
    for group,name in [('MAIN','01_项目主交接包.zip'),('RAW','02_大型RAW原始证据.zip')]:
        target=OUT/name
        if target.exists():raise SystemExit('Refusing to overwrite ZIP '+name)
        selected=[r for r in rows if r['archive']==group];start=time.time()
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
            if group=='MAIN':z.write(DEST/'FILE_MANIFEST.json',NAME+'/FILE_MANIFEST.json')
            for i,r in enumerate(selected):
                z.write(DEST/r['path'],NAME+'/'+r['path'])
                if i%400==0 or r['bytes']>100*1024*1024:print(f'Archive {group}: {i+1}/{len(selected)} {time.time()-start:.1f}s',flush=True)
        # Read every archived byte and compare SHA256, not just successful ZIP close.
        expected={NAME+'/'+r['path']:r for r in selected}
        if group=='MAIN':expected[NAME+'/FILE_MANIFEST.json']={'sha256':sha(DEST/'FILE_MANIFEST.json'),'bytes':(DEST/'FILE_MANIFEST.json').stat().st_size}
        with zipfile.ZipFile(target) as z:
            if set(z.namelist())!=set(expected):raise AssertionError('Archive entry mismatch')
            for n,ref in expected.items():
                h=hashlib.sha256();size=0
                with z.open(n) as f:
                    for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b);size+=len(b)
                if h.hexdigest()!=ref['sha256'] or size!=ref['bytes']:raise AssertionError('ZIP readback mismatch '+n)
        archives.append({'file':name,'bytes':target.stat().st_size,'sha256':sha(target),'files':len(expected),'all_entries_readback_sha256':'PASS'})
        print('Verified '+name,flush=True)
    receipt={'generated_at':datetime.now().astimezone().isoformat(),'archives':archives,
        'expanded_bytes':sum(r['bytes'] for r in rows),'total_payload_files':len(rows),
        'source_snapshot_unchanged':True,'no_new_LTspice_runs':True,
        'limitations':'Local relocation/analytic/UI-script checks only. Not all simulations rerun; not a fresh dependency installation on another PC.'}
    dump(OUT/'打包校验记录.json',receipt)
    (OUT/'SHA256SUMS.txt').write_text('\n'.join(a['sha256']+'  '+a['file'] for a in archives)+'\n',encoding='utf-8')
    (OUT/'交接包怎么用.txt').write_text('请将两个ZIP发送给接手人。解压到同一个父目录，合并为CTO_Handoff_20260915，不要嵌套两层。\n先读00_先读_项目交接说明.md，再安装依赖和运行handoff.py。\n主包含代码/配置/数据表/图/日志/小RAW/计划书/最新PPT/讲稿；大型RAW包不可遗漏，否则不是完整证据交接。\n不要在workspace历史快照中重跑；prepare会创建工作副本。\n软件安装程序、许可证、账号不在包内。\n已检查全部ZIP条目解压流SHA256；本次没有重新运行全套仿真。\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['stage','pack']);a=parser.parse_args()
    if a.action=='stage':stage()
    else:pack()
