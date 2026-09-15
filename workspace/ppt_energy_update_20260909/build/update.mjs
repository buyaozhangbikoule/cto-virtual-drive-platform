import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import JSZip from 'jszip';
import xmljs from 'xml-js';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const ROOT='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const DIR=`${ROOT}/ppt_energy_update_20260909`,B=`${DIR}/build`,O=`${DIR}/output`;
const SOURCE=`${ROOT}/ppt_acceptance_update_20260909/output/CTO组会汇报_第14页验收进展更新_2026-09-09.pptx`;
const SKILL='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const PYTHON='C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const d=JSON.parse(await fs.readFile(`${B}/data.json`,'utf8'));
const deck=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const rec=(await deck.inspect({kind:'slide,textbox,shape,image,table,chart,notes,layout',maxChars:450000})).ndjson.trim().split('\n').map(JSON.parse);
await fs.writeFile(`${B}/before.ndjson`,rec.map(r=>JSON.stringify(r)).join('\n'));
const slide=deck.resolve(rec.find(r=>r.kind==='slide'&&r.slide===15).id);
await fs.writeFile(`${B}/before.png`,new Uint8Array(await(await slide.export({format:'png',scale:1})).arrayBuffer()));
function txt(name,value,pos,size=21,color='#17324D',bold=false,align='left'){
  const r=rec.find(r=>r.slide===15&&r.name===name&&['textbox','shape'].includes(r.kind));
  if(!r)throw Error(name);
  const o=deck.resolve(r.id);o.text=value;if(pos)o.position=pos;
  o.text.style={typeface:'Calibri',fontSize:size,bold,color,autoFit:'none',alignment:align,verticalAlignment:'middle',
    insets:{top:0,bottom:0,left:0,right:0}};return o;
}
function add(name,value,pos,size=20,color='#17324D',bold=false){
  const o=slide.shapes.add({name,geometry:'textbox',position:pos,fill:'none',line:{fill:'none',width:0}});
  o.text=value;o.text.style={typeface:'Calibri',fontSize:size,bold,color,autoFit:'none',insets:{top:0,bottom:0,left:0,right:0}};return o;
}
txt('title-12','尾段误差为零，仍存在全过程电能损失',null,36,'#17324D',true);
txt('comparison-window','同一旧批次，0.8–6.4 s，共7个0.8 s扰动段，三种策略均接入共同保护',
  {left:72,top:112,width:1136,height:35},21,'#5F6B76');
const table=deck.resolve(rec.find(r=>r.slide===15&&r.kind==='table').id);
const names=['固定频率\n＋共同保护','周期扫频','扫描辅助P&O'];
const values=[['策略','尾段误差*','累积电能\n(J)','相对最优\n电能','未通过段\n(共7段)']];
d.rows.forEach((r,i)=>values.push([names[i],r.steady_error_pct.toFixed(2)+'%',r.energy_J.toFixed(3),r.capture_pct.toFixed(1)+'%',String(r.unsettled_segments)]));
for(let r=0;r<4;r++)for(let c=0;c<5;c++){
  table.cells.set(r,c,values[r][c]);const cell=table.getCell(r,c);
  cell.text.style={typeface:'Calibri',fontSize:r===0?19:20,bold:r===0,color:r===0?'#FFFFFF':'#17324D'};
  if(r>0)cell.fill='#FFFFFF';
}
// Replace the old recovery chart with the user's established Python figure workflow.
// Its original chart OOXML is removed after export. All other deck charts remain untouched.
slide.images.add({blob:new Uint8Array(await fs.readFile(`${O}/第15页_全过程电能比较.png`)),contentType:'image/png',
  fit:'contain',position:{left:765,top:173,width:443,height:337.52},crop:{left:0,top:0,right:0,bottom:0},
  alt:'共同0.8–6.4秒区间的记录功率采样保持积分。固定频率75.8%，周期扫频61.1%，扫描辅助P&O 67.7%，分母统一为0.775677 J。'});
