import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const D='C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_energy_update_20260909';
const contract=JSON.parse(await fs.readFile(`${D}/build/contract.json`,'utf8'));
await fs.mkdir(`${D}/build/all-slides`,{recursive:true});
for(const o of contract.outputs){
  const deck=await PresentationFile.importPptx(await FileBlob.load(o.final));
  if(deck.slides.items.length!==o.count)throw Error('Slide count');
  for(let i=0;i<o.count;i++){
    const target=o.count===1||i===14;
    const png=new Uint8Array(await(await deck.export({slide:deck.slides.items[i],format:'png',scale:target?1.5:.35})).arrayBuffer());
    await fs.writeFile(`${D}/build/all-slides/${o.count}-${String(i+1).padStart(2,'0')}.png`,png);
    if(target){
      await fs.writeFile(`${D}/output/${o.count===1?'第15页_单页预览':'第15页_完整PPT预览'}.png`,png);
      await fs.writeFile(`${D}/build/final-${o.count}.layout.json`,await(await deck.slides.items[i].export({format:'layout'})).text());
    }
  }
  console.log(`Imported and rendered ${o.count} final slides`);
}
