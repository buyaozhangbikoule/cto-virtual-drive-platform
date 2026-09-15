"""Run immutable packaged validators directly if Windows blocks child launch."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import zipfile
import xml.etree.ElementTree as ET

B=Path(__file__).resolve().parent
contract=json.loads((B/'contract.json').read_text(encoding='utf-8'))
S=Path('C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations/container_tools')
def check(script,args,label):
    out,err=io.StringIO(),io.StringIO()
    old=sys.argv;sys.argv=[str(S/script),*map(str,args)];code=0
    try:
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
            try:runpy.run_path(str(S/script),run_name='__main__')
            except SystemExit as x:code=x.code or 0
    finally:sys.argv=old
    try:data=json.loads(out.getvalue())
    except json.JSONDecodeError:data={'stdout':out.getvalue()}
    payload=dict(code=code,result=data,stderr=err.getvalue())
    (B/f'check_{label}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(label,code,str(data)[:500],flush=True)
    assert code==0,label
    return payload

ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
source=Path(contract['source'])
assert hashlib.sha256(source.read_bytes()).hexdigest()==contract['sourceSha256']
with zipfile.ZipFile(source) as source_zip:
    source_size=ET.fromstring(source_zip.read('ppt/presentation.xml')).find('{http://schemas.openxmlformats.org/presentationml/2006/main}sldSz')
    size_emu=source_size.attrib['cx']+','+source_size.attrib['cy']
reports=[]
for i,o in enumerate(contract['outputs']):
    p=Path(o['candidate']);record=dict(count=o['count'],candidate=str(p))
    record['integrity']=check('inspect_presentation_package_integrity.py',[p,'--fail-on-findings'],f'{i}_integrity')
    record['geometry']=check('inspect_presentation_layout_geometry.py',[p,'--fail-on-findings','--expected-slide-count',o['count'],
        '--expected-slide-size-emu',size_emu,'--validate-heading-fit','--validate-bullet-geometry',
        '--approved-font-family','Calibri'],f'{i}_geometry')
    discovery=check('native_quantitative_chart_gate.py',[p,'--discover-chart-slides'],f'{i}_chart_discovery')
    record['chart_titles']=check('native_chart_title_gate.py',[p],f'{i}_chart_titles')
    record['tables']=check('native_table_arithmetic_gate.py',[p,'--fail-on-findings'],f'{i}_tables')
    if discovery['result']['chart_owner_slides']:
        record['charts']=check('native_quantitative_chart_gate.py',[p,'--expected-chart-slides',
            ','.join(map(str,discovery['result']['chart_owner_slides'])),'--target-application','powerpoint'],f'{i}_charts')
    with zipfile.ZipFile(p) as z:
        text=' '.join(x.text or '' for x in ET.fromstring(z.read('ppt/slides/slide15.xml')).findall('.//a:t',ns))
        for value in ['0.588','0.474','0.525','75.8%','61.1%','67.7%','0.8–6.4 s','30.14%','0.00%','非新仿真','非声学效率','0.77568 J']:
            assert value in text,value
        assert '恢复指标（含未通过惩罚' not in text
        image=z.read('ppt/media/energy_comparison_20260909.png')
        assert image==(B.parent/'output/第15页_全过程电能比较.png').read_bytes()
        if o['count']==28:
            with zipfile.ZipFile(source) as old:
                changed=[n for n in old.namelist() if not n.endswith('/') and old.read(n)!=z.read(n)]
                assert set(changed)==set(contract['expectedChanges']),changed
                for n in range(1,29):
                    if n!=15:assert old.read(f'ppt/slides/slide{n}.xml')==z.read(f'ppt/slides/slide{n}.xml')
                record['only_target_parts_changed']=changed
    final=Path(o['final'])
    if final.exists():assert final.read_bytes()==p.read_bytes()
    else:
        with final.open('xb') as h:h.write(p.read_bytes())
    record['sha256']=hashlib.sha256(final.read_bytes()).hexdigest()
    reports.append(record)
(B/'validation_summary.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
