import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import JSZip from 'jszip';
import xmljs from 'xml-js';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const ROOT = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const BUILD = `${ROOT}/ppt_slide5_fix_20260906/build`;
const OUT = `${ROOT}/ppt_slide5_fix_20260906/output`;
const SOURCE = `${ROOT}/CTO超声换能器第一月教授组会汇报_逐页讲稿版_2026-09-04.pptx`;
const FINAL = `${OUT}/CTO第一月组会汇报_第5页修订_2026-09-06.pptx`;
const SKILL = 'C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations';
const PYTHON = 'C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
const A = 'http://schemas.openxmlformats.org/drawingml/2006/main';
const P = 'http://schemas.openxmlformats.org/presentationml/2006/main';
const R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships';
const parseXml=(text)=>xmljs.xml2js(text,{compact:false});
const writeXml=(doc)=>xmljs.js2xml(doc,{compact:false,spaces:0});
function elements(doc,localName) {
  const found=[];
  function walk(node) {
    if(node.type==='element' && node.name.split(':').at(-1)===localName) found.push(node);
    for(const child of node.elements??[]) walk(child);
  }
  walk(doc); return found;
}
const plotAudit = JSON.parse(await fs.readFile(`${BUILD}/plot_audit.json`, 'utf8'));
if (Math.abs(plotAudit.at_f0.ACTIVE_LOSSY.p_rm_mW - 170) > 0.001) throw Error('Power audit failed');

const notes = [
  '【建议时长】约60秒',
  '【本页结论】在0.9000 MHz、同一校准戴维南源和50 Ω源阻抗条件下，v2.1有损L型匹配使P_Rm达到未匹配时的约32.8倍。',
  '【逐字讲稿】这一页比较匹配网络本身带来的变化。全部曲线使用同一个冻结戴维南源，源电压约6.217 V RMS，源阻抗50欧姆。这里的6.217 V是理想源的有效值，100 Vpp则是加入有损匹配后在0.9 MHz得到的换能器端电压，二者测量位置和单位都不同。上图灰色虚线表示未匹配，橙色实线表示v2.1有损匹配，蓝色点线是理想无额外寄生损耗的匹配参考。在相同的0.9000 MHz处，P_Rm从5.186毫瓦提高到170.0毫瓦，约为原来的32.8倍。下图显示匹配网络输入端的反射代理，其定义使用50欧姆实参考阻抗。当前曲线来自已保存的LTspice频域结果，按线性模型的源幅度平方关系换算到统一的校准源条件。P_Rm表示BVD机械支路电阻的有功耗散，不能直接等同于声功率。',
  '【看图顺序】先读源条件。上图在0.9000 MHz比较未匹配与有损匹配的功率。再看下图输入反射代理。最后区分源电压和换能器端电压。',
  '【数值口径】计算使用Vs=6.217360894531728 V RMS，Rs=50 Ω，显示时将Vs取为6.217。已保存的1 V RMS源数据统一乘Vs²=38.65557649285237得到当前功率。未匹配5.186363126 mW，有损匹配169.999953760 mW，比值32.778258990。归一化的0.134168562 mW和4.397811886 mW仅用于换算说明，不与当前工作点交叉比较。',
  '【电压位置】本页100 Vpp、约5 mA RMS仅描述有损匹配在0.9000 MHz的换能器端工作点，不表示全频段端电压恒定，也不是戴维南源电压。全部曲线冻结同一源参数，没有逐频调整源幅度。',
  '【反射代理】Gamma=abs((Zin-50)/(Zin+50))，Zin为源电阻之后、匹配网络输入端阻抗。线性模型下该代理不随整体源幅度缩放而变化。它不是反射功率的瓦特值。',
  '【参数与限制】Lmatch约106.726 μH，Cmatch约283.599 pF，实际有损网络另含ESR。此处使用假设BVD模型参数，非实测。32.8倍是该工作点的P_Rm比值，不能解释为电声效率增益或临床效应。',
  '【教授可能追问】为什么1 V RMS仿真结果能换算到约6.217 V RMS？',
  '【建议回答】当前电路为线性AC模型，全部电压和电流相量随源幅度成比例，复功率随源幅度平方变化。对所有电路统一使用同一个幅度系数，阻抗、相位和反射代理不变。170 mW对应校准后的源条件，不能标成1 V RMS源条件的直接结果。',
  '【模糊推测】本页不对P_Rm与实际声功率的关系作定量推测。该关系尚需机电声耦合模型和实验标定验证。',
  '[Sources]',
  `${ROOT}/CTO_virtual_drive_platform_v2_1/evidence/ltspice/stage2/stage2_audit.json`,
  `${ROOT}/outputs/v2_self_consistent_rebuild/stage2_matching/stage2_匹配前后特征汇总.csv`,
  `${ROOT}/outputs/v2_self_consistent_rebuild/stage2_matching/stage2_LTspice逐频数据.csv`,
].join('\n\n');

