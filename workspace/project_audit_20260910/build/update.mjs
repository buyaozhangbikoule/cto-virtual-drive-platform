import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import JSZip from 'jszip';
import xmljs from 'xml-js';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const R='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const D=`${R}/project_audit_20260910`,B=`${D}/build`,O=`${D}/output`,P=`${R}/CTO_virtual_drive_platform_v2_1`;
const SOURCE=`${R}/ppt_energy_update_20260909/output/CTO组会汇报_第14与15页评价更新_2026-09-09.pptx`;
const SKILL='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const PYTHON='C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const report=`${P}/docs/验收缺口与版本边界_20260910.md`;
const replacements=JSON.parse(await fs.readFile(`${B}/reference_replacements.json`,'utf8'));
const notes=JSON.parse(await fs.readFile(`${B}/notes.json`,'utf8'));
// Mapping is display order -> original slide part number. P&O becomes an extension.
const order=Array.from({length:28},(_,i)=>i+1);[order[13],order[22]]=[order[22],order[13]];[order[14],order[23]]=[order[23],order[14]];
const number=Object.fromEntries(order.map((old,i)=>[old,i+1]));
const deck=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const rec=(await deck.inspect({kind:'slide,textbox,shape,image,table,chart,notes,layout',maxChars:500000})).ndjson.trim().split('\n').map(JSON.parse);
await fs.writeFile(`${B}/before.ndjson`,rec.map(r=>JSON.stringify(r)).join('\n'));
const touched=new Set();
const slide=n=>deck.resolve(rec.find(r=>r.kind==='slide'&&r.slide===n).id);
function txt(n,name,value,pos,size=23,color='#17324D',bold=false){
 const r=rec.find(r=>r.slide===n&&r.name===name&&['textbox','shape'].includes(r.kind));if(!r)throw Error(`${n} ${name}`);
 const o=deck.resolve(r.id);o.text=value;if(pos)o.position=pos;
 o.text.style={typeface:'Calibri',fontSize:size,bold,color,autoFit:'none',alignment:'left',verticalAlignment:'middle',insets:{top:0,bottom:0,left:0,right:0}};
 touched.add(n);return o;
}
function title(n,value,size=34){const name=rec.find(r=>r.slide===n&&r.name?.startsWith('title-')).name;return txt(n,name,value,null,size,'#17324D',true);}
function add(n,name,value,pos,size=21,color='#17324D',bold=false){
 const o=slide(n).shapes.add({name,geometry:'textbox',position:pos,fill:'none',line:{fill:'none',width:0}});o.text=value;
 o.text.style={typeface:'Calibri',fontSize:size,bold,color,autoFit:'none',insets:{top:0,bottom:0,left:0,right:0}};touched.add(n);return o;
}
function cell(n,row,col,value,size=20){const t=deck.resolve(rec.find(r=>r.slide===n&&r.kind==='table').id);t.cells.set(row,col,value);
 t.getCell(row,col).text.style={typeface:'Calibri',fontSize:size,bold:row===0,color:row===0?'#FFFFFF':'#17324D'};touched.add(n);return t;}
function footer(n,value){txt(n,'矩形 3',value,{left:72,top:688,width:1065,height:20},11.5,'#5F6B76');}

// Correct a pre-existing off-slide placement; preserve the original curve bitmap.
deck.resolve(rec.find(r=>r.slide===10&&r.kind==='image'&&r.name==='图片 22').id).position={left:90,top:155,width:843.65,height:205};
txt(10,'文本框 6','基准场景：最大功率点 ≈ 最小反射点',{left:320,top:126,width:615,height:28},21,'#17324D');
add(10,'criteria-shared-frequency-axis','两图共同扫频范围：0.84–0.96 MHz（线性轴）；步长0.5 kHz',
 {left:100,top:625,width:850,height:34},21,'#5F6B76');
title(12,'历史保护示例：保存样本受限，不代表采样间隙无越限');
txt(12,'矩形 17','历史主线时序\n后续修正见扩展页',null,19);
footer(12,'假设BVD模型，非实测    历史固定／扫频／P&O示例 a734eca013；非正式三策略验收表');
title(13,'已接入电压、电流保护，但完整约束验收尚未闭合');
txt(13,'矩形 9','历史保存样本审计',null,27,'#17324D',true);
txt(13,'矩形 10','1795条记录\n峰值Vpp = 130 V\n峰值电流 = 5.124 mA\n保存样本硬越限 = 0',null,23);
txt(13,'矩形 12','功率相对上限待定义\n反射代理未设独立上限\n逐点保护待正式集成\n采样间隙风险未解决',null,23);
txt(13,'矩形 14','保护后准稳态样本受限 ≠ 延迟、保持区间和实际瞬态绝不越限',null,24,'#FFFFFF',true);
footer(13,'假设BVD电学模型    旧主线与E01/E02实验分支分开审计；未声称硬件安全');

