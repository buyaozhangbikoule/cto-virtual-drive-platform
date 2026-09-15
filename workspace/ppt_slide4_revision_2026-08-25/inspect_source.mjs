import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from 'file:///C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';

const source = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx';
const outDir = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_slide4_revision_2026-08-25/inspect';
await fs.mkdir(outDir, { recursive: true });

const p = await PresentationFile.importPptx(await FileBlob.load(source));
const full = await p.inspect({
  kind: 'deck,slide,textbox,shape,image,notes,layout',
  include: 'id,slide,name,title,text,textPreview,bbox,bboxUnit,alt,isPlaceholder,placeholders',
  maxChars: 120000,
});
await fs.writeFile(`${outDir}/inspect.ndjson`, full.ndjson, 'utf8');

const focused = await p.inspect({
  kind: 'slide,textbox,shape,image,notes',
  search: 'Python解析解与LTspice RAW重合',
  maxChars: 30000,
});
await fs.writeFile(`${outDir}/focused.ndjson`, focused.ndjson, 'utf8');

const montage = await p.export({ format: 'webp', montage: { format: 'webp', width: 1800, slideWidth: 420, columns: 4 }, scale: 1 });
await fs.writeFile(`${outDir}/montage.webp`, new Uint8Array(await montage.arrayBuffer()));

const slide = p.slides.getItem(3);
const png = await slide.export({ format: 'png', scale: 2 });
await fs.writeFile(`${outDir}/slide4.png`, new Uint8Array(await png.arrayBuffer()));
const layout = await slide.export({ format: 'layout' });
await fs.writeFile(`${outDir}/slide4.layout.json`, await layout.text(), 'utf8');

console.log(`slides=${p.slides.items.length}`);
console.log(focused.ndjson);
