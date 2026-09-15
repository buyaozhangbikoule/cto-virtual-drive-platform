import fs from 'node:fs/promises';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const ROOT='C:/Users/24739/Documents/Codex/2026-08-10/new-chat';
const BUILD=`${ROOT}/ppt_acceptance_update_20260909/build`;
const SOURCE=`${ROOT}/ppt_control_fix_20260906/output/CTO第一月组会汇报_第5及12_14_15页修订_2026-09-06.pptx`;
const deck=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const snap=await deck.inspect({kind:'slide,textbox,shape,image,notes,layout',maxChars:350000});
await fs.writeFile(`${BUILD}/before.ndjson`,snap.ndjson);
const rr=snap.ndjson.trim().split('\n').map(JSON.parse);
const s=deck.resolve(rr.find(x=>x.kind==='slide'&&x.slide===14).id);
await fs.writeFile(`${BUILD}/before.png`,new Uint8Array(await(await deck.export({slide:s,format:'png',scale:1.5})).arrayBuffer()));
await fs.writeFile(`${BUILD}/before.layout.json`,await(await s.export({format:'layout'})).text());
console.log(JSON.stringify({slides:deck.slides.items.length,masters:deck.masters.items.map(x=>({id:x.id,name:x.name})),
  targets:rr.filter(x=>x.slide===14&&['slide','textbox','image'].includes(x.kind))}));
