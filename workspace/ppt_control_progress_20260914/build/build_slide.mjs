import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {Presentation, PresentationFile, FileBlob} from '@oai/artifact-tool';
import JSZip from 'jszip';
import xmljs from 'xml-js';

const B = path.dirname(new URL(import.meta.url).pathname.replace(/^\/(?:([A-Za-z]:))/, '$1'));
const W = path.dirname(B), R = path.dirname(W);
const source = `${R}/ppt_full_audit_20260911/output/CTO组会汇报_全28页图文核查版_2026-09-11.pptx`;
const before = await PresentationFile.importPptx(await FileBlob.load(source));
const snap = (await before.inspect({kind:'slide,textbox,shape,image,table,notes,layout', maxChars:1000000})).ndjson;
const records = snap.trim().split('\n').map(JSON.parse);
const targetRecord = records.find(r => r.kind === 'slide' && r.slide === 15);
if (!targetRecord) throw Error('Slide 15 not found');
const target = before.resolve(targetRecord.id);
await fs.writeFile(`${B}/before.layout.json`, await (await target.export({format:'layout'})).text());
await fs.writeFile(`${B}/before.png`, new Uint8Array(await (await target.export({format:'png',scale:1})).arrayBuffer()));
await fs.writeFile(`${B}/before.inspect.ndjson`, snap);