// Promote phase methodology without claiming a new formal comparison.
title(23,'计划策略三：相位闭环已实现，但固定相位不保证功率最优');
txt(23,'矩形 6','测点：匹配网络输入端\nφin = arg(Zin)',{left:850,top:145,width:340,height:70},24);
txt(23,'矩形 7','基准功率峰相位\n目标 −1.0782°',{left:865,top:242,width:310,height:76},27,'#17324D',true);
txt(23,'矩形 8','历史增益5 / 50 / 100 Hz/°\n方向由局部dφ/df决定',{left:850,top:335,width:340,height:62},21);
txt(23,'矩形 10','50、100 Hz/°各有1段\n相位误差小但功率较低\nP_Rm < 0.95 P*',{left:872,top:442,width:296,height:91},22,'#B23A35');
footer(23,'假设BVD模型；历史相位增益试验    固定目标不随扰动场景重新标定；统一验收仍待完成');
add(23,'phase-plot-scope','左图：K=5 Hz/°历史时序；右侧错误锁定计数来自全增益表。',
 {left:130,top:642,width:1040,height:28},19,'#5F6B76');

// Existing numerical supplement has incompatible windows: replace ranking with status table.
title(24,'正文三策略恢复计划书组合，统一验收仍是未完成项');
const status=[['计划书策略','已有控制实现','已有时序证据','统一正式指标','本次状态'],
 ['固定频率','0.9 MHz\n共同保护','代表扰动段','待同口径重评','不作新排名'],
 ['周期扫频','离散局部寻峰\n共同保护','代表扰动段','待同口径重评','不作新排名'],
 ['相位误差闭环','输入相位跟踪\n增益试验','历史补充表','窗口／判据待统一','不作新排名']];
let t;
for(let r=0;r<4;r++)for(let c=0;c<5;c++)t=cell(24,r,c,status[r][c],r===0?23:23);
t.position={left:72,top:170,width:1118,height:285};
for(let c=0;c<5;c++)t.columns.get(c).width=[195,245,220,238,220][c];
add(24,'formal-status-subtitle','已有相位表明确标注 NOT_FORMAL_RANKING；本页仅报告实现进展，正式排名待补齐。',
 {left:72,top:120,width:1136,height:36},21,'#5F6B76');
txt(24,'矩形 8','必须统一：源与模型、扰动日程、状态资格、功率参考、连续验收及扫描时间成本。\n相位闭环表现不佳也是结果；扫描辅助P&O作为第四种扩展方法，不替代计划策略。',
 {left:100,top:529,width:1060,height:70},22,'#17324D');
add(24,'coverage-note','覆盖缺口：34个静态登记场景，旧主控制序列仅含其中7个不同场景。',
 {left:86,top:644,width:1105,height:28},21,'#B23A35');
footer(24,'计划书正式组合：固定频率／周期扫频／相位闭环    本次未运行新的统一闭环验收');

// Previous latest P&O and energy pages are preserved as extensions, not overwritten by older plots.
footer(14,'扩展P&O试验，非实测    第三轮 cdde9dab61；第12/24页为旧批次，不能拼成同一运行');
footer(15,'扩展方法比较，非实测    旧批次 a734eca013；与第23页后续无PI候选分开评价');
title(15,'扩展比较：尾段误差为零，仍存在全过程电能损失');

title(18,'电学建模与控制原型已有证据，计划书验收尚未全部完成');
txt(18,'矩形 7','已有证据',null,28,'#17324D',true);
txt(18,'矩形 8','v2.1匹配与双线核对\n34个场景静态登记\n低／中／高组合静态验证\n选频、保护与控制原型\n电—声接口EA_IF_V1.0',null,23);
txt(18,'矩形 9','本月仍需补齐',null,28,'#B23A35',true);
txt(18,'矩形 10','固定／扫频／相位统一验收\n完整单因素与组合闭环\n逐点保护正式集成\n功率与反射验收合同\n采样间隙与全程电能评估',null,22);
txt(18,'矩形 11','后续外部验证',null,28,'#17324D',true);
txt(18,'矩形 12','实测阻抗与BVD辨识\n电压／电流／功率标定\n结构声场与网格收敛\n水听器声场验证\n不作治疗或安全外推',null,23);
footer(18,'假设BVD电学模型    不能把静态扫描齐全、实验分支通过或接口PASS等同于全部验收完成');

