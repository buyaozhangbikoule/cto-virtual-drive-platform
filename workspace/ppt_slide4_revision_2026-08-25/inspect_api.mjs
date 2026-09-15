import { FileBlob, PresentationFile } from 'file:///C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const source = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx';
const p = await PresentationFile.importPptx(await FileBlob.load(source));
const slide = p.slides.getItem(3);
const image = p.resolve('im/sbm5cbix');
const textbox = p.resolve('sh/w72947yt');
for (const [name, obj] of [['slides',p.slides],['slide',slide],['image',image],['textbox',textbox]]) {
  console.log(name, Object.getOwnPropertyNames(Object.getPrototypeOf(obj)).sort());
}
console.log(p.help('*',{search:'remove delete slides image',include:['index','notes','examples'],maxChars:12000}).ndjson ?? p.help('*',{search:'remove delete slides image',include:['index','notes','examples'],maxChars:12000}));
