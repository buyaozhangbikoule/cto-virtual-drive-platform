import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import JSZip from 'jszip';
import xmljs from 'xml-js';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const ROOT='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const DIR=`${ROOT}/ppt_acceptance_update_20260909`, BUILD=`${DIR}/build`, OUT=`${DIR}/output`;
const SOURCE=`${ROOT}/ppt_control_fix_20260906/output/CTO第一月组会汇报_第5及12_14_15页修订_2026-09-06.pptx`;
const SKILL='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const PYTHON='C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const d=JSON.parse(await fs.readFile(`${BUILD}/page_data.json`,'utf8')), m=d.metric;
const hash=d.source_manifest[0].sha256;
const deck=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const records=(await deck.inspect({kind:'slide,textbox,shape,image,notes,layout',maxChars:350000})).ndjson.trim().split('\n').map(JSON.parse);
const slide=deck.resolve(records.find(x=>x.kind==='slide'&&x.slide===14).id);
function text(name,value,position,size,color='#17324D',bold=false){
  const record=records.find(x=>x.slide===14&&x.name===name&&['textbox','shape'].includes(x.kind));
  if(!record)throw Error(name);
  const o=deck.resolve(record.id);o.text=value;if(position)o.position=position;
  o.text.style={typeface:'Calibri',fontSize:size,bold,color,autoFit:'none',alignment:'left',verticalAlignment:'middle',
    insets:{top:0,bottom:0,left:0,right:0}};
}
text('title-11','时序修正已使部分版本通过谐振漂移段的连续稳态验收，\n但全过程能量损失及采样间隙越限尚未解决',
  {left:72,top:26,width:1136,height:67},30,'#17324D',true);
text('矩形 6','后续实验：固定无PI候选',{left:901,top:125,width:306,height:31},23,'#17324D',true);
text('矩形 7','P&O等待500 ms，试探幅度≤0.9\n恢复门槛R2，重扫幅度仍≤0.4\n本段：fs−5%，2.4–3.2 s',
  {left:901,top:164,width:306,height:74},18,'#5F6B76');
text('矩形 8','本段连续稳态：通过',{left:901,top:258,width:306,height:30},23,'#2F73B7',true);
text('矩形 9',`首次合格：${m.accepted_start_s.toFixed(3)} s\n验收确认：${m.confirmation_s.toFixed(3)} s（延迟742 ms）\n连续合格12个，门槛10个\n尾段频率：0.8548 MHz`,
  {left:901,top:300,width:306,height:94},18,'#2F73B7');
text('矩形 10','能量损失与硬限：未解决',{left:901,top:410,width:306,height:30},22,'#C84444',true);
text('矩形 11',`本段能量捕获率：${m.held_energy_capture_pct.toFixed(1)}%\n间隙重放峰值：${m.held_command_peak_vpp.toFixed(1)} Vpp\n高于160 Vpp累计约1.0 ms`,
  {left:901,top:452,width:306,height:75},18,'#C84444');
text('矩形 12','验收冻结：0.8 s/段，功率≥98%\nNORMAL且频率未冻结，连续10样本\n保留异常检测及原保护保持时间\n硬边界：160 Vpp / 6 mA RMS',
  {left:901,top:558,width:306,height:94},17,'#17324D');
text('矩形 3',`假设BVD电学模型，非实测    第三轮时序 ${hash.slice(0,10)}    第12/15页仍为旧批次对照`,
  {left:72,top:688,width:1070,height:20},11.5,'#5F6B76');
const im=deck.resolve(records.find(x=>x.slide===14&&x.kind==='image').id);
im.replace({blob:new Uint8Array(await fs.readFile(`${OUT}/第14页_验收与风险证据图.png`)),contentType:'image/png',fit:'contain',
  alt:'第三轮无PI候选的完整局部控制时序。12个连续合格样本，本段能量45.4%，保持指令重放峰值188.2 Vpp，仍超过160 Vpp。'});
