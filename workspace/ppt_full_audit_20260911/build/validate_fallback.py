"""Run the unmodified bundled validators in-process after Node spawn EPERM.
No validator is disabled; publication is a separate explicit invocation.
"""
from pathlib import Path
import runpy,sys,io,json,contextlib,hashlib
B=Path(__file__).resolve().parent;O=B.parent/'output'
S=Path('C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations/container_tools')
source=B.parents[1]/'project_audit_20260910/output/CTO组会汇报_计划书口径与验收缺口修订_2026-09-10.pptx'
p=B/'candidate.pptx'
def invoke(script,args,label):
    out=io.StringIO();err=io.StringIO();old=sys.argv;sys.argv=[str(S/script),*map(str,args)];code=0
    try:
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:runpy.run_path(str(S/script),run_name='__main__')
            except SystemExit as e:code=e.code or 0
    finally:sys.argv=old
    try:result=json.loads(out.getvalue())
    except ValueError:result={'stdout':out.getvalue()}
    data={'exit_code':code,'result':result,'stderr':err.getvalue()}
    (B/f'validation_{label}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(label,code,str(result)[:750]);assert code==0,label
    return data
reports={}
reports['reference_fonts']=invoke('inspect_presentation_layout_geometry.py',[source,'--inspect-font-families'],'reference_fonts')
reports['integrity']=invoke('inspect_presentation_package_integrity.py',[p,'--fail-on-findings'],'integrity')
reports['layout']=invoke('inspect_presentation_layout_geometry.py',[p,'--fail-on-findings','--expected-slide-count','28','--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--validate-bullet-geometry','--approved-font-family','Calibri',*[x for n in [6,7,15,19,20,21,22,24,26] for x in ['--require-native-table-slide',str(n)]]],'layout')
reports['chart_discovery']=invoke('native_quantitative_chart_gate.py',[p,'--discover-chart-slides'],'chart_discovery')
reports['chart_titles']=invoke('native_chart_title_gate.py',[p],'chart_titles')
reports['table_arithmetic']=invoke('native_table_arithmetic_gate.py',[p,'--fail-on-findings'],'table_arithmetic')
assert not reports['chart_discovery']['result']['chart_owner_slides'],'Chart validation needs explicit owner handling'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
receipt={'mode':'Fallback: unchanged bundled validators called with runpy, due Node spawnSync EPERM. Not a successful run of finalizePresentation.', 'new_simulation':False,'PowerPoint_GUI_verified':False,'candidate_sha256':sha(p),'source_sha256':sha(source),'reports':reports}
if '--publish' in sys.argv:
    final=O/'CTO组会汇报_全28页图文核查版_2026-09-11.pptx'
    with final.open('xb') as f:f.write(p.read_bytes())
    receipt.update(final_path=str(final),final_sha256=sha(final))
    assert receipt['final_sha256']==receipt['candidate_sha256']
(B/'fallback_validation_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