const p = Presentation.create({slideSize:{width:1280,height:720}});
const s = p.slides.add();
s.background.fill = '#F7F8FA';
const navy='#17324D', blue='#2B70B5', gray='#5F6B76', purple='#866090';
function box(name, text, x, y, w, h, size=22, color=navy, bold=false) {
  const o=s.shapes.add({name,geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  o.text=text;
  o.text.style={typeface:'Calibri',fontSize:size,color,bold,autoFit:'none',alignment:'left',verticalAlignment:'middle',insets:{top:0,bottom:0,left:0,right:0}};
  return o;
}
function rule(name,x,y,w,h,color){s.shapes.add({name,geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:color,line:{fill:'none',width:0}});}
box('title-15','三种控制原型已实现：调频依据不同，扰动响应也不同',72,36,1136,58,32,navy,true);
rule('title-rule',72,98,1136,3,navy);
box('fixed-method-title','固定频率＋共同保护',72,119,344,31,25,gray,true);
box('fixed-method','正常保持0.9 MHz，不主动寻峰\n保护可降幅或停机',72,157,344,56,22);
box('fixed-purpose','用途：建立扰动响应基线',72,221,344,29,20,gray);
box('scan-method-title','周期扫频＋共同保护',455,119,344,31,25,blue,true);
box('scan-method','逐点比较功率，选择候选峰位\n恢复幅度后继续监测',455,157,344,56,22);
box('scan-purpose','用途：验证重新定位功率峰',455,221,344,29,20,gray);
box('phase-method-title','相位误差闭环',840,119,368,31,25,purple,true);
box('phase-method','按输入相位误差及局部斜率调频\n保护冻结时暂停频率更新',840,157,368,56,22);
box('phase-purpose','用途：检验基准相位目标适用性',840,221,368,29,20,gray);
rule('method-separator-1',432,121,1,126,'#D5DDE5');
rule('method-separator-2',816,121,1,126,'#D5DDE5');
rule('section-divider',72,263,1136,1,'#C7D1DC');

// Separate provenance, not a unified experimental ranking.
box('left-title','A  固定与扫频：同一历史主时序',72,276,551,30,23,navy,true);
box('left-provenance','2.4 s起 fs−5%，保留扫描与保护记录',72,307,551,27,18,gray);
box('right-title','B  相位反馈：独立历史试验',662,276,546,30,23,purple,true);
box('right-parameters','Kφ＝5 Hz/°，目标输入相位＝−1.0782°',662,307,546,27,18,gray);
for (const [name,file,x] of [['main-result','fixed_periodic_history',72],['phase-result','phase_history',662]]) {
  s.images.add({blob:new Uint8Array(await fs.readFile(`${B}/figures/${file}.png`)),contentType:'image/png',alt:name,fit:'contain',position:{left:x,top:337,width:546,height:304}});
}
rule('provenance-divider',641,279,1,367,'#D5DDE5');
box('left-result','已到新峰位，连续合格6/10样本，未通过本段验收',72,641,552,29,18,blue,true);
box('right-result','本段调频被保护冻结，不能据此只归因于小增益',662,641,550,29,18,purple,true);
rule('footer-rule',72,676,1136,1,'#C7D1DC');
box('ranking-boundary','相位试验与另外两种策略的口径尚未统一，本页展示实现与现象，不作性能排名。',72,679,1125,23,17,navy);
box('scope','假设BVD电学模型，非实测数据    扫描辅助P&O作为第四种扩展方法另页展示',72,703,1080,14,11,gray);
box('page-number','15',1160,703,37,14,11,gray);
s.speakerNotes.textFrame.setText(await fs.readFile(`${B}/notes.txt`,'utf8'));
await (await PresentationFile.exportPptx(p)).save(`${B}/single_candidate.pptx`);
await fs.writeFile(`${B}/authored.png`,new Uint8Array(await (await s.export({format:'png',scale:1.5})).arrayBuffer()));
await fs.writeFile(`${B}/authored.layout.json`,await (await s.export({format:'layout'})).text());

// Transplant only the authored slide content and notes, preserving original
// unmodified slide XML, media, theme, master, layouts and all other notes.
const parse=t=>xmljs.xml2js(t,{compact:false}), serial=d=>xmljs.js2xml(d,{compact:false,spaces:0});
function els(root,name){const a=[];function walk(x){if(x.type==='element'&&x.name.split(':').at(-1)===name)a.push(x);for(const y of x.elements??[])walk(y);}walk(root);return a;}
const resolve=(part,t)=>t.startsWith('/')?t.slice(1):path.posix.normalize(path.posix.join(path.posix.dirname(part),t));
const relpart=part=>`${path.posix.dirname(part)}/_rels/${path.posix.basename(part)}.rels`;
const z=await JSZip.loadAsync(await fs.readFile(source));
const originalBytes=new Map(await Promise.all(Object.keys(z.files).filter(x=>!z.files[x].dir).map(async x=>[x,await z.file(x).async('uint8array')])));
const a=await JSZip.loadAsync(await fs.readFile(`${B}/single_candidate.pptx`));
async function order(zip){const r=parse(await zip.file('ppt/_rels/presentation.xml.rels').async('string'));const m=Object.fromEntries(els(r,'Relationship').map(x=>[x.attributes.Id,resolve('ppt/presentation.xml',x.attributes.Target)]));return els(parse(await zip.file('ppt/presentation.xml').async('string')),'sldId').map(x=>m[x.attributes['r:id']]);}
const op=(await order(z))[14], ap=(await order(a))[0];
const ox=parse(await z.file(op).async('string')), ax=parse(await a.file(ap).async('string'));
const or=parse(await z.file(relpart(op)).async('string')), ar=parse(await a.file(relpart(ap)).async('string'));
const ot=els(ox,'spTree')[0], at=els(ax,'spTree')[0];
const metaNodes=new Set(['nvGrpSpPr','grpSpPr']);
ot.elements=[...ot.elements.filter(x=>metaNodes.has(x.name?.split(':').at(-1))),...at.elements.filter(x=>!metaNodes.has(x.name?.split(':').at(-1)))];
const originalRoot=els(ox,'sld')[0], authoredRoot=els(ax,'sld')[0];
for(const [k,v] of Object.entries(authoredRoot.attributes??{}))if(k.startsWith('xmlns:'))originalRoot.attributes[k]??=v;
let num=0;
for (const pic of els(ot,'pic')){
 const blip=els(pic,'blip')[0], rid=blip.attributes['r:embed'];
 const rel=els(ar,'Relationship').find(x=>x.attributes.Id===rid);
 const bytes=await a.file(resolve(ap,rel.attributes.Target)).async('uint8array');
 const media=`ppt/media/progress_20260915_${++num}.png`, newrid=`rIdProgress20260915_${num}`;
 z.file(media,bytes);blip.attributes['r:embed']=newrid;
 els(or,'Relationships')[0].elements.push({type:'element',name:'Relationship',attributes:{Id:newrid,Type:'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image',Target:`../media/${path.posix.basename(media)}`}});
}
z.file(op,serial(ox));z.file(relpart(op),serial(or));
const on=els(or,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
const an=els(ar,'Relationship').find(x=>x.attributes.Type.endsWith('/notesSlide'));
if(!on||!an)throw Error('Missing notes');
const onp=resolve(op,on.attributes.Target), anp=resolve(ap,an.attributes.Target);
const nx=parse(await z.file(onp).async('string')), na=parse(await a.file(anp).async('string'));
const body=o=>els(o,'sp').find(sp=>els(sp,'ph').some(ph=>ph.attributes.type==='body'));
const oldBody=body(nx),newBody=body(na);
if(!oldBody||!newBody)throw Error('Missing notes body');
oldBody.elements=oldBody.elements.map(el=>el.name?.split(':').at(-1)==='txBody'?els(newBody,'txBody')[0]:el);
z.file(onp,serial(nx));
const expectedChanges=new Set([op,relpart(op),onp]);
const changes=[];
for(const [name,bytes] of originalBytes){
 const now=await z.file(name).async('uint8array');
 if(Buffer.compare(Buffer.from(bytes),Buffer.from(now))!==0){changes.push(name);if(!expectedChanges.has(name))throw Error(`Unexpected modified part: ${name}`);}
}
await fs.writeFile(`${B}/full_candidate.pptx`,await z.generateAsync({type:'uint8array',compression:'DEFLATE'}));
await fs.writeFile(`${B}/build_receipt.json`,JSON.stringify({source,source_sha256:createHash('sha256').update(await fs.readFile(source)).digest('hex'),modified_page:15,total_slides:28,changed_existing_parts:changes,new_images:num,other_27_slides_and_notes_byte_identical:true,new_simulation:false,render_engine:'Artifact Tool, not PowerPoint GUI'},null,2));
console.log(JSON.stringify({single:'single_candidate.pptx',full:'full_candidate.pptx',changes},null,2));
