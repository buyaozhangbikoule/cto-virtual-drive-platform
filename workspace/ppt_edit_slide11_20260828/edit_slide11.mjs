import fs from "node:fs/promises";
import { PresentationFile, FileBlob } from "@oai/artifact-tool";

const root = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat";
const tmp = `${root}/ppt_edit_slide11_20260828`;
const source = `${tmp}/template-starter.pptx`;
const sweepCsv = `${root}/outputs/v2_self_consistent_rebuild/active_stage3_5/stage3_disturbance/stage3_frequency_response_all_cases.csv`;
const timelineCsv = `${root}/outputs/v2_self_consistent_rebuild/report_evidence_final/06_控制与保护/stage4_control_timeline.csv`;
const output = `${root}/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_峰位证据严谨修订版_2026-08-28.pptx`;
const qaDir = `${tmp}/qa`;

const COLORS = {
  navy: "#17324D",
  muted: "#5F6B76",
  gray: "#777777",
  grid: "#D9E0E6",
  blue: "#3978B8",
  red: "#B54343",
  bg: "#F7F8FA",
  white: "#FFFFFF",
};

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines[0].split(",");
  return lines.slice(1).map((line) => {
    const values = line.split(",");
    return Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));
  });
}

function num(value) {
  return Number.parseFloat(value);
}

function lineSeries(name, rows, xKey, yKey, color, width, marker = "none") {
  return {
    name,
    xValues: rows.map((row) => num(row[xKey])),
    values: rows.map((row) => num(row[yKey])),
    line: { style: "solid", fill: color, width },
    marker: { symbol: marker, size: marker === "none" ? 2 : 5 },
  };
}

async function writeBlob(path, blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  await fs.writeFile(path, bytes);
}

function setText(shape, text, position, style) {
  shape.position.merge(position);
  shape.text = text;
  shape.text.style = style;
}

