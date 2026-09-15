"""Unchanged bundled validators; in-process fallback when Node spawn is blocked."""
from pathlib import Path
import contextlib,hashlib,io,json,runpy,sys
B=Path(__file__).resolve().parent
S=Path('C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations/container_tools')
P=B/'full_candidate.pptx'
def run(script,args,label):
    old=sys.argv;sys.argv=[str(S/script),*map(str,args)];out=io.StringIO();err=io.StringIO();code=0
    try:
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:runpy.run_path(str(S/script),run_name='__main__')
            except SystemExit as e:code=e.code or 0
    finally:sys.argv=old
    try:result=json.loads(out.getvalue())
    except ValueError:result={'stdout':out.getvalue()}
    (B/f'qa_{label}.json').write_text(json.dumps({'exit_code':code,'result':result,'stderr':err.getvalue()},ensure_ascii=False,indent=2),encoding='utf-8')
    print(label,code,str(result)[:1000]);assert code==0,label
run('inspect_presentation_package_integrity.py',[P,'--fail-on-findings'],'integrity')
run('inspect_presentation_layout_geometry.py',[P,'--fail-on-findings','--expected-slide-count','32','--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--validate-bullet-geometry','--approved-font-family','Calibri',*[v for n in [17,18,21,26,31] for v in ['--require-native-table-slide',str(n)]]],'layout')
run('native_quantitative_chart_gate.py',[P,'--discover-chart-slides'],'charts')
run('native_chart_title_gate.py',[P],'titles')
run('native_table_arithmetic_gate.py',[P,'--fail-on-findings'],'arithmetic')
if '--publish' in sys.argv:
    target=B.parent/'output/CTO组会汇报_成果补全32页_2026-09-15.pptx'
    if target.exists():assert target.read_bytes()==P.read_bytes()
    else:
        with target.open('xb') as f:f.write(P.read_bytes())
    print('Published',target,hashlib.sha256(target.read_bytes()).hexdigest())
