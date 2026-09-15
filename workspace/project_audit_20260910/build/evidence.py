"""Read-only reference and historic-manifest audit; export new revision evidence."""
import csv
import hashlib
import json
from pathlib import Path

B=Path(__file__).resolve().parent
D=B.parent; R=D.parent; O=D/'output'; P=R/'CTO_virtual_drive_platform_v2_1'
W=Path('D:/微信文件/WeChat Files/wxid_f86c1kdajuft12/FileStorage/File/2026-08')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def csvout(p,rows):
    with p.open('w',encoding='utf-8-sig',newline='') as h:
        w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

replacements={
 'CTO超声换能器虚拟阻抗建模与自适应驱动控制_第一月计划书.docx':W/'CTO超声换能器虚拟阻抗建模与自适应驱动控制_第一月计划书.docx',
 'stage1_resonance_summary.csv':P/'evidence/ltspice/stage1/V2_1_STAGE1_audit.json',
 'stage2_matching_summary.csv':P/'evidence/ltspice/stage2/stage2_audit.json',
 'stage3_three_criteria_all_scenarios.csv':P/'results/tables/stage3_selection/stage3_initial_three_criteria.csv',
 'stage3_window_step_tradeoff.csv':P/'results/tables/stage3_selection/stage3_window_step_aggregate.csv',
 '前视超声治疗.pdf':W/'前视超声治疗.pdf',
 'High intensity focused ultrasound  Physical principles and devices.pdf':W/'High intensity focused ultrasound  Physical principles and devices.pdf',
 'SHA256_文件清单.csv':P/'results/manifests/evidence_manifest.csv',
}
refs=json.loads((B/'references.json').read_text(encoding='utf-8'))
fixed=[]
for r in refs['references']:
    if r['exists']:continue
    p=replacements[Path(r['path']).name];assert p.is_file(),p
    fixed.append(dict(original_slide=r['original_slide'],old_path=r['path'],resolved_path=p.as_posix(),
        sha256=sha(p),resolution='原路径错误；改引现存原件' if p.parent==W else '错误文件名；替换为实际支撑材料，不声称原文件已找回'))
write(B/'reference_replacements.json',fixed)
csvout(O/'引用路径修正表.csv',fixed)

manifest=P/'results/manifests/evidence_manifest.csv'
with manifest.open(encoding='utf-8-sig') as h:old=list(csv.DictReader(h))
rows=[]
for r in old:
    p=P/r['destination'];expected=r['sha256'].lower()
    now=sha(p) if p.is_file() else None
    rows.append(dict(destination=r['destination'],recorded_sha256=expected,current_sha256=now,
        status='MATCH' if now==expected else 'MISSING' if now is None else 'CHANGED_SINCE_MANIFEST'))
csvout(O/'历史哈希清单核查.csv',rows)
G=R/'outputs/v2_self_consistent_rebuild/active_stage3_5/ltspice_gui_evidence'
meta=json.loads((G/'LTspice_GUI_evidence_metadata.json').read_text(encoding='utf-8-sig'))
gui=[]
for ext in ['cir','raw','log']:
    field={'cir':'circuit_sha256','raw':'raw_sha256','log':'log_sha256'}[ext]
    p=G/f'CASE_000_BASELINE_GUI.{ext}'
    gui.append(dict(path=p.as_posix(),expected=meta[field].lower(),actual=sha(p),match=meta[field].lower()==sha(p)))
write(O/'历史GUI证据核查.json',dict(captured_at=meta['captured_at'],version=meta['executable_version'],
    evidence_scope='2026-08-15 baseline GUI evidence; not a screenshot of all current simulations',
    files=gui,all_match=all(x['match'] for x in gui),new_GUI_capture=False))
summary=dict(broken_reference_count=len(fixed),affected_pages=len(set(x['original_slide'] for x in fixed)),
    manifest_entries=len(rows),manifest_status_counts={s:sum(x['status']==s for x in rows) for s in ['MATCH','MISSING','CHANGED_SINCE_MANIFEST']},
    gui_captured_at=meta['captured_at'],gui_version=meta['executable_version'])
write(O/'证据核查摘要.json',summary)
print(json.dumps(summary,ensure_ascii=False,indent=2))
