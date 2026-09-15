import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const source = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx';
const deck = await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot = await deck.inspect({
  kind: 'slide,textbox,shape,image,notes,layout',
  include: 'id,slide,name,title,textPreview,bbox,bboxUnit,alt,isPlaceholder',
  maxChars: 30000,
});
await fs.writeFile('C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_protection_crop_fix_2026-08-26/deck-inspect.ndjson', snapshot.ndjson, 'utf8');
const slide = deck.slides.getItem(9);
const preview = await slide.export({ format: 'png', scale: 2 });
await fs.writeFile('C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_protection_crop_fix_2026-08-26/slide10-before.png', new Uint8Array(await preview.arrayBuffer()));
const layout = await slide.export({ format: 'layout' });
await fs.writeFile('C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_protection_crop_fix_2026-08-26/slide10-before.layout.json', JSON.stringify(layout, null, 2), 'utf8');
const image = deck.resolve('im/8jmtobq9');
console.log('IMAGE_PROPS', JSON.stringify({ frame: image.frame, crop: image.crop, fit: image.fit, position: image.position, lockAspectRatio: image.lockAspectRatio, alt: image.alt }, null, 2));
console.log(snapshot.ndjson.split('\n').filter(line => line.includes('"slide":10')).join('\n'));
