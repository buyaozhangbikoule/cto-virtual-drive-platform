import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import JSZip from 'jszip';
import xmljs from 'xml-js';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';

const ROOT='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const WORK=`${ROOT}/ppt_control_pages_fix_20260906`;
const BUILD=`${WORK}/build`;
const OUT=`${WORK}/output`;
const SOURCE=`${ROOT}/ppt_slide5_fix_20260906/output/CTO第一月组会汇报_第5页修订_2026-09-06.pptx`;
const FINAL=`${OUT}/CTO第一月组会汇报_控制图表修订_2026-09-06_v2.pptx`;
const SKILL='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const PYTHON='C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const audit=JSON.parse(await fs.readFile(`${BUILD}/control_revision_audit.json`,'utf8'));
const CHANGED=[12,14,15];
const MODEL_NOTICE='Hypothetical BVD model — non-measured parameters';
const NORMAL_FONT='Calibri';
const parseXml=t=>xmljs.xml2js(t,{compact:false});
const writeXml=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function elements(node,name) {
 const found=[];
 function walk(n) {if(n.type==='element' && n.name.split(':').at(-1)===name) found.push(n); for(const child of n.elements??[]) walk(child);}
 walk(node);return found;
}
const pt=(left,top,width,height)=>({left,top,width,height});
const srcFolder=`${ROOT}/CTO_virtual_drive_platform_v2_1/results/tables/stage4_5`;
const commonSource=[`${srcFolder}/stage4_control_timeline.csv`,`${srcFolder}/stage5_per_segment_metrics.csv`,`${srcFolder}/stage5_integrated_strategy_table.csv`,`${srcFolder}/stage4_5_audit.json`];
const provenance=`控制时序快照 SHA-256：${audit.source_inputs.find(x=>x.path.endsWith('stage4_control_timeline.csv')).sha256}\n三页使用同一份控制时序及其复算一致的汇总结果。离线功率曲线的安全最优值与该时序的参考值逐场景核对一致。`;
const notes={
  12:[
    '【建议时长】约65秒',
    '【本页结论】在fs减5%的扰动段，模型执行硬触发、保持及幅度恢复。扫描也占用时间并暂时降低驱动幅度。',
    '【逐字讲稿】本页和后两页使用同一份保存的控制时序。图中2.400秒开始进入fs减5%的场景，三种策略经历相同的绝对时间扰动。三幅曲线分别是换能器端电压、电流和幅度命令。模型判断当前驱动在新负载下超过允许范围后，进入HARD_TRIP并将幅度置零，然后进入RECOVERY_HOLD，再逐步恢复幅度。在硬保持、恢复保持和幅度渐升阶段，控制器冻结调频。固定频率策略恢复后仍停在0.9 MHz，并受到软限幅约束。两种自适应策略还要执行低幅扫描，随后在新峰位继续恢复幅度。因此电压或电流下降可能来自保护，也可能来自扫描，不能只凭曲线形状判断保护状态。',
    '【看图顺序】先看2.400秒的扰动线，再对齐电压、电流及幅度的置零段。随后看保持、渐升和低幅扫描。左侧仅示意硬触发路径，恢复过程中还可能进入SOFT_FOLDBACK分支。',
    '【记录与时序】控制采样步长20 ms，扫描点驻留1.5 ms。控制时序采用离散准稳态模型，图上折线按记录duration_s保持值绘制，不是瞬态振荡或真实LTspice瞬态波形。固定、周期扫频、P&O在本段首次硬触发记录分别约为2.4000、2.4175、2.4195秒，差异与各策略当时的采样/扫描时序有关。',
    '【保护边界】电压160 Vpp为用户给定仿真边界，电流6 mA RMS为假设硬限。130 Vpp及5.5 mA RMS为假设软触发阈值。本图显示保护处理后的保存样本。未观察到保存样本的硬越限，不证明实物系统在传感、执行延迟和电气瞬态下绝不越限。',
    '【实现限制】允许幅度由当前线性模型计算。低幅扫描点尚未逐点复用与普通控制样本完全相同的保护状态更新流程，现有结果不能作为任意扩展场景的硬件安全保证。',
    '【教授可能追问】为什么幅度下降后还有扫描？',
    '【建议回答】保护优先恢复到允许范围，随后才允许低幅重捕获。扫描使用a=0.4，所以在图中也会出现幅度降低。不能将这些区间全部归因于foldback。',
    '【模糊推测】将本页结果推广到真实功放或换能器安全性属于未验证推断，本页不作该结论。',
  ],
  14:[
    '【建议时长】约80秒',
    '【本页结论】两种自适应策略均到达0.8548 MHz附近的新峰位，但在2.400至3.200秒窗口内均未满足连续稳态验收。',
    '【逐字讲稿】先看上图离线安全功率曲线。基准峰位为0.9000 MHz、170.0 mW，fs减5%后的峰位为0.8548 MHz、140.2 mW，峰位下降45.2 kHz。中图显示当前保存时序的功率捕获率，包含保护、扫描和恢复阶段的数据。捕获率的分母是当前场景自身的安全最大功率，所以100%对应这个扰动场景约140.2 mW的峰值，并不表示恢复到了基准170.0 mW。下图只显示CONTROL样本的频率，在扫描区间断线。周期扫频和扫描辅助P&O都到达了新峰位，但这与通过连续稳态验收不同。判据要求连续10个合格控制样本。在本段结束前，周期扫频只有6个，P&O只有9个，因此两者均未通过。',
    '【严格判据】CONTROL样本必须处于NORMAL，frequency_frozen=0，安全功率捕获率不低于98%。相邻控制样本时间间隔还需不超过30 ms。RAMP_UP中达到98%的样本不计为合格，扫描或试探造成的间隔也可能打断连续计数。',
    '【本段数据】周期扫频首次在新峰位形成CONTROL记录的时刻为2.9770秒，此时仍在RAMP_UP。首个合格NORMAL样本为3.0970秒，本段最长连续合格序列为6个。P&O对应时刻为2.9190秒与3.0390秒，最长连续序列为9个。两者尾段捕获率均为100%，settled均为0，recovery_time_ms均为空。首次到达峰位、首次满足功率阈值和完成连续验收是三个不同事件。',
    '【原因边界】保护保持、恢复渐升和扫描已经占用了当前0.8秒扰动窗口，剩余时间不足以获得10个连续合格样本。不能仅将本段P&O未通过验收归因于周期性试探。',
    '【教授可能追问】P&O只差一个样本，能否算已经稳定？',
    '【建议回答】按事先设定的10样本判据，9个仍未通过。这是当前窗口内证据不足，不等同于证明系统发散或永远不能收敛。若要考察更长扰动驻留时间，应作为单独新实验，保留当前未通过结果。',
    '【模糊推测】延长窗口后可能通过，但当前记录未验证该推断。不能补画第10个样本。',
  ],
  15:[
    '【建议时长】约70秒',
    '【本页结论】同一批保存结果中，周期扫频与P&O的筛选尾段误差为零，但分别有2段和3段未通过连续验收。该表不能单独支持总体最优结论。',
    '【逐字讲稿】综合结果由前两页同一份控制时序复算得到，覆盖初始基准之后的7个时间段。固定频率策略的平均尾段误差为30.14%，周期扫频与P&O为0%。但尾段误差和连续验收是不同指标，周期扫频仍有2段、P&O有3段未通过。右侧柱图为含惩罚的平均恢复指标，分别为345.7、409.0和458.9毫秒。它对未通过的时间段使用800毫秒惩罚值，所以不能把这些数值解释为每段都实际恢复所需的时间。三种策略的保护处理后保存样本均无硬越限。本表反映当前模型和参数下的部分控制表现，尚不能据此给出总体优劣排名。',
    '【尾段误差的实际实现】每段优先选取最后25%时间内处于NORMAL且频率未冻结的CONTROL样本。若没有这些样本，则依次回退到该段最后5个NORMAL样本，或最后5个CONTROL样本。对选中样本计算平均捕获率，再计算相对当前场景安全功率参考的误差。因此零尾段误差不等于全时段零功率损失，也不等于通过连续10样本验收。',
    '【恢复指标的实际实现】对通过的段，记录首个满足10个连续合格控制样本窗口的起点相对扰动开始时刻的延迟；这是完成连续验收后的回溯起点，不是第10个样本的确认时刻。对未通过的段赋值800 ms，再对7段取平均。',
    '【安全计数口径】本表硬越限为保护处理后保存样本的电压/电流硬越限次数，不是HARD_TRIP事件次数。固定策略本批次硬触发1次，周期扫频和P&O各2次。已保存样本硬越限为0与发生过硬触发并不矛盾。',
    '【教授可能追问】为什么周期扫频的尾段误差为零，第14页仍然未通过？',
    '【建议回答】第14页尾段的6个合格样本都位于安全功率峰，因此它们的平均误差可以为零。但验收需要10个连续样本，6个不足。一个指标描述选中样本的功率水平，另一个指标描述持续保持证据。',
    '【评价边界】尚需结合全时段能量、扫描成本、更多扰动场景和统一的相位闭环比较，才能讨论更全面的策略权衡。这里不将某一指标的领先表述为普遍最优。',
    '【模糊推测】改变驻留时间、噪声或控制参数后的性能变化需要新实验，当前不作定量预测。',
  ],
};
for(const n of CHANGED) {
 notes[n].push('[Sources]',...commonSource,provenance);
 if(n===14) notes[n].push(audit.source_inputs.find(x=>x.path.endsWith('stage3_frequency_response_all_cases.csv')).path);
}

