import fs from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const W = 1280;
const H = 720;
const BG = "#F7F8FA";
const WHITE = "#FFFFFF";
const NAVY = "#17324D";
const TEAL = "#2A7F8E";
const ORANGE = "#E69F00";
const RED = "#B33A3A";
const BLUE = "#3978B8";
const PO = "#B54343";
const GRAY = "#777777";
const DARK = "#1F2933";
const MID = "#5F6B76";
const LIGHT = "#D9E0E6";
const PALE_BLUE = "#EAF1F7";
const PALE_TEAL = "#E8F3F3";
const PALE_ORANGE = "#FFF4DD";
const PALE_RED = "#F9E7E7";
const FONT_CN = "Microsoft YaHei";

const ROOT = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\v2_self_consistent_rebuild\\report_evidence_final";
const SHOTS = path.join(ROOT, "07_汇报截图");
const BUILD = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\ppt_build_2026-08-24";
const OUT = path.join(ROOT, "CTO超声换能器第一月教授组会汇报_2026-08-24.pptx");
const PREVIEWS = path.join(BUILD, "previews");
const CRITERIA_BASELINE = path.join(BUILD, "criteria-baseline-crop.png");
const CRITERIA_FS_M5 = path.join(BUILD, "criteria-fs-m5-crop.png");

async function imageBytes(file) {
  const b = await fs.readFile(file);
  return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
}

async function prepareDerivedAssets() {
  const source = path.join(SHOTS, "stage3_selection_01_criteria_examples.png");
  await sharp(source).extract({ left: 0, top: 70, width: 2140, height: 520 }).png().toFile(CRITERIA_BASELINE);
  await sharp(source).extract({ left: 0, top: 600, width: 2140, height: 530 }).png().toFile(CRITERIA_FS_M5);
}

function textBox(slide, text, left, top, width, height, opts = {}) {
  const s = slide.shapes.add({
    geometry: "textbox",
    name: opts.name,
    position: { left, top, width, height },
    fill: opts.fill ?? "none",
    line: opts.line ?? { style: "solid", fill: "none", width: 0 },
  });
  s.text = text;
  s.text.style = {
    fontFamily: opts.fontFamily ?? FONT_CN,
    fontSize: opts.fontSize ?? 20,
    color: opts.color ?? DARK,
    bold: opts.bold ?? false,
    alignment: opts.align ?? "left",
    verticalAlignment: opts.valign ?? "top",
  };
  return s;
}

function rect(slide, left, top, width, height, fill, lineFill = fill, lineWidth = 0, radius = 0) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left, top, width, height },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
    ...(radius ? { borderRadius: radius } : {}),
  });
}

function title(slide, t, page) {
  textBox(slide, t, 72, 36, 1136, 54, { fontSize: 36, bold: true, color: NAVY, valign: "middle", name: `title-${page}` });
  rect(slide, 72, 96, 1136, 3, NAVY);
}

function footer(slide, page, backup = false) {
  rect(slide, 72, 682, 1136, 1, LIGHT);
  textBox(slide, backup ? "Electrical model only — structural/acoustic validation pending" : "Hypothetical BVD model — non-measured parameters", 72, 688, 720, 20, { fontSize: 12, color: MID });
  textBox(slide, String(page), 1160, 688, 48, 20, { fontSize: 12, color: MID, align: "right" });
}

function notes(slide, talk, sources) {
  const src = sources.map((s) => `- ${s}`).join("\n");
  slide.speakerNotes.textFrame.setText(`${talk}\n\n[Sources]\n${src}`);
  slide.speakerNotes.setVisible(true);
}

async function addImage(slide, file, left, top, width, height, opts = {}) {
  return slide.images.add({
    blob: await imageBytes(file),
    contentType: "image/png",
    alt: opts.alt ?? path.basename(file),
    fit: opts.fit ?? "contain",
    position: { left, top, width, height },
    ...(opts.crop ? { crop: opts.crop } : {}),
    geometry: "rect",
  });
}

function slideBase(presentation, t, page, backup = false) {
  const s = presentation.slides.add();
  s.background.fill = BG;
  title(s, t, page);
  footer(s, page, backup);
  return s;
}

function node(slide, x, y, w, h, label, fill = WHITE, line = LIGHT, color = NAVY) {
  rect(slide, x, y, w, h, fill, line, 1.5, 6);
  textBox(slide, label, x + 10, y + 8, w - 20, h - 16, { fontSize: 20, bold: true, color, align: "center", valign: "middle" });
}

function arrow(slide, x, y, w, h, fill = LIGHT) {
  slide.shapes.add({ geometry: "rightArrow", position: { left: x, top: y, width: w, height: h }, fill, line: { style: "solid", fill, width: 0 } });
}

function addSimpleTable(slide, values, left, top, width, height, colTracks, opts = {}) {
  const table = slide.tables.add({ rows: values.length, columns: values[0].length, left, top, width, height, values, columnTracks: colTracks });
  table.borders.assign({ style: "solid", fill: opts.border ?? LIGHT, width: 1 });
  table.styleOptions = { headerRow: true, bandedRows: false };
  for (let r = 0; r < values.length; r++) {
    for (let c = 0; c < values[0].length; c++) {
      const cell = table.getCell(r, c);
      cell.fill = r === 0 ? NAVY : (r % 2 ? WHITE : "#F1F4F6");
      cell.text.style = { fontFamily: FONT_CN, fontSize: opts.fontSize ?? 17, color: r === 0 ? WHITE : DARK, bold: r === 0 };
    }
  }
  return table;
}

