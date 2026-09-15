"""Use the unchanged bundled validators in-process if Windows blocks Node spawn."""
from pathlib import Path
import contextlib
import hashlib
import io
import json
import runpy
import sys
import zipfile
import xml.etree.ElementTree as ET

B=Path(__file__).resolve().parent
O=B.parent/'output'
S=Path('C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations/container_tools')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def invoke(script,args,label):
    stdout,stderr=io.StringIO(),io.StringIO()
    previous=sys.argv;sys.argv=[str(S/script),*map(str,args)]
    code=0
    try:
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            try: runpy.run_path(str(S/script),run_name='__main__')
            except SystemExit as e: code=e.code or 0
    finally: sys.argv=previous
    try: value=json.loads(stdout.getvalue())
    except ValueError:value={'stdout':stdout.getvalue()}
    result={'exit_code':code,'result':value,'stderr':stderr.getvalue()}
    (B/f'{label}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(label,code,str(value)[:200])
    assert code==0,label
    return result

receipts={}
for stem,count,name in [('single',1,'第15页_控制方法与阶段性结果_2026-09-15.pptx'),('full',28,'CTO组会汇报_仅第15页更新_2026-09-15.pptx')]:
    p=B/f'{stem}_candidate.pptx'
    reports={}
    reports['integrity']=invoke('inspect_presentation_package_integrity.py',[p,'--fail-on-findings'],f'{stem}_integrity')
    reports['layout']=invoke('inspect_presentation_layout_geometry.py',[p,'--fail-on-findings','--expected-slide-count',str(count),'--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--validate-bullet-geometry','--approved-font-family','Calibri'],f'{stem}_layout')
    reports['chart_discovery']=invoke('native_quantitative_chart_gate.py',[p,'--discover-chart-slides'],f'{stem}_chart_discovery')
    reports['chart_titles']=invoke('native_chart_title_gate.py',[p],f'{stem}_chart_titles')
    reports['table_arithmetic']=invoke('native_table_arithmetic_gate.py',[p,'--fail-on-findings'],f'{stem}_table_arithmetic')
    assert not reports['chart_discovery']['result']['chart_owner_slides']
    receipt={'candidate_sha256':sha(p),'reports':reports,'method':'Unmodified bundled validators called via runpy because Node subprocess launch returned EPERM. Artifact Tool authoring/rendering, no PowerPoint GUI claim.'}
    if '--publish' in sys.argv:
        target=O/name
        with target.open('xb') as out:out.write(p.read_bytes())
        receipt.update(output=str(target),sha256=sha(target))
    receipts[stem]=receipt
(B/'fallback_validation_receipt.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8')
if '--publish' in sys.argv:
    summary={'modified_slide':15,'new_simulation':False,'new_GUI_screenshot':False,'PowerPoint_GUI_verified':False,'source_retained':True,'other_slides_retained':True,'outputs':{p.name:sha(p) for p in O.iterdir() if p.is_file()}}
    (B/'delivery_receipt.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