const sourceBytes=await fs.readFile(SOURCE);
const deck=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
if(deck.slides.items.length!==28) throw Error('Source slide count changed');
const snapshot=await deck.inspect({kind:'slide,textbox,shape,image,table,chart,notes,layout',maxChars:350000});
await fs.writeFile(`${BUILD}/before-inspect.ndjson`,snapshot.ndjson);
const records=snapshot.ndjson.trim().split('\n').map(t=>JSON.parse(t));
function slide(n){const r=records.find(r=>r.kind==='slide'&&r.slide===n);if(!r)throw Error(`Missing slide ${n}`);return deck.resolve(r.id);}
function named(n,name){const r=records.find(r=>r.slide===n&&r.name===name&&(r.kind==='shape'||r.kind==='textbox'));if(!r)throw Error(`Missing ${n}/${name}`);return deck.resolve(r.id);}
function edit(n,name,text,position,size=22,color='#17324D',bold=false,alignment='left'){
 const s=named(n,name);s.text=text;if(position)s.position=position;
 s.text.style={typeface:NORMAL_FONT,fontSize:size,color,bold,alignment,verticalAlignment:'middle',autoFit:'none',insets:{left:4,right:4,top:2,bottom:2}};return s;
}
function add(n,name,text,position,size=20,color='#17324D',bold=false,alignment='left'){
 const s=slide(n).shapes.add({geometry:'textbox',name,position,fill:'none',line:{fill:'none',width:0}});s.text=text;
 s.text.style={typeface:NORMAL_FONT,fontSize:size,color,bold,alignment,verticalAlignment:'middle',autoFit:'none',insets:{left:0,right:0,top:0,bottom:0}};return s;
}
async function replaceFigure(n,stem,frame,alt){
 const r=records.find(r=>r.slide===n&&r.kind==='image');if(!r)throw Error(`Missing image ${n}`);
 const im=deck.resolve(r.id);im.replace({blob:new Uint8Array(await fs.readFile(`${BUILD}/${stem}.png`)),contentType:'image/png',alt,fit:'contain'});
 im.frame=frame;im.crop={left:0,top:0,right:0,bottom:0};
}
for(const n of CHANGED) {
 const data=await deck.export({slide:slide(n),format:'png',scale:1});
 await fs.writeFile(`${BUILD}/before-page${n}.png`,new Uint8Array(await data.arrayBuffer()));
}