async function main() {
  await fs.mkdir(PREVIEWS, { recursive: true });
  await prepareDerivedAssets();
  const p = Presentation.create({ slideSize: { width: W, height: H } });

  // 1. Cover
  {
    const s = p.slides.add();
    s.background.fill = BG;
    rect(s, 0, 0, 18, H, TEAL);
    textBox(s, "CTO超声换能器虚拟阻抗建模\n与自适应驱动控制", 92, 160, 820, 150, { fontSize: 54, bold: true, color: NAVY, valign: "middle" });
    textBox(s, "第一月：BVD建模、阻抗匹配、扰动分析与控制原型", 96, 332, 920, 42, { fontSize: 24, color: TEAL });
    rect(s, 96, 405, 160, 5, ORANGE);
    textBox(s, "第一月工作汇报  |  2026.08", 96, 445, 500, 32, { fontSize: 20, color: MID });
    textBox(s, "端口电学模型与准稳态控制，不涉及治疗效果结论", 96, 612, 840, 32, { fontSize: 16, color: MID });
    textBox(s, "1", 1160, 688, 48, 20, { fontSize: 12, color: MID, align: "right" });
    notes(s, "开场只做边界定义：本月完成的是端口电学模型、匹配、扰动扫描和控制原型，不是CTO治疗效果验证。", [path.join(ROOT, "01_项目口径与参数", "03_Codex任务说明_修订版_v2_1.md")]);
  }

  // 2. Problem and boundary
  {
    const s = slideBase(p, "固定0.9 MHz未必能在阻抗漂移后维持最佳电学工作点", 2);
    for (const x of [244, 464, 684, 904]) arrow(s, x, 264, 70, 34, LIGHT);
    node(s, 86, 235, 160, 92, "假设BVD\n模型", PALE_BLUE, BLUE);
    node(s, 306, 235, 160, 92, "L型匹配", PALE_TEAL, TEAL);
    node(s, 526, 235, 160, 92, "参数扰动", PALE_ORANGE, ORANGE);
    node(s, 746, 235, 160, 92, "阻抗与功率", WHITE, LIGHT);
    node(s, 966, 235, 190, 92, "选频与保护", PALE_RED, RED);
    textBox(s, "小信号线性等效电路", 108, 410, 300, 40, { fontSize: 22, bold: true, color: NAVY });
    textBox(s, "参数为假设基线或扫描变量", 450, 410, 360, 40, { fontSize: 22, bold: true, color: NAVY });
    textBox(s, "不计算声压、温升、空化或临床效果", 824, 410, 380, 48, { fontSize: 18, bold: true, color: NAVY });
    notes(s, "这页回答项目在解决什么：负载或参数变化导致电学最优点移动，固定频率可能失配。随后引出参数必须先自洽。", [path.join(ROOT, "01_项目口径与参数", "03_Codex任务说明_修订版_v2_1.md")]);
  }

  // 3. Parameter conflict
  {
    const s = slideBase(p, "旧参数无法同时满足100 Vpp、5 mA与100 Ω串联谐振", 3);
    rect(s, 72, 130, 520, 470, WHITE, LIGHT, 1);
    textBox(s, "旧参数的数量级冲突", 96, 154, 440, 32, { fontSize: 26, bold: true, color: ORANGE });
    textBox(s, "V_RMS = 100/(2√2) = 35.36 V", 104, 220, 430, 44, { fontSize: 25, color: DARK });
    textBox(s, "若串联谐振时 Rm = 100 Ω", 104, 286, 430, 44, { fontSize: 23, color: DARK });
    textBox(s, "I_RMS ≈ 353.6 mA", 124, 358, 380, 44, { fontSize: 29, bold: true, color: RED });
    textBox(s, "P ≈ 12.5 W", 124, 414, 380, 44, { fontSize: 29, bold: true, color: RED });
    textBox(s, "与约5 mA、0.17 W目标明显冲突", 104, 510, 430, 52, { fontSize: 21, bold: true, color: ORANGE });
    rect(s, 620, 130, 588, 470, PALE_BLUE, BLUE, 1);
    textBox(s, "v2.1假设基线", 650, 154, 500, 32, { fontSize: 26, bold: true, color: NAVY });
    const params = ["C₀ = 6.858 pF", "Rₘ = 7.353 kΩ", "Qₘ = 800", "Lₘ = 1.040 H", "Cₘ = 0.0301 pF", "fₛ = 0.9 MHz"];
    params.forEach((v, i) => textBox(s, v, 668 + (i % 2) * 245, 230 + Math.floor(i / 2) * 82, 220, 44, { fontSize: 24, bold: i === 1 || i === 5, color: i === 1 || i === 5 ? TEAL : DARK }));
    textBox(s, "数量级自洽的虚拟模型，非实测辨识参数", 650, 506, 520, 50, { fontSize: 21, bold: true, color: NAVY, align: "center" });
    notes(s, "教授最可能追问参数来源。先主动展示旧参数冲突，再强调v2.1只解决数学自洽，不代表器件真实性。", [path.join(ROOT, "01_项目口径与参数", "v2_1_活动基线参数.csv"), path.join(ROOT, "01_项目口径与参数", "03_Codex任务说明_修订版_v2_1.md")]);
  }

  // 4. Cross validation
  {
    const s = slideBase(p, "Python解析解与LTspice RAW重合，数值实现具有可复现性", 4);
    await addImage(s, path.join(SHOTS, "V2_1_STAGE1_LTspice_RAW交叉验证.png"), 100, 112, 743, 520, { fit: "stretch", alt: "Complete LTspice RAW and Python analytic impedance comparison" });
    textBox(s, "100 001", 936, 136, 220, 44, { fontSize: 34, bold: true, color: NAVY, align: "center" });
    textBox(s, "频率点", 936, 178, 220, 26, { fontSize: 17, color: MID, align: "center" });
    textBox(s, "1.36×10⁻⁷", 936, 236, 220, 44, { fontSize: 30, bold: true, color: TEAL, align: "center" });
    textBox(s, "最大|Z|相对误差", 936, 278, 220, 28, { fontSize: 17, color: MID, align: "center" });
    textBox(s, "0%", 936, 334, 220, 44, { fontSize: 34, bold: true, color: ORANGE, align: "center" });
    textBox(s, "串联谐振频率误差", 936, 376, 220, 28, { fontSize: 17, color: MID, align: "center" });
    await addImage(s, path.join(SHOTS, "LTspice_SPICE_Error_Log.png"), 928, 442, 250, 116, { fit: "contain", alt: "LTspice SPICE Error Log screenshot" });
    textBox(s, "实现一致性 ≠ 参数真实性", 920, 580, 270, 32, { fontSize: 18, bold: true, color: RED, align: "center" });
    notes(s, "先讲同一拓扑和参数下两种实现几乎完全重合，再主动限定：这证明程序与网表一致，不证明BVD参数代表真实换能器。", [path.join(ROOT, "02_LTspice真实运行", "V2_1_STAGE1_LTspice_解析交叉验证.csv"), path.join(SHOTS, "V2_1_STAGE1_LTspice_RAW交叉验证.png"), path.join(SHOTS, "LTspice_SPICE_Error_Log.png")]);
  }

  // 5. Matching
  {
    const s = slideBase(p, "同一源条件下，L型匹配将运动支路有功功率代理提高约32.8倍", 5);
    await addImage(s, path.join(SHOTS, "stage2_02_匹配前后功率与反射_RAW.png"), 72, 116, 714, 500, { fit: "stretch", alt: "Complete matched versus unmatched power and reflection proxy" });
    await addImage(s, path.join(SHOTS, "stage2_01_匹配前后输入阻抗_RAW.png"), 830, 132, 350, 245, { fit: "stretch", alt: "Complete matched versus unmatched input impedance" });
    rect(s, 846, 418, 318, 150, PALE_TEAL, TEAL, 1, 6);
    textBox(s, "Lmatch ≈ 106.726 μH\nCmatch ≈ 283.599 pF\n设计中心：0.9 MHz", 872, 440, 270, 95, { fontSize: 21, bold: true, color: NAVY, align: "center" });
    textBox(s, "P_Rm × 32.8", 880, 576, 250, 40, { fontSize: 28, bold: true, color: ORANGE, align: "center" });
    textBox(s, "电学功率传递改善，不等于电声效率提高32.8倍", 430, 638, 760, 28, { fontSize: 15, color: RED, align: "right" });
    notes(s, "强调比较使用同一Thevenin源，不在每个网络后重新校准端电压。32.8倍只描述P_Rm代理，不应称为效率。", [path.join(ROOT, "03_匹配网络", "stage2_匹配前后特征汇总.csv"), path.join(ROOT, "03_匹配网络", "stage2_LTspice_解析交叉验证.csv"), path.join(SHOTS, "stage2_02_匹配前后功率与反射_RAW.png")]);
  }

  // 6. Sensitivity matrix
  {
    const s = slideBase(p, "fs主导峰位，Rm与匹配损耗主要改变峰高和峰宽", 6);
    const vals = [
      ["最高档扰动", "峰位变化", "峰高变化", "峰宽变化"],
      ["C₀ +30%", "0.0 kHz", "−0.15%", "−0.16%"],
      ["Rₘ +50%", "0.0 kHz", "−6.36%", "+26.50%"],
      ["fₛ −5%", "−45.2 kHz", "−17.51%", "−29.85%"],
      ["Rₛ +20%", "0.0 kHz", "−16.40%", "−7.24%"],
      ["Lmatch +10%", "+0.3 kHz", "−14.80%", "−23.56%"],
      ["电感Q = 20", "0.0 kHz", "−33.50%", "−14.30%"],
    ];
    const table = addSimpleTable(s, vals, 72, 142, 850, 440, [{ mode: "fr", value: 1.4 }, { mode: "fr", value: 1 }, { mode: "fr", value: 1 }, { mode: "fr", value: 1 }], { fontSize: 18 });
    table.getCell(3, 1).fill = PALE_ORANGE; table.getCell(3, 1).text.style = { fontFamily: FONT_CN, fontSize: 19, color: ORANGE, bold: true };
    table.getCell(6, 2).fill = PALE_RED; table.getCell(6, 2).text.style = { fontFamily: FONT_CN, fontSize: 19, color: RED, bold: true };
    table.getCell(2, 3).fill = PALE_TEAL; table.getCell(2, 3).text.style = { fontFamily: FONT_CN, fontSize: 19, color: TEAL, bold: true };
    textBox(s, "控制含义", 966, 152, 220, 34, { fontSize: 25, bold: true, color: NAVY });
    textBox(s, "1  先捕获峰位漂移\n\n2  再处理峰高损失\n\n3  按峰宽选择步长", 966, 210, 220, 220, { fontSize: 19, color: DARK });
    rect(s, 966, 468, 218, 86, PALE_ORANGE, ORANGE, 1, 6);
    textBox(s, "最大峰位变化\n−45.2 kHz", 986, 482, 178, 60, { fontSize: 23, bold: true, color: ORANGE, align: "center" });
    notes(s, "这页不是念完整扫描表，而是回答谁控制峰位、峰高和峰宽。重点指出fs漂移决定控制器的捕获范围。", [path.join(ROOT, "04_扰动与Qm", "stage3_trend_table.csv"), path.join(ROOT, "04_扰动与Qm", "stage3_scenario_registry_and_summary.csv")]);
  }

  // 7. Qm
  {
    const s = slideBase(p, "Qm越高，功率峰越窄，选频步长和频率抖动要求越严格", 7);
    await addImage(s, path.join(SHOTS, "stage3_03_Qm_sensitivity.png"), 98, 112, 682, 550, { fit: "stretch", alt: "Complete Qm sensitivity power and impedance curves" });
    textBox(s, "FWHM", 920, 156, 230, 36, { fontSize: 26, bold: true, color: NAVY, align: "center" });
    const qm = [["Qm=500", "3.451 kHz", BLUE], ["Qm=800", "2.144 kHz", TEAL], ["Qm=1000", "1.713 kHz", ORANGE]];
    qm.forEach((q, i) => {
      rect(s, 890, 220 + i * 98, 280, 62, i === 0 ? PALE_BLUE : i === 1 ? PALE_TEAL : PALE_ORANGE, q[2], 1, 5);
      textBox(s, q[0], 906, 230 + i * 98, 120, 40, { fontSize: 18, bold: true, color: q[2] });
      textBox(s, q[1], 1026, 230 + i * 98, 126, 40, { fontSize: 20, bold: true, color: DARK, align: "right" });
    });
    textBox(s, "高Q不自动代表系统更好；\n它意味着更严格的频率分辨率。", 890, 535, 290, 82, { fontSize: 19, bold: true, color: NAVY, align: "center" });
    notes(s, "三组保持fs、Rm和C0固定，并重新推导Lm/Cm。峰高约0.17 W保持不变，峰宽随Qm增加而缩小。", [path.join(ROOT, "04_扰动与Qm", "stage3_Qm_500_800_1000_summary.csv"), path.join(SHOTS, "stage3_03_Qm_sensitivity.png")]);
  }

  // 8. Criteria
  {
    const s = slideBase(p, "零相位不保证最大功率，相位闭环不能无条件以0°为目标", 8);
    await addImage(s, CRITERIA_BASELINE, 72, 150, 880, 205, { fit: "contain", alt: "Baseline selection criteria" });
    await addImage(s, CRITERIA_FS_M5, 72, 385, 880, 205, { fit: "contain", alt: "fs minus 5 percent selection criteria" });
    textBox(s, "基准场景", 90, 132, 180, 28, { fontSize: 19, bold: true, color: NAVY });
    textBox(s, "fs −5%场景", 90, 367, 180, 28, { fontSize: 19, bold: true, color: NAVY });
    rect(s, 980, 220, 220, 162, PALE_ORANGE, ORANGE, 1, 6);
    textBox(s, "最大功率\n0.8550 MHz\n\n最小相位\n0.9045 MHz", 1000, 236, 180, 132, { fontSize: 20, bold: true, color: ORANGE, align: "center" });
    rect(s, 980, 420, 220, 92, PALE_TEAL, TEAL, 1, 6);
    textBox(s, "频率差\n约49.5 kHz", 1000, 435, 180, 64, { fontSize: 23, bold: true, color: TEAL, align: "center" });
    textBox(s, "相位可作为观测量，但目标应来自受约束最大功率点", 970, 548, 240, 64, { fontSize: 17, bold: true, color: NAVY, align: "center" });
    notes(s, "先看基准场景，再看fs-5%的反例。最大功率点与最小相位点相差49.5 kHz，说明零相位不能直接作为功率最大化目标。", [path.join(ROOT, "05_选频准则", "stage3_initial_three_criteria.csv"), path.join(SHOTS, "stage3_selection_01_criteria_examples.png")]);
  }

  // 9. Window step tradeoff
  {
    const s = slideBase(p, "窗口决定能否捕获漂移峰，步长决定精度与扫描代价", 9);
    await addImage(s, path.join(SHOTS, "stage3_selection_02_window_step_tradeoff.png"), 72, 106, 1136, 481, { fit: "stretch", alt: "Complete window and step tradeoff heatmaps" });
    rect(s, 814, 594, 360, 78, PALE_TEAL, TEAL, 1, 6);
    textBox(s, "推荐：±50 kHz / 1 kHz / 101点\n扫描时间代理：151.5 ms", 838, 603, 312, 58, { fontSize: 20, bold: true, color: NAVY, align: "center" });
    textBox(s, "大扰动：宽窗口粗扫", 86, 598, 310, 32, { fontSize: 22, bold: true, color: ORANGE });
    textBox(s, "接近峰值：缩窗并细化至0.1–1 kHz", 86, 635, 650, 30, { fontSize: 22, bold: true, color: TEAL });
    notes(s, "±20 kHz会漏掉部分漂移峰；±50 kHz可覆盖当前28场景。扫描时间按1.5 ms/点估算，只是准稳态代理。", [path.join(ROOT, "05_选频准则", "stage3_window_step_aggregate.csv"), path.join(ROOT, "05_选频准则", "stage3_selection_report.md")]);
  }

  // 10. Protection
  {
    const s = slideBase(p, "保护状态机先调幅并冻结频率，稳定后才恢复追踪", 10);
    // Draw arrows first, then nodes.
    arrow(s, 156, 210, 32, 22, LIGHT); arrow(s, 156, 310, 32, 22, LIGHT); arrow(s, 156, 410, 32, 22, LIGHT); arrow(s, 156, 510, 32, 22, LIGHT);
    node(s, 82, 158, 145, 62, "NORMAL", PALE_BLUE, BLUE);
    node(s, 82, 258, 145, 62, "FOLDBACK", PALE_ORANGE, ORANGE);
    node(s, 82, 358, 145, 62, "HOLD", PALE_RED, RED);
    node(s, 82, 458, 145, 62, "RAMP UP", PALE_TEAL, TEAL);
    textBox(s, "硬触发：HARD TRIP", 66, 554, 190, 46, { fontSize: 14, bold: true, color: RED, align: "center" });
    await addImage(s, path.join(SHOTS, "stage4_02_protection_state_machine.png"), 380, 110, 735, 535, { fit: "stretch", alt: "Complete protection state machine triggered-limit timeline" });
    textBox(s, "软触发：130 Vpp / 5.5 mA RMS    硬上限：160 Vpp / 6 mA RMS", 340, 648, 790, 24, { fontSize: 16, bold: true, color: RED, align: "center" });
    notes(s, "围绕约2.4 s真实触发窗口讲解。任何非NORMAL状态都先调幅并冻结频率，预测裁剪保证实际硬越限次数为0。阈值是仿真假设。", [path.join(ROOT, "06_控制与保护", "stage4_control_timeline.csv"), path.join(ROOT, "06_控制与保护", "stage4_5_control_report.md"), path.join(SHOTS, "stage4_02_protection_state_machine.png")]);
  }

  // 11. Timeline
  {
    const s = slideBase(p, "固定频率在谐振漂移段失去功率，自适应策略可重新定位峰值", 11);
    await addImage(s, path.join(SHOTS, "stage4_01_three_strategy_timeline.png"), 145, 105, 722, 560, { fit: "stretch", alt: "Complete three-strategy power, frequency, and amplitude timeline" });
    textBox(s, "固定0.9 MHz", 980, 160, 210, 30, { fontSize: 21, bold: true, color: GRAY });
    textBox(s, "漂移段不能恢复峰值", 980, 195, 210, 48, { fontSize: 17, color: MID });
    textBox(s, "周期扫频", 980, 282, 210, 30, { fontSize: 21, bold: true, color: BLUE });
    textBox(s, "重新定位后稳定捕获", 980, 317, 210, 48, { fontSize: 17, color: MID });
    textBox(s, "扫描辅助P&O", 980, 404, 210, 30, { fontSize: 21, bold: true, color: PO });
    textBox(s, "可到达稳态，但确认恢复较慢", 980, 439, 210, 60, { fontSize: 17, color: MID });
    textBox(s, "三种策略经历完全相同的8段绝对时间扰动序列", 958, 570, 240, 58, { fontSize: 18, bold: true, color: NAVY, align: "center" });
    notes(s, "按照扰动—响应—恢复顺序讲图，不逐点念曲线。不要说P&O恢复最快；当前严格验收下周期扫频更稳健。", [path.join(ROOT, "06_控制与保护", "stage4_control_timeline.csv"), path.join(SHOTS, "stage4_01_three_strategy_timeline.png")]);
  }

  // 12. Integrated metrics
  {
    const s = slideBase(p, "按98%功率连续10样本验收，周期扫频在当前参数下最稳健", 12);
    const vals = [
      ["策略", "稳态误差", "恢复时间", "未收敛段", "硬越限"],
      ["固定0.9 MHz", "30.14%", "345.7 ms", "3", "0"],
      ["周期扫频", "0%", "95.5 ms", "0", "0"],
      ["P&O", "0%", "800.0 ms", "7", "0"],
    ];
    const table = addSimpleTable(s, vals, 72, 170, 650, 290, [{ mode: "fr", value: 1.5 }, { mode: "fr", value: 1 }, { mode: "fr", value: 1.1 }, { mode: "fr", value: 0.9 }, { mode: "fr", value: 0.8 }], { fontSize: 18 });
    for (let c = 0; c < 5; c++) { table.getCell(2, c).fill = PALE_TEAL; table.getCell(2, c).text.style = { fontFamily: FONT_CN, fontSize: 18, color: c === 0 ? TEAL : DARK, bold: true }; }
    s.charts.add("bar", {
      position: { left: 770, top: 160, width: 420, height: 320 },
      categories: ["固定", "周期扫频", "P&O"],
      series: [{ name: "恢复时间", values: [345.7, 95.5, 800.0], fill: BLUE, points: [{ idx: 0, fill: GRAY }, { idx: 1, fill: BLUE }, { idx: 2, fill: PO }] }],
      barOptions: { direction: "bar", grouping: "clustered", gapWidth: 55 },
      hasLegend: false,
      xAxis: { title: "恢复时间代理 (ms)", min: 0, max: 900, majorGridlines: { style: "solid", fill: LIGHT, width: 1 }, textStyle: { fontSize: 14, fill: MID } },
      yAxis: { textStyle: { fontSize: 16, fill: DARK }, majorGridlines: null },
      dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 16, fill: DARK, bold: true } },
      chartFill: "none", plotAreaFill: "none", chartLine: { style: "solid", fill: "none", width: 0 }, plotAreaLine: { style: "solid", fill: "none", width: 0 },
    });
    rect(s, 72, 506, 1118, 112, PALE_ORANGE, ORANGE, 1, 6);
    textBox(s, "0%只表示尾段达到离线参考点；P&O的800 ms包含7段未收敛惩罚。\n结果排序只对当前线性模型、扰动时窗、驻留时间和控制参数成立。", 100, 530, 1060, 68, { fontSize: 20, bold: true, color: NAVY, align: "center" });
    notes(s, "这页给出正式验收结论。固定频率稳态误差高；周期扫频在所有扰动段满足验收；P&O尾段可到最优，但7段未满足连续10样本确认。", [path.join(ROOT, "06_控制与保护", "stage5_integrated_strategy_table.csv"), path.join(ROOT, "06_控制与保护", "stage5_per_segment_metrics.csv"), path.join(ROOT, "06_控制与保护", "stage4_5_control_report.md")]);
  }

  // 13. Evidence boundary
  {
    const s = slideBase(p, "文献支持负载影响电学状态，但尚不能建立病变到BVD的一一映射", 13);
    arrow(s, 236, 232, 48, 28, LIGHT); arrow(s, 526, 232, 48, 28, LIGHT);
    node(s, 82, 178, 220, 130, "文献直接事实\n\n纤维化、钙化、\n结构异质性", PALE_BLUE, BLUE);
    node(s, 350, 178, 220, 130, "工程建模假设\n\nfs、Rm、匹配状态\n可能变化", PALE_ORANGE, ORANGE);
    node(s, 618, 178, 220, 130, "待验证\n\n病变类型到BVD参数\n的定量映射", PALE_RED, RED);
    rect(s, 892, 152, 286, 390, WHITE, LIGHT, 1);
    textBox(s, "当前能力边界", 918, 178, 235, 34, { fontSize: 25, bold: true, color: NAVY, align: "center" });
    textBox(s, "已完成\n端口电学模型\n准稳态控制原型\n\n未完成\n结构模态与声场\n热效应与空化\n临床效果", 932, 232, 208, 260, { fontSize: 21, color: DARK, align: "center" });
    textBox(s, "文献层、工程假设层、待验证层必须分开", 118, 394, 680, 50, { fontSize: 26, bold: true, color: NAVY, align: "center" });
    textBox(s, "当前模型只讨论特定BVD与扰动范围内的电学稳定性", 118, 474, 680, 50, { fontSize: 21, color: TEAL, align: "center" });
    notes(s, "文献可以支持CTO结构异质性及负载变化的物理背景，但不能直接给出病变类型到fs、Rm、C0的定量换算。", [path.join(ROOT, "08_结构声场未完成说明", "literature_axisymmetric_reproduction_spec.md"), "本项目文献补齐目录中的CTO、治疗超声和前视超声资料；具体DOI需在最终汇报备注中逐条核对。"]);
  }

  // 14. Conclusion
  {
    const s = slideBase(p, "电学链条已闭环，真实参数、P&O整定和结构声场仍需继续", 14);
    rect(s, 438, 150, 2, 430, LIGHT); rect(s, 850, 150, 2, 430, LIGHT);
    textBox(s, "已经证明", 82, 160, 320, 38, { fontSize: 28, bold: true, color: TEAL, align: "center" });
    textBox(s, "v2.1数量级自洽\nPython/LTspice实现一致\n单因素与组合扰动已完成\n选频与保护原型可复现", 92, 230, 300, 250, { fontSize: 21, color: DARK, align: "center" });
    textBox(s, "尚未证明", 474, 160, 340, 38, { fontSize: 28, bold: true, color: RED, align: "center" });
    textBox(s, "假设参数代表真实换能器\nP_Rm等于声功率\n准稳态时间等于硬件响应\n任何CTO治疗效果", 492, 230, 304, 250, { fontSize: 21, color: DARK, align: "center" });
    textBox(s, "下一阶段", 888, 160, 280, 38, { fontSize: 28, bold: true, color: ORANGE, align: "center" });
    textBox(s, "整定P&O并重新验收\n保留相位控制作消融\n获取实测阻抗并拟合BVD\n建立结构—声场模型", 892, 230, 272, 250, { fontSize: 21, color: DARK, align: "center" });
    rect(s, 104, 550, 1070, 64, NAVY, NAVY, 0, 4);
    textBox(s, "当前结论仅适用于特定假设BVD模型与设定扰动范围", 140, 565, 1000, 36, { fontSize: 24, bold: true, color: WHITE, align: "center" });
    notes(s, "结束时保持本页。用三列明确区分已完成、未证明和下一步，不以泛化结论收尾。", [path.join(ROOT, "FINAL_COMPLETION_AUDIT_2026-08-15.md"), path.join(ROOT, "08_结构声场未完成说明", "README_ANSYS_COMSOL_BLOCKED.md")]);
  }

  // 15. Parameter table backup
  {
    const s = slideBase(p, "备份：v2.1参数均有明确来源类别", 15, true);
    const vals = [
      ["参数", "数值", "单位", "来源类别"],
      ["目标频段", "0.8–1.0", "MHz", "用户约束"],
      ["初始频率", "0.9", "MHz", "用户约束"],
      ["端口电压", "100 / 160上限", "Vpp", "用户约束"],
      ["端口电流", "5 / 6上限", "mA RMS", "仿真假设"],
      ["C₀", "6.858", "pF", "假设基线"],
      ["Rₘ", "7.353", "kΩ", "假设基线"],
      ["Qₘ", "800", "—", "假设基线"],
      ["Lₘ / Cₘ", "1.040 / 0.0301", "H / pF", "反推基线"],
      ["Rₛ", "50", "Ω", "仿真假设"],
    ];
    addSimpleTable(s, vals, 130, 140, 1020, 485, [{ mode: "fr", value: 1.1 }, { mode: "fr", value: 1.3 }, { mode: "fr", value: 0.8 }, { mode: "fr", value: 1.4 }], { fontSize: 18 });
    notes(s, "答疑时用这页回答参数从哪里来。所有数值分成用户约束、假设基线和扫描变量，不能称为实测。", [path.join(ROOT, "01_项目口径与参数", "v2_1_活动基线参数.csv"), path.join(ROOT, "01_项目口径与参数", "v2_1_Qm敏感性参数.csv")]);
  }

  // 16. Disturbance registry
  {
    const s = slideBase(p, "备份：单因素与组合扰动均有编号和复现参数", 16, true);
    textBox(s, "单因素最高档", 88, 140, 500, 34, { fontSize: 25, bold: true, color: NAVY });
    const vals = [["因子", "最高档"], ["C₀", "+30%"], ["Rₘ", "+50%"], ["fₛ", "−5%"], ["Rₛ", "+20%"], ["Lmatch", "+10%"], ["电感Q", "20"]];
    addSimpleTable(s, vals, 88, 188, 420, 360, [{ mode: "fr", value: 1.3 }, { mode: "fr", value: 1 }], { fontSize: 18 });
    textBox(s, "统一扰动序列", 596, 140, 560, 34, { fontSize: 25, bold: true, color: NAVY });
    textBox(s, "Baseline → C₀+30% → Rₘ+50% → fₛ−5%\n→ Lmatch+10% → QL=20 → Combined High → Baseline", 596, 196, 570, 100, { fontSize: 22, bold: true, color: TEAL, align: "center" });
    rect(s, 596, 336, 570, 188, PALE_BLUE, BLUE, 1, 6);
    textBox(s, "0.9 MHz固定点基线\n|Z| ≈ 7.071 kΩ   相位 ≈ −15.916°\nP_Rm ≈ 0.170 W   I_RMS ≈ 5.000 mA\nVport ≈ 100 Vpp", 628, 360, 505, 140, { fontSize: 22, bold: true, color: NAVY, align: "center" });
    notes(s, "用于回答扰动为何这样选、各场景是否可复现，以及基准0.9 MHz各指标。", [path.join(ROOT, "04_扰动与Qm", "stage3_scenario_registry_and_summary.csv"), path.join(ROOT, "06_控制与保护", "stage4_control_timeline.csv")]);
  }

  // 17. Criteria backup
  {
    const s = slideBase(p, "备份：三种选频准则优化的是不同目标函数", 17, true);
    const vals = [
      ["准则", "定义", "优点", "主要风险"],
      ["最大功率", "max P_Rm", "直接对齐控制目标", "需功率估计"],
      ["最小相位", "min |arg(V/I)|", "观测简单", "可能锁到低功率零相位点"],
      ["最小反射", "min Γ代理", "适合匹配评价", "不一定等于运动支路功率最大"],
    ];
    addSimpleTable(s, vals, 86, 154, 1100, 270, [{ mode: "fr", value: 1 }, { mode: "fr", value: 1.2 }, { mode: "fr", value: 1.3 }, { mode: "fr", value: 1.8 }], { fontSize: 18 });
    rect(s, 148, 480, 970, 100, PALE_ORANGE, ORANGE, 1, 6);
    textBox(s, "典型反例：fs−5%时，最大功率点0.8550 MHz，最小绝对相位点0.9045 MHz，差49.5 kHz。", 176, 510, 914, 44, { fontSize: 23, bold: true, color: ORANGE, align: "center" });
    notes(s, "用于回答为什么主控制目标选择最大功率，而相位和反射只作为对照。", [path.join(ROOT, "05_选频准则", "stage3_initial_three_criteria.csv")]);
  }

  // 18. Phase ablation
  {
    const s = slideBase(p, "备份：相位闭环已作为消融保留，但不能替代最大功率准则", 18, true);
    await addImage(s, path.join(SHOTS, "phase_ablation_selected_gain.png"), 72, 132, 760, 500, { fit: "contain", alt: "Phase controller gain ablation" });
    textBox(s, "φ = arg(Vport / Iport)", 880, 158, 280, 40, { fontSize: 26, bold: true, color: NAVY, align: "center" });
    textBox(s, "目标相位\n−1.0782°", 900, 230, 240, 70, { fontSize: 25, bold: true, color: TEAL, align: "center" });
    textBox(s, "方向由局部 dφ/df 决定", 870, 340, 300, 42, { fontSize: 21, bold: true, color: NAVY, align: "center" });
    rect(s, 850, 420, 340, 130, PALE_RED, RED, 1, 6);
    textBox(s, "50与100 Hz/°各出现1个错误锁定段\n|eφ|小，但 P_Rm < 0.95 P*", 872, 448, 296, 74, { fontSize: 17, bold: true, color: RED, align: "center" });
    notes(s, "相位目标不是0度，而是基准受约束最大功率点的相位。局部相位曲线斜率决定更新方向。高增益仍可能错误锁定。", [path.join(ROOT, "06_控制与保护", "phase_gain_sweep_summary.csv"), path.join(SHOTS, "phase_ablation_selected_gain.png")]);
  }

  // 19. LTspice evidence
  {
    const s = slideBase(p, "备份：LTspice GUI、RAW、Log与哈希共同构成运行证据", 19, true);
    await addImage(s, path.join(SHOTS, "LTspice_GUI_waveform_mag_phase.png"), 72, 130, 720, 420, { fit: "contain", alt: "LTspice GUI waveform screenshot" });
    await addImage(s, path.join(SHOTS, "LTspice_SPICE_Error_Log.png"), 830, 138, 350, 180, { fit: "contain", alt: "LTspice Error Log" });
    rect(s, 830, 352, 350, 198, PALE_BLUE, BLUE, 1, 6);
    textBox(s, "证据层级\nGUI截图：运行痕迹\nRAW文件：数值输出\n解析误差：交叉验证\nSHA-256：文件追溯", 860, 374, 290, 150, { fontSize: 21, bold: true, color: NAVY, align: "center" });
    textBox(s, "GUI截图本身不是数值正确性的证明", 330, 585, 620, 34, { fontSize: 20, bold: true, color: RED, align: "center" });
    notes(s, "用于回应‘是否真的运行LTspice’。截图证明运行痕迹，RAW解析与误差CSV才证明结果一致，哈希用于追溯。", [path.join(ROOT, "02_LTspice真实运行"), path.join(ROOT, "SHA256_文件清单.csv"), path.join(SHOTS, "LTspice_GUI_waveform_mag_phase.png")]);
  }

  // 20. Metric definitions
  {
    const s = slideBase(p, "备份：控制器比较采用统一且可复现的指标定义", 20, true);
    const vals = [
      ["指标", "本次定义"],
      ["P*", "该场景约束下离线高分辨率最大P_Rm"],
      ["稳态误差", "最后25% NORMAL控制样本的(1−P/P*)均值"],
      ["恢复时间", "P≥0.98P*并连续保持10个NORMAL控制样本"],
      ["过冲", "相对新场景P*的最大正偏差"],
      ["频率饱和", "频率停留在0.8或1.0 MHz边界的时间"],
      ["错误相位锁定", "相位误差达标但P_Rm<0.95P*"],
    ];
    addSimpleTable(s, vals, 92, 142, 1090, 420, [{ mode: "fr", value: 1.1 }, { mode: "fr", value: 3.4 }], { fontSize: 18 });
    textBox(s, "130 Vpp/5.5 mA为软触发；160 Vpp/6 mA为硬限。均为本次仿真假设，待实测确认。", 118, 596, 1040, 42, { fontSize: 19, bold: true, color: RED, align: "center" });
    notes(s, "用于回答恢复时间、稳态误差和错误锁定如何定义。强调所有策略用相同定义。", [path.join(ROOT, "01_项目口径与参数", "03_Codex任务说明_修订版_v2_1.md"), path.join(ROOT, "06_控制与保护", "stage4_5_control_report.md")]);
  }

  // 21. Reproducibility
  {
    const s = slideBase(p, "备份：每张图都能追溯到参数、脚本和原始输出", 21, true);
    for (const x of [260, 486, 712, 938]) arrow(s, x, 270, 54, 28, LIGHT);
    node(s, 82, 220, 180, 120, "参数CSV\n场景注册表", PALE_BLUE, BLUE);
    node(s, 314, 220, 180, 120, "Python脚本\nLTspice .cir", PALE_TEAL, TEAL);
    node(s, 540, 220, 180, 120, ".raw / .log\n控制时序CSV", WHITE, LIGHT);
    node(s, 766, 220, 180, 120, "汇总CSV\n指标表", PALE_ORANGE, ORANGE);
    node(s, 992, 220, 180, 120, "PNG/PDF/SVG\nPPT图表", PALE_RED, RED);
    textBox(s, "README_汇报工作痕迹索引.md", 250, 420, 780, 40, { fontSize: 24, bold: true, color: NAVY, align: "center" });
    textBox(s, "SHA256_文件清单.csv", 388, 486, 510, 40, { fontSize: 24, bold: true, color: TEAL, align: "center" });
    textBox(s, "图表不是孤立截图，而是可重新运行的产物", 266, 560, 760, 44, { fontSize: 25, bold: true, color: ORANGE, align: "center" });
    notes(s, "用于回答复现性和文件组织。展示从参数到图表的完整链条。", [path.join(ROOT, "README_汇报工作痕迹索引.md"), path.join(ROOT, "SHA256_文件清单.csv"), path.join(ROOT, "09_复现脚本")]);
  }

  // 22. Structural acoustic gap
  {
    const s = slideBase(p, "备份：结构—声场结果尚未完成，当前只能给出输入与验收清单", 22, true);
    const leftItems = ["几何尺寸与完整模型树", "压电材料矩阵与极化方向", "电极、机械、耦合面和PML", "粗/中/细三档网格", "模态频率与关键模态形状"];
    const rightItems = ["端口阻抗/导纳曲线", "位移幅值与相位", "声压云图与轴向曲线", "网格收敛表", "Solver Log正常结束页面"];
    textBox(s, "建模输入", 124, 150, 430, 38, { fontSize: 27, bold: true, color: NAVY, align: "center" });
    textBox(s, leftItems.map(x => `• ${x}`).join("\n\n"), 116, 214, 450, 340, { fontSize: 21, color: DARK });
    rect(s, 630, 142, 2, 440, LIGHT);
    textBox(s, "必须保留的结果证据", 700, 150, 430, 38, { fontSize: 27, bold: true, color: NAVY, align: "center" });
    textBox(s, rightItems.map(x => `• ${x}`).join("\n\n"), 692, 214, 460, 340, { fontSize: 21, color: DARK });
    rect(s, 164, 590, 950, 50, PALE_RED, RED, 1, 6);
    textBox(s, "当前没有真实ANSYS/COMSOL截图，不得生成伪造云图填充汇报", 198, 600, 880, 32, { fontSize: 22, bold: true, color: RED, align: "center" });
    notes(s, "这页用于坦诚说明结构声场尚未完成，并列出下一阶段需要自己从ANSYS/COMSOL截图保存的证据。", [path.join(ROOT, "08_结构声场未完成说明", "GUI_evidence_capture_checklist.md"), path.join(ROOT, "08_结构声场未完成说明", "solver_input_requirements.csv"), path.join(ROOT, "08_结构声场未完成说明", "README_ANSYS_COMSOL_BLOCKED.md")]);
  }

  // Export previews and deck.
  for (const [i, slide] of p.slides.items.entries()) {
    const stem = `slide-${String(i + 1).padStart(2, "0")}`;
    const png = await p.export({ slide, format: "png", scale: 1 });
    await fs.writeFile(path.join(PREVIEWS, `${stem}.png`), new Uint8Array(await png.arrayBuffer()));
    const layout = await slide.export({ format: "layout" });
    await fs.writeFile(path.join(PREVIEWS, `${stem}.layout.json`), await layout.text());
  }
  const montage = await p.export({ format: "webp", montage: true, scale: 0.7 });
  await fs.writeFile(path.join(BUILD, "deck-montage.webp"), new Uint8Array(await montage.arrayBuffer()));
  const pptx = await PresentationFile.exportPptx(p);
  await pptx.save(OUT);
  console.log(`WROTE ${OUT}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