title(19,'备份：用户工作要求与假设模型／控制参数分别登记');
cell(19,4,0,'电流目标／硬限',20);cell(19,4,1,'约5 / 6',20);cell(19,4,3,'用户量级；RMS与6为假设',18);
cell(19,8,3,'按假设fs、Qm、Rm反推',18);
cell(19,9,0,'戴维南源Rs',20);cell(19,9,3,'假设源阻抗，非完整功放',18);
add(19,'threshold-classification','130 Vpp / 5.5 mA为假设软阈值；160 Vpp是用户给定边界，不是实测器件额定值。',
 {left:100,top:643,width:1080,height:30},20,'#5F6B76');
title(20,'备份：Rm派生Qm已修正；静态覆盖不等于闭环覆盖');
txt(20,'矩形 7','历史代表性控制序列',null,27,'#17324D',true);
add(20,'rm-qm-correction','Rm-only：+15% / +30% / +50% → Qm = 695.7 / 615.4 / 533.3\nLm、Cm未改；34场景×2001频点回归，电学响应数组修正前后完全一致。',
 {left:100,top:594,width:1080,height:64},22,'#17324D');
footer(20,'本次只修正派生字段与描述，非新LTspice仿真    完整同口径闭环覆盖仍待补齐');
cell(22,2,1,'min |arg Zin|',22);
title(25,'备份：已有真实历史GUI证据，须标明日期与覆盖场景');
txt(25,'矩形 9','历史基准：2026-08-15｜LTspice 26.0.2.1；非全部当前场景截图',
 {left:130,top:580,width:1020,height:43},22,'#17324D',true);
footer(25,'GUI副本cir/raw/log与当时记录哈希一致；本次没有重新运行或截取LTspice界面');
title(26,'备份：正式比较需冻结以下口径，尚未统一重跑');
const metricRows=[['指标','拟统一的正式口径（不是新仿真结果）'],
 ['安全最优P*','同场景、同幅度权限与约束；仅作离线评价参考'],
 ['稳态窗口','98%以上、NORMAL且频率未冻结、连续10控制样本'],
 ['恢复与缺失','报告序列起点及第10样本确认；未通过单列，稳态记NA'],
 ['全程电能','相同时间区间积分，计入扫描、试探与保护降幅'],
 ['安全与饱和','分开报告保存样本、保持区间；电压／电流／频率边界'],
 ['功率／反射合同','明确上限对象、参考分母、阈值及无可行点处置']];
for(let r=0;r<7;r++)for(let c=0;c<2;c++)cell(26,r,c,metricRows[r][c],r===0?23:22);
txt(26,'矩形 6','不降低98%门槛、不延长原0.8 s扰动段、不取消异常检测、不提高160 Vpp边界。\n独立PI不是必需项；无积分控制时，“积分饱和”标为不适用。',
 {left:105,top:592,width:1070,height:67},22,'#B23A35');
title(27,'备份：修复引用并保留版本证据，不覆盖历史运行');
txt(27,'矩形 19','10处失效引用已定位支撑材料；涉及9页',null,27,'#17324D',true);
txt(27,'矩形 20','新修订清单与历史 evidence_manifest.csv 分开',
 {left:200,top:480,width:890,height:43},23,'#17324D');
txt(27,'矩形 21','旧清单154项：151一致，0丢失，3项修改；旧哈希不代表新文件',
 {left:128,top:552,width:1040,height:70},23,'#5F6B76');

for(const old of [14,15,23,24])txt(old,'矩形 4',String(number[old]),null,12,'#5F6B76');