const deck = await PresentationFile.importPptx(await FileBlob.load(SOURCE));
if (deck.slides.items.length !== 28) throw Error('Source slide count changed');
const snapshot = await deck.inspect({kind:'slide,textbox,shape,image,notes,layout',maxChars:300000});
await fs.writeFile(`${BUILD}/before-inspect.ndjson`, snapshot.ndjson);
const records = snapshot.ndjson.trim().split('\n').map(line=>JSON.parse(line));
const slideRecord = records.find(r=>r.kind==='slide' && r.slide===5);
if (!slideRecord) throw Error('Slide 5 not found');
const slide = deck.resolve(slideRecord.id);
await fs.writeFile(`${BUILD}/before-slide5.png`, new Uint8Array(await (await deck.export({slide,format:'png',scale:1})).arrayBuffer()));
function byName(name) {
  const r=records.find(r=>r.slide===5 && r.name===name && (r.kind==='shape'||r.kind==='textbox'));
  if (!r) throw Error(`Missing shape ${name}`);
  return deck.resolve(r.id);
}
function update(name,text,position,size,color='#17324D',bold=true,alignment='center') {
  const item=byName(name); item.text=text;
  if(position) item.position=position;
  item.text.style={typeface:'Calibri',fontSize:size,color,bold,alignment,verticalAlignment:'middle',autoFit:'none',insets:{left:4,right:4,top:2,bottom:2}};
  return item;
}
function addText(name,text,position,size,color='#17324D',bold=false,alignment='left') {
  const item=slide.shapes.add({name,geometry:'textbox',position,fill:'none',line:{fill:'none',width:0}});
  item.text=text;
  item.text.style={typeface:'Calibri',fontSize:size,color,bold,alignment,verticalAlignment:'middle',autoFit:'none',insets:{left:0,right:0,top:0,bottom:0}};
  return item;
}
update('title-5','同一源条件下，L型匹配使0.9 MHz的有功功率达到约32.8倍',null,36,'#17324D',true,'left');
addText('source-condition-corrected','冻结戴维南源：6.217 V RMS，Rs = 50 Ω，全部曲线使用相同源参数',
  {left:72,top:110,width:1136,height:34},23,'#5F6B76');

const imageRecord=records.find(r=>r.slide===5 && r.kind==='image');
if(!imageRecord) throw Error('Slide 5 chart image missing');
const pic=deck.resolve(imageRecord.id);
pic.replace({blob:new Uint8Array(await fs.readFile(`${BUILD}/matching_calibrated.png`)),contentType:'image/png',
  alt:'已保存LTspice频域数据统一换算到6.2173608945 V RMS源。0.9 MHz未匹配5.186 mW，有损匹配170.0 mW。下图为无量纲输入反射代理。',fit:'contain'});
pic.frame={left:72,top:155,width:738,height:494.46};
pic.crop={left:0,top:0,right:0,bottom:0};

byName('矩形: 圆角 7').position={left:850,top:175,width:350,height:125};
update('矩形 8','Lmatch ≈ 106.726 μH\nCmatch ≈ 283.599 pF\n设计中心：0.9 MHz',
  {left:860,top:186,width:330,height:103},22);
update('矩形 9','0.9000 MHz\n未匹配 5.186 mW\n有损匹配 170.0 mW\n比值约32.8倍',
  {left:850,top:321,width:350,height:140},27,'#CA8400');
addText('port-operating-point','有损匹配工作点\n换能器端约100 Vpp\n电流约5 mA RMS',
  {left:850,top:477,width:350,height:88},22,'#17324D',false,'center');
update('矩形 10','结果限于假设BVD电学模型\n32.8倍不代表电声效率增益',
  {left:850,top:588,width:350,height:63},20,'#B33A3A',false,'center');
slide.speakerNotes.textFrame.setText(notes);
slide.speakerNotes.setVisible(true);
await fs.writeFile(`${BUILD}/slide5_讲稿.txt`, notes,'utf8');
await fs.writeFile(`${BUILD}/after-edit-layout.json`,await (await slide.export({format:'layout'})).text());
const EXPORTED=`${BUILD}/artifact-edited.pptx`;
await (await PresentationFile.exportPptx(deck)).save(EXPORTED);

