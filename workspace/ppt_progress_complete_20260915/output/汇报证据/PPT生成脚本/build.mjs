import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {Presentation,PresentationFile,FileBlob} from '@oai/artifact-tool';
import JSZip from 'jszip';
import xmljs from 'xml-js';
const B=path.dirname(fileURLToPath(import.meta.url)), W=path.dirname(B), R=path.dirname(W);
const source=`${R}/ppt_control_progress_20260914/output/CTO组会汇报_仅第15页更新_2026-09-15.pptx`;
const platform=`${R}/CTO_virtual_drive_platform_v2_1`;
const replay=`${R}/ltspice_transient_replay_20260911_continue`;
const feedback=`${platform}/results/ltspice_closed_loop/CL_20260914_124949_410d5f9d`;
const factorial=`${R}/control_factorial_20260907`;
const json=async f=>JSON.parse(await fs.readFile(f,'utf8'));
const sha=b=>createHash('sha256').update(b).digest('hex');
const session=await json(`${feedback}/session.json`), acceptance=await json(`${feedback}/reversal_acceptance.json`);
if(session.records.length!==5||!acceptance.feedback_reversal_passed)throw Error('Five-round evidence not confirmed');
for(let i=1;i<5;i++)if(session.records[i].command.frequency_hz!==session.records[i-1].next_command.frequency_hz)throw Error('Broken causal chain');
const csv=(await fs.readFile(`${factorial}/results/summary.csv`,'utf8')).trim().split(/\r?\n/).map(r=>r.split(','));
const data=csv.slice(1).map(r=>Object.fromEntries(csv[0].map((k,i)=>[k,r[i]])));
const rows=(v,s)=>data.find(r=>r.variant===v&&r.strategy===s&&Number(r.segment_duration_s)===.8);
const sourceDeck=await PresentationFile.importPptx(await FileBlob.load(source));
await fs.writeFile(`${B}/source.inspect.ndjson`,(await sourceDeck.inspect({kind:'slide,textbox,shape,image,table,notes,layout',maxChars:1000000})).ndjson);
const p=Presentation.create({slideSize:{width:1280,height:720}}), authored=[];
const navy='#17324D',blue='#2B70B5',gray='#5F6B76',red='#BE3A3A',teal='#167B88';
function tx(s,name,text,x,y,w,h,size=22,color=navy,bold=false){const q=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});q.text=text;q.text.style={typeface:'Calibri',fontSize:size,color,bold,autoFit:'none',verticalAlignment:'middle',insets:{top:0,bottom:0,left:0,right:0}};return q;}
function line(s,x,y,w,h=1,color='#C7D1DC'){s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:color,line:{fill:'none',width:0}});}
function slide(key,title,page,foot){const s=p.slides.add();s.background.fill='#F7F8FA';tx(s,'title',title,72,36,1136,57,32,navy,true);line(s,72,98,1136,3,navy);line(s,72,678,1136);tx(s,'scope',foot,72,687,1090,21,12,gray);tx(s,'page-number',String(page),1170,687,38,21,12,gray);authored.push({key,page,s});return s;}
function table(s,values,x,y,width,height,widths,size=21){const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width,height,columnWidths:widths,values});t.borders.assign({fill:'#D0D9E2',width:1});t.cells.block({row:0,column:0,rowCount:values.length,columnCount:values[0].length}).assign({margins:{left:10,right:10,top:6,bottom:6},anchor:'center',textStyle:{typeface:'Calibri',fontSize:size,color:navy}});for(let i=0;i<values.length;i++){t.rows[i].height=height/values.length;for(let j=0;j<values[0].length;j++){const c=t.getCell(i,j);c.fill=i===0?navy:i%2?'#FFFFFF':'#EAF1F5';c.text.style={typeface:'Calibri',fontSize:size,color:i===0?'#FFFFFF':navy,bold:i===0};}}return t;}
async function img(s,file,x,y,w,h,alt){s.images.add({blob:new Uint8Array(await fs.readFile(file)),contentType:file.endsWith('.jpg')?'image/jpeg':'image/png',alt,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
const notes={};
function note(s,key,text){notes[key]=text;s.speakerNotes.textFrame.setText(text);}

// New main page 3. Actual webpage screenshot, no synthetic UI.
{
const s=slide('platform','网页平台原型与操作流程',3,'2026-09-15真实网页截图    假设线性BVD参数，非实测数据    页面功能与物理验收分别报告');
tx(s,'sub','单场景交互计算、登记结果浏览与独立LTspice验证入口',72,119,1136,33,24,gray);
await img(s,`${B}/assets/platform_home.jpg`,72,166,768,432,'平台实际主页截图，未改写像素');
tx(s,'a','① 设定单场景参数',876,169,332,32,25,blue,true);
tx(s,'ad','修改C₀、Rₘ、Lₘ、Cₘ等\n计算当前频响和工作点',876,210,332,61,22);
tx(s,'b','② 查看电学结果',876,286,332,32,25,blue,true);
tx(s,'bd','源功率、端口功率、η_elec\n并列报告多个谐振特征点',876,326,332,61,22);
tx(s,'c','③ 浏览与验证',876,402,332,32,25,blue,true);
tx(s,'cd','登记场景、峰值趋势、P(f)\n调用AC验证，导出RAW证据\n另页查看LTspice逐轮反馈',876,442,332,94,22);
tx(s,'caption','截图基准：0.9000 MHz，P_Rm＝170.0 mW，P_source＝362.3 mW，η_elec＝46.92%',72,606,1136,30,21,navy,true);
tx(s,'limit','单场景滑块与“已登记结果”分区独立。η_elec只表示电学功率分配，不能解释为电声效率。',72,644,1136,26,18,gray);
note(s,'platform',`【建议时长】50秒\n【本页结论】脚本已经组织成可操作的网页原型，具备电学计算、登记结果浏览和真实LTspice验证入口。\n【讲稿】这页是实际网页截图。左侧可以修改单场景的BVD与匹配参数，主区显示当前功率峰位、机械支路有功功率，以及源功率、端口功率和电学功率分配比例。下方还分别报告谐振特征点，并提供登记场景的峰值趋势与完整频响。当前单场景随滑块重算，登记场景图反映已经冻结的正式数据，两者不能混淆。网页也有真实LTspice AC验证按钮和独立反馈验证页。这里展示的是软件原型，不代表实测设备或全部控制验收完成。\n【看图】先指左侧参数，再指主区0.9000 MHz、170.0 mW和46.92%，最后说明验证入口。\n【单位口径】P_source为戴维南理想源提供的有功功率。η_elec=P_port/P_source；图中输入相位arg(Zin)不等于端口V/I相位。原网页部分指标标签有省略号，完整字段以代码与导出表为准，未通过改写截图掩盖。\n【证据】${platform}/streamlit_app.py\n${platform}/pages/03_LTspice闭环验证.py\n${B}/assets/platform_home.jpg\n【边界】本次仅打开网页并读取历史结果，没有点击AC求解或新建反馈会话。所有器件参数是假设，非实测。`);
}
// New main page 17. Real LTspice GUI and actual tail comparison.
{
const s=slide('replay','真实LTspice瞬态重放：所选尾段与准稳态预测接近',17,'2026-09-11/12瞬态批次    历史P&O片段开环重放    仅固定fs−5%负载，不代表三策略完整闭环');
tx(s,'sub','重放原时序2.838–3.059 s的61条相交指令记录，保留原持续时间',72,116,1136,35,24,gray);
await img(s,`${replay}/GUI_20260912_replay_full.png`,72,173,735,378,'2026-09-12真实LTspice GUI，完整窗口');
tx(s,'legend','上两栏：频率与幅度命令　下两栏：瞬时电流与电压',72,563,735,30,19,navy);
tx(s,'aux','辅助节点V(f_mhz)以电压数值编码MHz，V(a_cmd)编码无量纲幅度a。',72,598,735,42,17,gray);
tx(s,'tail','尾段223–224 ms，0.8548 MHz，a＝1',842,159,366,55,23,blue,true);
table(s,[['指标','LTspice','Python'],['Vpp / V','96.5473','96.9773'],['I / mA RMS','4.9209','4.9531'],['P_Rm / mW','139.3401','140.2304']],842,226,366,206,[142,112,112],18);
tx(s,'error','所选尾段功率差异 0.635%',842,451,366,40,26,blue,true);
tx(s,'convergence','已核查50、10、5、2 ns步长\n50 ns结果未通过，保留失败记录\n另做1 ns选点核查',842,508,366,98,21);
tx(s,'caveat','截图时间轴含新增3 ms建立段。瞬时电流峰值不能直接与6 mA RMS比较。',72,643,1136,28,19,red);
note(s,'replay',`【建议时长】75秒\n【本页结论】对历史P&O的一段指令完成真实LTspice瞬态求解，所选稳态尾段与解析预测接近。\n【讲稿】前面主要是离散准稳态控制。为检查真实电路求解的瞬态响应，我们把历史P&O在2.838至3.059秒这一小段的频率、幅度指令送入LTspice。左图是实际软件窗口，上两栏是以辅助节点编码的指令，下两栏是LTspice求解的电流、电压载波。右表选取LTspice时间223至224毫秒的稳定尾段，对应0.8548 MHz和幅度1。机械支路有功功率为139.3401毫瓦，解析预测140.2304毫瓦，相对差异约0.635%。此前50纳秒步长未通过，缩小至2纳秒后才得到此结果，失败记录没有删除。该误差只属于这一统计窗口，不能作为全部瞬态的误差上界。\n【时间映射】原时序=LT时间+2.835 s；新增3 ms建立段不进入正式片段统计。固定fs−5%负载，没有重放2.4 s的负载突变，也没有完整0.8 s段或另外两策略。\n【关键限制】这是开环指令重放，LTspice结果不改变本段后续指令。不是闭环验收、实测、硬件安全或声学验证。图上约7 mA是瞬时峰值，不与6 mA RMS直接比较。50μs统计窗口最大129.994 Vpp和4.9296 mA RMS，无超限窗口不等于连续时间硬保护证明。\n【数值方法】最大步长2 ns，关闭压缩；112000514点、RAW约3.136 GB、批处理约691.6 s。幅度边沿1 ns为假设。日志内部solver elapsed与外部进程耗时不同。\n【证据】${replay}/运行与核查报告.md\n${replay}/PO_FS_M5_REPLAY_DT2NS.cir\n${replay}/PO_FS_M5_REPLAY_DT2NS.raw\n${replay}/PO_FS_M5_REPLAY_DT2NS.log\n${replay}/baseline_convergence.csv\n${replay}/finer_step_spotchecks.json\n${replay}/GUI_20260912_replay_full.png\n【统计差异】尾表为RAW后处理。日志.meas的功率0.139337 W与RAW139.3401 mW有采样积分末位差异，二者不可无解释地混用。`);
}
// New main page 18. Native table obtained directly from real session JSON.
{
const s=slide('feedback','五轮LTspice反馈：功率下降后反向指令已实际执行',18,'真实求解批次：CL_20260914_124949_410d5f9d    固定负载、低幅离线反馈接口检查');
tx(s,'sub','固定基准负载，a＝0.40，每轮电路时间1 ms，功率取末200 μs',72,116,1136,36,24,gray);
const vals=[['轮次','本轮频率\nMHz','RAW端口功率\nmW','下一条频率\nMHz']];
session.records.forEach((r,i)=>vals.push([String(i+1),(r.command.frequency_hz/1e6).toFixed(4),(r.measurement.p_port_W*1e3).toFixed(3),(r.next_command.frequency_hz/1e6).toFixed(4)]));
const t=table(s,vals,72,183,736,335,[90,206,224,216],23);
for(const row of [4,5])for(let c=0;c<4;c++)t.getCell(row,c).fill=row===4?'#F9E8E5':'#E3F0F2';
tx(s,'event','第4轮：功率下降',848,181,360,40,27,red,true);
tx(s,'eventdetail','27.187降至22.175 mW\nPython反转调频方向\n提出0.9000 MHz下一指令',848,233,360,102,23);
tx(s,'executed','第5轮：执行反向指令',848,363,360,40,27,teal,true);
tx(s,'executeddetail','LTspice以0.9000 MHz求解\n功率回到27.186 mW\n保留RAW、日志和前后指令哈希',848,417,360,102,23);
tx(s,'method','每轮重算完整指令历史，保留电路状态历史效应。单轮实际耗时约14–27 s，非实时控制。',72,552,1136,59,22);
tx(s,'limit','第5轮产生的0.8995 MHz尚未执行。本页不证明动态扰动追踪、连续稳态或全过程硬保护。',72,626,1136,43,21,red,true);
note(s,'feedback',`【建议时长】70秒\n【本页结论】真实RAW结果已影响下一条指令，并由后续LTspice求解实际执行，离线因果反馈链成立。\n【讲稿】这一页与上一页的区别在于，下一条指令不再预先给定，而由本轮LTspice输出决定。我们在固定基准负载、0.4倍幅度下完成五轮求解。第3轮在0.9000 MHz得到27.187毫瓦的端口功率，第4轮试探到0.9005 MHz后降至22.175毫瓦，Python据此反向。第5轮实际回到0.9000 MHz，得到27.186毫瓦。因此，反馈不仅计算出来，还在下一次求解中执行。每轮电路时间为1毫秒，但计算机实际求解要14至27秒，这是一项离线接口验证。\n【方法】每次从相同初态重算截至本轮的完整指令历史，并从新增末区间提取RAW反馈。没有用旧控制CSV替代新指令，也没有从解析扫频表读取最优频率。反馈采用P_port=平均v(t)i(t)，不是前面PRm指标统一重评。相位来自端口V/I基波，亦不同于历史相位闭环argZin。幅度全程a=.4，a不是端口电压比例在任意频率都恒定。\n【范围】固定负载无运行中突变，简单500Hz局部P&O，无全局峰值保证。第5轮生成899500Hz指令没有第6轮执行结果。会话COMPLETE仅表示达到5轮上限，不等于优化收敛。3ms建立段不计反馈，末200μs统计功率、50μs窗口检查保护。保护只能在求解结束后下达后续动作，不能撤销已经发生的越限。\n【证据】${feedback}/session.json\n${feedback}/config.json\n${feedback}/reversal_acceptance.json\n${feedback}/step_003/feedback.json\n${feedback}/step_004/stimulus.json\n各轮circuit.cir/.raw/.log、execution.json，完整链路相邻指令一致。\n【本次工作】读取2026-09-14既有会话，不重新启动LTspice。`);
}
// Completion replaces old page18 (new21).
{
const s=slide('completion','阶段完成度：平台与联算证据已补齐，统一验收仍有缺口',21,'汇报截止：2026-09-15    完成软件与电学验证不等于完成结构声场、器件测量或安全验证');
table(s,[['工作范围','当前已有证据','尚未完成／不能据此宣称'],['电学模型与匹配','v2.1自洽基线，Python/LTspice AC对照','真实器件参数辨识'],['静态扰动与选频','34个登记场景，单因素与组合扫描','全部场景的同口径闭环评估'],['网页平台','单场景计算、登记结果、AC及反馈入口','完整软件测试与硬件实时部署'],['控制与改进研究','控制原型，8组合＋2对照，已有部分验收','固定／扫频／相位的统一性能排名'],['LTspice瞬态与反馈','P&O片段重放，固定低幅五轮反馈','动态负载闭环、全过程约束证明'],['结构—声场连接','电学字段与声学回传模板已定义','ANSYS/COMSOL结构声场求解']],72,139,1136,391,[218,458,460],21);
tx(s,'next','下一步优先级',72,554,1136,36,25,blue,true);
tx(s,'nextdesc','统一三策略的统计窗口与场景覆盖，再核查扫描逐点保护、采样间隙风险及功率／反射约束。',72,603,1136,60,24);
note(s,'completion',`【建议时长】55秒\n【讲稿】截至9月15日，我们的完成内容已不只是脚本和几张曲线。已有自洽的BVD匹配模型、34个登记静态场景、可操作网页、控制原型和改进对照研究，并进一步取得真实LTspice瞬态重放及五轮离线反馈证据。但这些工作不能拼成一个“所有任务均通过”的结论。相位控制与固定、扫频仍未统一评价，全部单因素和组合场景还未进入同口径闭环，动态负载反馈和全过程硬限也未证明。结构声场目前只有接口。下一步应先补齐这些定义和验证缺口，而不是增加更多算法名称。\n【已有部分验收的含义】新实验版本在原0.8秒fs漂移段中部分通过连续窗口；历史主时序的未通过结果保留，不用新版本替换其成绩。消融见第26页，后续候选见第27页。\n【工程进度与科学边界】6mA硬限和软阈值是仿真假设，实物阻抗/功率/声场测量尚未做。所有结论只限于假设BVD电学范围。\n【证据】${platform}/streamlit_app.py\n${replay}/运行与核查报告.md\n${feedback}/reversal_acceptance.json\n${factorial}/deliverables/第二轮控制消融验证报告.md\n${platform}/results/tables/stage4_5/plan_fixed_periodic_phase_integrated.csv`);
}
// New backup26, 2^3 experiment plus phase ablations.
{
const s=slide('ablation','备份：算法消融显示，增加模块未带来一致收益',26,'2026-09-07独立实验批次    原0.8 s/段结果    非原历史主时序，非正式三策略统一排名');
tx(s,'sub','A：相位辅助　B：独立幅度PI　C：受约束选频；8种完整组合＋2种去相位对照',72,117,1136,39,22,gray);
const variants=['E02_000','E03_A','E04_B','E05_C','E06_AB','E07_AC','E08_BC','E09_ABC','D01_LOCAL','D02_LOCAL_BC'];
const labels=['000 对照','A','B','C','AB','AC','BC','ABC','仅局部功率','局部功率＋BC'];
const vals=[['版本','扫频通过\n段数/7','扫频电能\n捕获%','P&O通过\n段数/7','P&O电能\n捕获%']];
variants.forEach((v,i)=>{const a=rows(v,'PERIODIC_SCAN'),b=rows(v,'P_AND_O');if(!a||!b)throw Error(v);vals.push([labels[i],a.settled_segments_of_7,Number(a.held_energy_capture_pct).toFixed(2),b.settled_segments_of_7,Number(b.held_energy_capture_pct).toFixed(2)]);});
const ta=table(s,vals,72,176,728,408,[188,117,143,137,143],18);
ta.cells.block({row:0,column:0,rowCount:11,columnCount:5}).assign({margins:{left:8,right:8,top:2,bottom:2}});
ta.rows[0].height=52;
for(let r=1;r<11;r++)ta.rows[r].height=35;
tx(s,'obs','如何解释这些结果',837,176,371,40,26,blue,true);
tx(s,'o1','独立PI没有稳定改善验收\n加入ABC后，P&O电能上升，\n但通过段数由4降至3',837,234,371,106,23);
tx(s,'o2','C在原序列峰位处约束不活跃\n另设受限场景才显现作用\n该诊断属于探索性结果',837,363,371,105,23);
tx(s,'o3','去相位对照提示：\n局部功率搜索也能减少扫描\n不能把收益全部归于相位',837,489,371,105,23);
tx(s,'den','电能分母：当前序列软限最优功率的时间积分。统计保留扫描、降幅、恢复及风险区间。',72,611,1136,29,20,gray);
tx(s,'risk','所有版本的连续时间硬限仍未证明；表中电能不能直接称为安全收益或声学效率。',72,645,1136,26,20,red,true);
note(s,'ablation',`【建议时长】备份，问到算法改进时讲75秒\n【讲稿】我们并没有只尝试一个复杂控制器。这个批次将相位辅助、独立幅度PI和受约束选频分别开关，完成八种组合，再增加两个去掉相位的局部功率搜索对照。表中全部取原0.8秒每段，且各版本用相同序列。最重要的结果是没有全面胜出的组合。例如P&O的ABC电能比例54.69%高于对照50.33%，但通过段数从4降为3。独立PI也没有稳定提高成绩。C在原登记场景峰位处通常约束不活跃，所以原序列成绩几乎不变；后续负Rm受限场景只是探索性诊断。因而现阶段应处理恢复代价和保护缺口，而不是凭模块数量宣布改进。\n【设计】8组合+2去相位对照，各3策略，0.8/1.6秒两种段时长，共60条准稳态时序。此页只展示原0.8秒的扫频/P&O，固定基线和1.6秒补充在完整报告，不把延长段时长当作原验收通过。\n【A/B/C】A的输入相位只给候选，必须局部功率核验。B在a²坐标PI：Kp=.6、Ki=.8/s为假设。C按(Pport/a²)×a_allow²评分，是软约束局部网格优化，不是CBF或全局动态优化。\n【验收】CONTROL、NORMAL、频率未冻结、捕获≥98%、相邻样本间隔≤30ms、连续10样本。B的NORMAL允许在a_goal<1时成立这一语义扩展已在报告公开，另有去状态标签对照。\n【能量】按保持指令与真实扰动边界积分的准稳态电能，分母为软限最优功率积分；越限风险区间也计入，不能称为安全收益。原统计点无硬越限，但保持指令风险复算发现超160Vpp，不是LTspice瞬态。\n【证据】${factorial}/results/summary.csv\n${factorial}/deliverables/第二轮控制消融验证报告.md\n【研究性质】所有控制参数是假设值，本轮不等于复现某篇论文的完整方法；无器件或声场实验。`);
}
// Replace old screenshot slide25 (new29), retaining historic identity in notes.
{
const s=slide('gui','备份：完整瞬态GUI与日志已留存，按批次使用证据',29,'截图时间：2026-09-12    求解时间：2026-09-11    LTspice 26.0.2    此图属于瞬态重放，不是旧AC截图');
tx(s,'sub','本页展示真实SPICE Output Log，第17页展示同一RAW的完整波形窗口',72,117,1136,37,23,gray);
await img(s,`${replay}/GUI_20260912_LTspice_Error_Log.png`,72,177,820,460,'完整LTspice瞬态日志截图，含版本、正常结束和meas');
tx(s,'items','截图中可核对',927,183,281,39,26,blue,true);
tx(s,'list','软件版本与文件名\n求解正常结束\n统计窗口0.223–0.224 s\nVpp、RMS及有功功率',927,245,281,168,23);
tx(s,'history','旧AC截图仍保留归档',927,441,281,37,24,navy,true);
tx(s,'boundary','2026-08-15截图有裁切\n不能借此新瞬态截图\n补证旧AC全部场景',927,494,281,112,22,red);
note(s,'gui',`【建议时长】备份，查证时讲40秒\n【讲稿】我们已取得完整LTspice波形和Error Log截图，所以不能再说项目只有残缺截图。这里显示9月11日求解、9月12日截取的瞬态日志，能看到版本、求解结束和末窗口.meas。第17页是同一重放RAW的完整波形窗口。原8月15日AC截图仍在历史文件中保留，但它属于另一批次，而且有裁切，不能拿这张瞬态截图当作旧AC场景的证明。\n【数值】Log.meas：96.5473098755Vpp、.00492089171808Arms、.139337367035W，FROM .223 TO .224。RAW后处理PRm139.3401mW有末位积分差异。Log内部elapsed682.287s，外部进程计时691.6s，定义不同。\n【证据】${replay}/GUI_20260912_LTspice_Error_Log.png\n${replay}/GUI_20260912_replay_full.png\n${replay}/GUI_20260912_tail_carrier.png\n${replay}/GUI_20260912_capture_notes.json\n${replay}/PO_FS_M5_REPLAY_DT2NS.log\n【历史原稿保留】${source}，原第25页。截图为已留存的真实软件窗口，本次未重新截图LTspice软件，也未启动新求解。`);
}
// Replace old evidence slide27 (new31).
{
const s=slide('evidence','备份：静态、准稳态、瞬态重放与反馈结果分别追溯',31,'汇报截止2026-09-15    原数据与失败记录保留    完整路径、批次、窗口和哈希见备注及随附证据索引');
table(s,[['证据类型／批次','原始文件','支持的结论'],['v2.1静态AC对照','统一配置、.cir、.raw、.log、误差表','相同拓扑和参数的两条求解路径一致'],['历史准稳态控制 a734…','控制CSV、状态、扫描点、持续时间','该历史序列内的控制现象与能量统计'],['2026-09-07消融／后续候选','8组合＋2对照、完整时序与验收表','改进来源、代价与未解决的约束风险'],['2026-09-11/12瞬态重放','61条指令、真实RAW、.meas、GUI','P&O所选片段的真实电路响应'],['2026-09-14五轮反馈','逐轮stimulus、RAW、feedback及哈希','本轮测量改变下一轮实际执行指令'],['2026-09-15网页展示','实际网页截图、界面代码、历史会话','平台当前可查看和操作的功能']],72,135,1136,395,[292,424,420],20);
tx(s,'contract','各证据层不互相替代',72,554,1136,34,25,blue,true);
tx(s,'boundary','AC数值一致性不能证明瞬态安全；开环重放不能证明闭环性能；五轮固定负载反馈不能证明动态扰动验收。',72,600,1136,65,24,red);
note(s,'evidence',`【建议时长】备份，追问证据时讲60秒\n【讲稿】这页把证据分层。静态AC交叉验证核对电路求解；历史准稳态时序展示控制和扫描代价；9月7日消融测试用于研究改进来源；9月11日瞬态重放核对一段电路响应；9月14日五轮反馈验证因果指令链。网页截图证明平台操作界面已组织起来。这些批次采用不同窗口和目标，不能混成一次统一实验，也不能互相替代。\n【主要路径】\n静态：${platform}/evidence/ltspice/stage2/stage2_audit.json\n历史：${R}/ppt_control_fix_20260906/build/data/stage4_control_timeline.csv\n消融：${factorial}/results/summary.csv\n瞬态：${replay}/source_traceability.json\n${replay}/PO_FS_M5_REPLAY_DT2NS_execution.json\n反馈：${feedback}/reversal_acceptance.json\n平台：${platform}/streamlit_app.py\n【批次区分】历史主时序sha256 a734eca013d415f7a875c2785068745cd80ad811d7284e893bbcd1e974c5f0a0。后续候选cdde9dab61另列第27页。瞬态RAW sha256 aacc5b49f002f3d5636968686499275533e614d7f9f71cc69ea619aeb1422288。反馈每轮RAW各有独立哈希，见session与execution。\n【本次整理范围】本次PPT更新没有运行新的LTspice或控制仿真。只读取既有结果、截取真实网页、制作可追溯的汇报页面。`);
}

await (await PresentationFile.exportPptx(p)).save(`${B}/authored.pptx`);
await fs.mkdir(`${B}/authored-render`,{recursive:true});
for(const a of authored){await fs.writeFile(`${B}/authored-render/${a.key}.png`,new Uint8Array(await(await a.s.export({format:'png',scale:1})).arrayBuffer()));await fs.writeFile(`${B}/authored-render/${a.key}.layout.json`,await(await a.s.export({format:'layout'})).text());}
// OOXML transplantation preserves all original slide content outside the explicit changes.
const parse=t=>xmljs.xml2js(t,{compact:false}),serial=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function els(root,name){const a=[];function walk(x){if(x.type==='element'&&x.name.split(':').at(-1)===name)a.push(x);for(const y of x.elements??[])walk(y);}walk(root);return a;}
const resolve=(part,t)=>t.startsWith('/')?t.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(part),t));
const relpart=part=>`${path.posix.dirname(part)}/_rels/${path.posix.basename(part)}.rels`;
async function order(z){const rels=parse(await z.file('ppt/_rels/presentation.xml.rels').async('string'));const m=Object.fromEntries(els(rels,'Relationship').map(r=>[r.attributes.Id,resolve('ppt/presentation.xml',r.attributes.Target)]));return els(parse(await z.file('ppt/presentation.xml').async('string')),'sldId').map(x=>({part:m[x.attributes['r:id']],id:x}));}
const z=await JSZip.loadAsync(await fs.readFile(source)), a=await JSZip.loadAsync(await fs.readFile(`${B}/authored.pptx`));
const oo=await order(z),aa=await order(a),ct=parse(await z.file('[Content_Types].xml').async('string'));
const prez=parse(await z.file('ppt/presentation.xml').async('string')),prels=parse(await z.file('ppt/_rels/presentation.xml.rels').async('string'));
const origNoteParts=new Map();for(const item of oo){const rr=parse(await z.file(relpart(item.part)).async('string'));origNoteParts.set(item.part,resolve(item.part,els(rr,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide')).attributes.Target));}
const newParts={}, changeLog=[];
for(let j=0;j<authored.length;j++){
 const au=authored[j], from=aa[j].part, replaceOld={completion:18,gui:25,evidence:27}[au.key];
 const to=replaceOld?oo[replaceOld-1].part:`ppt/slides/supplement_${au.key}.xml`;
 newParts[au.key]=to;
 const sx=parse(await a.file(from).async('string')),sr=parse(await a.file(relpart(from)).async('string'));
 const oldrels=replaceOld?parse(await z.file(relpart(to)).async('string')):parse(await z.file(relpart(oo[1].part)).async('string'));
 const layoutrel=els(oldrels,'Relationship').find(x=>x.attributes.Type.endsWith('/slideLayout'));
 const notesRel=els(sr,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
 const sourceNotes=resolve(from,notesRel.attributes.Target),toNotes=replaceOld?origNoteParts.get(to):`ppt/notesSlides/supplement_${au.key}.xml`;
 const rr={declaration:{attributes:{version:'1.0',encoding:'UTF-8',standalone:'yes'}},elements:[{type:'element',name:'Relationships',attributes:{xmlns:'http://schemas.openxmlformats.org/package/2006/relationships'},elements:[]}]};
 rr.elements[0].elements.push({type:'element',name:'Relationship',attributes:{Id:'rIdLayoutSupplement',Type:layoutrel.attributes.Type,Target:layoutrel.attributes.Target}});
 rr.elements[0].elements.push({type:'element',name:'Relationship',attributes:{Id:'rIdNotesSupplement',Type:notesRel.attributes.Type,Target:`../notesSlides/${path.posix.basename(toNotes)}`}});
 let idx=0;for(const pic of els(sx,'pic')){const blip=els(pic,'blip')[0],rid=blip.attributes['r:embed'];const pr=els(sr,'Relationship').find(x=>x.attributes.Id===rid);const oldfile=resolve(from,pr.attributes.Target);const ext=path.extname(oldfile);const media=`ppt/media/supplement_${au.key}_${++idx}${ext}`;z.file(media,await a.file(oldfile).async('uint8array'));const newrid=`rIdSupplementImg${idx}`;blip.attributes['r:embed']=newrid;rr.elements[0].elements.push({type:'element',name:'Relationship',attributes:{Id:newrid,Type:pr.attributes.Type,Target:`../media/${path.posix.basename(media)}`}});if(!els(ct,'Default').some(d=>d.attributes.Extension===ext.slice(1)))els(ct,'Types')[0].elements.push({type:'element',name:'Default',attributes:{Extension:ext.slice(1),ContentType:ext==='.png'?'image/png':'image/jpeg'}});}
 z.file(to,serial(sx));z.file(relpart(to),serial(rr));
 const sn=parse(await a.file(sourceNotes).async('string'));
 z.file(toNotes,serial(sn));
 const onr=parse(await z.file(relpart(origNoteParts.get(oo[1].part))).async('string'));
 const back=els(onr,'Relationship').find(x=>x.attributes.Type.endsWith('/slide'));back.attributes.Target=`../slides/${path.posix.basename(to)}`;
 z.file(relpart(toNotes),serial(onr));
 if(!replaceOld){for(const [part,type]of[[to,'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'],[toNotes,'application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml']])els(ct,'Types')[0].elements.push({type:'element',name:'Override',attributes:{PartName:`/${part}`,ContentType:type}});const rid=`rIdSupplement_${au.key}`;els(prels,'Relationships')[0].elements.push({type:'element',name:'Relationship',attributes:{Id:rid,Type:'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide',Target:`slides/${path.posix.basename(to)}`}});au.id={type:'element',name:'p:sldId',attributes:{id:String(700+j),'r:id':rid}};}
 changeLog.push({key:au.key,new_page:au.page,old_page:replaceOld??null,slide_part:to});
}
const sequence=[1,2,'platform',...Array.from({length:13},(_,i)=>i+3),'replay','feedback',16,17,18,19,20,21,22,'ablation',23,24,25,26,27,28];
if(sequence.length!==32)throw Error('wrong count');
els(prez,'sldIdLst')[0].elements=sequence.map(x=>typeof x==='number'?oo[x-1].id:authored.find(a=>a.key===x).id);
const oldToNew=Object.fromEntries(sequence.map((x,i)=>[typeof x==='number'?x:x,i+1]));
const pageMap=[];const scriptParts=[];
for(let i=0;i<sequence.length;i++){
const key=sequence[i],part=typeof key==='number'?oo[key-1].part:newParts[key];
const sx=parse(await z.file(part).async('string'));
if(typeof key==='number'&&![18,25,27].includes(key)){
 for(const sp of els(sx,'sp')){
   const text=els(sp,'t').map(n=>(n.elements??[]).map(e=>e.text??'').join('')).join('');
   const xfrm=els(sp,'xfrm')[0],off=xfrm?els(xfrm,'off')[0]:null;
   if(text.trim()===String(key)&&off&&Number(off.attributes.y)>620*9525&&Number(off.attributes.x)>1080*9525){const ts=els(sp,'t');ts[0].elements=[{type:'text',text:String(i+1)}];for(const n of ts.slice(1))n.elements=[];}
 }
 for(const n of els(sx,'t'))for(const t of n.elements??[])if(t.type==='text'){
   t.text=t.text.replace(/第\s*(\d+)\s*页/g,(m,n)=>oldToNew[n]?`第${oldToNew[n]}页`:m);
   if(key===1)t.text=t.text.replaceAll('2026.09.11','2026.09.15').replaceAll('2026-09-11','2026-09-15');
 }
 z.file(part,serial(sx));
}
const rels=parse(await z.file(relpart(part)).async('string'));
const np=resolve(part,els(rels,'Relationship').find(r=>r.attributes.Type.endsWith('/notesSlide')).attributes.Target);
const nx=parse(await z.file(np).async('string'));
els(nx,'notes')[0].attributes['xmlns:a']='http://schemas.openxmlformats.org/drawingml/2006/main';
const body=els(nx,'sp').find(sp=>els(sp,'ph').some(ph=>ph.attributes.type==='body'));
if(typeof key==='number'&&![18,25,27].includes(key))for(const n of els(body,'t'))for(const t of n.elements??[])if(t.type==='text')t.text=t.text.replace(/第\s*(\d+)\s*页/g,(m,n)=>oldToNew[n]?`第${oldToNew[n]}页`:m);
let nt=els(body,'p').map(pp=>els(pp,'t').map(n=>(n.elements??[]).map(e=>e.text??'').join('')).join('')).join('\n');
if(key===1){nt=nt.replaceAll('2026.09.11','2026.09.15').replaceAll('2026-09-11','2026-09-15');nt+='\n【本次汇报截止】2026-09-15。共32页，正文1–21页，备份22–32页。历史主时序、9月7日算法消融、9月11/12日瞬态重放、9月14日五轮反馈为不同批次，不能理解为同一次统一实验。当前是阶段成果汇报，项目全部验收尚未完成。新增平台第3页、瞬态第17页、反馈第18页、消融第26页。';}
if(key===15)nt+='\n【进一步澄清】左图2.4s之前为Rm+50%场景，约159.2mW，不是170mW基准。2.4s切换为独立fs−5%场景，Rm回到基准，不是两种扰动累计。曲线按记录持续时间采样保持，跨扰动边界的旧记录不能被解释成电路真实未响应。相位K5段频率冻结，不能只归因于小增益。新瞬态与反馈另见第17、18页，不能冒充本页三策略同次运行。';
if(key===13)nt+='\n【进度更新】本页“待补齐”限定历史主控制实现。后续独立实验对扫描动作保护已有修正和部分复验，见第26、27页，尚未完成回归到原计划三策略同口径验收。第17页真实瞬态只验证一个固定负载片段，不消除本页采样间隙局限。';
// Replace only notes body text with simple DrawingML paragraphs, preserving notes layout.
const txbody=els(body,'txBody')[0];txbody.elements=txbody.elements.filter(e=>!e.name?.endsWith(':p'));
for(const line of nt.split('\n'))txbody.elements.push({type:'element',name:'a:p',elements:[{type:'element',name:'a:r',elements:[{type:'element',name:'a:rPr',attributes:{lang:'zh-CN',sz:'1200'}},{type:'element',name:'a:t',elements:[{type:'text',text:line}]}]}]});
z.file(np,serial(nx));
const title=els(sx,'sp').map(sp=>els(sp,'t').map(n=>(n.elements??[]).map(t=>t.text??'').join('')).join('')).find(t=>t.length>8)??String(key);
pageMap.push({page:i+1,old_page:typeof key==='number'?key:null,key,title,role:i<21?'正文':'备份'});
scriptParts.push(`第${i+1}页${typeof key==='number'?`（原第${key}页）`:'（新增）'}\n${title}\n${nt}`);
}
z.file('ppt/presentation.xml',serial(prez));z.file('ppt/_rels/presentation.xml.rels',serial(prels));z.file('[Content_Types].xml',serial(ct));
if(z.file('docProps/app.xml')){let d=await z.file('docProps/app.xml').async('string');d=d.replace(/<Slides>\d+<\/Slides>/,'<Slides>32</Slides>');z.file('docProps/app.xml',d);}
await fs.writeFile(`${B}/full_candidate.pptx`,await z.generateAsync({type:'uint8array',compression:'DEFLATE'}));
await fs.writeFile(`${B}/page_map.json`,JSON.stringify(pageMap,null,2));
await fs.writeFile(`${W}/output/逐页讲稿_成果补全_2026-09-15.txt`,scriptParts.join('\n\n'+'='.repeat(64)+'\n\n'),'utf8');
await fs.writeFile(`${B}/build_receipt.json`,JSON.stringify({source,source_sha256:sha(await fs.readFile(source)),source_slides:28,final_slides:32,added:4,changeLog,new_simulation:false,screenshot:'Real browser viewport 2026-09-15 and existing LTspice GUI 2026-09-12',source_preserved:true,authoring:'Artifact Tool plus OOXML transplant to preserve unrelated evidence'},null,2));
console.log(JSON.stringify({count:32,added:changeLog.filter(r=>!r.old_page),updated:changeLog.filter(r=>r.old_page)},null,2));