edit(12,'title-10','硬触发后停机保持，渐升幅度期间冻结频率',null,36,'#17324D',true);
add(12,'state-path-caption','硬触发路径示意',pt(81,120,150,30),17,'#5F6B76');
edit(12,'矩形 10','NORMAL',pt(92,166,125,46),20,'#17324D',true,'center');
edit(12,'矩形 12','HARD_TRIP',pt(92,266,125,46),18,'#B33A3A',true,'center');
edit(12,'矩形 14','RECOVERY\nHOLD',pt(92,364,125,48),18,'#17324D',true,'center');
edit(12,'矩形 16','RAMP_UP',pt(92,466,125,46),19,'#17324D',true,'center');
edit(12,'矩形 17','另有软限幅分支\nSOFT_FOLDBACK',pt(66,548,180,58),17,'#B33A3A',true,'center');
add(12,'scan-interpretation','低幅扫描也会\n使电压、电流下降',pt(68,608,174,53),17,'#5F6B76',false,'center');
named(12,'矩形: 圆角 11').fill='#F8E8E8';
named(12,'矩形: 圆角 13').fill='#EAF1F7';
await replaceFigure(12,'page12_protection_current',pt(254,118,944,524.444),'同一控制时序中2.25至3.20秒的端口电压、电流、幅度命令。包含全部扫描和保护记录。');
edit(12,'矩形 19','假设软阈值：130 Vpp / 5.5 mA RMS     硬边界：160 Vpp / 6 mA RMS',pt(273,645,930,30),17,'#B33A3A',true,'center');