im.frame={left:72,top:132,width:810,height:524.12};im.crop={left:0,right:0,top:0,bottom:0};
const notes=[
'【建议讲解时间】约90秒',
'【版本关系】本页更新为第三轮固定无PI候选的后续实验。完整版中的第12、15页仍保留此前同一次运行的历史对照，不能与本页拼成同一次运行的综合成绩。',
'【讲稿】前面的版本已经找到了新的功率峰，但没有留下足够的连续合格样本。本页展示时序修正后的一个简单候选，采用扫描辅助P&O，不加独立PI。等待参数为500毫秒，P&O试探幅度上限0.9，重捕获扫描仍为0.4。图中保留全部保护、扫描和恢复动作。fs降低5%后，控制器在2.962秒出现首次合格NORMAL样本，在3.142秒确认第10个合格样本，本段最长连续12个，所以这一次满足原稳态窗口标准。',
'【讲稿续】但本段能量捕获率只有45.4%，因为前面的保护、搜索和恢复占用了输出时间。下面的电压图把负载切换发生在采样之间时，旧指令继续保持的区间也算进来，重放峰值188.2 Vpp，超过160 Vpp约1毫秒。这个结果说明稳态窗口通过了，但电学能量损失和硬限问题还没有解决。下一步固定这个候选，分别处理恢复余量与采样间隙风险，不继续叠加更多算法。',
'【冻结条件】本段保持2.4至3.2秒，即0.8秒。门槛保持功率捕获率至少98%，CONTROL、NORMAL、频率未冻结、连续10个合格样本，相邻CONTROL间隔不超过30毫秒。硬限160 Vpp/6 mA RMS、异常检测与原保护保持时间不修改。6 mA RMS为本项目假设硬限，160 Vpp来自用户要求。',
'【指标定义】742毫秒是3.142减2.4，是第10个样本的确认延迟。10个20毫秒等间隔样本的首末跨度为180毫秒。本段最长连续12个，不表示全程保持高功率。',
'【能量定义】本段能量捕获率为实际P_Rm在整个0.8秒区间的积分，除以本段安全最优P_Rm乘0.8秒。分母约140.2 mW，尾段100%不代表恢复到基准170.0 mW。积分包含所有保护、扫描、试探与恢复，也包含重放越限区间，不能称为完全安全的收益或源到负载效率。',
'【候选】B0_T500_A90_R2，第三轮0.8秒/段。T500是等待参数，不是实际两次试探起点间隔。R2是在原调度条件外，要求恢复后的正常等待和10个稳定样本，不读取离线最佳功率作为触发答案。该候选全序列稳态7/7不是全序列硬安全通过。',
'【真实性与限制】本次只读取已经保存的数据、重建保持指令及更新PPT，没有重新运行控制器或LTspice。图为假设线性BVD离散准稳态结果，不是示波器、LTspice瞬态或实测器件波形。模型重放不能预测真实储能振铃，当前保护还利用准确模型预估。',
'【模糊推测内容】下一轮通过安全裕量或恢复时序调整能否消除越限、提高能量尚未验证，本页没有把这些计划写成已实现结果。',
`【数据出处】时序SHA256：${hash}。`,...d.source_manifest.map(x=>x.path)
].join('\n\n');
slide.speakerNotes.textFrame.setText(notes);slide.speakerNotes.setVisible(true);
await fs.writeFile(`${OUT}/第14页_讲解稿.txt`,notes,'utf8');
const authored=`${BUILD}/authored.pptx`;
await(await PresentationFile.exportPptx(deck)).save(authored);

