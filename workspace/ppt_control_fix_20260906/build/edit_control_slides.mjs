import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import JSZip from 'jszip';
import xmljs from 'xml-js';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';

const ROOT='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const BUILD=`${ROOT}/ppt_control_fix_20260906/build`;
const OUT=`${ROOT}/ppt_control_fix_20260906/output`;
const SOURCE=`${ROOT}/ppt_slide5_fix_20260906/output/CTO第一月组会汇报_第5页修订_2026-09-06.pptx`;
const FINAL=`${OUT}/CTO第一月组会汇报_第5及12_14_15页修订_2026-09-06.pptx`;
const SKILL='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const PYTHON='C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const report=JSON.parse(await fs.readFile(`${BUILD}/control_revision_audit.json`,'utf8'));
const timelineHash=report.source_manifest.find(r=>r.source.endsWith('stage4_control_timeline.csv')).sha256;
const version=timelineHash.slice(0,10);
const numbers=Object.fromEntries(report.integrated.map(r=>[r.strategy,r]));
const f=report.fs_details;
if(f.PERIODIC_SCAN.settled || f.P_AND_O.settled) throw Error('Acceptance changed; review required');
const SOURCES=[`${BUILD}/data/stage4_control_timeline.csv`,`${BUILD}/data/stage5_per_segment_metrics.csv`,
  `${BUILD}/data/stage5_integrated_strategy_table.csv`,`${BUILD}/data/stage4_5_audit.json`];