edit(14,'title-11','到达0.8548 MHz新峰位，尚未满足连续稳态验收',null,36,'#17324D',true);
await replaceFigure(14,'page14_peak_and_acceptance_current',pt(72,113,800,557.692),'基准与fs减5%的离线安全功率峰，以及同一当前时序中的捕获率和CONTROL频率。两种自适应策略均未通过本段连续10样本验收。');
edit(14,'矩形 6','fs−5%验收窗口',pt(907,123,297,35),25,'#17324D',true);
edit(14,'矩形 7','2.400–3.200 s\n连续10个CONTROL样本\nNORMAL、未冻结、捕获率≥98%\n相邻控制样本间隔≤30 ms',pt(907,168,297,111),19.5);
edit(14,'矩形 8','周期扫频：未通过',pt(907,291,297,36),25,'#2F73B7',true);
edit(14,'矩形 9','到达峰位 0.8548 MHz\n尾段捕获率 100%\n合格连续样本 6 / 10',pt(907,334,297,96),22,'#17324D');
edit(14,'矩形 10','P&O：未通过',pt(907,450,297,36),25,'#C84444',true);
edit(14,'矩形 11','到达峰位 0.8548 MHz\n尾段捕获率 100%\n合格连续样本 9 / 10',pt(907,492,297,96),22,'#17324D');
edit(14,'矩形 12','100%按当前场景安全峰值归一化\n对应约140.2 mW\n不等于恢复基准170.0 mW',pt(907,606,297,65),17.5,'#17324D',false);

edit(15,'title-12','尾段误差为零，仍可能未通过连续稳态验收',null,36,'#17324D',true);
const tRecord=records.find(r=>r.slide===15&&r.kind==='table');
const table=deck.resolve(tRecord.id);
const values=[['策略','尾段误差*','恢复指标*\n含惩罚 / ms','未通过段','硬越限*']];
for(const s of ['FIXED_0P9','PERIODIC_SCAN','P_AND_O']){
 const row=audit.integrated.find(r=>r.strategy===s);
 values.push([s==='FIXED_0P9'?'固定0.9 MHz':s==='PERIODIC_SCAN'?'周期扫频':'扫描辅助P&O',
   Math.abs(row.steady_error_pct)<1e-8?'0%':`${row.steady_error_pct.toFixed(2)}%`,
   row.mean_recovery_time_ms_penalized.toFixed(1),`${row.unsettled_segments} / 7`,String(row.actual_hard_violations)]);
}
for(let r=0;r<4;r++)for(let c=0;c<5;c++){
 table.cells.set(r,c,values[r][c]);
 const cell=table.getCell(r,c);cell.text.style={typeface:NORMAL_FONT,fontSize:r===0?18:20,color:r===0?'#FFFFFF':'#17324D',bold:r===0};
 if(r>0)cell.fill='#FFFFFF';
}
// The existing native bar chart already contains these same rounded CSV values.
// Keep its original native chart part intact and verify the values before transplant.
const chartRecord=records.find(r=>r.slide===15&&r.kind==='chart');
const chart=deck.resolve(chartRecord.id);
const actual=chart.series.getItemAt(0).values;
const expected=['FIXED_0P9','PERIODIC_SCAN','P_AND_O'].map(s=>Number(audit.integrated.find(r=>r.strategy===s).mean_recovery_time_ms_penalized.toFixed(1)));
if(JSON.stringify(Array.from(actual))!==JSON.stringify(expected))throw Error('Original slide15 chart does not match current data');
add(15,'recovery-axis-title','平均恢复指标（ms，含惩罚）',pt(800,123,400,34),21,'#17324D',true,'center');
named(15,'矩形: 圆角 7').position=pt(72,496,1118,146);
edit(15,'矩形 8','尾段误差仅统计选定控制样本，不能代表全时段功率损失。\n未通过段按800 ms计入平均恢复指标，不能据此单独排序。\n硬越限为保护处理后保存样本的统计，与HARD_TRIP次数不同。',
 pt(98,515,1066,108),22,'#17324D',false,'left');

