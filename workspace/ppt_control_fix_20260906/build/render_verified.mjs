import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const dir='C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_control_fix_20260906';
const contract=JSON.parse(await fs.readFile(`${dir}/build/preservation_contract.json`,'utf8'));
const deck=await PresentationFile.importPptx(await FileBlob.load(contract.final));
if(deck.slides.items.length!==28)throw Error('Expected 28 slides');
await fs.mkdir(`${dir}/build/final-preview`,{recursive:true});
for(let i=0;i<28;i++) {
  const n=i+1, changed=[12,14,15].includes(n);
  const bytes=new Uint8Array(await (await deck.export({slide:deck.slides.items[i],format:'png',scale:changed?1.5:0.5})).arrayBuffer());
  await fs.writeFile(`${dir}/build/final-preview/slide-${String(n).padStart(2,'0')}.png`,bytes);
  if(changed) {
    await fs.writeFile(`${dir}/output/第${n}页_修订预览.png`,bytes);
    await fs.writeFile(`${dir}/build/final-slide${n}.layout.json`,await (await deck.slides.items[i].export({format:'layout'})).text());
  }
}
await fs.copyFile(`${dir}/build/第12_14_15页_讲稿.txt`,`${dir}/output/第12_14_15页_讲稿.txt`);
const check={final:contract.final,slideCount:28,renderedSlideCount:28,sha256:createHash('sha256').update(await fs.readFile(contract.final)).digest('hex'),nativePowerPointOpened:false};
await fs.writeFile(`${dir}/build/import_and_render_check.json`,JSON.stringify(check,null,2));
console.log(JSON.stringify(check));