const commonNotes=`【数据来源】三页读取同一份已保存控制时序及其逐段、综合验收表。控制时序SHA256：${timelineHash}。\n\n【研究边界】假设BVD线性电学模型，离散准稳态仿真。无实测换能器、硬件闭环或声场安全性证明。`;
const notes={
12:[
  '【建议时长】约65秒',
  '【本页结论】fs−5%扰动后，三种策略均先发生保护动作。两种自适应策略随后低幅重扫并在新频率渐升幅度。',
  '【逐字讲稿】本页与后两页使用同一份保存的控制数据，重点看2.4到3.2秒的fs减5%扰动段。图中灰、蓝、红分别是固定频率、周期扫频和扫描辅助P&O。上、中、下三图分别是换能器端电压、端口电流和源幅度命令a。扰动后，保护逻辑判断原驱动幅度不再满足模型约束，进入硬停机，幅度命令归零。之后是低幅保持和渐升。固定频率策略停留在0.9 MHz，最终受软限幅约束。两种自适应策略在软限幅稳定后，以a等于0.40顺序扫描，再在选中的新频率恢复幅度。扫描期间的电压、电流变化全部保留，不能把这些变化都解释为负载再次漂移。',
  '【状态说明】左侧是本段保护过程的简化示意，不是完整状态转移图。HARD_TRIP硬保持约60 ms，RECOVERY_HOLD约100 ms，RAMP_UP每个控制步增加0.05幅度命令。SOFT_FOLDBACK稳定100 ms后允许低幅扫描。NORMAL表示控制器正常工作，不等于已通过连续稳态验收。',
  '【频率冻结口径】普通跟踪在硬停机、恢复保持和初始调幅过程中暂停。保护稳定后可以进行低幅扫描，因此不能说整段保护期间频率始终不变。',
  '【读图提示】控制记录按time_s和duration_s作采样保持绘图，包含CONTROL、SCAN和P&O参考/试探样本。淡色带标出本扰动段两次扫描的时间区间。不是示波器捕获的连续波形，也不重建采样间瞬态。',
  '【电压、电流边界】电压160 Vpp为用户给定的仿真硬边界。电流6 mA RMS硬限以及130 Vpp、5.5 mA RMS软限均为假设控制阈值。幅度a是戴维南源相对冻结基线的比例，不是端口电压本身。',
  '【教授可能追问】为什么存在HARD_TRIP记录，但图中没有超过160 Vpp或6 mA？',
  '【建议回答】模型先评估当前幅度在扰动后的可允许范围，再保存保护处理后的输出。因此保护触发次数与保存样本硬越限次数是不同指标。图中没有越限，不能证明真实系统在采样和执行延迟期间没有过冲。',
  '【模糊推测】本页没有对真实硬件保护速度或安全性作推测。阈值和时序常数是仿真假设。',commonNotes,
  '[Sources]',...SOURCES,`${BUILD}/data/run_stage4_5_control.py`,
].join('\n\n'),
14:[
  '【建议时长】约80秒',
  '【本页结论】两种自适应策略均到达0.8548 MHz新峰位，但在2.4–3.2 s扰动段内都未满足连续10个合格控制样本的稳态验收。',
  '【逐字讲稿】先看上图的离线安全功率曲线。基准峰位在0.9000 MHz，约170.0毫瓦。fs降低5%后，峰位移到0.8548 MHz，约140.2毫瓦，频率下移45.2千赫。中图和下图来自同一份当前控制时序，包含保护、扫描和幅度恢复，不再省略选频过程。P&O在2.9190秒首次以控制动作使用0.8548 MHz，周期扫频对应时刻为2.9770秒，此时两者还在渐升幅度。P&O从3.0390秒开始出现合格NORMAL样本，周期扫频从3.0970秒开始。到3.2秒切换下一扰动时，两者分别只有9个和6个连续合格样本，均不足10个。因此可以说到达了峰位和场景内峰值，不能说本段已经通过稳态验收，也没有可报告的本段验收恢复时间。',
  '【验收定义】只统计action=CONTROL、protection_state=NORMAL、frequency_frozen=0、功率捕获率至少98%的记录。相邻CONTROL记录间隔不得超过控制周期的1.5倍，即30 ms。连续10个合格样本才判通过。20 ms控制周期下，10个等间隔样本的首末跨度通常为180 ms。',
  `【本段重新计数】周期扫频：首次控制采用新峰位${f.PERIODIC_SCAN.first_control_at_peak_s.toFixed(4)} s，首次合格NORMAL样本${f.PERIODIC_SCAN.first_good_normal_s.toFixed(4)} s，最多连续${f.PERIODIC_SCAN.max_consecutive_good}个，settled=0。P&O：首次控制采用新峰位${f.P_AND_O.first_control_at_peak_s.toFixed(4)} s，首次合格NORMAL样本${f.P_AND_O.first_good_normal_s.toFixed(4)} s，最多连续${f.P_AND_O.max_consecutive_good}个，settled=0。`,
  '【为什么100%仍未通过】功率捕获率分母是当前场景自身的安全最优P_Rm。尾段100%表示选定的尾段样本达到约140.2 mW，不表示恢复基准170.0 mW，也不表示此前保护和扫描阶段没有功率损失。点值、尾段均值和连续验收是三个不同概念。',
  '【本段未通过的依据】保护保持、幅度渐升和扫描消耗了扰动段内的可用时间。达到合格NORMAL状态后，直到段结束仍不足10个样本。本段记录中不能继续使用旧版“P&O持续周期试探导致未通过”的解释。',
  '【教授可能追问】是否已经证明这两个控制器不能收敛？',
  '【建议回答】没有。这里证明的是它们未在给定0.8 s扰动段内满足既定验收。是否延长驻留时间后通过，需要另做实验，当前不能提前宣称通过。',
  '【模糊推测】延长扰动驻留时间可能改变验收结果，本次尚未做延长窗口实验，不作为已验证结论。',commonNotes,
  '[Sources]',...SOURCES,`${BUILD}/data/offline_safe_power_reference.csv`,`${BUILD}/control_revision_audit.json`,
].join('\n\n'),
15:[
  '【建议时长】约70秒',
  '【本页结论】两种自适应策略的所选尾段误差为0%，但仍各有未通过连续稳态验收的扰动段，不能仅凭尾段误差作总体优劣判断。',
  '【逐字讲稿】这一页与前两页使用同一份控制运行数据。综合评价包含初始基准之后的7个时间段，每段0.8秒。固定频率的平均尾段功率误差为30.14%，3段未通过。周期扫频和扫描辅助P&O的平均尾段误差均为0%，但分别有2段和3段未通过。这里特别需要区分：尾段误差取选定样本的平均值，连续稳态验收还要求NORMAL状态下连续10个样本达到98%。右侧恢复指标包含未通过惩罚，未通过段计800毫秒，再与其他段取平均，所以345.7、409.0和458.9毫秒不能读成每段都已经成功恢复。当前这些指标不足以支持某个策略总体最优的结论。',
  '【统计窗口】尾段功率优先选本段最后25%时间内的NORMAL且频率未冻结CONTROL样本。如果没有，依次退回本段最后5个NORMAL样本，再退回最后5个CONTROL样本。原始CSV字段仍名为steady_error_pct，本页用“尾段误差”避免将其误解为连续验收已经通过。',
  '【恢复指标口径】对通过的段，当前代码记录合格连续序列起点相对扰动起点的延迟，而不是第10个样本的确认时刻。对未通过的段记800 ms。之后对初始基准后的7段取平均。此项是含惩罚的综合指标，不是全部场景的实测恢复时间。',
  '【安全口径】表中零越限指保存的保护处理后准稳态样本，没有包括采样间瞬态。三策略均接入同一保护逻辑，固定策略指固定频率和固定名义幅度，不表示幅度在保护期间保持不变。',
  '【教授可能追问】为什么周期扫频有2段未通过，尾段误差还能为0？',
  '【建议回答】fs−5%段末已有达到场景峰值的样本，因样本数不足10个而未通过。另一个未通过段为匹配电感+10%。尾段均值不会自动检查连续样本数，也不体现扫描和降幅过程的电能损失。',
  '【进一步评价边界】若要对总体效果排名，还应同时评价全时段功率损失、扫描成本和不同扰动驻留时间。本页不以最短柱或零尾段误差单独判定最优。',
  '【模糊推测】真实噪声、不同驻留时间或控制参数整定可能改变结果，当前尚未验证。',commonNotes,
  '[Sources]',...SOURCES,`${BUILD}/data/run_stage4_5_control.py`,
].join('\n\n')};

