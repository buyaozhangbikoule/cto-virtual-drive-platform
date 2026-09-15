import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const D='C:/Users/24739/Documents/Codex/2026-08-10/new-chat/project_audit_20260910';
const c=JSON.parse(await fs.readFile(`${D}/build/contract.json`,'utf8'));
const final=c.outputs[0].final;
const deck=await PresentationFile.importPptx(await FileBlob.load(final));
if(deck.slides.items.length!==28)throw Error('Slide count');
await fs.mkdir(`${D}/build/all-slides`,{recursive:true});
for(let i=0;i<28;i++){
 const touched=c.visibleTouched.includes(c.order[i]);
 const s=deck.slides.items[i];
 const png=new Uint8Array(await(await s.export({format:'png',scale:touched?1.2:.5})).arrayBuffer());
 await fs.writeFile(`${D}/build/all-slides/${String(i+1).padStart(2,'0')}.png`,png);
 if(touched)await fs.writeFile(`${D}/build/all-slides/${String(i+1).padStart(2,'0')}.layout.json`,await(await s.export({format:'layout'})).text());
 if([13,14,17].includes(i))await fs.writeFile(`${D}/output/第${i+1}页预览.png`,png);
 console.log('Rendered',i+1);
}
