"""Read-only scientific audit and synchronized lecture export. No solver runs."""
from pathlib import Path
import json,csv,hashlib,math,zipfile,posixpath,xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parents[2];B=Path(__file__).resolve().parent;O=B.parent/'output';O.mkdir(exist_ok=True)
P=R/'CTO_virtual_drive_platform_v2_1';A=R/'outputs/v2_self_consistent_rebuild'
SOURCE=R/'project_audit_20260910/output/CTO组会汇报_计划书口径与验收缺口修订_2026-09-10.pptx'
pages=json.loads((B/'content.json').read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
checks=[]
def check(name,ok,details):
    checks.append(dict(check=name,passed=bool(ok),details=details))
check('source_unchanged',sha(SOURCE)=='91ef28cc9a284a6bc3880639e1bf2b795386d1a100ca6ae44ee58a3fd0c4bbc0',sha(SOURCE))
srcs=sorted(set(p for s in pages for p in s['sources']))
check('all_page_sources_resolve',all(Path(p).is_file() for p in srcs),{'count':len(srcs),'missing':[p for p in srcs if not Path(p).is_file()]})
registry=pd.read_csv(P/'results/tables/stage3_disturbance/stage3_scenario_registry_and_summary.csv')
check('static_registry_count',len(registry)==34,registry.groupby('family').size().to_dict())
base=registry[registry.case_id=='CASE_000_BASELINE'].iloc[0]
rm=registry[registry.case_id.isin(['CASE_RM_P15','CASE_RM_P30','CASE_RM_P50'])].copy()
rm['Qm_recomputed']=2*np.pi*rm.fs_Hz*rm.Lm_H/rm.Rm_ohm
check('Rm_only_derived_Qm',np.allclose(rm.Qm,rm.Qm_recomputed) and np.allclose(rm.Lm_H,base.Lm_H) and np.allclose(rm.Cm_F,base.Cm_F),rm[['case_id','Qm','Qm_recomputed']].to_dict('records'))
s2=pd.read_csv(A/'stage2_matching/stage2_LTspice逐频数据.csv');work=s2[s2.frequency_Hz==900000].set_index('scenario')
Vs=float(base.source_a1_Vrms);scale=Vs**2
details={k:dict(source_1Vrms_mW=float(work.loc[k,'p_rm_W']*1000),source_calibrated_mW=float(work.loc[k,'p_rm_W']*1000*scale)) for k in ['BEFORE','ACTIVE_LOSSY']}
details['source_Vrms']=Vs;details['power_scale']=scale
check('page5_common_source',abs(details['BEFORE']['source_calibrated_mW']-5.186363126)<1e-6 and abs(details['ACTIVE_LOSSY']['source_calibrated_mW']-170)<1e-3,details)
RL=2*np.pi*900000*base.Lmatch_H/base.inductor_Q;RC=1/(2*np.pi*900000*base.Cmatch_F*base.capacitor_Q)
check('page6_ESR',abs(RL-6.035202883)<1e-6 and abs(RC-.623552827)<1e-6,{'RL_ohm':RL,'RC_ohm':RC,'reference_Hz':900000,'constant_ESR_in_netlist':True})
cross=pd.read_csv(P/'results/tables/stage3_disturbance/stage3_LTspice_cross_validation.csv');matches=[]
for _,v in cross.iterrows():
    for ext in ['raw','log']:
        path=P/'evidence/ltspice/stage3_selected_cases'/f'{v.case_id}.{ext}'
        matches.append(dict(path=str(path),match=path.is_file() and sha(path)==v[f'{ext}_sha256'].lower()))
check('12_LTspice_static_evidence_pairs',len(cross)==12 and all(v['match'] for v in matches),matches)
oldpath=R/'ppt_control_fix_20260906/build/data/stage4_control_timeline.csv';old=pd.read_csv(oldpath)
check('old_control_batch',sha(oldpath)=='a734eca013d415f7a875c2785068745cd80ad811d7284e893bbcd1e974c5f0a0' and len(old)==1795,{'rows':len(old),'strategies':old.groupby('strategy').size().to_dict(),'peak_Vpp':float(old.vport_vpp.max()),'peak_mA':float(old.iport_irms_A.max()*1000),'unique_cases':int(old.case_id.nunique())})
refs=old[old.state_index>0].groupby('state_index').optimal_safe_power_W.first();reference=float(refs.sum()*.8)
saved=json.loads((R/'ppt_energy_update_20260909/build/data.json').read_text(encoding='utf-8'))
energies=[]
for strategy,g in old.groupby('strategy',sort=False):
    g=g.sort_values('time_s');lo=np.maximum(.8,g.time_s.to_numpy());hi=np.minimum(6.4,(g.time_s+g.duration_s).to_numpy());dt=np.maximum(0,hi-lo);mask=dt>1e-12
    assert np.allclose(lo[mask][1:],hi[mask][:-1],atol=1e-10,rtol=0)
    E=float(np.sum(g.p_rm_W.to_numpy()*dt));expected=next(x for x in saved['rows'] if x['strategy']==strategy)
    energies.append(dict(strategy=strategy,energy_J=E,capture_pct=100*E/reference,duration_s=float(dt.sum()),matches_saved=abs(E-expected['energy_J'])<1e-12))
check('page24_energy_independent_recalculation',all(x['matches_saved'] for x in energies),{'interval_s':[.8,6.4],'reference_J':reference,'method':'Recorded P multiplied by clipped recorded duration, all actions retained. Not intersample physical replay.','results':energies})
pd.DataFrame(energies).to_csv(O/'历史时序电能独立复核.csv',index=False,encoding='utf-8-sig')
phasepath=P/'results/phase_ablation/phase_timeline_selected_gain.csv';phase=pd.read_csv(phasepath)
check('page14_current_phase_data',sha(phasepath)=='b170bc930dfbdcd07a58b9f3b2d37f7121f9cd9d3cd0239ebe8034ec079f8085',{'max_capture_ratio':float(phase.safe_power_capture_ratio.max()),'max_P_Rm_mW':float(phase.p_rm_W.max()*1000),'phase_slope_from_model_probe':True,'probe_time_cost_counted':False})
cand=pd.read_csv(R/'po_scheduling_20260909/results/B0_T500_A90_R2_dwell_0.8s/acceptance_and_energy.csv');v=cand[cand.case_id=='CASE_FS_M5'].iloc[0]
check('page23_saved_candidate_not_new_run',v.settled==1 and v.max_consecutive_good==12 and abs(v.confirmation_delay_ms-742)<1e-6 and v.held_command_peak_vpp>160,v.to_dict())
gdir=A/'active_stage3_5/ltspice_gui_evidence';meta=json.loads((gdir/'LTspice_GUI_evidence_metadata.json').read_text(encoding='utf-8-sig'));gui=[]
for ext,key in [('cir','circuit_sha256'),('raw','raw_sha256'),('log','log_sha256')]:
    p=gdir/f'CASE_000_BASELINE_GUI.{ext}';gui.append(dict(path=str(p),match=sha(p)==meta[key].lower()))
check('historical_GUI_files_hashes',all(x['match'] for x in gui),{'captured_at':meta['captured_at'],'files':gui,'image_full_axes':False,'new_GUI_capture_this_audit':False})

# Verify speaker notes against the sole text source and preserve historical media.
ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
def relpath(p):return posixpath.dirname(p)+'/_rels/'+posixpath.basename(p)+'.rels'
def resolve(p,t):return t.lstrip('/') if t.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(p),t))
candidate=B/'candidate.pptx'
with zipfile.ZipFile(candidate) as z,zipfile.ZipFile(SOURCE) as orig:
    pres=ET.fromstring(z.read('ppt/presentation.xml'));rels=ET.fromstring(z.read('ppt/_rels/presentation.xml.rels'));mapping={r.attrib['Id']:resolve('ppt/presentation.xml',r.attrib['Target']) for r in rels}
    parts=[mapping[x.attrib['{'+ns['r']+'}id']] for x in pres.findall('.//p:sldId',ns)]
    notes_ok=[];tableowners=[];alltexts=[]
    for n,part in enumerate(parts,1):
        root=ET.fromstring(z.read(part));alltexts.extend(x.text or '' for x in root.findall('.//a:t',ns))
        if root.findall('.//a:tbl',ns):tableowners.append(n)
        rels=ET.fromstring(z.read(relpath(part)));note=next(r for r in rels if r.attrib['Type'].endswith('/notesSlide'))
        nr=ET.fromstring(z.read(resolve(part,note.attrib['Target'])))
        texts=[]
        for sp in nr.findall('.//p:sp',ns):
            ph=sp.find('./p:nvSpPr/p:nvPr/p:ph',ns)
            if ph is not None and ph.attrib.get('type')=='body':texts+=[''.join(x.itertext()) for x in sp.findall('./p:txBody/a:p/a:r/a:t',ns)]
        actual=''.join(texts);expected=pages[n-1]['notes'];compact=lambda s:''.join(s.split())
        notes_ok.append(dict(page=n,match=compact(actual)==compact(expected)))
    check('28_embedded_notes_synchronized',len(parts)==28 and all(x['match'] for x in notes_ok),notes_ok)
    originals=[n for n in orig.namelist() if n.startswith('ppt/media/')]
    check('all_original_media_bytes_retained',all(z.read(n)==orig.read(n) for n in originals),{'count':len(originals),'note':'Unused old media remain in ZIP; visible replacement plots are explicitly new images.'})
    check('required_tables_editable',tableowners==[6,7,15,19,20,21,22,24,26],tableowners)
    check('removed_stale_96_5ms_claim','96.5' not in '\n'.join(alltexts),'No 96.5 ms claim in visible native text. Source images reviewed separately.')