// Notes: retain supported content, remove invalid claims and repair exact references.
for(const [key,value] of Object.entries(notes)){
 let s=value;
 for(const m of replacements)s=s.replaceAll(m.old_path,m.resolved_path);
 s=s.replaceAll('第14页','第23页').replaceAll('第15页','第24页');
 notes[key]=s;
}
notes['1']=notes['1'].replace('本月完成的是假设BVD模型下的电学建模、匹配、扰动与带约束控制验证','本月已有假设BVD电学建模、匹配、扰动与控制原型证据；原计划统一三策略验收尚待完成');
notes['6']=notes['6'].replaceAll('相位控制消融','相位闭环试验');
notes['7']=notes['7'].replace('使安全功率峰约下移','使冻结源功率峰约下移');
notes['7']+='\n【2026-09-10派生字段修正】Rm-only固定Lm、Cm，Qm随Rm增大下降。此前登记仍为800属于派生字段错误。三档已改为695.6522、615.3846、533.3333；回归确认曲线与功率未改变，不需用暗改Lm来保持Qm。';
notes['10']=notes['10'].replace('它作为计划书要求的消融对照，用基准最大功率点相位作目标并加入局部斜率符号；正式推荐策略仍是直接以功率为目标的扫描辅助P&O。','相位误差闭环是计划书规定的第三种正式比较方法。历史实现采用基准功率峰相位目标与局部斜率符号；它可能锁到较低功率点，这也是需要报告的结果。P&O保留为第四种扩展方法，未统一评价前不宣称哪种总体更优。');
notes['10']+='\n【原图范围】两张图是原共享频率轴四联图的前两面板，原面板本身未重复标注横轴数值；本次补充共同0.84–0.96 MHz线性频率范围与0.5 kHz步长。图像像素不改动。';
notes['12']=notes['12'].replace('本页与后两页使用同一份保存的控制数据','本页与当前第24页使用同一旧批次保存控制数据');
notes['14']=notes['14'].replaceAll('第12、15页','第12、24页');
notes['12']+='\n【版本纠偏】本图保留旧批次a734eca013的固定／扫频／P&O时序，只说明历史保护动作，不作为计划书固定／扫频／相位的正式比较。后续E01/E02已经在隔离实验中逐扫描点调用保护并同步幅度；尚不能把这一改进描述成正式主线已全部集成。';
notes['13']=[
 '【建议时长】约50秒',
 '【逐字讲稿】当前控制并非只找峰，已经接入频率、电压、电流和幅度约束。但这里必须区分约束机制存在与硬安全已经证明。历史主线1795条保存记录中，电压最高130 Vpp、电流最高约5.124 mA，保存样本硬越限为零；这些是已知模型预览与保护处理后的准稳态结果，不等于采样间隙或实际瞬态永远不越限。',
 '【实现缺口】旧主线扫描点与普通控制样本的保护调用仍不完全一致。E01/E02后续隔离实验已经修正这一点，但仍需正式集成与三策略回归。第23页后续候选的保持指令重放仍检出188.2 Vpp，因此不能宣称硬限完成。',
 '【约束合同】功率相对上限的分母及数值未冻结；反射代理目前用于检测，不是独立硬限。线性网络固定频率下，降幅不改变Zin和Gamma，不能把降幅等同于恢复匹配。若加入反射上限却无可行频点，需预先定义降额待机或停机，不得无限重扫后称为受限。',
 '【答疑】独立PI不是必须；当前目标是最大功率，调频与安全降额是可研究的架构。无积分器时，积分饱和为不适用。',
 '【模糊推测内容】补齐接口与延迟模型可能改善鲁棒性，效果尚待同条件仿真，不是本页已验证结论。',
 `[Sources]\n${report}\n${P}/results/audits/constrained_control_audit.json\n${R}/control_feasibility_20260907/run_experiments.py`
 ].join('\n\n');
