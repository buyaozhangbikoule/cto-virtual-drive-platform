import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const sourcePptx = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx';
const csvPath = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/stage2_matching/stage2_LTspice逐频数据.csv';
const outDir = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_slide5_matching_revision_2026-08-26/final';
const outputPptx = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/第5页_匹配输入阻抗局部放大与0.9MHz数值表_修订版.pptx';

await fs.mkdir(outDir, { recursive: true });

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const headers = lines[0].split(',');
  return lines.slice(1).map((line) => {
    const cols = line.split(',');
    return Object.fromEntries(headers.map((h, i) => [h, cols[i]]));
  });
}

const rows = parseCsv(await fs.readFile(csvPath, 'utf8'));
const seriesRows = {};
for (const scenario of ['BEFORE', 'IDEAL', 'ACTIVE_LOSSY']) {
  seriesRows[scenario] = rows
    .filter((r) => r.scenario === scenario && Number(r.frequency_Hz) >= 880000 && Number(r.frequency_Hz) <= 920000)
    .filter((_, i) => i % 5 === 0)
    .map((r) => ({
      fMHz: Number(r.frequency_Hz) / 1e6,
      absZ: Number(r.zin_abs_ohm),
      phase: Number(r.zin_phase_deg),
    }));
}

const p = await PresentationFile.importPptx(await FileBlob.load(sourcePptx));
const slide = p.slides.getItem(4);
for (const s of [...p.slides.items]) {
  if (s.id !== slide.id) s.delete();
}

p.resolve('sh/ahkvi1cb').text = '0.9 MHz处：理想匹配接近50 Ω，有损匹配保留小量失配';
p.resolve('im/srmx0vmd').delete();
p.resolve('im/jmdw3qlg').delete();

const panel = p.resolve('sh/n6dcr65o');
panel.position = { left: 818, top: 126, width: 390, height: 418 };

const condition = p.resolve('sh/m5kbi1oj');
condition.text = '0.9 MHz固定频点\n同一1 Vrms Thevenin源｜Rs=50 Ω';
condition.position = { left: 838, top: 142, width: 350, height: 58 };

const callout = p.resolve('sh/w32dkbuh');
callout.text = '有损：56.70 Ω ∠−1.08°';
callout.position = { left: 840, top: 494, width: 340, height: 34 };

const conclusion = p.resolve('sh/x4vedgvm');
conclusion.text = '理想匹配≈50 Ω纯电阻；考虑ESR后为56.686−j1.067 Ω｜完整0.8–1.0 MHz曲线见备份页';
conclusion.position = { left: 100, top: 634, width: 1080, height: 28 };

const blue = '#2F75B5';
const orange = '#ED7D31';
const gray = '#808080';
const grid = '#D9E1E8';
const text = '#18324D';

const ideal = seriesRows.IDEAL;
const lossy = seriesRows.ACTIVE_LOSSY;
const before = seriesRows.BEFORE;

slide.charts.add('scatter', {
  name: 'zin-magnitude-local',
  position: { left: 72, top: 126, width: 720, height: 224 },
  title: '匹配后输入阻抗幅值（匹配前量级见右表）',
  titlePlacement: 'aboveChart',
  titleTextStyle: { fontSize: 18, bold: true, fill: text },
  series: [
    { name: '理想匹配', xValues: ideal.map(d => d.fMHz), values: ideal.map(d => d.absZ), line: { style: 'solid', fill: blue, width: 2.5 }, marker: { symbol: 'none' } },
    { name: '有损匹配', xValues: lossy.map(d => d.fMHz), values: lossy.map(d => d.absZ), line: { style: 'solid', fill: orange, width: 2.5 }, marker: { symbol: 'none' } },
    { name: '0.9 MHz', xValues: [0.9, 0.9], values: [0, 65], line: { style: 'dashed', fill: gray, width: 1.5 }, marker: { symbol: 'none' } },
  ],
  scatterOptions: { style: 'line' },
  hasLegend: true,
  legend: { position: 'top', overlay: false, textStyle: { fontSize: 14, fill: text } },
  xAxis: { min: 0.88, max: 0.92, majorUnit: 0.01, numberFormatCode: '0.000', textStyle: { fontSize: 14, fill: text }, majorGridlines: { style: 'solid', fill: grid, width: 1 } },
  yAxis: { min: 0, max: 65, majorUnit: 10, title: { text: '|Zin| (Ω)', textStyle: { fontSize: 15, fill: text } }, textStyle: { fontSize: 14, fill: text }, majorGridlines: { style: 'solid', fill: grid, width: 1 } },
  chartFill: '#FFFFFF',
  plotAreaFill: '#FFFFFF',
  chartLine: { style: 'solid', fill: '#C9D3DC', width: 1 },
  plotAreaLine: { style: 'solid', fill: '#C9D3DC', width: 1 },
});

