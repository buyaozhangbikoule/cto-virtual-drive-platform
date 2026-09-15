import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const source = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx';
const output = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_第10页保护图完整修正版.pptx';
const qaDir = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_protection_crop_fix_2026-08-26/qa';

await fs.mkdir(qaDir, { recursive: true });
const deck = await PresentationFile.importPptx(await FileBlob.load(source));
const slide = deck.resolve('sl/m90b6t0r');
const image = deck.resolve('im/8jmtobq9');

const before = await slide.export({ format: 'png', scale: 2 });
await fs.writeFile(`${qaDir}/slide10-before.png`, new Uint8Array(await before.arrayBuffer()));

image.crop = { left: 0, top: 0.05, right: 0, bottom: 0 };
image.frame = { left: 385, top: 124, width: 702, height: 500 };

const after = await slide.export({ format: 'png', scale: 2 });
await fs.writeFile(`${qaDir}/slide10-after.png`, new Uint8Array(await after.arrayBuffer()));

const focused = await deck.inspect({
  target: { id: 'sl/m90b6t0r', beforeLines: 0, afterLines: 60 },
  kind: 'slide,textbox,shape,image,notes',
  maxChars: 16000,
});
await fs.writeFile(`${qaDir}/slide10-after.ndjson`, focused.ndjson, 'utf8');

for (let i = 0; i < deck.slides.items.length; i += 1) {
  const rendered = await deck.slides.items[i].export({ format: 'png', scale: 1 });
  await fs.writeFile(`${qaDir}/final-slide-${String(i + 1).padStart(2, '0')}.png`, new Uint8Array(await rendered.arrayBuffer()));
}

const montage = await deck.export({ format: 'webp', montage: true, scale: 1 });
await fs.writeFile(`${qaDir}/final-montage.webp`, new Uint8Array(await montage.arrayBuffer()));

const pptx = await PresentationFile.exportPptx(deck);
await pptx.save(output);
console.log(output);