notes['23']=notes['23'].replace('【建议时长】答疑50秒','【建议时长】约60秒')+'\n【正文身份】这是计划书第三种策略的历史方法证据，不是以P&O代替相位的理由。三策略正式同口径排名待完成。';
notes['23']=notes['23'].replace('增益5 Hz每度较平稳；','左图展示增益5 Hz每度的历史时序；');
notes['22']=notes['22'].replace('最大功率频率定义为受电压电流约束下P_Rm最大的频点','本页离线选频的最大功率频率是在冻结源曲线上使P_Rm最大的频点；正式控制还必须考虑电压电流与允许幅度约束，两者不能混用');
notes['24']=[
 '【建议时长】约60秒',
 '【本页结论】恢复计划书三种方法，诚实区分“算法已经实现”与“统一验收已经完成”。',
 '【逐字讲稿】本项目正式比较应是固定频率、周期扫频和相位误差闭环。三者都有既有实现或历史时序证据，但目前相位补充表的窗口和部分判据与另外两种策略不完全一致，文件也明确标为不用于正式排名。因此本页不再摆出貌似可比的误差和恢复时间排序，而是列出真实进展。下一步需要统一源、模型、扰动日程、保护接口和评价器，再对完整场景重跑。相位性能不佳同样是有效结果，不必换成P&O才汇报。',
 '【历史数据保留】原补充CSV仍保存固定30.14%、周期扫频0%、相位K5约39.91%的描述性尾段误差。它们不构成此次新正式排名；旧文件未删除或改写。原相位排名柱图从正文移除，避免与本页进度表混淆；源PPT保留。',
 '【覆盖】静态登记34场景，旧主控制序列8段、7个不同场景；低中组合、Lm-only、Cm-only等完整闭环仍缺。不能从静态LTspice一致性推断闭环全覆盖。',
 '【教授可能追问】那本月三策略比较算完成了吗？',
 '【建议回答】实现与代表性试验已有基础，按原计划同口径、全场景的正式验收还没有完成。这一项明确列为本月未完成工作，P&O作为第四种扩展，不替代它。',
 '【模糊推测内容】无；本页是文件和程序状态审计，不预测最终策略排名。',
 `[Sources]\n${P}/results/tables/stage4_5/plan_fixed_periodic_phase_integrated.csv\n${O}/静态与闭环覆盖核查.csv\n${report}`
 ].join('\n\n');
notes['18']=[
 '【建议时长】约50秒',
 '【逐字讲稿】总结时需要收窄“已完成”的范围。电学建模、匹配交叉验证、单因素与组合静态扫描、控制原型以及电声接口已有证据。Rm派生Qm的登记错误本次已经修正，确认没有改变电学响应。但原计划固定、扫频、相位的统一验收、完整闭环场景、正式集成逐点保护及功率反射合同仍未完成；采样间隙越限也尚未解决。只有这些内部验收补齐之后，才能进一步讨论模型外部有效性。实测阻抗、功率标定、结构声场和水听器属于后续验证，不能用这些尚未开展的工作掩盖当前代码与评价缺口。',
 '【答疑】当前项目可汇报为“可复现的电学仿真平台及控制原型，原计划统一验收尚待收尾”，不能写全部完成。结论只限特定BVD与扰动范围内的电学稳定性。',
 '【模糊推测内容】无；本页为完成状态核查。',`[Sources]\n${report}\n${O}/Rm派生Qm修正验证.json\n${O}/静态与闭环覆盖核查.csv`
 ].join('\n\n');
notes['19']+='\n【来源细分】0.8–1.0 MHz、起点0.9 MHz、约100 Vpp与160 Vpp边界来自用户。约5 mA是用户给定量级，解释为RMS是仿真假设。6 mA硬限、130 Vpp/5.5 mA软阈值、50 Ω戴维南源与控制增益周期属于假设，不是器件额定值。160 Vpp不能写成助手任意提出的阈值。';
notes['20']=notes['20'].replace('右侧是所有策略共同经历的绝对时间扰动序列','右侧是历史固定／扫频／P&O主批次共同使用的代表性扰动序列').replace('统一时间序列保证策略公平比较','完整覆盖及同口径评价仍需补齐');
notes['20']+='\n【派生量修正】Rm仅增加15%、30%、50%时，Qm由800分别变为695.6522、615.3846、533.3333。只修正登记和生成代码；Lm、Cm不变，34场景×2001频点电学数组完全一致。组合场景按其登记的联合构造重算Lm/Cm并保留Qm800，不是简单叠加原始元件单因素变体。';
notes['21']=notes['21'].replace('这里能够排除主要代码实现错误','这显著降低了两套静态求解实现存在主要差异的可能性');
notes['21']+='\n【覆盖边界】此页是静态LTspice交叉验证，不能代表低中高组合均已通过相位在内的统一闭环验收。本次没有重跑这些LTspice场景。';
notes['25']=[
 '【建议时长】答疑约35秒',
 '【逐字讲稿】不是没有真实GUI截图，而是已有历史基准截图。元数据记录采集于2026年8月15日，LTspice版本26.0.2.1。本次复核相应GUI副本cir、raw、log，三份哈希均与当时记录一致。这些截图只能说明对应基准场景的历史运行痕迹，不能充当全部当前参数和所有控制版本的新界面证明。',
 '【证据边界】GUI辅助展示；数值复核依靠网表、RAW、日志与独立解析误差。哈希证明与登记版本的一致性，不证明物理真实性或求解必然正确。本次未新开LTspice，未生成新GUI截图。',
 '【模糊推测内容】无。',`[Sources]\n${R}/outputs/v2_self_consistent_rebuild/active_stage3_5/ltspice_gui_evidence/LTspice_GUI_evidence_metadata.json\n${O}/历史GUI证据核查.json`
 ].join('\n\n');