for(const n of CHANGED){
 const text=notes[n].join('\n\n');
 slide(n).speakerNotes.textFrame.setText(text);slide(n).speakerNotes.setVisible(true);
 await fs.writeFile(`${BUILD}/第${n}页_讲稿.txt`,text);
 await fs.writeFile(`${BUILD}/page${n}-edited.layout.json`,await (await slide(n).export({format:'layout'})).text());
}
const exportedPath=`${BUILD}/artifact-edited.pptx`;
await(await PresentationFile.exportPptx(deck)).save(exportedPath);
const original=await JSZip.loadAsync(sourceBytes);
const exported=await JSZip.loadAsync(await fs.readFile(exportedPath));
const resolveTarget=(part,target)=>target.startsWith('/')?target.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(part),target));
for(const n of CHANGED){
 const part=`ppt/slides/slide${n}.xml`, relPart=`ppt/slides/_rels/slide${n}.xml.rels`;
 const srcR=parseXml(await original.file(relPart).async('string'));
 const newR=parseXml(await exported.file(relPart).async('string'));
 const srcRels=elements(srcR,'Relationship'),newRels=elements(newR,'Relationship');
 const oldRelation=type=>srcRels.find(r=>r.attributes.Type.endsWith(`/${type}`));
 const newRelation=type=>newRels.find(r=>r.attributes.Type.endsWith(`/${type}`));
 const doc=parseXml(await exported.file(part).async('string'));
 const pics=elements(doc,'blip');
 if(n!==15){
   if(pics.length!==1)throw Error(`Unexpected picture count on ${n}`);
   pics[0].attributes['r:embed']=oldRelation('image').attributes.Id;
   const media=`ppt/media/page${n}_current_control_20260906.png`;
   oldRelation('image').attributes.Target=`/${media}`;
   original.file(media,await exported.file(resolveTarget(part,newRelation('image').attributes.Target)).async('uint8array'));
   original.file(relPart,writeXml(srcR));
 }else{
   const charts=elements(doc,'chart');if(charts.length!==1)throw Error('Expected one native slide15 chart');
   charts[0].attributes['r:id']=oldRelation('chart').attributes.Id;
 }
 original.file(part,writeXml(doc));
 original.file(resolveTarget(part,oldRelation('notesSlide').attributes.Target),await exported.file(resolveTarget(part,newRelation('notesSlide').attributes.Target)).async('uint8array'));
}
const candidate=`${BUILD}/candidate.pptx`;
await fs.writeFile(candidate,await original.generateAsync({type:'uint8array',compression:'DEFLATE'}));
await fs.writeFile(`${BUILD}/output_config.json`,JSON.stringify({ROOT,WORK,BUILD,OUT,SOURCE,FINAL,CHANGED,candidate},null,2));
const {finalizePresentation}=await import(pathToFileURL(`${SKILL}/container_tools/artifact_tool_utils.mjs`).href);
try{
 await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath:FINAL,pythonExecutable:PYTHON,
  integrityValidatorPath:`${SKILL}/container_tools/inspect_presentation_package_integrity.py`,
  layoutValidatorPath:`${SKILL}/container_tools/inspect_presentation_layout_geometry.py`,
  explicitTotalSlideCount:28,requiredNativeTableOwnerSlides:[15],requiredNativeChartOwnerSlides:[15],nativeChartTargetApplication:'powerpoint',
  layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],
  fontPolicy:{basis:'reference',families:['Calibri'],referencePath:SOURCE,referenceSha256:createHash('sha256').update(sourceBytes).digest('hex')},
  verifyArtifactToolImport:true,receiptPath:`${BUILD}/finalizer-validation.json`});
 console.log(JSON.stringify({final:FINAL,status:'FINALIZED'}));
}catch(error){
 if(!String(error).includes('EPERM'))throw error;
 await fs.writeFile(`${BUILD}/finalizer-environment-limit.json`,JSON.stringify({message:String(error),action:'Run immutable packaged validators in the directly invoked bundled Python process'},null,2));
 console.log(JSON.stringify({candidate,status:'DIRECT_VALIDATION_REQUIRED',reason:'Node spawnSync EPERM'}));
}
