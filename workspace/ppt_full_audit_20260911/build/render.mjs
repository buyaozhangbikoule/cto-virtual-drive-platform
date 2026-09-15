import fs from 'node:fs/promises';
import path from 'node:path';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const R='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const source=process.argv[2]||`${R}/project_audit_20260910/output/CTO组会汇报_计划书口径与验收缺口修订_2026-09-10.pptx`;
const dest=process.argv[3]||`${R}/ppt_full_audit_20260911/build/source-render`;
const deck=await PresentationFile.importPptx(await FileBlob.load(source));
await fs.mkdir(dest,{recursive:true});
await fs.writeFile(`${dest}/inspect.ndjson`,(await deck.inspect({kind:'slide,textbox,shape,image,table,chart,notes',maxChars:1000000})).ndjson);
for(let i=0;i<deck.slides.items.length;i++){
  const slide=deck.slides.items[i];
  await fs.writeFile(`${dest}/${String(i+1).padStart(2,'0')}.png`,new Uint8Array(await (await slide.export({format:'png',scale:1})).arrayBuffer()));
  await fs.writeFile(`${dest}/${String(i+1).padStart(2,'0')}.layout.json`,await (await slide.export({format:'layout'})).text());
  console.log(`rendered ${i+1}`);
}