add('energy-title','全过程电能捕获率',{left:819,top:162,width:380,height:29},23,'#17324D',true);
// Reuse the original conclusion band's position but remove decorative box styling.
const band=deck.resolve(rec.find(r=>r.slide===15&&r.name==='矩形: 圆角 7').id);
band.fill='none';band.line={fill:'none',width:0};
txt('矩形 8','0%仅描述筛选后的尾段样本，不代表全程无损失或连续验收通过。\n当前短扰动段下，扫描、试探和保护恢复的时间成本不可忽略。\n本结果不能证明周期扫频总体最优，也不能外推固定频率普遍更好。',
  {left:72,top:532,width:1136,height:91},21,'#17324D');
add('energy-definition','采样保持积分：E_Rm = Σ P_Rm,k · Δt_k    共同安全最优电能 = 0.77568 J',
  {left:72,top:476,width:650,height:44},17,'#5F6B76');
add('energy-method','已有离散数据复算，包含扫描、试探和保护记录，非新仿真、非声学效率。',
  {left:72,top:640,width:1136,height:27},18,'#5F6B76');
txt('矩形 3','假设BVD电学模型，非实测    旧批次时序 a734eca013    与第14页后续候选分开评价',
  {left:72,top:688,width:1070,height:20},11.5,'#5F6B76');