async function main() {
  await fs.mkdir(qaDir, { recursive: true });
  const sweepRows = parseCsv(await fs.readFile(sweepCsv, "utf8"));
  const timelineRows = parseCsv(await fs.readFile(timelineCsv, "utf8"));

  const peakFrequency = {
    CASE_000_BASELINE: 900000,
    CASE_FS_M5: 854800,
  };

  const sweepByCase = {};
  for (const caseId of Object.keys(peakFrequency)) {
    const peak = peakFrequency[caseId];
    sweepByCase[caseId] = sweepRows
      .filter((row) => row.case_id === caseId)
      .filter((row) => {
        const f = num(row.frequency_Hz);
        return f >= 840000 && f <= 920000 && (f % 500 === 0 || Math.abs(f - peak) <= 3000 || f === peak);
      })
      .sort((a, b) => num(a.frequency_Hz) - num(b.frequency_Hz))
      .map((row) => ({
        frequency_MHz: num(row.frequency_Hz) / 1e6,
        safe_power_mW: num(row.safe_power_W) * 1000,
      }));
  }

  const strategyOrder = ["FIXED_0P9", "PERIODIC_SCAN", "P_AND_O"];
  const strategyColors = {
    FIXED_0P9: COLORS.gray,
    PERIODIC_SCAN: COLORS.blue,
    P_AND_O: COLORS.red,
  };
  const timelineByStrategy = {};
  for (const strategy of strategyOrder) {
    timelineByStrategy[strategy] = timelineRows
      .filter((row) => row.strategy === strategy && row.action === "CONTROL")
      .filter((row) => num(row.time_s) >= 2.2 && num(row.time_s) <= 3.5)
      .sort((a, b) => num(a.time_s) - num(b.time_s))
      .map((row) => ({
        time_s: num(row.time_s),
        capture_pct: num(row.safe_power_capture_ratio) * 100,
        frequency_MHz: num(row.frequency_MHz),
      }));
  }

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

  const baseline = sweepByCase.CASE_000_BASELINE;
  const fsMinus5 = sweepByCase.CASE_FS_M5;
  const sweepChart = slide.charts.add("scatter", {
    position: { left: 72, top: 112, width: 820, height: 225 },
    title: "离线局部扫频：安全运动支路有功功率",
    titleTextStyle: { fontSize: 16, bold: true, fill: COLORS.navy },
    titlePlacement: "aboveChart",
    series: [
      {
        name: "基准场景",
        xValues: baseline.map((row) => row.frequency_MHz),
        values: baseline.map((row) => row.safe_power_mW),
        line: { style: "solid", fill: COLORS.blue, width: 3 },
        marker: { symbol: "none", size: 2 },
      },
      {
        name: "fs−5%场景",
        xValues: fsMinus5.map((row) => row.frequency_MHz),
        values: fsMinus5.map((row) => row.safe_power_mW),
        line: { style: "solid", fill: COLORS.red, width: 3 },
        marker: { symbol: "none", size: 2 },
      },
    ],
    scatterOptions: { style: "line" },
    hasLegend: false,
    xAxis: {
      min: 0.84,
      max: 0.92,
      majorUnit: 0.02,
      numberFormatCode: "0.000",
      title: { text: "Frequency (MHz)", textStyle: { fontSize: 11, fill: COLORS.muted } },
      textStyle: { fontSize: 14, fill: COLORS.muted },
      line: { style: "solid", fill: COLORS.gray, width: 1 },
      majorGridlines: { style: "solid", fill: "#E8EDF1", width: 1 },
    },
    yAxis: {
      min: 0,
      max: 180,
      majorUnit: 50,
      title: { text: "Safe power (mW)", textStyle: { fontSize: 11, fill: COLORS.muted } },
      textStyle: { fontSize: 14, fill: COLORS.muted },
      line: { style: "solid", fill: COLORS.gray, width: 1 },
      majorGridlines: { style: "solid", fill: "#E8EDF1", width: 1 },
    },
    chartFill: COLORS.white,
    plotAreaFill: COLORS.white,
    chartLine: { style: "solid", fill: COLORS.grid, width: 1 },
  });
  sweepChart.name = "local-safe-power-sweep";

  const strategyNames = {
    FIXED_0P9: "固定0.900 MHz",
    PERIODIC_SCAN: "周期扫频 ○",
    P_AND_O: "扫描辅助P&O △",
  };
  const captureSeries = strategyOrder.map((strategy) => ({
    name: strategyNames[strategy],
    xValues: timelineByStrategy[strategy].map((row) => row.time_s),
    values: timelineByStrategy[strategy].map((row) => row.capture_pct),
    line: {
      style: strategy === "PERIODIC_SCAN" ? "dashed" : "solid",
      fill: strategyColors[strategy],
      width: strategy === "PERIODIC_SCAN" ? 4 : strategy === "P_AND_O" ? 2 : 2.5,
    },
    marker: { symbol: "none", size: 2 },
  }));
  const captureChart = slide.charts.add("scatter", {
    position: { left: 72, top: 345, width: 820, height: 165 },
    title: "同一 fs−5% 扰动窗口：安全功率捕获率\n捕获率按当前扰动场景自身的安全最大功率归一化",
    titleTextStyle: { fontSize: 14, bold: true, fill: COLORS.navy },
    series: captureSeries,
    scatterOptions: { style: "line" },
    hasLegend: true,
    legend: { position: "top", overlay: false, textStyle: { fontSize: 12, fill: COLORS.muted } },
    xAxis: {
      min: 2.2,
      max: 3.5,
      majorUnit: 0.2,
      numberFormatCode: "0.0",
      tickLabelPosition: "none",
      line: { style: "solid", fill: COLORS.gray, width: 1 },
      majorGridlines: { style: "solid", fill: "#E8EDF1", width: 1 },
    },
    yAxis: {
      min: 0,
      max: 105,
      majorUnit: 50,
      title: { text: "Capture (%)", textStyle: { fontSize: 14, fill: COLORS.muted } },
      textStyle: { fontSize: 14, fill: COLORS.muted },
      line: { style: "solid", fill: COLORS.gray, width: 1 },
      majorGridlines: { style: "solid", fill: "#E8EDF1", width: 1 },
    },
    chartFill: COLORS.white,
    plotAreaFill: COLORS.white,
    chartLine: { style: "solid", fill: COLORS.grid, width: 1 },
  });
  captureChart.name = "fs-minus5-capture-timeline";

  const frequencySeries = strategyOrder.map((strategy) => ({
    name: strategyNames[strategy],
    xValues: timelineByStrategy[strategy].map((row) => row.time_s),
    values: timelineByStrategy[strategy].map((row) => row.frequency_MHz),
    line: {
      style: strategy === "PERIODIC_SCAN" ? "dashed" : "solid",
      fill: strategyColors[strategy],
      width: strategy === "PERIODIC_SCAN" ? 4 : strategy === "P_AND_O" ? 2 : 2.5,
    },
    marker: { symbol: "none", size: 2 },
  }));
  const frequencyChart = slide.charts.add("scatter", {
    position: { left: 72, top: 518, width: 820, height: 145 },
    title: "同一窗口：控制频率",
    titleTextStyle: { fontSize: 15, bold: true, fill: COLORS.navy },
    series: frequencySeries,
    scatterOptions: { style: "line" },
    hasLegend: false,
    xAxis: {
      min: 2.2,
      max: 3.5,
      majorUnit: 0.2,
      numberFormatCode: "0.0",
      title: { text: "Quasi-steady time (s)", textStyle: { fontSize: 14, fill: COLORS.muted } },
      textStyle: { fontSize: 14, fill: COLORS.muted },
      line: { style: "solid", fill: COLORS.gray, width: 1 },
      majorGridlines: { style: "solid", fill: "#E8EDF1", width: 1 },
    },
    yAxis: {
      min: 0.85,
      max: 0.905,
      majorUnit: 0.01,
      numberFormatCode: "0.000",
      title: { text: "Frequency (MHz)", textStyle: { fontSize: 14, fill: COLORS.muted } },
      textStyle: { fontSize: 14, fill: COLORS.muted },
      line: { style: "solid", fill: COLORS.gray, width: 1 },
      majorGridlines: { style: "solid", fill: "#E8EDF1", width: 1 },
    },
    chartFill: COLORS.white,
    plotAreaFill: COLORS.white,
    chartLine: { style: "solid", fill: COLORS.grid, width: 1 },
  });
  frequencyChart.name = "fs-minus5-frequency-timeline";

  const plotLeft = 132;
  const plotWidth = 744;
  const xForFrequency = (fMHz) => plotLeft + ((fMHz - 0.84) / 0.08) * plotWidth;
  const guideTop = 164;
  const guideHeight = 150;
  const redGuide = slide.shapes.add({
    geometry: "rect",
    name: "guide-fs-minus5-peak",
    position: { left: xForFrequency(0.8548) - 1, top: guideTop, width: 2, height: guideHeight },
    fill: COLORS.red,
    line: { style: "solid", fill: COLORS.red, width: 0 },
  });
  const grayGuide = slide.shapes.add({
    geometry: "rect",
    name: "guide-fixed-0p9",
    position: { left: xForFrequency(0.9) - 1, top: guideTop, width: 2, height: guideHeight },
    fill: COLORS.gray,
    line: { style: "solid", fill: COLORS.gray, width: 0 },
  });
  redGuide.bringToFront();
  grayGuide.bringToFront();

  const redPeak = slide.shapes.add({
    geometry: "ellipse",
    name: "marker-fs-minus5-peak",
    position: { left: xForFrequency(0.8548) - 5, top: 190, width: 10, height: 10 },
    fill: COLORS.red,
    line: { style: "solid", fill: COLORS.white, width: 1 },
  });
  const bluePeak = slide.shapes.add({
    geometry: "ellipse",
    name: "marker-baseline-peak",
    position: { left: xForFrequency(0.9) - 5, top: 168, width: 10, height: 10 },
    fill: COLORS.blue,
    line: { style: "solid", fill: COLORS.white, width: 1 },
  });
  redPeak.bringToFront();
  bluePeak.bringToFront();

  const addLabel = (name, text, position, color, fontSize = 14, alignment = "center") => {
    const shape = slide.shapes.add({
      geometry: "textbox",
      name,
      position,
      fill: COLORS.white,
      line: { style: "solid", fill: "none", width: 0 },
    });
    shape.text = text;
    shape.text.style = { fontSize, bold: true, color, alignment };
    shape.bringToFront();
    return shape;
  };

  addLabel(
    "label-fs-minus5-peak",
    "fs−5%峰值：0.8548 MHz",
    { left: 160, top: 146, width: 220, height: 24 },
    COLORS.red,
    14,
  );
  addLabel(
    "label-baseline-peak",
    "基准峰值：0.9000 MHz",
    { left: 582, top: 146, width: 220, height: 24 },
    COLORS.blue,
    14,
  );

  const timePlotLeft = 152;
  const timePlotWidth = 724;
  const xForTime = (timeS) => timePlotLeft + ((timeS - 2.2) / 1.3) * timePlotWidth;
  for (const spec of [
    { name: "event-start-capture", time: 2.4, top: 420, height: 74, color: COLORS.gray },
    { name: "event-arrival-capture", time: 2.497, top: 420, height: 74, color: COLORS.blue },
    { name: "event-start-frequency", time: 2.4, top: 560, height: 86, color: COLORS.gray },
    { name: "event-arrival-frequency", time: 2.497, top: 560, height: 86, color: COLORS.blue },
  ]) {
    const marker = slide.shapes.add({
      geometry: "rect",
      name: spec.name,
      position: { left: xForTime(spec.time) - 1, top: spec.top, width: 2, height: spec.height },
      fill: spec.color,
      line: { style: "solid", fill: spec.color, width: 0 },
    });
    marker.bringToFront();
  }

  addLabel(
    "label-disturbance-start",
    "扰动开始",
    { left: xForTime(2.4) - 48, top: 544, width: 88, height: 22 },
    COLORS.gray,
    13,
  );
  addLabel(
    "label-arrival-time",
    "约2.50 s到达新峰位",
    { left: xForTime(2.497) + 6, top: 544, width: 156, height: 22 },
    COLORS.blue,
    13,
    "left",
  );
  addLabel(
    "label-frequency-fixed-platform",
    "固定：0.9000 MHz",
    { left: 700, top: 557, width: 168, height: 22 },
    COLORS.gray,
    13,
  );
  addLabel(
    "label-frequency-adaptive-platform",
    "自适应：0.8548 MHz",
    { left: 520, top: 627, width: 184, height: 22 },
    COLORS.blue,
    13,
  );

  const addDataMarker = (name, geometry, centerX, centerY, fill, lineColor, size = 8) => {
    const marker = slide.shapes.add({
      geometry,
      name,
      position: { left: centerX - size / 2, top: centerY - size / 2, width: size, height: size },
      fill,
      line: { style: "solid", fill: lineColor, width: 1.5 },
    });
    marker.bringToFront();
    return marker;
  };

  for (const [index, timeS] of [2.60, 2.80, 3.00, 3.20, 3.40].entries()) {
    addDataMarker(`periodic-capture-circle-${index}`, "ellipse", xForTime(timeS), 423, COLORS.white, COLORS.blue, 8);
  }
  for (const [index, timeS] of [2.70, 2.90, 3.10, 3.30, 3.45].entries()) {
    addDataMarker(`pando-capture-triangle-${index}`, "triangle", xForTime(timeS), 423, COLORS.red, COLORS.red, 9);
  }
  for (const [index, timeS] of [2.60, 2.80, 3.00].entries()) {
    addDataMarker(`periodic-frequency-circle-${index}`, "ellipse", xForTime(timeS), 609, COLORS.white, COLORS.blue, 8);
  }
  for (const [index, timeS] of [2.70, 2.90, 3.10].entries()) {
    addDataMarker(`pando-frequency-triangle-${index}`, "triangle", xForTime(timeS), 609, COLORS.red, COLORS.red, 9);
  }

  const note = [
    "先用上方离线扫频直接证明安全功率峰位由0.9000 MHz移动到0.8548 MHz，再用下方同一扰动窗口解释控制器如何定位新峰值。",
    "捕获率按每个扰动场景自身的安全最大功率归一化；100%不等于恢复基准场景约170 mW的绝对功率。",
    "周期扫频在约96.5 ms后满足连续10个NORMAL控制样本保持在98%以上；P&O在98.5 ms首次到达同一峰位，但周期性参考/试探使其未在本段内通过连续稳态验收。",
    "下方时序仅绘制CONTROL控制样本；低幅扫描和保护细节见上一页。不要由本页推断P&O已经完成稳定锁定。",
    "",
    "[Sources]",
    `- ${sweepCsv.replaceAll("/", "\\")}`,
    `- ${timelineCsv.replaceAll("/", "\\")}`,
  ].join("\n");
  slide.speakerNotes.textFrame.setText(note);
  slide.speakerNotes.setVisible(true);

  await writeBlob(`${qaDir}/after-slide-11.png`, await presentation.export({ slide, format: "png", scale: 1.5 }));
  await fs.writeFile(`${qaDir}/after-slide-11.layout.json`, await (await slide.export({ format: "layout" })).text(), "utf8");
  const after = await presentation.inspect({
    target: { id: "sl/jetc3ut0", beforeLines: 0, afterLines: 30 },
    kind: "slide,textbox,shape,image,chart,notes",
    maxChars: 30000,
  });
  await fs.writeFile(`${qaDir}/after-slide-11.inspect.ndjson`, after.ndjson, "utf8");
  await writeBlob(`${qaDir}/after-montage.webp`, await presentation.export({ format: "webp", montage: true, scale: 0.6 }));

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(output);
  console.log(output);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