slide.charts.add('scatter', {
  name: 'zin-phase-local',
  position: { left: 72, top: 366, width: 720, height: 242 },
  title: '输入阻抗相位',
  titlePlacement: 'aboveChart',
  titleTextStyle: { fontSize: 18, bold: true, fill: text },
  series: [
    { name: '匹配前', xValues: before.map(d => d.fMHz), values: before.map(d => d.phase), line: { style: 'solid', fill: gray, width: 2 }, marker: { symbol: 'none' } },
    { name: '理想匹配', xValues: ideal.map(d => d.fMHz), values: ideal.map(d => d.phase), line: { style: 'solid', fill: blue, width: 2.5 }, marker: { symbol: 'none' } },
    { name: '有损匹配', xValues: lossy.map(d => d.fMHz), values: lossy.map(d => d.phase), line: { style: 'solid', fill: orange, width: 2.5 }, marker: { symbol: 'none' } },
    { name: '0.9 MHz', xValues: [0.9, 0.9], values: [-100, 100], line: { style: 'dashed', fill: gray, width: 1.5 }, marker: { symbol: 'none' } },
  ],
  scatterOptions: { style: 'line' },
  hasLegend: true,
  legend: { position: 'top', overlay: false, textStyle: { fontSize: 14, fill: text } },
  xAxis: { min: 0.88, max: 0.92, majorUnit: 0.01, numberFormatCode: '0.000', title: { text: 'Frequency (MHz)', textStyle: { fontSize: 15, fill: text } }, textStyle: { fontSize: 14, fill: text }, majorGridlines: { style: 'solid', fill: grid, width: 1 } },
  yAxis: { min: -100, max: 100, majorUnit: 50, title: { text: 'Phase (°)', textStyle: { fontSize: 15, fill: text } }, textStyle: { fontSize: 14, fill: text }, majorGridlines: { style: 'solid', fill: grid, width: 1 } },
  chartFill: '#FFFFFF',
  plotAreaFill: '#FFFFFF',
  chartLine: { style: 'solid', fill: '#C9D3DC', width: 1 },
  plotAreaLine: { style: 'solid', fill: '#C9D3DC', width: 1 },
});

const table = slide.tables.add({
  rows: 5,
  columns: 4,
  left: 830,
  top: 207,
  width: 366,
  height: 270,
  columnWidths: [78, 92, 92, 104],
  values: [
    ['指标', '匹配前', '理想匹配', '有损匹配'],
    ['|Z| / Ω', '7071.1', '50.000', '56.696'],
    ['ReZ / Ω', '6800.0', '50.000', '56.686'],
    ['ImZ / Ω', '−1939.1', '≈0', '−1.067'],
    ['相位 / °', '−15.916', '≈0', '−1.078'],
  ],
});
table.borders.assign({ style: 'solid', fill: '#B8C6D1', width: 1 });
table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 4 }).assign({
  fill: '#18324D',
  textStyle: { fontSize: 14, bold: true, color: '#FFFFFF', alignment: 'center' },
  anchor: 'middle',
});
table.cells.block({ row: 1, column: 0, rowCount: 4, columnCount: 1 }).assign({
  fill: '#EAF2F5',
  textStyle: { fontSize: 14, bold: true, color: text, alignment: 'center' },
  anchor: 'middle',
});
table.cells.block({ row: 1, column: 1, rowCount: 4, columnCount: 3 }).assign({
  fill: '#FFFFFF',
  textStyle: { fontSize: 14, color: text, alignment: 'center' },
  anchor: 'middle',
});

slide.speakerNotes.textFrame.setText([
  '讲述顺序：先看右表的0.9 MHz固定频点，再看左上匹配后|Zin|局部曲线，最后看左下相位变化。',
  '比较条件：同一个1 Vrms RMS戴维南源和50 Ω源阻抗；换能器BVD参数相同。',
  '0.9 MHz结果：匹配前Zin=6800.001−j1939.072 Ω；理想匹配Zin≈50−j0 Ω；有损匹配Zin=56.686−j1.067 Ω。',
  '理想网络同时接近50 Ω和0°。有损网络由于电感Q=100、电容Q=1000，并且优化目标是最大化P_Rm而不是强制Γ=0，因此保留小量失配。',
  '左上图不画匹配前曲线，是因为匹配前|Z|在局部窗口内约6.8 kΩ至96.8 kΩ，若与0–65 Ω的匹配后曲线共用线性坐标，匹配后曲线将不可读；匹配前数值已保留在右表。',
  '结论边界：结果来自假设BVD参数和线性AC模型，不是实测换能器参数。',
  '',
  '[Sources]',
  '- C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\v2_self_consistent_rebuild\\stage2_matching\\stage2_LTspice逐频数据.csv',
  '- C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\v2_self_consistent_rebuild\\stage2_matching\\stage2_匹配前后特征汇总.csv',
  '- C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\v2_self_consistent_rebuild\\stage2_matching\\stage2_匹配设计参数.json'
].join('\n'));
slide.speakerNotes.setVisible(true);

const preview = await slide.export({ format: 'png', scale: 2 });
await fs.writeFile(`${outDir}/slide5-matching-revised.png`, new Uint8Array(await preview.arrayBuffer()));
const layout = await slide.export({ format: 'layout' });
await fs.writeFile(`${outDir}/slide5-matching-revised.layout.json`, await layout.text(), 'utf8');
const inspect = await p.inspect({ kind: 'slide,textbox,shape,image,table,chart,notes,layout', maxChars: 50000 });
await fs.writeFile(`${outDir}/final-inspect.ndjson`, inspect.ndjson, 'utf8');

const pptx = await PresentationFile.exportPptx(p);
await pptx.save(outputPptx);
console.log(outputPptx);