// Preserve all unrelated package members exactly. Only slide 14, its notes,
// its image relationship and a new image part are transplanted.
const parse=t=>xmljs.xml2js(t,{compact:false}), serial=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function els(root,name){const result=[];function walk(n){if(n.type==='element'&&n.name.split(':').at(-1)===name)result.push(n);for(const e of n.elements??[])walk(e);}walk(root);return result;}
const resolve=(part,target)=>target.startsWith('/')?target.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(part),target));
const sourceBytes=await fs.readFile(SOURCE);
const z=await JSZip.loadAsync(sourceBytes), edited=await JSZip.loadAsync(await fs.readFile(authored));
const part='ppt/slides/slide14.xml',rp='ppt/slides/_rels/slide14.xml.rels';
const oldRel=parse(await z.file(rp).async('string')),newRel=parse(await edited.file(rp).async('string'));
const oldImage=els(oldRel,'Relationship').find(x=>x.attributes.Type.endsWith('/image'));
const newImage=els(newRel,'Relationship').find(x=>x.attributes.Type.endsWith('/image'));
const slideXml=parse(await edited.file(part).async('string'));
els(slideXml,'blip')[0].attributes['r:embed']=oldImage.attributes.Id;
const imagePart='ppt/media/acceptance_candidate_20260909.png';
oldImage.attributes.Target='/'+imagePart;
z.file(imagePart,await edited.file(resolve(part,newImage.attributes.Target)).async('uint8array'));
z.file(part,serial(slideXml));z.file(rp,serial(oldRel));
const oldNotes=els(oldRel,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
const newNotes=els(newRel,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
const notePart=resolve(part,oldNotes.attributes.Target);
z.file(notePart,await edited.file(resolve(part,newNotes.attributes.Target)).async('uint8array'));
const full=`${BUILD}/candidate-full.pptx`;
await fs.writeFile(full,await z.generateAsync({type:'uint8array',compression:'DEFLATE'}));

// Create a separate one-slide extract; retain reachable template dependencies.
const pdoc=parse(await z.file('ppt/presentation.xml').async('string'));
const ids=els(pdoc,'sldId');const keep=ids[13];
const lst=els(pdoc,'sldIdLst')[0];lst.elements=[keep];
const relDoc=parse(await z.file('ppt/_rels/presentation.xml.rels').async('string'));
els(relDoc,'Relationships')[0].elements=els(relDoc,'Relationships')[0].elements.filter(x=>
  x.type!=='element'||!x.attributes.Type?.endsWith('/slide')||x.attributes.Id===keep.attributes['r:id']);
z.file('ppt/presentation.xml',serial(pdoc));z.file('ppt/_rels/presentation.xml.rels',serial(relDoc));
const rootRel=parse(await z.file('_rels/.rels').async('string'));
els(rootRel,'Relationships')[0].elements=els(rootRel,'Relationships')[0].elements.filter(x=>x.type!=='element'||!x.attributes.Type?.endsWith('/thumbnail'));
z.file('_rels/.rels',serial(rootRel));
const app=parse(await z.file('docProps/app.xml').async('string'));
for(const n of els(app,'Slides'))n.elements=[{type:'text',text:'1'}];
for(const n of els(app,'Properties'))n.elements=n.elements.filter(x=>!['TitlesOfParts','HeadingPairs'].includes(x.name?.split(':').at(-1)));
z.file('docProps/app.xml',serial(app));
const reachable=new Set(['[Content_Types].xml']);
async function visit(partName){
  if(reachable.has(partName))return;
  if(!z.file(partName))throw Error(`Missing dependency ${partName}`);
  reachable.add(partName);
  const relationship=partName===''?'_rels/.rels':path.posix.join(path.posix.dirname(partName),'_rels',path.posix.basename(partName)+'.rels');
  if(z.file(relationship)){
    reachable.add(relationship);
    for(const x of els(parse(await z.file(relationship).async('string')),'Relationship')){
      if(x.attributes.TargetMode==='External')continue;
      await visit(resolve(partName,x.attributes.Target));
    }
  }
}
reachable.add('_rels/.rels');
for(const x of els(rootRel,'Relationship'))if(x.attributes.TargetMode!=='External')await visit(resolve('',x.attributes.Target));
const ct=parse(await z.file('[Content_Types].xml').async('string'));
els(ct,'Types')[0].elements=els(ct,'Types')[0].elements.filter(x=>x.name?.split(':').at(-1)!=='Override'||reachable.has(x.attributes.PartName.replace(/^\//,'')));
z.file('[Content_Types].xml',serial(ct));
const singleZip=new JSZip();for(const name of reachable)singleZip.file(name,await z.file(name).async('uint8array'));
const single=`${BUILD}/candidate-single.pptx`;
await fs.writeFile(single,await singleZip.generateAsync({type:'uint8array',compression:'DEFLATE'}));
const finalFull=`${OUT}/CTO组会汇报_第14页验收进展更新_2026-09-09.pptx`;
const finalSingle=`${OUT}/第14页_稳态验收与未解决风险_2026-09-09.pptx`;
await fs.writeFile(`${BUILD}/contract.json`,JSON.stringify({source:SOURCE,sourceSha256:createHash('sha256').update(sourceBytes).digest('hex'),
  expectedChanges:[part,rp,notePart],newImage:imagePart,
  outputs:[{candidate:full,final:finalFull,count:28},{candidate:single,final:finalSingle,count:1}]},null,2));
const {finalizePresentation}=await import(pathToFileURL(`${SKILL}/container_tools/artifact_tool_utils.mjs`).href);
for(const [i,o]of [{candidate:full,final:finalFull,count:28},{candidate:single,final:finalSingle,count:1}].entries()){
  try{
    await finalizePresentation({workspaceDir:DIR,candidatePath:o.candidate,finalPath:o.final,pythonExecutable:PYTHON,
      integrityValidatorPath:`${SKILL}/container_tools/inspect_presentation_package_integrity.py`,
      layoutValidatorPath:`${SKILL}/container_tools/inspect_presentation_layout_geometry.py`,explicitTotalSlideCount:o.count,
      layoutArgs:['--expected-slide-size-emu',`${els(pdoc,'sldSz')[0].attributes.cx},${els(pdoc,'sldSz')[0].attributes.cy}`,'--validate-heading-fit','--validate-bullet-geometry'],
      fontPolicy:{basis:'reference',families:['Calibri'],referencePath:SOURCE,referenceSha256:createHash('sha256').update(sourceBytes).digest('hex')},
      verifyArtifactToolImport:true,receiptPath:`${BUILD}/finalizer-${i}.json`});
  }catch(error){
    await fs.writeFile(`${BUILD}/finalizer-${i}-error.json`,JSON.stringify({message:error.message,code:error.code},null,2));
    console.log('Finalizer could not finish. Run the same bundled validators directly.',error.message);
  }
}
console.log('Candidates authored; verify before publishing.');
