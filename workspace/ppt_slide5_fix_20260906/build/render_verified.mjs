import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const dir='C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_slide5_fix_20260906';
const final=`${dir}/output/CTO第一月组会汇报_第5页修订_2026-09-06.pptx`;
const deck=await PresentationFile.importPptx(await FileBlob.load(final));
if(deck.slides.items.length!==28) throw Error('Slide count mismatch');
await fs.mkdir(`${dir}/build/final-preview`,{recursive:true});
for(let i=0;i<28;i++) {
  const bytes=new Uint8Array(await (await deck.export({slide:deck.slides.items[i],format:'png',scale:i===4?1.5:0.5})).arrayBuffer());
  await fs.writeFile(`${dir}/build/final-preview/slide-${String(i+1).padStart(2,'0')}.png`,bytes);
  if(i===4) await fs.writeFile(`${dir}/output/第5页_修订预览.png`,bytes);
}
await fs.writeFile(`${dir}/build/final-slide5.layout.json`,await (await deck.slides.items[4].export({format:'layout'})).text());
await fs.copyFile(`${dir}/build/slide5_讲稿.txt`,`${dir}/output/第5页_讲稿.txt`);
console.log(JSON.stringify({final,slides:28,rendered:28}));