const deck=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
if(deck.slides.items.length!==28) throw Error('Unexpected slide count');
const snap=await deck.inspect({kind:'slide,textbox,shape,image,chart,table,notes,layout',maxChars:320000});
const records=snap.ndjson.trim().split('\n').map(JSON.parse);
await fs.writeFile(`${BUILD}/before-inspect.ndjson`,snap.ndjson);
const slides={};
for(const n of [12,14,15]) {
  slides[n]=deck.resolve(records.find(r=>r.kind==='slide' && r.slide===n).id);
  await fs.writeFile(`${BUILD}/before-slide${n}.png`,new Uint8Array(await (await deck.export({slide:slides[n],format:'png',scale:1})).arrayBuffer()));
}
function item(n,name) {
  const r=records.find(r=>r.slide===n && r.name===name && ['textbox','shape'].includes(r.kind));
  if(!r) throw Error(`Missing ${n}/${name}`);return deck.resolve(r.id);
}
function text(n,name,value,position,size=22,color='#17324D',bold=false,align='left') {
  const o=item(n,name);o.text=value;if(position)o.position=position;
  o.text.style={typeface:'Calibri',fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',autoFit:'none',insets:{left:3,right:3,top:2,bottom:2}};
  return o;
}
function add(n,name,value,position,size=22,color='#17324D',bold=false,align='left') {
  const o=slides[n].shapes.add({name,geometry:'textbox',position,fill:'none',line:{fill:'none',width:0}});
  o.text=value;o.text.style={typeface:'Calibri',fontSize:size,color,bold,alignment:align,verticalAlignment:'middle',autoFit:'none',insets:{left:0,right:0,top:0,bottom:0}};return o;
}
async function replacePic(n,file,frame,alt) {
  const r=records.find(r=>r.slide===n && r.kind==='image');
  const o=deck.resolve(r.id);o.replace({blob:new Uint8Array(await fs.readFile(`${BUILD}/${file}.png`)),contentType:'image/png',fit:'contain',alt});
  o.frame=frame;o.crop={left:0,right:0,top:0,bottom:0};
}
for(const n of [12,14,15]) {
  text(n,'矩形 3',`假设BVD电学模型，非实测数据    控制时序版本 ${version}`,null,12,'#5F6B76');
  slides[n].speakerNotes.textFrame.setText(notes[n]);slides[n].speakerNotes.setVisible(true);
}

// Slide 12: same fs -5% event as slide 14, all saved actions retained.
text(12,'title-10','fs−5%扰动下的电压、电流与保护调幅',null,36,'#17324D',true);
add(12,'state-diagram-label','保护过程示意',{left:75,top:122,width:160,height:30},18,'#5F6B76',false,'center');
const stateNames=['矩形 10','矩形 12','矩形 14','矩形 16'];
const stateText=['硬停机\nHARD_TRIP','恢复保持\nHOLD','幅度渐升\nRAMP_UP','软限幅\nFOLDBACK'];
for(let i=0;i<4;i++)text(12,stateNames[i],stateText[i],null,18,'#17324D',true,'center');
for(let i=0;i<4;i++)item(12,`箭头: 右 ${5+i}`).position={left:151,top:222+i*100,width:25,height:16,rotation:90};
text(12,'矩形 17','限幅稳定后低幅重扫\n选频后再渐升幅度',{left:69,top:561,width:182,height:62},17,'#B33A3A',false,'center');
await replacePic(12,'slide12_protection_current',{left:265,top:125,width:943,height:506.30},'同一控制时序fs−5%段的端口电压、电流和幅度命令。包含所有记录动作，曲线未裁切，160 Vpp及6 mA硬边界完整显示。');
text(12,'矩形 19','软阈值：130 Vpp / 5.5 mA RMS    硬边界：160 Vpp / 6 mA RMS',
  {left:272,top:639,width:932,height:29},18,'#B33A3A',true,'center');

// Slide 14: distinguish selecting the new frequency, attaining its power, and passing acceptance.
text(14,'title-11','fs−5%后已到达新峰位，两种策略均未通过本段稳态验收',null,34,'#17324D',true);
await replacePic(14,'slide14_peak_and_acceptance_current',{left:72,top:126,width:805,height:540.5},
  '上：同模型离线安全功率峰。中下：当前控制时序的完整捕获率和扫描/控制频率。两策略在本段均未达到连续10个合格NORMAL样本。');
text(14,'矩形 6','扰动段 2.4–3.2 s（0.8 s）',{left:897,top:126,width:310,height:31},23,'#17324D',true);
text(14,'矩形 7','基准：0.9000 MHz，170.0 mW\nfs−5%：0.8548 MHz，140.2 mW\n峰位偏移：−45.2 kHz',
  {left:897,top:165,width:310,height:88},19,'#5F6B76');
text(14,'矩形 8','周期扫频：未通过验收',{left:897,top:275,width:310,height:32},23,'#2F73B7',true);
text(14,'矩形 9',`控制采用新峰位：${f.PERIODIC_SCAN.first_control_at_peak_s.toFixed(4)} s\n合格NORMAL：${f.PERIODIC_SCAN.first_good_normal_s.toFixed(4)} s起\n尾段100%，连续合格 6 / 10`,
  {left:897,top:313,width:310,height:90},19,'#2F73B7');
text(14,'矩形 10','扫描辅助P&O：未通过验收',{left:897,top:420,width:310,height:32},23,'#C84444',true);
text(14,'矩形 11',`控制采用新峰位：${f.P_AND_O.first_control_at_peak_s.toFixed(4)} s\n合格NORMAL：${f.P_AND_O.first_good_normal_s.toFixed(4)} s起\n尾段100%，连续合格 9 / 10`,
  {left:897,top:458,width:310,height:90},19,'#C84444');
text(14,'矩形 12','验收：NORMAL、频率未冻结\n且功率捕获率≥98%，连续10样本\n100%以当前场景140.2 mW归一化\n不等于恢复基准170.0 mW',
  {left:897,top:571,width:310,height:91},18,'#17324D',false);

// Slide 15: keep the editable table and chart but remove unsupported overall ranking.
text(15,'title-12','同一扰动序列下，尾段误差与连续稳态验收结果',null,36,'#17324D',true);
add(15,'comparison-window','评价初始基准之后的7段，每段0.8 s，三种策略均接入共同保护',
  {left:72,top:112,width:1136,height:35},22,'#5F6B76');
const table=deck.resolve(records.find(r=>r.slide===15 && r.kind==='table').id);
const names=['固定0.9 MHz','周期扫频','扫描辅助P&O'];
const values=[['策略','尾段误差*','恢复指标*\n(ms)','未通过段\n(共7段)','保护后\n硬越限']];
report.integrated.forEach((r,i)=>values.push([names[i],`${Number(r.steady_error_pct).toFixed(2)}%`,
  Number(r.mean_recovery_time_ms_penalized).toFixed(1),r.unsettled_segments,r.actual_hard_violations]));
for(let r=0;r<4;r++)for(let c=0;c<5;c++) {
  table.cells.set(r,c,values[r][c]);
  const cell=table.getCell(r,c);
  cell.text.style={typeface:'Calibri',fontSize:r===0?19:20,bold:r===0,color:r===0?'#FFFFFF':'#17324D'};
  if(r>0)cell.fill='#FFFFFF';
}
const chart=deck.resolve(records.find(r=>r.slide===15 && r.kind==='chart').id);
chart.categories=names;chart.series.getItemAt(0).categories=names;
chart.series.getItemAt(0).values=report.integrated.map(r=>Number(Number(r.mean_recovery_time_ms_penalized).toFixed(1)));
chart.title='恢复指标（含未通过惩罚，ms）';
Object.assign(chart.titleTextStyle,{typeface:'Calibri',fontSize:19,fill:'#17324D',bold:true});
text(15,'矩形 8','尾段误差0%仅描述所选样本，不代表全程功率无损失或连续验收通过。\n恢复指标：成功段取合格序列起点延迟，未通过段计800 ms，再求均值。',
  {left:93,top:526,width:1060,height:81},21,'#17324D',false,'center');

await fs.writeFile(`${BUILD}/第12_14_15页_讲稿.txt`,[12,14,15].map(n=>`第${n}页\n${notes[n]}`).join('\n\n'+'='.repeat(55)+'\n\n'),'utf8');
await fs.writeFile(`${BUILD}/content.json`,JSON.stringify({version,notes,values,source:SOURCE},null,2));
const authored=`${BUILD}/artifact-edited.pptx`;
await (await PresentationFile.exportPptx(deck)).save(authored);

const parse=t=>xmljs.xml2js(t,{compact:false});
const serial=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function els(root,name){const out=[];function walk(n){if(n.type==='element' && n.name.split(':').at(-1)===name)out.push(n);for(const e of n.elements??[])walk(e);}walk(root);return out;}
const rels=d=>els(d,'Relationship');
const resolve=(part,target)=>target.startsWith('/')?target.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(part),target));
const sourceBytes=await fs.readFile(SOURCE);
const original=await JSZip.loadAsync(sourceBytes);
const edit=await JSZip.loadAsync(await fs.readFile(authored));
const expectedChanges=[];
for(const n of [12,14,15]) {
  const part=`ppt/slides/slide${n}.xml`, rp=`ppt/slides/_rels/slide${n}.xml.rels`;
  const oldRel=parse(await original.file(rp).async('string'));
  const newRel=parse(await edit.file(rp).async('string'));
  const slideXml=parse(await edit.file(part).async('string'));
  for(const type of ['image','chart']) {
    const old=rels(oldRel).find(r=>r.attributes.Type.endsWith('/'+type));
    const newer=rels(newRel).find(r=>r.attributes.Type.endsWith('/'+type));
    if(!old && !newer)continue;
    if(!old || !newer)throw Error(`Unexpected ${type} dependency on ${n}`);
    const anchor=els(slideXml,type==='image'?'blip':'chart')[0];
    const attr=type==='image'?'r:embed':'r:id';anchor.attributes[attr]=old.attributes.Id;
    const newPart=resolve(part,newer.attributes.Target);
    if(type==='image') {
      const imagePart=`ppt/media/control_revision_slide${n}_${version}.png`;
      old.attributes.Target='/'+imagePart;
      original.file(imagePart,await edit.file(newPart).async('uint8array'));
      original.file(rp,serial(oldRel));expectedChanges.push(rp);
    } else {
      const oldPart=resolve(part,old.attributes.Target);
      original.file(oldPart,await edit.file(newPart).async('uint8array'));expectedChanges.push(oldPart);
    }
  }
  original.file(part,serial(slideXml));expectedChanges.push(part);
  const oldNotes=rels(oldRel).find(r=>r.attributes.Type.endsWith('/notesSlide'));
  const newNotes=rels(newRel).find(r=>r.attributes.Type.endsWith('/notesSlide'));
  const notePart=resolve(part,oldNotes.attributes.Target);
  original.file(notePart,await edit.file(resolve(part,newNotes.attributes.Target)).async('uint8array'));
  expectedChanges.push(notePart);
}
const candidate=`${BUILD}/candidate.pptx`;
await fs.writeFile(candidate,await original.generateAsync({type:'uint8array',compression:'DEFLATE'}));
await fs.writeFile(`${BUILD}/preservation_contract.json`,JSON.stringify({source:SOURCE,sourceSha256:createHash('sha256').update(sourceBytes).digest('hex'),expectedChanges:[...new Set(expectedChanges)],final:FINAL},null,2));
if(process.argv.includes('--author-only')) {console.log(JSON.stringify({candidate,manualValidation:'validate_control_deck.py'}));process.exit(0);}

