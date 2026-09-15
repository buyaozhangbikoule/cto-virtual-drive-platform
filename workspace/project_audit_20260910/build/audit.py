"""Metadata regression and source-link audit. No controller/LTspice rerun."""
import csv
import hashlib
import json
import math
import re
import sys
import types
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

B=Path(__file__).resolve().parent
DIR=B.parent;ROOT=DIR.parent;OUT=DIR/'output'
LIVE=ROOT/'outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py'
SOURCE=ROOT/'ppt_energy_update_20260909/output/CTO组会汇报_第14与15页评价更新_2026-09-09.pptx'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def load_model(name,text):
    m=types.ModuleType(name);m.__file__=str(LIVE);sys.modules[name]=m
    exec(compile(text,str(LIVE),'exec'),m.__dict__)
    return m
old=load_model('audit_before_model',(DIR/'before/0_model_v2_1.py').read_text(encoding='utf-8'))
new=load_model('audit_after_model',LIVE.read_text(encoding='utf-8'))
f=np.arange(800000.,1000000.1,100.)
before=old.scenario_map();after=new.scenario_map();assert before.keys()==after.keys()
checks=[]
for key,s in after.items():
    a=old.response(f,before[key]);b=new.response(f,s)
    assert all(np.array_equal(a[k],b[k],equal_nan=True) for k in a),key
    expected=2*math.pi*s.bvd.fs*s.bvd.lm/s.bvd.rm
    assert math.isclose(s.bvd.qm,expected,rel_tol=1e-12),key
    assert math.isclose(s.bvd.fs,1/(2*math.pi*math.sqrt(s.bvd.lm*s.bvd.cm)),rel_tol=1e-12),key
    if key.startswith('CASE_RM_'):
        p=int(key.split('_P')[1]);assert s.bvd.lm==new.BASE_BVD.lm and s.bvd.cm==new.BASE_BVD.cm
        checks.append(dict(case_id=key,old_Qm=before[key].bvd.qm,new_Qm=s.bvd.qm,
            expected_Qm=800/(1+p/100),Lm_unchanged=True,Cm_unchanged=True,response_exact=True))
for bad in [0,-1,math.nan,math.inf]:
    try:new.changed_rm_only(new.BASE_BVD,bad)
    except ValueError:pass
    else:raise AssertionError(bad)
registry_paths=[ROOT/'CTO_virtual_drive_platform_v2_1/scenarios/stage3_scenario_registry_and_summary.csv',
 ROOT/'CTO_virtual_drive_platform_v2_1/results/tables/stage3_disturbance/stage3_scenario_registry_and_summary.csv',
 LIVE.parent/'stage3_disturbance/stage3_scenario_registry_and_summary.csv']
for index,p in enumerate(registry_paths,4):
    with p.open(encoding='utf-8-sig') as h:now=list(csv.DictReader(h))
    with (DIR/f'before/{index}_{p.name}').open(encoding='utf-8-sig') as h:prior=list(csv.DictReader(h))
    assert len(now)==len(prior)
    for a,b in zip(prior,now):
        changed={k for k in a if a[k]!=b[k]}
        assert changed==({'Qm','description'} if a['case_id'].startswith('CASE_RM_') else set()),(p,a['case_id'],changed)
        assert math.isclose(float(b['Qm']),after[b['case_id']].bvd.qm,rel_tol=1e-12)
save(OUT/'Rm派生Qm修正验证.json',dict(status='PASS',cases=len(after),frequencies=len(f),
    tested_response_fields=len(new.response(f,new.all_scenarios()[0])),
    electrical_response_all_arrays_exact=True,corrected=checks,
    old_model_sha256=sha(DIR/'before/0_model_v2_1.py'),new_model_sha256=sha(LIVE),
    registry_changes='Qm and description only in the three Rm-only rows',controller_rerun=False,LTspice_rerun=False))

# Resolve notes references, retaining exact original values for review.
ns={'a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main'}
refs=[];notes={};slides={}
pattern=re.compile(r'[A-Za-z]:[\\/][^\r\n<>\"|]*?\.(?:csv|json|py|md|png|svg|pdf|raw|log|txt|cir|pptx|docx|zip)(?=$|[\s)\]。；;,])',re.I)
with zipfile.ZipFile(SOURCE) as z:
    for i in range(1,29):
        x=ET.fromstring(z.read(f'ppt/notesSlides/notesSlide{i}.xml'))
        text='\n'.join(''.join(n.itertext()) for n in x.findall('.//a:t',ns))
        notes[str(i)]=text
        sx=ET.fromstring(z.read(f'ppt/slides/slide{i}.xml'))
        slides[str(i)]='\n'.join(n.text or '' for n in sx.findall('.//a:t',ns))
        for p in dict.fromkeys(pattern.findall(text)):
            actual=Path(p)
            refs.append(dict(original_slide=i,path=p,exists=actual.is_file(),sha256=sha(actual) if actual.is_file() else None))
missing=[r for r in refs if not r['exists']]
save(B/'notes.json',notes);save(B/'slide_text.json',slides)
save(B/'references.json',dict(source=str(SOURCE),source_sha256=sha(SOURCE),references=refs,
 missing_count=len(missing),missing_slides=sorted({r['original_slide'] for r in missing})))
print(json.dumps({'model_cases_verified':len(after),'Qm':checks,'missing_references':missing},ensure_ascii=False,indent=2))

# Coverage facts use saved metadata, not hypothetical new trials.
schedule=json.loads((ROOT/'CTO_virtual_drive_platform_v2_1/results/tables/stage4_5/stage4_5_audit.json').read_text(encoding='utf-8'))['schedule']
controlled={s['case_id'] for s in schedule}
with (OUT/'静态与闭环覆盖核查.csv').open('w',encoding='utf-8-sig',newline='') as h:
    w=csv.DictWriter(h,fieldnames=['case_id','factor','registered_static','historical_fixed_scan_po_sequence','formal_fixed_scan_phase_unified'])
    w.writeheader()
    for k,s in after.items():w.writerow(dict(case_id=k,factor=s.factor,registered_static=1,
        historical_fixed_scan_po_sequence=int(k in controlled),formal_fixed_scan_phase_unified=0))
