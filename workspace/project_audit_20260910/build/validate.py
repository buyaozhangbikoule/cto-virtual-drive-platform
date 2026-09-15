"""Use bundled, unmodified PPTX validators in-process on Windows."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import sys
import zipfile
import xml.etree.ElementTree as ET

B=Path(__file__).resolve().parent; O=B.parent/'output'
C=json.loads((B/'contract.json').read_text(encoding='utf-8'))
S=Path('C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations/container_tools')
def check(script,args,label):
    out,err=io.StringIO(),io.StringIO();old=sys.argv;sys.argv=[str(S/script),*map(str,args)];code=0
    try:
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:runpy.run_path(str(S/script),run_name='__main__')
            except SystemExit as ex:code=ex.code or 0
    finally:sys.argv=old
    try:data=json.loads(out.getvalue())
    except json.JSONDecodeError:data={'stdout':out.getvalue()}
    result=dict(code=code,result=data,stderr=err.getvalue())
    (B/f'check_{label}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(label,code,str(data)[:700],flush=True);assert code==0,label
    return result

o=C['outputs'][0];p=Path(o['candidate']);source=Path(C['source']);ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
assert hashlib.sha256(source.read_bytes()).hexdigest()==C['sourceSha256']
reports={}
reports['integrity']=check('inspect_presentation_package_integrity.py',[p,'--fail-on-findings'],'integrity')
reports['geometry']=check('inspect_presentation_layout_geometry.py',[p,'--fail-on-findings','--expected-slide-count','28',
    '--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--validate-bullet-geometry','--approved-font-family','Calibri'],'geometry')
discovery=check('native_quantitative_chart_gate.py',[p,'--discover-chart-slides'],'chart_discovery')
reports['chart_titles']=check('native_chart_title_gate.py',[p],'chart_titles')
reports['tables']=check('native_table_arithmetic_gate.py',[p,'--fail-on-findings'],'tables')
if discovery['result']['chart_owner_slides']:
    reports['charts']=check('native_quantitative_chart_gate.py',[p,'--expected-chart-slides',
        ','.join(map(str,discovery['result']['chart_owner_slides'])),'--target-application','powerpoint'],'charts')

pattern=re.compile(r'[A-Za-z]:[\\/][^\r\n<>\"|]*?\.(?:csv|json|py|md|png|svg|pdf|raw|log|txt|cir|pptx|docx|zip|yaml|mjs)(?=$|[\s)\]。；;,])',re.I)
refs=[]
with zipfile.ZipFile(source) as old,zipfile.ZipFile(p) as new:
    actual=[n for n in old.namelist() if not n.endswith('/') and old.read(n)!=new.read(n)]
    assert set(actual).issubset(C['expectedChanges']),set(actual)-set(C['expectedChanges'])
    assert all(old.read(n)==new.read(n) for n in old.namelist() if n.startswith('ppt/media/'))
    def text(part):return '\n'.join(n.text or '' for n in ET.fromstring(new.read(part)).findall('.//a:t',ns))
    for oldnum in range(1,29):
        s=text(f'ppt/notesSlides/notesSlide{oldnum}.xml')
        assert '正式排名第三策略仍为扫描辅助P&O' not in s
        assert '正式策略排名仍采用固定、周期扫频和扫描辅助P&O' not in s
        for target in dict.fromkeys(pattern.findall(s)):
            f=Path(target);assert f.is_file(),target
            refs.append(dict(slide=C['order'].index(oldnum)+1,path=f.as_posix(),sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
    phase=text('ppt/slides/slide24.xml');assert '不作新排名' in phase and '39.91%' not in phase
    assert '计划策略三' in text('ppt/slides/slide23.xml')
    assert '695.7 / 615.4 / 533.3' in text('ppt/slides/slide20.xml')
    assert '尚未全部完成' in text('ppt/slides/slide18.xml')
    assert '0.588' in text('ppt/slides/slide15.xml')
    assert '188.2 Vpp' in text('ppt/slides/slide14.xml')
    reports['changed_parts']=actual;reports['all_original_media_unchanged']=True
    reports['resolved_note_references']=len(refs)

final=Path(o['final'])
if final.exists() and final.read_bytes()!=p.read_bytes():
    prior=json.loads((O/'PPT校验摘要.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(final.read_bytes()).hexdigest()==prior['sha256'],'Unexpected external edit to revision PPT'
    final.write_bytes(p.read_bytes())
elif not final.exists():
    with final.open('xb') as h:h.write(p.read_bytes())
reports['sha256']=hashlib.sha256(final.read_bytes()).hexdigest()
(O/'PPT校验摘要.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
(O/'逐页证据引用与哈希.json').write_text(json.dumps(refs,ensure_ascii=False,indent=2),encoding='utf-8')
