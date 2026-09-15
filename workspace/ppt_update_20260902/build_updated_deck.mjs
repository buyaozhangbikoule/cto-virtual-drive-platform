import fs from "node:fs/promises";
import path from "node:path";
import JSZip from "jszip";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const ROOT = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_update_20260902";
const STARTER = `${ROOT}/template-starter.pptx`;
const RAW_FINAL = `${ROOT}/final-before-theme-restore.pptx`;
const FINAL = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO超声换能器第一月教授组会汇报_进展补充版_2026-09-02.pptx";
const CM_FIGURE = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/figures/stage3_disturbance/cm_only/stage3_07_cm_only_power_and_electrical_limits.png";

async function writeBlob(filePath, blob) {
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

function shapeByName(slide, name) {
  const shape = slide.shapes.items.find((item) => item.name === name);
  if (!shape) throw new Error(`Missing shape ${name}`);
  return shape;
}

function replaceText(slide, name, oldText, newText) {
  const shape = shapeByName(slide, name);
  shape.text.replace(oldText, newText);
  return shape;
}

function setText(slide, name, newText) {
  const shape = shapeByName(slide, name);
  shape.text = newText;
  return shape;
}

function addTextShape(slide, {
  name,
  text,
  position,
  geometry = "textbox",
  fill = "none",
  line = { style: "solid", fill: "none", width: 0 },
  fontSize = 20,
  color = "#17365D",
  bold = false,
  alignment = "center",
}) {
  const shape = slide.shapes.add({ geometry, name, position, fill, line });
  shape.text = text;
  shape.text.style = { fontSize, color, bold, alignment };
  return shape;
}

function setNotes(slide, text) {
  slide.speakerNotes.textFrame.setText(text);
  slide.speakerNotes.setVisible(true);
}

function setTableValues(table, values) {
  for (let r = 0; r < values.length; r += 1) {
    for (let c = 0; c < values[r].length; c += 1) {
      table.cells.set(r, c, values[r][c]);
    }
  }
}

async function restoreThemes(sourcePptx, exportedPptx, finalPptx) {
  const sourceZip = await JSZip.loadAsync(await fs.readFile(sourcePptx));
  const finalZip = await JSZip.loadAsync(await fs.readFile(exportedPptx));
  const themeNames = Object.keys(sourceZip.files).filter((name) => /^ppt\/theme\/theme\d+\.xml$/i.test(name));
  for (const name of themeNames) {
    const bytes = await sourceZip.file(name).async("uint8array");
    finalZip.file(name, bytes, { binary: true });
  }
  const finalBytes = await finalZip.generateAsync({ type: "uint8array", compression: "DEFLATE" });
  await fs.writeFile(finalPptx, finalBytes);
}

const deck = await PresentationFile.importPptx(await FileBlob.load(STARTER));
const slides = deck.slides.items;
if (slides.length !== 28) throw new Error(`Expected 28 slides, found ${slides.length}`);

const sourceSlides = [1,2,3,4,5,6,7,14,8,9,10,11,16,12,13,23,15,16,17,18,22,19,20,13,21,22,23,24];
const sourcePageText = {1:"1",2:"2",3:"3",4:"4",5:"5",6:"5",7:"6",8:"7",9:"8",10:"9",11:"10",12:"11",13:"12",14:"12",15:"13",16:"14",17:"15",18:"16",19:"17",20:"18",21:"19",22:"20",23:"21",24:"22"};

for (let i = 0; i < slides.length; i += 1) {
  const pageShapeName = sourceSlides[i] === 1 ? "矩形 6" : "矩形 4";
  replaceText(slides[i], pageShapeName, sourcePageText[sourceSlides[i]], String(i + 1));
}

// Slide 1: title-page freshness only; source content and boundary statement remain unchanged.
replaceText(slides[0], "矩形 4", "第一月工作汇报  |  2026.08", "第一月工作汇报（补充审计版）  |  2026.09");

// Slide 8: final Cm-only power, voltage and current evidence.  Source slide 14 is
// intentionally repurposed so the following Qm slide keeps its independent image resource.
replaceText(slides[7], "title-12", "按98%功率连续10样本验收，周期扫频在当前参数下最稳健", "机械支路电容 Cm 增大使功率峰下移并降低峰高");
shapeByName(slides[7], "矩形: 圆角 7").delete();
shapeByName(slides[7], "矩形 8").delete();
slides[7].tables.deleteById(slides[7].tables.items[0].id);
slides[7].charts.deleteById(slides[7].charts.items[0].id);
const cmBytes = await fs.readFile(CM_FIGURE);
slides[7].images.add({
  blob: cmBytes,
  contentType: "image/png",
  alt: "机械支路电容Cm单因素扰动下的功率、电压与电流曲线",
  fit: "contain",
  position: { left: 72, top: 112, width: 746, height: 548 },
});
addTextShape(slides[7], {
  name: "cm-summary-title",
  text: "关键结论",
  position: { left: 842, top: 132, width: 320, height: 42 },
  fontSize: 26,
  bold: true,
});
addTextShape(slides[7], {
  name: "cm-shift-callout",
  text: "峰位总移   −78.6 kHz",
  position: { left: 846, top: 205, width: 316, height: 64 },
  geometry: "roundRect",
  fill: "#EAF1F7",
  line: { style: "solid", fill: "#3978B8", width: 1.5 },
  fontSize: 19,
  bold: true,
});
addTextShape(slides[7], {
  name: "cm-height-callout",
  text: "峰高变化   −43.3%",
  position: { left: 846, top: 301, width: 316, height: 64 },
  geometry: "roundRect",
  fill: "#E8F3F3",
  line: { style: "solid", fill: "#2A7F8E", width: 1.5 },
  fontSize: 19,
  bold: true,
});
addTextShape(slides[7], {
  name: "cm-limit-callout",
  text: "未保护扫频   Vpp > 160 V",
  position: { left: 846, top: 397, width: 316, height: 64 },
  geometry: "roundRect",
  fill: "#FFF4DD",
  line: { style: "solid", fill: "#E69F00", width: 1.5 },
  fontSize: 18,
  bold: true,
});
addTextShape(slides[7], {
  name: "cm-boundary-note",
  text: "Cm-only是原始元件单因素；\n派生 fs、Qm 会同时变化。",
  position: { left: 842, top: 520, width: 324, height: 82 },
  fontSize: 18,
  bold: true,
});
setNotes(slides[7], [
  "这页补齐机械支路电容Cm-only正式扫描。峰位由0.9000 MHz移至0.8214 MHz，方向和数量级与1/√Cm一致；峰高由170.0 mW降至96.4 mW。",
  "功率峰点未超过假设硬限，但a=1全频未保护扫描存在Vpp超过160 V的区间，因此不能把离线扫频曲线当成受保护控制时序。",
  "[Sources]",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/figures/stage3_disturbance/cm_only/stage3_07_cm_only_power_and_electrical_limits.png",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/tables/stage3_disturbance/stage3_cm_only_power_safety_summary.csv",
].join("\n"));

// Slide 13: constrained-control audit.
replaceText(slides[12], "title-14", "电学链条已闭环，真实参数、P&O整定和结构声场仍需继续", "控制已从“找峰值”升级为带频率、幅度与保护约束的问题");
replaceText(slides[12], "矩形 7", "已经证明", "已接入约束");
setText(slides[12], "矩形 8", "0.8–1.0 MHz硬边界\n130/160 Vpp软/硬限\n5.5/6.0 mA RMS软/硬限\n幅度0–1与foldback");
replaceText(slides[12], "矩形 9", "尚未证明", "保存结果审计");
setText(slides[12], "矩形 10", "1795条控制时序\n峰值Vpp = 130 V\n峰值电流 = 5.124 mA\n实际硬越限 = 0");
replaceText(slides[12], "矩形 11", "下一阶段", "仍有缺口");
setText(slides[12], "矩形 12", "反射代理仅参与检测\n没有独立反射硬限\n没有壁面声压代理\n不是硬件安全验证");
replaceText(slides[12], "矩形 14", "当前结论仅适用于特定假设BVD模型与设定扰动范围", "当前是带约束的电学准稳态控制，不是无约束离线argmax，也不是完整功放或声场控制");
setNotes(slides[12], [
  "这页回答控制是否仍是单纯找峰值。频率、幅度、软硬电压电流限制和保护状态都进入保存时序；三种策略实际硬越限均为0。",
  "反射代理目前只用于异常投票和重捕获触发，没有独立硬工作上限，因此仍是明确限制。",
  "[Sources]",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/audits/constrained_control_audit.json",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/audits/plan_control_coupling_audit.json",
].join("\n"));

// Slide 16: standardized electrical-to-acoustic interface.
replaceText(slides[15], "title-21", "备份：每张图都能追溯到参数、脚本和原始输出", "电—声接口已标准化：COMSOL未运行，但输入合同已就绪");
setText(slides[15], "矩形 10", "电学场景\n参数CSV");
setText(slides[15], "矩形 12", "安全工作点\nf, Vport∠θ");
setText(slides[15], "矩形 14", "复端口激励\nVrms exp(+jωt)");
setText(slides[15], "矩形 16", "声学查找表\nηacoustic(f)");
setText(slides[15], "矩形 18", "相对声压代理\ntarget / wall");
replaceText(slides[15], "矩形 19", "README_汇报工作痕迹索引.md", "EA_IF_V1.0｜基准+低/中/高组合4条记录｜接口审计 PASS");
replaceText(slides[15], "矩形 20", "SHA256_文件清单.csv", "声学字段：NOT_AVAILABLE（未运行COMSOL）");
replaceText(slides[15], "矩形 21", "图表不是孤立截图，而是可重新运行的产物", "接口一致不等于声场结果；复端口电压作为FEM激励");
setNotes(slides[15], [
  "电—声接口已经完成字段定义和4条代表性电学工作点导出。COMSOL未运行，因此相对声学效率、靶区和壁面压力代理保持空值。",
  "复端口电压按RMS、exp(+jωt)约定作为FEM激励；预测电流只用于交叉校核。",
  "[Sources]",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/interfaces/electro_acoustic_v1/electro_acoustic_interface_audit.json",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/interfaces/electro_acoustic_v1/interface_field_dictionary.csv",
].join("\n"));

// Slide 18: current completion summary.
replaceText(slides[17], "title-14", "电学链条已闭环，真实参数、P&O整定和结构声场仍需继续", "电学与带约束控制已闭环，剩余缺口是实测和结构声场");
replaceText(slides[17], "矩形 7", "已经证明", "本月已完成");
setText(slides[17], "矩形 8", "v2.1匹配网络与双线验证\nC0/Rm/fs/Rs/匹配/ESR/Lm/Cm扫描\n低/中/高组合LTspice验证\n选频、保护、P&O与相位消融\n电—声接口EA_IF_V1.0");
replaceText(slides[17], "矩形 9", "尚未证明", "仍未证明");
setText(slides[17], "矩形 10", "假设参数代表实物\nP_Rm等于声功率\n准稳态时间等于硬件响应\n反射代理等于实测反射功率\n任何治疗或临床安全结论");
replaceText(slides[17], "矩形 11", "下一阶段", "下一阶段");
setText(slides[17], "矩形 12", "实测阻抗并拟合BVD\n电压/电流/功率标定\n设定独立反射约束\n运行结构声场与网格收敛\n水听器声场验证");
replaceText(slides[17], "矩形 14", "当前结论仅适用于特定假设BVD模型与设定扰动范围", "当前结论仅适用于特定假设BVD、v2.1匹配网络和设定扰动范围");
setNotes(slides[17], [
  "收尾时明确：计划逐条审核为8项完成、1项部分完成、1项因无COMSOL输入未开始。",
  "已完成的是电学模型、匹配、扰动、选频、保护、相位消融和接口合同；未完成的是实物参数验证、独立反射硬限以及结构声场结果。",
  "[Sources]",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/audits/plan_control_coupling_audit.json",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/docs/NEXT_STAGE_REAL_VALIDATION_PLAN.md",
].join("\n"));

// Slide 21: low/medium/high combination LTspice validation.
replaceText(slides[20], "title-20", "备份：控制器比较采用统一且可复现的指标定义", "备份：低中高组合均通过LTspice/Python交叉验证");
setTableValues(slides[20].tables.items[0], [
  ["组合场景", "真实LTspice/Python交叉验证"],
  ["低", "2001点｜最大|Zin|相对误差 0.01461%｜PASS"],
  ["中", "2001点｜最大|Zin|相对误差 0.00751%｜PASS"],
  ["高", "2001点｜最大|Zin|相对误差 0.00295%｜PASS"],
  ["运行证据", ".cir / .raw / .log / SHA-256"],
  ["验收线", "误差 < 5%"],
  ["结论边界", "实现一致，不等于真实器件参数正确"],
]);
replaceText(slides[20], "矩形 6", "130 Vpp/5.5 mA为软触发；160 Vpp/6 mA为硬限。均为本次仿真假设，待实测确认。", "三档误差均远低于5%验收线；这排除了主要实现差异，但不能验证假设参数是真实器件参数。");
setNotes(slides[20], [
  "此前只有高组合完成交叉验证；现在低、中、高组合均已有真实LTspice批处理输出和Python对照。",
  "最大输入阻抗相对误差分别约0.01461%、0.00751%和0.00295%。",
  "[Sources]",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/tables/stage3_disturbance/stage3_LTspice_cross_validation.csv",
].join("\n"));

// Slide 24: plan-required fixed/periodic/phase supplement.
replaceText(slides[23], "title-12", "按98%功率连续10样本验收，周期扫频在当前参数下最稳健", "备份：相位闭环仅作计划书补充消融，不替代P&O排名");
setTableValues(slides[23].tables.items[0], [
  ["策略", "稳态误差", "惩罚恢复时间", "峰值电流", "实际硬越限"],
  ["固定0.9 MHz", "30.14%", "345.7 ms", "5.124 mA", "0"],
  ["周期扫频", "0%", "409.0 ms", "5.124 mA", "0"],
  ["相位K5消融", "39.91%", "374.3 ms", "5.124 mA", "0"],
]);
const phaseChart = slides[23].charts.items[0];
phaseChart.categories = ["固定0.9 MHz", "周期扫频", "相位K5消融"];
phaseChart.series.getItemAt(0).categories = ["固定0.9 MHz", "周期扫频", "相位K5消融"];
phaseChart.series.getItemAt(0).values = [345.7, 409.0, 374.3];
setText(slides[23], "矩形 8", "正式排名第三策略仍为扫描辅助P&O；相位K5不替代P&O结论。\n在fs漂移与高组合场景中，相位目标可能对应较低功率工作点。");
setNotes(slides[23], [
  "这页按计划书原始三策略口径给出固定、周期扫频和相位闭环的补充比较。正式综合排名仍使用固定、周期扫频和扫描辅助P&O。",
  "相位闭环在当前代表时间表中平均稳态误差较高，因此只保留为消融，不能把零相位当成最大功率的通用替代。",
  "[Sources]",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/tables/stage4_5/plan_fixed_periodic_phase_integrated.csv",
  "- C:/Users/24739/Documents/Codex/2026-08-10/new-chat/CTO_virtual_drive_platform_v2_1/results/audits/scan_vs_phase_scenario_comparison.csv",
].join("\n"));

// Export, restore the original theme XML byte-for-byte, then render the final artifact for QA.
const exported = await PresentationFile.exportPptx(deck);
await exported.save(RAW_FINAL);
await restoreThemes(`${ROOT}/source.pptx`, RAW_FINAL, FINAL);

const finalDeck = await PresentationFile.importPptx(await FileBlob.load(FINAL));
const previewDir = `${ROOT}/final-preview`;
const layoutDir = `${ROOT}/final-layout`;
await fs.mkdir(previewDir, { recursive: true });
await fs.mkdir(layoutDir, { recursive: true });
for (let i = 0; i < finalDeck.slides.items.length; i += 1) {
  const slide = finalDeck.slides.items[i];
  const stem = `final-slide-${String(i + 1).padStart(2, "0")}`;
  await writeBlob(`${previewDir}/${stem}.png`, await finalDeck.export({ slide, format: "png", scale: 1 }));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(`${layoutDir}/${stem}.layout.json`, await layout.text(), "utf8");
}
const inspect = await finalDeck.inspect({ kind: "slide,textbox,shape,image,table,chart,notes,layout", maxChars: 150000 });
await fs.writeFile(`${ROOT}/final-inspect.ndjson`, inspect.ndjson, "utf8");
console.log(JSON.stringify({ final: FINAL, slideCount: finalDeck.slides.items.length, previewDir, layoutDir }, null, 2));
