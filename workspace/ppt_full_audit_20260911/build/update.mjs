import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import JSZip from 'jszip';
import xmljs from 'xml-js';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const R='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const D=`${R}/ppt_full_audit_20260911`,B=`${D}/build`;
const SOURCE=`${R}/project_audit_20260910/output/CTO组会汇报_计划书口径与验收缺口修订_2026-09-10.pptx`;
const pages=JSON.parse(await fs.readFile(`${B}/content.json`,'utf8'));
const inventory=JSON.parse(await fs.readFile(`${B}/source_inventory.json`,'utf8'));
const deck=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const rec=(await deck.inspect({kind:'slide,textbox,shape,image,table,chart',maxChars:1000000})).ndjson.trim().split('\n').map(JSON.parse);
const slide=n=>deck.slides.items[n-1];
const found=(n,name,kind)=>{const r=rec.find(r=>r.slide===n&&r.name===name&&(!kind||r.kind===kind));if(!r)throw Error(`missing ${n} ${name}`);return deck.resolve(r.id);};
function style(o,size,color='#17324D',bold=false){o.text.style={typeface:'Calibri',fontSize:size,color,bold,autoFit:'none',verticalAlignment:'middle',alignment:'left',insets:{top:0,bottom:0,left:0,right:0}};return o;}
function txt(n,name,value,pos,size=23,color='#17324D',bold=false){const o=found(n,name);o.text=value;if(pos)o.position=pos;return style(o,size,color,bold);}
function add(n,name,value,pos,size=20,color='#17324D',bold=false){const o=slide(n).shapes.add({name,geometry:'textbox',position:pos,fill:'none',line:{fill:'none',width:0}});o.text=value;return style(o,size,color,bold);}
function cell(n,row,col,value,size=21){const o=deck.resolve(rec.find(r=>r.slide===n&&r.kind==='table').id);o.cells.set(row,col,value);o.getCell(row,col).text.style={typeface:'Calibri',fontSize:size,color:row===0?'#FFFFFF':'#17324D',bold:row===0};return o;}
function foot(n,s){if(n===1)return;txt(n,n===4?'矩形 8':'矩形 3',s,{left:72,top:688,width:1100,height:20},11.5,'#5F6B76');}
const droppedNames=new Map();
function drop(n,...names){droppedNames.set(n,new Set([...(droppedNames.get(n)??[]),...names]));}
const newImages=[];
async function fig(n,file,pos){const alt=`AUDIT_P${n}_${file}`;slide(n).images.add({blob:new Uint8Array(await fs.readFile(`${B}/figures/${file}.png`)),contentType:'image/png',fit:'contain',alt,position:pos});newImages.push({page:n,alt,file});}
// Page count/order and existing layout remain unchanged. Notes and lecture share content.json.
for(const s of pages){
 if(s.page>1){const tr=rec.find(r=>r.slide===s.page&&r.name?.startsWith('title-'));txt(s.page,tr.name,s.title,{left:80,top:38,width:1130,height:58},32,'#17324D',true);}
 slide(s.page).speakerNotes.textFrame.setText(s.notes);
 foot(s.page,'假设BVD电学模型，非实测数据    本次仅审核旧证据、复核数据与修订图文');
}
txt(1,'矩形 4','第一月工作汇报    2026.09.11',{left:103,top:444,width:950,height:40},22,'#5F6B76');
txt(1,'矩形 5','已有电学模型与控制原型，统一三策略验收尚未全部完成',null,19,'#5F6B76');
txt(2,'矩形 20','目标：P_Rm电学耗散\n参数为假设与扫描变量',{left:450,top:402,width:380,height:72},22,'#17324D',true);
txt(3,'矩形 9','I_Rm,RMS ≈ 353.6 mA',null,27,'#B84040',true);
txt(3,'矩形 10','P_Rm ≈ 12.5 W',null,27,'#B84040',true);
txt(3,'矩形 11','单是运动支路就超出5 mA量级',null,22,'#DE8800',true);
drop(4,'图片 12');await fig(4,'p04_bare_bvd',{left:72,top:125,width:822,height:525});
txt(4,'矩形 18','1.36×10⁻⁵ %',null,29,'#328898',true);
txt(4,'矩形 20','最大复阻抗相对误差',null,21,'#5F6B76');
txt(4,'矩形 22','0.900000 MHz',{left:950,top:339,width:290,height:44},27,'#DE8800',true);
txt(4,'矩形 24','两条路径的电导峰',{left:952,top:386,width:276,height:42},20,'#5F6B76');
txt(4,'矩形 26','已存RAW与解析复核\n同参数、同网格对照\n实现吻合不等于参数真实',{left:935,top:464,width:298,height:115},22,'#B84040',true);
foot(4,'裸BVD，保留Rm损耗    复核已保存RAW，非新LTspice仿真    误差以Python复阻抗为分母');
foot(5,'同一冻结源的未保护离线AC曲线    P_Rm为等效Rm电学耗散，32.8倍不是声学效率增益');
// Replace native plots with Python plots sourced from the same original CSV.
await fig(6,'p06_input_impedance',{left:72,top:130,width:720,height:477});
txt(6,'矩形 8','0.9 MHz固定频点\n1 V RMS等效源，Rs=50 Ω',{left:850,top:140,width:342,height:59},22,'#17324D',true);
cell(6,1,0,'|Zin| / Ω',17);cell(6,2,0,'Re Zin / Ω',17);cell(6,3,0,'Im Zin / Ω',17);cell(6,4,0,'arg Zin / °',17);
txt(6,'矩形 10','在0.9 MHz定义：QL=100 → RL,ESR=6.035 Ω；QC=1000 → RC,ESR=0.624 Ω\n网表采用固定ESR；有损方案的L/C相对理想匹配值亦有小量微调。',{left:86,top:615,width:1100,height:58},20,'#17324D');
foot(6,'测点为源电阻之后的匹配网络输入端    含电感与电容ESR    相位不是BVD端口相位');
txt(7,'矩形 6','读表要点',null,28,'#17324D',true);
txt(7,'矩形 7','峰位：优先看fs行\n峰高：看损耗变化\n峰宽：看FWHM列',{left:974,top:220,width:242,height:180},23);
txt(7,'矩形 9','表内最大峰移\n−45.2 kHz',null,25,'#DE8800',true);
add(7,'scope-table','表内为部分代表因素；未含Cm-only。除指定扰动外，其余元件与源电压固定。',{left:74,top:611,width:1105,height:36},20,'#5F6B76');
cell(7,0,0,'代表因素最高档',22);cell(7,0,3,'P_Rm半高宽',22);
foot(7,'相对v2.1基线的冻结源P_Rm特征    100 Hz网格    0.0 kHz不代表无限精度下绝无漂移');
drop(8,'图片 22');await fig(8,'p08_cm_power_limits',{left:72,top:125,width:740,height:515});
txt(8,'cm-summary-title','Cm+20%相对基准',{left:875,top:129,width:340,height:55},25,'#17324D',true);
txt(8,'cm-shift-callout','峰位变化  −78.6 kHz',null,23,'#17324D',true);
txt(8,'cm-boundary-note','峰位 / 峰高（MHz / mW）\n基准 0.9000 / 170.0\n+5%  0.8781 / 164.3\n+10% 0.8579 / 144.3\n+20% 0.8214 / 96.4',{left:860,top:497,width:355,height:135},20);
foot(8,'机械支路电容Cm，不是匹配电容    原始元件单因素，fs与Qm派生变化    同源a=1未保护扫描');
drop(9,'图片 24');await fig(9,'p09_qm_response',{left:72,top:125,width:744,height:528});
txt(9,'矩形 11','Qm=800',null,19,'#777F89',true);
txt(9,'矩形 14','Qm=1000',null,19,'#D44343',true);
found(9,'矩形: 圆角 10').fill='#F0F1F3';found(9,'矩形: 圆角 10').line={fill:'#777F89',width:1};
found(9,'矩形: 圆角 13').fill='#FBEDEE';found(9,'矩形: 圆角 13').line={fill:'#D44343',width:1};
txt(9,'矩形 16','静态峰宽结果\n未验证实际建立时间\n或噪声下的控制表现',{left:886,top:536,width:320,height:84},23,'#17324D',true);
foot(9,'Qm=500/800/1000，固定fs、Rm、C0并联合重算Lm/Cm    FWHM为P_Rm半高宽');
drop(10,'图片 22','图片 23','矩形 7','矩形 8','文本框 6');
await fig(10,'p10_criteria',{left:72,top:122,width:858,height:506});
txt(10,'矩形 10','fs−5%离线选点\n最大功率 0.8550\n最小|相位| 0.9045\n最小Γ 0.8545 MHz',{left:984,top:221,width:215,height:150},21,'#DE8800',true);
txt(10,'矩形 13','先确定测点与目标\n再检查电压、电流约束',{left:974,top:535,width:236,height:86},22,'#17324D',true);
txt(10,'criteria-shared-frequency-axis','0.84–0.96 MHz，步长0.5 kHz；全部为同源a=1未保护离线选点。',{left:87,top:642,width:1080,height:32},21,'#5F6B76');
foot(10,'相位指arg Zin，反射代理参考50 Ω    网格最小绝对相位不等于插值相位零点');
drop(11,'图片 5');await fig(11,'p11_windows',{left:73,top:128,width:1128,height:368});
txt(11,'矩形 7','±100 kHz / 1 kHz示例\n201点，301.5 ms代理时间\n覆盖峰不等于精确捕获峰高',{left:833,top:527,width:343,height:80},21,'#17324D',true);
txt(11,'矩形 8','窗外参考峰：±20漏10例，±50漏2例',{left:95,top:535,width:690,height:42},24,'#DE8800',true);
txt(11,'矩形 9','1.5 ms/点是假设时间，不是硬件实测',{left:95,top:583,width:690,height:40},23,'#328898',true);
foot(11,'当前34场景，窗口中心0.9 MHz    左图包括漏峰误差；右图为点数×假设每点驻留时间');
drop(12,'箭头: 右 5','箭头: 右 6','箭头: 右 7','箭头: 右 8');
txt(12,'state-diagram-label','状态名称示意',{left:94,top:126,width:160,height:30},18,'#5F6B76');
txt(12,'矩形 17','不是固定转移链\n动作需查时序CSV',{left:68,top:566,width:195,height:68},19);
foot(12,'旧批次a734eca013，固定/扫频/P&O历史示例    与第24页同源；不是第23页后续候选');
foot(13,'旧批次1795条保护后记录    零记录越限≠采样间隙安全    扫描逐点保护仍待正式集成');
drop(14,'图片 18');await fig(14,'p14_phase_current',{left:80,top:126,width:728,height:508});
txt(14,'矩形 6','测点：匹配网络输入端\nφin = arg(Zin)',{left:850,top:136,width:344,height:78},24);
txt(14,'矩形 7','固定基准相位目标\n−1.0782°',{left:865,top:236,width:320,height:75},28,'#17324D',true);
txt(14,'矩形 8','5 / 10 / 25 / 50 / 100 Hz/°\n斜率来自模型±100 Hz探针',{left:848,top:334,width:344,height:77},21);
txt(14,'矩形 10','50与100 Hz/°各1段\n尾段|相位误差|≤0.5°\n但功率比<95%',{left:872,top:442,width:297,height:94},22,'#B84040');
txt(14,'phase-plot-scope','左图K=5，第三幅为绝对P_Rm。模型相位探针未计测量耗时。',{left:89,top:640,width:1100,height:31},20,'#5F6B76');
foot(14,'当前选定增益CSV b170bc930d    历史独立相位试验，不用于三策略正式排名');
txt(15,'formal-status-subtitle','以下为进展表，非成绩排名。已有相位补充表明确标注 NOT_FORMAL_RANKING。',{left:72,top:119,width:1120,height:37},21,'#5F6B76');
cell(15,1,1,'0.9 MHz\n名义固定幅度＋保护',21);
foot(15,'正式三策略：固定频率 / 周期扫频 / 相位误差闭环    P&O仅为扩展方法');
txt(16,'矩形 12','模型内工作点\nf, Vport∠θ',null,22,'#17324D',true);
txt(16,'矩形 16','待完成\n声学查找表',null,22,'#17324D',true);
txt(16,'矩形 18','待完成\n靶区/壁面代理',null,22,'#17324D',true);
txt(16,'矩形 19','EA_IF_V1.0：基准与低/中/高组合4条电学记录，字段审计通过',null,24,'#17324D',true);
txt(16,'矩形 21','这是项目接口定义，不是行业标准，也不是声场求解结果。',null,24,'#DE8800',true);
foot(16,'2026-09-01已有电学导出    RMS、exp(+jωt)    未运行COMSOL/ANSYS，声学字段为空');
txt(17,'矩形 8','项目背景\nCTO及治疗超声\n不提供BVD定量参数',null,22,'#17324D',true);
txt(17,'矩形 10','扫描变量\nC0、Rm、fs等\n工程压力测试范围',null,22,'#17324D',true);
txt(17,'矩形 12','尚待标定\n真实负载到BVD\n的定量映射',null,22,'#17324D',true);
txt(17,'矩形 15','已有\n电学模型与控制原型\n\n待完成\n结构模态与声场\n\n本项目不涉及\n热、空化、临床结论',{left:918,top:232,width:266,height:280},22);
txt(17,'矩形 16','不能把扫描等级解释为病变严重程度',{left:190,top:408,width:690,height:52},28,'#17324D',true);
txt(17,'矩形 17','模糊推测：真实负载可能影响等效参数；方向与幅度尚待标定。',{left:110,top:496,width:762,height:58},22,'#328898');
foot(17,'本页不再使用无精确出处的医学因果断言    只讨论特定BVD及登记扰动范围');
txt(18,'矩形 8','v2.1匹配与双线核对\n34个场景静态扫描\n其中12例LTspice核对\n选频、保护与控制原型\n电—声接口字段',{left:90,top:282,width:332,height:187},23);
txt(18,'矩形 11','后续建模与外部验证',null,26,'#17324D',true);
foot(18,'当前不能写“全部完成”    34个Python静态场景不等于34个LTspice场景，也不等于闭环验收');
foot(19,'电路数值为假设基线或扫描变量    用户工作要求另列    本表无真实器件辨识值');
txt(20,'矩形 5','代表性单因素最高档',null,25,'#17324D',true);
txt(20,'rm-qm-correction','Rm-only：+15% / +30% / +50% → Qm=695.7 / 615.4 / 533.3\n2026-09-10元数据回归：Lm/Cm未改，34×2001频点电学数组一致。',{left:100,top:594,width:1090,height:62},22);
foot(20,'右侧旧主序列共8段、7个不同场景    低中组合与Lm/Cm-only完整闭环验收仍缺');
for(const [row,val] of [[1,'0.01461'],[2,'0.00751'],[3,'0.00295']])cell(21,row,1,`2001点，最大复Zin相对误差 ${val}%，通过5%阈值`,21);
cell(21,0,1,'已保存LTspice/Python静态对照',22);
txt(21,'矩形 6','同一配置下两条求解路径吻合；不能排除共同模型假设错误，也不代表闭环验收。',{left:118,top:589,width:1078,height:66},23,'#B84040',true);
foot(21,'历史LTspice批处理输出    复阻抗相对误差以Python值为分母    本次未新运行LTspice');
cell(22,0,1,'离线定义（未保护）',22);cell(22,2,0,'最小绝对相位',21);cell(22,3,1,'min |(Zin−50)/(Zin+50)|',20);
foot(22,'冻结源的离散选点，不等于受约束可执行频率    相位与反射均在匹配网络输入端定义');
txt(23,'矩形 6','后续仿真：无PI候选',null,27,'#17324D',true);
foot(23,'后续候选cdde9dab61    图含模型保持指令重放，非LTspice瞬态    与第12/24页分属不同批次');
txt(24,'矩形 8','*尾段误差含筛选与回退，不等于正式稳态指标；0%不表示全程无损失。\n本批次固定频率记录电能较高，但不能外推为其他模型或扰动时长下更优。',{left:72,top:542,width:1123,height:66},23);
txt(24,'energy-definition','记录功率保持积分：E_Rm=ΣP_Rm,k Δt_k；共同参考电能0.77568 J',{left:72,top:478,width:1120,height:39},20,'#5F6B76');
txt(24,'energy-method','包含扫描、试探和保护记录；不重放采样间隙负载变化，非声学效率。',{left:72,top:633,width:1122,height:32},21,'#5F6B76');
foot(24,'旧批次a734eca013，0.8–6.4 s记录积分    与第23页物理保持指令重放的积分方法不同');
txt(25,'矩形 8','历史留痕局限\n左图为V(n_port)幅相\n不是阻抗相位\n原图缺横轴，需重截\n数值应回查RAW/Log',null,22,'#17324D',true);
txt(25,'矩形 9','2026-08-15基准局部截图；Log显示26.0.2，文件版本26.0.2.1',{left:90,top:581,width:1110,height:42},23,'#17324D',true);
foot(25,'保留真实历史截图原件，不伪造缺失像素    仅作运行痕迹，不能替代完整波形截图');
foot(26,'本页为待统一实施的评价定义    不构成已运行结果    稳态、全过程电能与硬限分别报告');
txt(27,'矩形 19','静态批处理、离散控制、保持指令重放、GUI截图分开登记',null,25,'#17324D',true);
txt(27,'矩形 20','哈希用于识别文件版本，不证明物理模型正确',null,24,'#17324D');
txt(27,'矩形 21','每页讲稿附数据与脚本路径；原始仿真文件和旧PPT均保留。',null,24,'#5F6B76');
foot(27,'本次操作：文件审核、原始数据复核、Python重绘和PPT修订    无新控制/LTspice/声场仿真');
txt(28,'矩形 5','建模与求解准备',null,28,'#17324D',true);
txt(28,'矩形 6','软件版本与许可证记录\n几何、材料矩阵与极化\n电极、机械及耦合边界\n吸收边界与粗/中/细网格\n模态与谐响应求解设置',{left:115,top:215,width:490,height:300},24);
txt(28,'矩形 9','模态列表与关键形状\n端口阻抗/导纳、位移幅相\n声压云图及轴向曲线\n网格收敛表\nSolver Log正常结束',{left:704,top:215,width:490,height:300},24);
txt(28,'矩形 11','当前未完成结构声场求解，没有可用的真实云图或求解截图。',null,24,'#B84040',true);
foot(28,'电—声接口字段已定义，不等于模型、网格或声场结果已完成');
await(await PresentationFile.exportPptx(deck)).save(`${B}/authored.pptx`);