const {finalizePresentation}=await import(pathToFileURL(`${SKILL}/container_tools/artifact_tool_utils.mjs`).href);
try {
  await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath:FINAL,pythonExecutable:PYTHON,
    integrityValidatorPath:`${SKILL}/container_tools/inspect_presentation_package_integrity.py`,
    layoutValidatorPath:`${SKILL}/container_tools/inspect_presentation_layout_geometry.py`,
    explicitTotalSlideCount:28,requiredNativeTableOwnerSlides:[15],requiredNativeChartOwnerSlides:[15],
    nativeChartTargetApplication:'powerpoint',
    layoutArgs:['--expected-slide-size-emu','12191999,6858000','--validate-heading-fit','--validate-bullet-geometry','--require-native-table-slide','15'],
    fontPolicy:{basis:'reference',families:['Calibri'],referencePath:SOURCE,referenceSha256:createHash('sha256').update(sourceBytes).digest('hex')},
    verifyArtifactToolImport:true,receiptPath:`${BUILD}/validation.json`});
} catch(error) {
  await fs.writeFile(`${BUILD}/finalizer_error.json`,JSON.stringify({message:error.message,code:error.code,validator:error.validator},null,2));
  if(!error.message.includes('EPERM'))throw error;
  console.log('Finalizer child-process EPERM. Candidate retained; run the same packaged validators directly.');
}