const notes=[
'【建议讲解时间】约90秒',
'【版本关系】本页对原控制批次做评价口径修正，与第12页使用同一旧批次。第14页是第三轮后续无PI候选，本页三策略总表不是该候选的综合结果。',
'【讲稿】前面提到周期扫频和扫描辅助P&O的尾段误差是零，这个零有严格的样本范围。原指标优先选择每个扰动段后四分之一中的NORMAL、频率未冻结控制样本，缺少时采用程序规定的回退样本，再对7段求均值。因此，它没有完整计入前面的扫描、试探和保护恢复损失，也不表示连续稳态验收通过。',
'【讲稿续】为评价时间成本，我对相同0.8到6.4秒区间做了记录功率的采样保持积分，保留所有动作，以实际记录持续时间加权。固定频率加共同保护累积机械支路有功电能0.588焦耳，周期扫频0.474焦耳，扫描辅助P&O 0.525焦耳。统一除以该扰动日程的安全最优电能约0.77568焦耳，对应75.8%、61.1%和67.7%。这表明在当前短扰动段和扫描设置下，重新寻峰与保护恢复的时间代价不可忽略。尾段达到最优，不保证累计电能最优。',
'【结论边界】本批次固定频率的记录积分电能较高，但仍有较大的尾段误差和3个未通过段。周期扫频有2个未通过段，扫描辅助P&O有3个。不能仅按一个指标宣布总体优劣，更不能把排序外推到其他模型、扰动持续时间或真实器件。',
'【积分方法】每条记录按[t_k,t_k+duration_k)保持p_rm_W，与[0.8,6.4)相交后的持续时间相乘再求和。三策略均覆盖5.6秒，记录区间无重叠和缺口。包含CONTROL、SCAN及P&O参考与试探、保护降幅和停机记录。此处没有重新计算采样间隙内负载改变后的物理响应，不是第14页的保持指令跨扰动重放，不能用于证明硬限安全。',
`【统一分母】按同一绝对扰动日程，7段各0.8秒：E_safe,opt = Σ_j P_safe,max,j ×0.8 = ${d.reference_J.toFixed(12)} J。不能分别按各策略采样时刻的场景标签累加分母，否则会得到略有不同的比较基准。该比值既不是源到负载电学效率，也不是声学效率。`,
'【尾段误差回退规则】优先使用该段末25%内的NORMAL且频率未冻结CONTROL样本；若为空，取该段最后5个符合上述状态的CONTROL样本；仍为空，取最后5个CONTROL样本。每段计算100×(1−平均功率捕获率)，再对初始基准之后的7段等权平均。0.00%为显示精度下的尾段指标。',
'【原恢复指标备查】固定345.7 ms，周期扫频409.0 ms，P&O 458.9 ms。旧指标为成功段合格序列起点延迟，未通过段计800 ms后求均值；不是第10个样本的验收确认延迟。旧表保存样本硬越限均为0，不证明采样间隙没有越限。',
'【真实性】本次读取已有离散时序并积分、绘图，没有运行新控制仿真或LTspice。机械支路有功电能是等效电阻Rm中的电学积分量，不等于实测机械输出、声能或临床剂量。',
'【模糊推测内容】通过缩短扫描或优化保护恢复可以改善电能捕获率，属于后续待验证设计；本页未把该推测写成已验证改进。',
`【时序SHA256】${d.sources[0].sha256}`,
...d.sources.map(x=>`${d.source_dir}/${x.file}  SHA256=${x.sha256}`)
].join('\n\n');
slide.speakerNotes.textFrame.setText(notes);slide.speakerNotes.setVisible(true);
await fs.writeFile(`${O}/第15页_讲解稿.txt`,notes);
await(await PresentationFile.exportPptx(deck)).save(`${B}/authored.pptx`);
const parse=t=>xmljs.xml2js(t,{compact:false}),serial=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function els(root,name){const out=[];function walk(n){if(n.type==='element'&&n.name.split(':').at(-1)===name)out.push(n);for(const x of n.elements??[])walk(x);}walk(root);return out;}
const resolve=(p,t)=>t.startsWith('/')?t.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(p),t));
const sourceBytes=await fs.readFile(SOURCE),z=await JSZip.loadAsync(sourceBytes),edit=await JSZip.loadAsync(await fs.readFile(`${B}/authored.pptx`));
const part='ppt/slides/slide15.xml',rp='ppt/slides/_rels/slide15.xml.rels';
const oldRel=parse(await z.file(rp).async('string')),newRel=parse(await edit.file(rp).async('string'));
const sx=parse(await edit.file(part).async('string'));
for(const tree of els(sx,'spTree'))tree.elements=tree.elements.filter(n=>!(n.name?.split(':').at(-1)==='graphicFrame'&&els(n,'chart').length));
const newImage=els(newRel,'Relationship').find(n=>n.attributes.Type.endsWith('/image'));
const imagePart='ppt/media/energy_comparison_20260909.png',imageId='rIdEnergy20260909';
els(sx,'blip')[0].attributes['r:embed']=imageId;
const relRoot=els(oldRel,'Relationships')[0];
relRoot.elements=relRoot.elements.filter(n=>!n.attributes?.Type?.endsWith('/chart'));
relRoot.elements.push({type:'element',name:'Relationship',attributes:{Id:imageId,Type:newImage.attributes.Type,Target:'/'+imagePart}});
z.file(imagePart,await edit.file(resolve(part,newImage.attributes.Target)).async('uint8array'));
z.file(part,serial(sx));z.file(rp,serial(oldRel));
const oldNote=els(oldRel,'Relationship').find(n=>n.attributes.Type.endsWith('/notesSlide'));
const newNote=els(newRel,'Relationship').find(n=>n.attributes.Type.endsWith('/notesSlide'));
const notePart=resolve(part,oldNote.attributes.Target);
z.file(notePart,await edit.file(resolve(part,newNote.attributes.Target)).async('uint8array'));
const full=`${B}/candidate-full.pptx`;
await fs.writeFile(full,await z.generateAsync({type:'uint8array',compression:'DEFLATE'}));
const pdoc=parse(await z.file('ppt/presentation.xml').async('string')),keep=els(pdoc,'sldId')[14];
els(pdoc,'sldIdLst')[0].elements=[keep];
const pr=parse(await z.file('ppt/_rels/presentation.xml.rels').async('string'));
els(pr,'Relationships')[0].elements=els(pr,'Relationships')[0].elements.filter(n=>!n.attributes?.Type?.endsWith('/slide')||n.attributes.Id===keep.attributes['r:id']);
z.file('ppt/presentation.xml',serial(pdoc));z.file('ppt/_rels/presentation.xml.rels',serial(pr));
const rr=parse(await z.file('_rels/.rels').async('string'));
els(rr,'Relationships')[0].elements=els(rr,'Relationships')[0].elements.filter(n=>!n.attributes?.Type?.endsWith('/thumbnail'));
z.file('_rels/.rels',serial(rr));
const app=parse(await z.file('docProps/app.xml').async('string'));
for(const n of els(app,'Slides'))n.elements=[{type:'text',text:'1'}];
for(const n of els(app,'Properties'))n.elements=n.elements.filter(x=>!['TitlesOfParts','HeadingPairs'].includes(x.name?.split(':').at(-1)));
z.file('docProps/app.xml',serial(app));
const reach=new Set(['[Content_Types].xml','_rels/.rels']);
async function visit(p){if(reach.has(p))return;if(!z.file(p))throw Error(p);reach.add(p);
  const r=path.posix.join(path.posix.dirname(p),'_rels',path.posix.basename(p)+'.rels');
  if(z.file(r)){reach.add(r);for(const n of els(parse(await z.file(r).async('string')),'Relationship'))if(n.attributes.TargetMode!=='External')await visit(resolve(p,n.attributes.Target));}}