// Transplant authored text/tables/notes into original package. Retain untouched
// original images, and copy only explicitly introduced Python images with new IDs.
const parse=s=>xmljs.xml2js(s,{compact:false}),serial=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function els(root,name){const a=[];function walk(x){if(x.type==='element'&&x.name.split(':').at(-1)===name)a.push(x);for(const y of x.elements??[])walk(y);}walk(root);return a;}
const resolve=(part,target)=>target.startsWith('/')?target.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(part),target));
const relpath=part=>`${path.posix.dirname(part)}/_rels/${path.posix.basename(part)}.rels`;
const original=await JSZip.loadAsync(await fs.readFile(SOURCE));const edited=await JSZip.loadAsync(await fs.readFile(`${B}/authored.pptx`));
async function slideOrder(z){const r=parse(await z.file('ppt/_rels/presentation.xml.rels').async('string'));const map=Object.fromEntries(els(r,'Relationship').map(x=>[x.attributes.Id,resolve('ppt/presentation.xml',x.attributes.Target)]));return els(parse(await z.file('ppt/presentation.xml').async('string')),'sldId').map(x=>map[x.attributes['r:id']]);}
const oo=await slideOrder(original),eo=await slideOrder(edited);const changes=[];
for(let n=1;n<=28;n++){
 const op=oo[n-1],ep=eo[n-1];const ox=parse(await original.file(op).async('string')),ex=parse(await edited.file(ep).async('string'));
 const or=parse(await original.file(relpath(op)).async('string')),er=parse(await edited.file(relpath(ep)).async('string'));
 const root=els(ex,'sld')[0];for(const [k,v]of Object.entries(els(ox,'sld')[0].attributes??{}))if(k.startsWith('xmlns:'))root.attributes[k]??=v;
 const originals=new Map(els(ox,'pic').map(p=>[els(p,'cNvPr')[0]?.attributes?.name,p]));
 const tree=els(ex,'spTree')[0];const removes=droppedNames.get(n)??new Set();let cnt=0;
 const next=[];
 for(const element of tree.elements??[]){
  const tag=element.name?.split(':').at(-1);const meta=els(element,'cNvPr')[0]?.attributes??{};
  if(removes.has(meta.name))continue;
  if(n===6&&tag==='graphicFrame'&&els(element,'chart').length)continue;
  if(tag==='pic'){
   if((meta.descr??'').startsWith('AUDIT_') || (!meta.name && newImages.some(x=>x.page===n))){
    const specification=newImages.find(x=>x.page===n);meta.name=specification.alt;meta.descr=specification.alt;
    const blip=els(element,'blip')[0];const rid=blip.attributes['r:embed'];const rel=els(er,'Relationship').find(x=>x.attributes.Id===rid);if(!rel)throw Error(`image rel ${n}`);
    const target=resolve(ep,rel.attributes.Target);const bytes=await edited.file(target).async('uint8array');
    const media=`ppt/media/full_audit_20260911_p${n}_${++cnt}.png`;original.file(media,bytes);
    const newrid=`rIdAuditImage${n}_${cnt}`;blip.attributes['r:embed']=newrid;
    els(or,'Relationships')[0].elements.push({type:'element',name:'Relationship',attributes:{Id:newrid,Type:'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image',Target:`../media/${path.posix.basename(media)}`}});
    next.push(element);changes.push(media);
   }else{const orig=originals.get(meta.name);if(!orig)throw Error(`unmatched retained image ${n} ${meta.name}`);next.push(orig);}
  }else next.push(element);
 }
 tree.elements=next;original.file(op,serial(ex));original.file(relpath(op),serial(or));changes.push(op);
 const oldnote=els(or,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
 const newnote=els(er,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
 original.file(resolve(op,oldnote.attributes.Target),await edited.file(resolve(ep,newnote.attributes.Target)).async('uint8array'));
}
await fs.writeFile(`${B}/candidate.pptx`,await original.generateAsync({type:'uint8array',compression:'DEFLATE'}));
await fs.writeFile(`${B}/build_receipt.json`,JSON.stringify({source:SOURCE,source_sha256:createHash('sha256').update(await fs.readFile(SOURCE)).digest('hex'),pages:28,replotted_pages:[4,6,8,9,10,11,14],all_source_media_preserved:true,newImages,changes,notes_source:`${B}/content.json`,new_LTspice_run:false,new_controller_run:false,new_GUI:false},null,2));
console.log('Draft packaged with 28 synchronized notes; original media retained.');