notes['26']=[
 '【建议时长】答疑约50秒',
 '【本页身份】这是待统一实施的正式评价合同，不是声称当前三个策略已经采用完全相同评价器。',
 '【逐字讲稿】正式重跑首先固定评价口径。安全最优P星必须使用同场景、同幅度权限和同约束，仅供离线评价，不能泄漏给控制器。保持原98%门槛与连续10个NORMAL、频率未冻结的控制样本。恢复同时报告合格序列起点与第10个样本的确认时刻；段内不满足就写未通过。没有合格稳态窗口时写NA，不能以回退样本伪装稳态通过。旧数据的描述性尾段统计保留在扩展页。',
 '【过程指标】同一时间区间积分，纳入扫描、试探与保护恢复。分别统计保存样本和保持区间的电压电流极值、越限与频率饱和；不将已知模型的预览保护称为硬件无延迟保证。功率相对上限与反射上限仍需明确限制对象、分母、阈值及无可行点处置。',
 '【参数来源】160 Vpp为用户给定边界；130 Vpp、5.5/6 mA和98%连续10样本属于本次假设控制／验收参数。独立PI非必须；没有积分器时，积分饱和不适用。',
 '【模糊推测内容】统一口径后各策略排名可能变化，当前不能预测结论。',`[Sources]\n${report}`
 ].join('\n\n');
notes['27']=[
 '【建议时长】答疑约40秒',
 '【逐字讲稿】本次追溯以9月9日最新版完整PPT为输入，查到10处失效引用、涉及9页，而不是直接沿用旧版本的12处。已定位用户原始文档及实际存在的审计、汇总文件；错误命名的CSV改引真正支撑说明的JSON或CSV，并不是假装找回不存在的同名文件。修订路径表逐项保留旧路径、替代路径和当前哈希。',
 '【版本】旧平台证据清单154项中151项一致、0项丢失、3项在本次元数据修正后改变。旧清单不覆盖更新，另存修订清单和原文件备份。旧控制、RAW、截图与原PPT仍保留，不能用新文件冒充旧批次。',
 '【复现边界】本次执行的是Python元数据回归、文件与PPT审核，不是全流程重新运行；统一三策略验收与真实多物理场仍待完成。',
 '【模糊推测内容】无。',`[Sources]\n${O}/引用路径修正表.csv\n${O}/历史哈希清单核查.csv\n${P}/results/manifests/evidence_manifest.csv\n${report}`
 ].join('\n\n');

// Do not allow a legacy recommendation in notes to reinstate P&O as planned strategy three.
for(let n=1;n<=28;n++){
 if([12,14,15].includes(n))notes[n]+='\n【计划书组合】本页属于历史示例或第四种P&O扩展，正文正式三策略仍为固定／扫频／相位；不能以本页结果替代统一验收。';
 slide(n).speakerNotes.textFrame.setText(notes[n]);slide(n).speakerNotes.setVisible(true);
}
await fs.writeFile(`${O}/逐页讲解稿_计划书口径修订.txt`,order.map((old,i)=>`第${i+1}页（原第${old}页）\n${notes[old]}`).join('\n\n'+'='.repeat(60)+'\n\n'));
await fs.writeFile(`${B}/revised_notes.json`,JSON.stringify(notes,null,2));
await(await PresentationFile.exportPptx(deck)).save(`${B}/authored.pptx`);

