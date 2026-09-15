import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const BUILD='C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_control_pages_fix_20260906/build';
const cfg=JSON.parse(await fs.readFile(`${BUILD}/output_config.json`,'utf8'));
const deck=await PresentationFile.importPptx(await FileBlob.load(cfg.FINAL));
if(deck.slides.items.length!==28)throw Error('Wrong slide count');
await fs.mkdir(`${BUILD}/final-preview`,{recursive:true});
for(let i=0;i<28;i++){
 const n=i+1,changed=cfg.CHANGED.includes(n);
 const bytes=new Uint8Array(await(await deck.export({slide:deck.slides.items[i],format:'png',scale:changed?1.5:0.5})).arrayBuffer());
 await fs.writeFile(`${BUILD}/final-preview/slide-${String(n).padStart(2,'0')}.png`,bytes);
 if(changed){
   await fs.writeFile(`${cfg.OUT}/第${n}页_修订预览.png`,bytes);
   await fs.writeFile(`${BUILD}/page${n}-final.layout.json`,await(await deck.slides.items[i].export({format:'layout'})).text());
 }
}
let text='';
for(const n of cfg.CHANGED)text+=`第${n}页\n\n${await fs.readFile(`${BUILD}/第${n}页_讲稿.txt`,'utf8')}\n\n`;
await fs.writeFile(`${cfg.OUT}/第12、14、15页_修订讲稿.txt`,text,'utf8');
console.log(JSON.stringify({final:cfg.FINAL,rendered:28,changed:cfg.CHANGED}));