for(const n of els(rr,'Relationship'))if(n.attributes.TargetMode!=='External')await visit(resolve('',n.attributes.Target));
const ct=parse(await z.file('[Content_Types].xml').async('string'));
els(ct,'Types')[0].elements=els(ct,'Types')[0].elements.filter(n=>n.name?.split(':').at(-1)!=='Override'||reach.has(n.attributes.PartName.replace(/^\//,'')));
z.file('[Content_Types].xml',serial(ct));
const sz=new JSZip();for(const n of reach)sz.file(n,await z.file(n).async('uint8array'));
const single=`${B}/candidate-single.pptx`;await fs.writeFile(single,await sz.generateAsync({type:'uint8array',compression:'DEFLATE'}));
const outputs=[{candidate:full,final:`${O}/CTO组会汇报_第14与15页评价更新_2026-09-09.pptx`,count:28},
 {candidate:single,final:`${O}/第15页_尾段误差与全过程电能_2026-09-09.pptx`,count:1}];
const sha=createHash('sha256').update(sourceBytes).digest('hex');
await fs.writeFile(`${B}/contract.json`,JSON.stringify({source:SOURCE,sourceSha256:sha,expectedChanges:[part,rp,notePart],newImage:imagePart,outputs},null,2));
const {finalizePresentation}=await import(pathToFileURL(`${SKILL}/container_tools/artifact_tool_utils.mjs`).href);
for(const [i,o]of outputs.entries())try{
 await finalizePresentation({workspaceDir:DIR,candidatePath:o.candidate,finalPath:o.final,pythonExecutable:PYTHON,
  integrityValidatorPath:`${SKILL}/container_tools/inspect_presentation_package_integrity.py`,layoutValidatorPath:`${SKILL}/container_tools/inspect_presentation_layout_geometry.py`,
  explicitTotalSlideCount:o.count,requiredNativeTableOwnerSlides:[o.count===1?1:15],
  layoutArgs:['--expected-slide-size-emu',`${els(pdoc,'sldSz')[0].attributes.cx},${els(pdoc,'sldSz')[0].attributes.cy}`,'--validate-heading-fit','--validate-bullet-geometry'],
  fontPolicy:{basis:'reference',families:['Calibri'],referencePath:SOURCE,referenceSha256:sha},verifyArtifactToolImport:true,receiptPath:`${B}/finalizer-${i}.json`});
 }catch(e){await fs.writeFile(`${B}/finalizer-${i}-error.json`,JSON.stringify({message:e.message,code:e.code},null,2));console.log('Finalizer fallback needed:',e.message);}
console.log('Authored slide 15 candidates.');
