import fs from 'node:fs/promises';
import path from 'node:path';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const B=path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1'));
const W=path.dirname(B);
const deckPath=process.argv[2]||`${B}/full_candidate.pptx`;
const deck=await PresentationFile.importPptx(await FileBlob.load(deckPath));
await fs.mkdir(`${B}/final-render`,{recursive:true});
await fs.writeFile(`${B}/final.inspect.ndjson`,(await deck.inspect({kind:'slide,textbox,shape,image,table,notes',maxChars:1000000})).ndjson);
for(let i=0;i<deck.slides.items.length;i++){
 if(process.argv[3]==='15' && i!==14)continue;
 const s=deck.slides.items[i],name=String(i+1).padStart(2,'0');
 await fs.writeFile(`${B}/final-render/${name}.png`,new Uint8Array(await(await s.export({format:'png',scale:1})).arrayBuffer()));
 if(i===14){
  await fs.writeFile(`${B}/final-render/${name}.layout.json`,await(await s.export({format:'layout'})).text());
  await fs.writeFile(`${W}/output/第15页_预览.png`,new Uint8Array(await(await s.export({format:'png',scale:1.5})).arrayBuffer()));
 }
 console.log(`rendered ${name}`);
}
