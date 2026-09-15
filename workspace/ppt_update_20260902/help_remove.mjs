import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const file = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_update_20260902/template-starter.pptx";
const deck = await PresentationFile.importPptx(await FileBlob.load(file));
const slide = deck.slides.items[7];
function protoNames(value) {
  const out = [];
  let current = value;
  for (let i = 0; current && i < 4; i += 1) {
    out.push({ level: i, names: Object.getOwnPropertyNames(current).sort() });
    current = Object.getPrototypeOf(current);
  }
  return out;
}
function list(items) {
  return items.map((x) => ({ id:x.id, name:x.name, type:x.type, frame:x.frame, text:x.text?.toString?.() ?? null }));
}
console.log(JSON.stringify({
  shapes: list(slide.shapes.items),
  tables: list(slide.tables.items),
  charts: list(slide.charts.items),
  images: list(slide.images.items),
}, null, 2));
