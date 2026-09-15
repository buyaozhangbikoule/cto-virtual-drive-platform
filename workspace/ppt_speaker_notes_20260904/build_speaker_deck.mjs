import fs from "node:fs/promises";
import path from "node:path";
import JSZip from "jszip";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const ROOT = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat";
const WORK = `${ROOT}/ppt_speaker_notes_20260904`;
const SOURCE = `${WORK}/source.pptx`;
const RAW = `${WORK}/before-theme-restore.pptx`;
const FINAL = `${ROOT}/CTO超声换能器第一月教授组会汇报_逐页讲稿版_2026-09-04.pptx`;
const content = JSON.parse(await fs.readFile(`${WORK}/speaker_content.json`, "utf8"));

function shapeByName(slide, name) {
  const shape = slide.shapes.items.find((item) => item.name === name);
  if (!shape) throw new Error(`Missing shape '${name}' on slide ${slide.id}`);
  return shape;
}

function setTableValues(table, values) {
  for (let r = 0; r < values.length; r += 1) {
    for (let c = 0; c < values[r].length; c += 1) table.cells.set(r, c, values[r][c]);
  }
}

function absoluteSource(source) {
  return source.match(/^[A-Za-z]:\//) ? source : `${ROOT}/${source}`;
}

function notesText(item) {
  const sources = item.sources.map((source) => `- ${absoluteSource(source)}`).join("\n");
  return [
    `【建议时长】${item.duration}`,
    `【本页结论】${item.conclusion}`,
    `【逐字讲稿】${item.script}`,
    `【看图顺序】${item.read_order}`,
    `【口径与限制】${item.caveat}`,
    `【教授可能追问】${item.question}`,
    `【建议回答】${item.answer}`,
    `【模糊推测】${item.fuzzy}`,
    "[Sources]",
    sources,
  ].join("\n\n");
}

async function restoreThemes(sourcePptx, exportedPptx, finalPptx) {
  const sourceZip = await JSZip.loadAsync(await fs.readFile(sourcePptx));
  const finalZip = await JSZip.loadAsync(await fs.readFile(exportedPptx));
  const themeNames = Object.keys(sourceZip.files).filter((name) => /^ppt\/theme\/theme\d+\.xml$/i.test(name));
  for (const name of themeNames) finalZip.file(name, await sourceZip.file(name).async("uint8array"), { binary: true });
  await fs.writeFile(finalPptx, await finalZip.generateAsync({ type: "uint8array", compression: "DEFLATE" }));
}

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

const deck = await PresentationFile.importPptx(await FileBlob.load(SOURCE));
if (deck.slides.items.length !== 28 || content.length !== 28) throw new Error("Expected 28 slides and 28 note records");

// Slide 15: replace stale integrated-control numbers with the current saved table.
const s15 = deck.slides.items[14];
setTableValues(s15.tables.items[0], [
  ["策略", "稳态误差", "恢复时间（惩罚）", "未收敛段", "硬越限"],
  ["固定0.9 MHz", "30.14%", "345.7 ms", "3", "0"],
  ["周期扫频", "0%", "409.0 ms", "2", "0"],
  ["扫描辅助P&O", "0%", "458.9 ms", "3", "0"],
]);
const recoveryChart = s15.charts.items[0];
const recoveryCategories = ["固定0.9 MHz", "周期扫频", "扫描辅助P&O"];
recoveryChart.categories = recoveryCategories;
recoveryChart.series.getItemAt(0).categories = recoveryCategories;
recoveryChart.series.getItemAt(0).values = [345.7, 409.0, 458.9];
shapeByName(s15, "矩形 8").text = "0%表示尾段达到各场景自身安全功率参考；恢复时间含未收敛惩罚。\n固定策略时间较短不表示更优：其平均稳态误差仍为30.14%。";

// Slide 20: make the measurement plane explicit and distinguish it from Zin.
shapeByName(deck.slides.items[19], "矩形 10").text = "0.9 MHz换能器端口基线（匹配网络后端，非Zin）\n|Zport| ≈ 7.071 kΩ   相位 ≈ −15.916°\nP_Rm ≈ 0.170 W   I_RMS ≈ 5.000 mA\nVport ≈ 100 Vpp";

// Slide 23: correct the implemented phase measurement definition.
shapeByName(deck.slides.items[22], "矩形 6").text = "φin = arg(Zin) = arg(Vinput / Isource)";

for (let i = 0; i < content.length; i += 1) {
  const item = content[i];
  if (item.slide !== i + 1) throw new Error(`Speaker-content order mismatch at ${i + 1}`);
  const slide = deck.slides.items[i];
  slide.speakerNotes.textFrame.setText(notesText(item));
  slide.speakerNotes.setVisible(true);
}

await (await PresentationFile.exportPptx(deck)).save(RAW);
await restoreThemes(SOURCE, RAW, FINAL);

const qaDeck = await PresentationFile.importPptx(await FileBlob.load(FINAL));
const previewDir = `${WORK}/final-preview`;
const layoutDir = `${WORK}/final-layout`;
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(layoutDir, { recursive: true });
for (let i = 0; i < qaDeck.slides.items.length; i += 1) {
  const slide = qaDeck.slides.items[i];
  const stem = `slide-${String(i + 1).padStart(2, "0")}`;
  await writeBlob(`${previewDir}/${stem}.png`, await qaDeck.export({ slide, format: "png", scale: 1 }));
  await fs.writeFile(`${layoutDir}/${stem}.json`, await (await slide.export({ format: "layout" })).text(), "utf8");
}
const inspect = await qaDeck.inspect({ kind: "slide,textbox,shape,image,table,chart,notes,layout", maxChars: 250000 });
await fs.writeFile(`${WORK}/final-inspect.ndjson`, inspect.ndjson, "utf8");
console.log(JSON.stringify({ final: FINAL, slideCount: qaDeck.slides.items.length, notesCount: content.length }, null, 2));