// Preserve original images/chart XML, relationships, and all non-target slide parts.
const parse=t=>xmljs.xml2js(t,{compact:false}),serial=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function els(root,name){const out=[];function visit(n){if(n.type==='element'&&n.name.split(':').at(-1)===name)out.push(n);for(const a of n.elements??[])visit(a);}visit(root);return out;}
const resolve=(p,t)=>t.startsWith('/')?t.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(p),t));
const sourceBytes=await fs.readFile(SOURCE),z=await JSZip.loadAsync(sourceBytes),e=await JSZip.loadAsync(await fs.readFile(`${B}/authored.pptx`));
const expectedChanges=[];
for(let n=1;n<=28;n++){
 const part=`ppt/slides/slide${n}.xml`,rp=`ppt/slides/_rels/slide${n}.xml.rels`;
 const or=parse(await z.file(rp).async('string')),er=parse(await e.file(rp).async('string'));
 if(touched.has(n)){
  const original=parse(await z.file(part).async('string')),edited=parse(await e.file(part).async('string'));
  const origRoot=els(original,'sld')[0],editRoot=els(edited,'sld')[0];
  for(const [key,value] of Object.entries(origRoot.attributes??{}))if(key.startsWith('xmlns:'))editRoot.attributes[key]??=value;
  const origPics=els(original,'pic');let pi=0;
  if(n===10){const pic=origPics.find(x=>els(x,'cNvPr')[0]?.attributes.name==='图片 22');
   if(!pic)throw Error('Slide 10 baseline image');els(pic,'off')[0].attributes.x=String(90*9525);}
  for(const tree of els(edited,'spTree'))tree.elements=tree.elements.map(x=>x.name?.split(':').at(-1)==='pic'?origPics[pi++]:x);
  if(pi!==origPics.length)throw Error(`Image count ${n}`);
  if(n===24){
   for(const tree of els(edited,'spTree'))tree.elements=tree.elements.filter(x=>!(x.name?.split(':').at(-1)==='graphicFrame'&&els(x,'chart').length));
   const root=els(or,'Relationships')[0];root.elements=root.elements.filter(x=>!x.attributes?.Type?.endsWith('/chart'));
   z.file(rp,serial(or));expectedChanges.push(rp);
  }
  z.file(part,serial(edited));expectedChanges.push(part);
 }
 const oldNote=els(or,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
 const newNote=els(er,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
 const np=resolve(part,oldNote.attributes.Target);
 z.file(np,await e.file(resolve(part,newNote.attributes.Target)).async('uint8array'));expectedChanges.push(np);
}
const pdoc=parse(await z.file('ppt/presentation.xml').async('string'));
const ids=els(pdoc,'sldId');els(pdoc,'sldIdLst')[0].elements=order.map(n=>ids[n-1]);
z.file('ppt/presentation.xml',serial(pdoc));expectedChanges.push('ppt/presentation.xml');
// Update app's ordered title list using current slide titles, preserving themes and slide parts.
const candidate=`${B}/candidate.pptx`,final=`${O}/CTO组会汇报_计划书口径与验收缺口修订_2026-09-10.pptx`;
await fs.writeFile(candidate,await z.generateAsync({type:'uint8array',compression:'DEFLATE'}));
const sha=createHash('sha256').update(sourceBytes).digest('hex');
const contract={source:SOURCE,sourceSha256:sha,order,visibleTouched:[...touched],expectedChanges,
 outputs:[{candidate,final,count:28}],noNewSimulation:true,noNewGUI:true,allExistingMediaPreserved:true};
await fs.writeFile(`${B}/contract.json`,JSON.stringify(contract,null,2));
const {finalizePresentation}=await import(pathToFileURL(`${SKILL}/container_tools/artifact_tool_utils.mjs`).href);
try{await finalizePresentation({workspaceDir:D,candidatePath:candidate,finalPath:final,pythonExecutable:PYTHON,
 integrityValidatorPath:`${SKILL}/container_tools/inspect_presentation_package_integrity.py`,
 layoutValidatorPath:`${SKILL}/container_tools/inspect_presentation_layout_geometry.py`,explicitTotalSlideCount:28,
 requiredNativeTableOwnerSlides:[15,19,22,24,26],
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--validate-bullet-geometry'],
 fontPolicy:{basis:'reference',families:['Calibri'],referencePath:SOURCE,referenceSha256:sha},
 verifyArtifactToolImport:true,receiptPath:`${B}/finalizer.json`});}
catch(err){await fs.writeFile(`${B}/finalizer-error.json`,JSON.stringify({message:err.message,code:err.code},null,2));console.log('Packaged validators require direct-process fallback:',err.message);}
console.log(JSON.stringify({candidate,touched:[...touched],order}));
