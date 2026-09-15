import fs from "node:fs/promises";
import { PresentationFile, FileBlob } from "@oai/artifact-tool";

const root = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat";
const tmp = `${root}/ppt_edit_slide11_python_20260828`;
const source = `${tmp}/template-starter.pptx`;
const figurePng = `${tmp}/figure/slide11_python_charts.png`;
const sweepCsv = `${root}/outputs/v2_self_consistent_rebuild/active_stage3_5/stage3_disturbance/stage3_frequency_response_all_cases.csv`;
const timelineCsv = `${root}/outputs/v2_self_consistent_rebuild/report_evidence_final/06_控制与保护/stage4_control_timeline.csv`;
const metricsCsv = `${root}/outputs/v2_self_consistent_rebuild/report_evidence_final/06_控制与保护/stage5_per_segment_metrics.csv`;
const output = `${root}/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_第11页Python精确作图版_2026-08-28.pptx`;
const qaDir = `${tmp}/qa`;

const COLORS = {
  navy: "#17324D",
  muted: "#5F6B76",
  blue: "#2F73B7",
  red: "#C84444",
};

async function writeBlob(path, blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  await fs.writeFile(path, bytes);
}

async function readImageBlob(imagePath) {
  const bytes = await fs.readFile(imagePath);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function setText(shape, text, position, style) {
  shape.position.merge(position);
  shape.text = text;
  shape.text.style = style;
}

async function main() {
  await fs.mkdir(qaDir, { recursive: true });
  const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
  const slide = presentation.resolve("sl/jetc3ut0");

  await writeBlob(`${qaDir}/before-slide-11.png`, await presentation.export({ slide, format: "png", scale: 1.5 }));
  await fs.writeFile(`${qaDir}/before-slide-11.layout.json`, await (await slide.export({ format: "layout" })).text(), "utf8");

  presentation.resolve("im/21cnihkf").delete();

  const title = presentation.resolve("sh/0b6tc3yx");
  title.text = "峰值由0.9000 MHz移至0.8548 MHz，自适应策略成功定位新峰值";

  setText(
    presentation.resolve("sh/o7ih0r6h"),
    "定位结果与验收边界",
    { left: 920, top: 120, width: 280, height: 32 },
    { fontSize: 21, bold: true, color: COLORS.navy, alignment: "left" },
  );
  setText(
    presentation.resolve("sh/72t03qp0"),
    "基准峰值  0.9000 MHz｜170.0 mW\nfs−5%峰值  0.8548 MHz｜140.2 mW\n峰位变化  −45.2 kHz",
    { left: 920, top: 156, width: 288, height: 112 },
    { fontSize: 16, bold: true, color: COLORS.muted, alignment: "left" },
  );
  setText(
    presentation.resolve("sh/61kzalof"),
    "周期扫频：通过稳态验收",
    { left: 920, top: 292, width: 280, height: 30 },
    { fontSize: 19, bold: true, color: COLORS.blue, alignment: "left" },
  );
  setText(
    presentation.resolve("sh/ofqtgnyt"),
    "稳定锁定0.8548 MHz；捕获率100%\n约96.5 ms满足连续10样本判据",
    { left: 920, top: 325, width: 288, height: 72 },
    { fontSize: 15, color: COLORS.muted, alignment: "left" },
  );
  setText(
    presentation.resolve("sh/9gza9sze"),
    "P&O：到达峰位但未通过验收",
    { left: 920, top: 420, width: 280, height: 30 },
    { fontSize: 18, bold: true, color: COLORS.red, alignment: "left" },
  );
  setText(
    presentation.resolve("sh/mdobedg3"),
    "到达0.8548 MHz、捕获率100%\n但周期性参考/试探使其未满足\n连续10个控制样本保持窗口",
    { left: 920, top: 453, width: 288, height: 88 },
    { fontSize: 15, color: COLORS.muted, alignment: "left" },
  );
  setText(
    presentation.resolve("sh/nehs7iho"),
    "ηP＝P当前 / P安全最大,当前场景\n100%表示找到该场景自身安全峰值\n不等于恢复基准绝对功率170.0 mW",
    { left: 920, top: 568, width: 288, height: 82 },
    { fontSize: 15, bold: true, color: COLORS.navy, alignment: "center" },
  );

  const chartImage = slide.images.add({
    blob: await readImageBlob(figurePng),
    contentType: "image/png",
    alt: "Python生成的三联图：离线安全功率峰位、场景归一化捕获率及CONTROL样本控制频率",
    fit: "contain",
    position: { left: 68, top: 105, width: 832, height: 558 },
  });
  chartImage.name = "python-slide11-evidence";

  const note = [
    "本页左侧三联图由Python/Matplotlib直接读取项目CSV生成，并以300 dpi PNG嵌入PPT；没有使用PowerPoint原生图表重绘，也没有人为平移数据。",
    "a图：CASE_000_BASELINE与CASE_FS_M5的离线安全功率扫描，峰值分别为0.9000 MHz/170.0 mW与0.8548 MHz/140.2 mW。",
    "b图：捕获率按当前扰动场景自身的安全最大功率归一化。100%不等于恢复基准绝对功率。",
    "c图：仅绘制CONTROL样本；扫描/试探导致的时间间隔不插值、不连线。fs−5%窗口严格截断在3.200 s之前，避免混入下一扰动场景。",
    "周期扫频在2.4965 s到达峰值并通过稳态验收；P&O在2.4985 s首次到达同一峰位，但未通过连续稳态验收。",
    "",
    "[Sources]",
    `- ${sweepCsv.replaceAll("/", "\\")}`,
    `- ${timelineCsv.replaceAll("/", "\\")}`,
    `- ${metricsCsv.replaceAll("/", "\\")}`,
    `- ${figurePng.replaceAll("/", "\\")}`,
  ].join("\n");
  slide.speakerNotes.textFrame.setText(note);
  slide.speakerNotes.setVisible(true);

  await writeBlob(`${qaDir}/after-slide-11.png`, await presentation.export({ slide, format: "png", scale: 1.5 }));
  await fs.writeFile(`${qaDir}/after-slide-11.layout.json`, await (await slide.export({ format: "layout" })).text(), "utf8");
  const inspect = await presentation.inspect({
    target: { id: "sl/jetc3ut0", beforeLines: 0, afterLines: 28 },
    kind: "slide,textbox,shape,image,chart,notes",
    maxChars: 30000,
  });
  await fs.writeFile(`${qaDir}/after-slide-11.inspect.ndjson`, inspect.ndjson, "utf8");

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(output);
  console.log(output);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