(B/'scientific_checks.json').write_text(json.dumps({'operation':'read-only audit, postprocessing, slide editing','new_simulation':False,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
assert all(x['passed'] for x in checks),[(x['check'],x['details']) for x in checks if not x['passed']]

intro='全28页图文同步讲稿\n版本：2026-09-11\n\n正文为第1–18页，建议约15分钟；第19–28页为答疑备份。\n【逐字讲稿】可直接讲；【本页指示顺序】只说明鼠标在当前页指哪里，不要求再出示额外截图。\n口径、限制和追问用于备课，不需要全部朗读。所有数值是已有假设模型仿真或本次已有数据复核，不是实测。\n本次未新运行LTspice、控制器或ANSYS/COMSOL，未生成真实GUI截图。\n\n'
(O/'逐页讲稿_图文同步_2026-09-11.txt').write_text(intro+'\n\n'+'\n\n'+'\n\n' .join(s['notes'] for s in pages),encoding='utf-8-sig')
index=[]
for s in pages:
    for p in s['sources']:index.append(dict(page=s['page'],title=s['title'],source=p,bytes=Path(p).stat().st_size,sha256=sha(p)))
for n,rel in [(5,'ppt_slide5_fix_20260906/build/plot_calibrated_matching.py'),(12,'ppt_control_fix_20260906/build/plot_control_revision.py'),(23,'ppt_acceptance_update_20260909/build/prepare_page.py'),(24,'ppt_energy_update_20260909/build/prepare.py')]:
    p=R/rel;index.append(dict(page=n,title=pages[n-1]['title'],source=str(p),bytes=p.stat().st_size,sha256=sha(p)))
pd.DataFrame(index).to_csv(O/'逐页证据索引_SHA256.csv',index=False,encoding='utf-8-sig')
report=['# PPT及讲稿图文核查报告','',
'审查对象：2026-09-10计划书口径版，28页。原文件不变，原哈希：`'+sha(SOURCE)+'`。',
'本次范围：逐页文字与图片、嵌入讲稿、数据文件、公式口径、版本和证据路径。操作仅含读取、独立后处理及图文修订，没有新控制器、LTspice、结构声场仿真，也没有实物实验。',
'','## 结论与不能声称完成的事项','',
'- 电学模型、v2.1匹配及静态扫描有文件证据。34个静态场景中，12个代表场景有LTspice交叉验证。',
'- 固定频率、周期扫频、相位闭环的同口径正式验收尚未全部完成，P&O是扩展方法。',
'- 旧主控制序列为8段、7个不同场景，不覆盖全部单因素和低、中组合闭环。',
'- 后续候选通过fs−5%连续稳态窗口，同时保持指令重放仍有188.2 Vpp越限，不能只报通过。',
'- 记录样本未越限，不证明采样间隙或真实硬件瞬态安全。功率、反射上限和无解处置仍待统一。',
'- 电—声接口仅有字段和4条电学记录，声学数据为空，没有COMSOL/ANSYS求解、网格、云图。',
'- 未作新医学文献检索；删除无具体出处的定量病变映射，推测项明示，不把工程扰动写成临床分级。',
'','## 关键修正','',
'1. 第5页所有功率统一6.217 V RMS戴维南源，未匹配5.186 mW、有损170.0 mW，保留1 V源缩放推导于讲稿。',
'2. 第6页注明电感与电容ESR以及L/C微调，不仅归因电感损耗；输入相位与端口相位分开。',
'3. 第7页讲稿按实际表格指示，fs的最大峰移只指表内代表因素，Cm-only另有更大漂移。',
'4. 第4页最大“复阻抗相对误差”不再误称“阻抗幅值误差”，比例和百分数明确。',
'5. 第11页由当前34场景表重绘：±20漏10例，±50漏2例。1.5 ms/点只是假设扫描时间。',
'6. 第14页按当前相位CSV重绘绝对P_Rm，移除旧图与当前数据不一致的约120%捕获率；披露斜率来自模型探针且未计探针耗时。',
'7. 第12/24页旧批次a734eca013、第23页后续候选cdde9dab61分开；电能积分方法也分开。',
'8. 第25页保留原始局部GUI图。原图没有横轴下沿，无法从现有像素补出真实完整软件页面。需重新打开历史RAW及Error Log截图。',
'','## 逐页修改与证据边界','']
for s in pages:
    report += [f"### 第{s['page']}页：{s['title']}",'',f"实际图表：{s['visual']}",f"修改：{s['change']}",f"边界：{s['limits']}",f"推测标记：{s['uncertain']}",'']
report += ['## 文件与讲稿使用方法','',
'PPT内28页演讲者备注与TXT逐页段落由同一content.json生成，并逐页比对。TXT额外的开头是使用说明。',
'每页源路径与当前哈希见《逐页证据索引_SHA256.csv》。7组重绘图提供Python脚本与PNG/SVG/PDF。原PPT、原RAW/CSV/Log及历史图片未覆盖。',
'“完整审核”表示覆盖全部28页，不表示所有历史实验均在本次重新执行或所有模型假设已获得外部验证。',
'视觉检查使用PPT文件渲染与逐页核查。本次未在PowerPoint GUI中逐页放映，不能声称完成原生GUI验证。',
'','## 需要保留或另行完成的真实工作痕迹','',
'- 当前可保存：原配置、生成脚本、网表、RAW/Log、控制CSV、逐页来源索引与本次重绘脚本。',
'- 用户需补截：LTspice完整波形窗口（含横纵轴、变量名、场景文件名）及可读的Error Log。历史局部图不能替代。',
'- 尚未产生：正式统一三策略完整验收、结构/声场模型树、几何材料、网格收敛、模态谐响应及声压求解结果。',
'- 不允许用AI生成、后处理拟造的软件界面或示意声压云图充当真实运行证据。',
'','## 本次独立数值复核','',f"自动核查{len(checks)}项全部通过。核查的是文件一致性和明确代数/积分关系，不能外推为全项目验收通过。详细结果在工作痕迹包的scientific_checks.json。"]
(O/'全28页图文审核报告.md').write_text('\n'.join(report)+'\n',encoding='utf-8-sig')
print(json.dumps({'checks':len(checks),'passed':True,'speaker_pages':28,'unique_sources':len(srcs),'main_talk_seconds':sum(x['seconds'] for x in pages[:18]),'energy':energies},ensure_ascii=False))