// Transplant only the authored slide, its notes and replacement image.
// Keep every original package member unrelated to slide 5 byte-for-byte intact.
const originalBytes=await fs.readFile(SOURCE);
const original=await JSZip.loadAsync(originalBytes);
const exported=await JSZip.loadAsync(await fs.readFile(EXPORTED));
const relName='ppt/slides/_rels/slide5.xml.rels';
const relDoc=parseXml(await exported.file(relName).async('string'));
const rels=elements(relDoc,'Relationship');
const exportedImg=rels.find(r=>r.attributes.Type.endsWith('/image'));
const exportedNote=rels.find(r=>r.attributes.Type.endsWith('/notesSlide'));
const srcRelDoc=parseXml(await original.file(relName).async('string'));
const srcRels=elements(srcRelDoc,'Relationship');
const srcImg=srcRels.find(r=>r.attributes.Type.endsWith('/image'));
const srcNote=srcRels.find(r=>r.attributes.Type.endsWith('/notesSlide'));
const sourceSlidePath='ppt/slides/slide5.xml';
const resolveTarget=(part,target)=>target.startsWith('/')?target.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(part),target));
const slideDoc=parseXml(await exported.file(sourceSlidePath).async('string'));
const blips=elements(slideDoc,'blip');
if(blips.length!==1) throw Error('Unexpected chart-image count on slide 5');
blips[0].attributes['r:embed']=srcImg.attributes.Id;
const imagePath='ppt/media/slide5_matching_calibrated_20260906.png';
srcImg.attributes.Target=`/${imagePath}`;
original.file(sourceSlidePath,writeXml(slideDoc));
original.file(relName,writeXml(srcRelDoc));
original.file(resolveTarget(sourceSlidePath,srcNote.attributes.Target),
  await exported.file(resolveTarget(sourceSlidePath,exportedNote.attributes.Target)).async('uint8array'));
original.file(imagePath,await exported.file(resolveTarget(sourceSlidePath,exportedImg.attributes.Target)).async('uint8array'));
const CANDIDATE=`${BUILD}/candidate.pptx`;
await fs.writeFile(CANDIDATE,await original.generateAsync({type:'uint8array',compression:'DEFLATE'}));
if(process.argv.includes('--author-only')) {
  console.log(JSON.stringify({candidate:CANDIDATE,followUp:'Run validate_fallback.py and render_verified.mjs'}));
  process.exit(0);
}

const { finalizePresentation }=await import(pathToFileURL(`${SKILL}/container_tools/artifact_tool_utils.mjs`).href);
const sldSize=elements(parseXml(await original.file('ppt/presentation.xml').async('string')),'sldSz')[0];
const result=await finalizePresentation({
  workspaceDir:ROOT,candidatePath:CANDIDATE,finalPath:FINAL,pythonExecutable:PYTHON,
  integrityValidatorPath:`${SKILL}/container_tools/inspect_presentation_package_integrity.py`,
  layoutValidatorPath:`${SKILL}/container_tools/inspect_presentation_layout_geometry.py`,
  explicitTotalSlideCount:28,
  layoutArgs:['--expected-slide-size-emu',`${sldSize.attributes.cx},${sldSize.attributes.cy}`,'--validate-bullet-geometry','--validate-heading-fit'],
  requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
  fontPolicy:{basis:'reference',families:['Calibri','Calibri Light'],referencePath:SOURCE,
    referenceSha256:createHash('sha256').update(originalBytes).digest('hex')},
  verifyArtifactToolImport:true,receiptPath:`${BUILD}/validation.json`,
});
await fs.writeFile(`${BUILD}/finalization-result.json`,JSON.stringify(result,null,2));

const finalBytes=await fs.readFile(FINAL);
const oldZip=await JSZip.loadAsync(originalBytes);
const newZip=await JSZip.loadAsync(finalBytes);
const changed=[];
for(const name of Object.keys(oldZip.files).filter(n=>!oldZip.files[n].dir)) {
  if(!newZip.file(name)) throw Error(`Lost original package member: ${name}`);
  if(!Buffer.from(await oldZip.file(name).async('uint8array')).equals(Buffer.from(await newZip.file(name).async('uint8array')))) changed.push(name);
}
const allowed=new Set([sourceSlidePath,relName,'ppt/notesSlides/notesSlide5.xml']);
if(changed.some(n=>!allowed.has(n))) throw Error(`Unrelated package change: ${changed.join(', ')}`);
await fs.writeFile(`${BUILD}/preservation-audit.json`,JSON.stringify({changedMembers:changed,addedMedia:imagePath,
  sourceSha256:createHash('sha256').update(originalBytes).digest('hex'),finalSha256:createHash('sha256').update(finalBytes).digest('hex'),
  unchangedSlides:Array.from({length:28},(_,i)=>i+1).filter(n=>n!==5)},null,2));

const verified=await PresentationFile.importPptx(await FileBlob.load(FINAL));
await fs.mkdir(`${BUILD}/final-preview`,{recursive:true});
for(let i=0;i<verified.slides.items.length;i++) {
  const bytes=new Uint8Array(await (await verified.export({slide:verified.slides.items[i],format:'png',scale:i===4?1.5:0.5})).arrayBuffer());
  await fs.writeFile(`${BUILD}/final-preview/slide-${String(i+1).padStart(2,'0')}.png`,bytes);
}
await fs.copyFile(`${BUILD}/final-preview/slide-05.png`,`${OUT}/第5页_修订预览.png`);
await fs.copyFile(`${BUILD}/slide5_讲稿.txt`,`${OUT}/第5页_讲稿.txt`);
console.log(JSON.stringify({final:FINAL,slideCount:28,changedMembers:changed,preview:`${OUT}/第5页_修订预览.png`},null,2));
