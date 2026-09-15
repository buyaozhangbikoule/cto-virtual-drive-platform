import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outDir = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\fourth_step_control_strategies";
const previewDir = path.join(outDir, "workbook_previews");
await fs.mkdir(previewDir, { recursive: true });

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i], next = text[i + 1];
    if (ch === '"') {
      if (inQuotes && next === '"') { cell += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      row.push(cell); cell = "";
    } else if ((ch === "\n" || ch === "\r") && !inQuotes) {
      if (ch === "\r" && next === "\n") i++;
      row.push(cell);
      if (row.some(v => v !== "")) rows.push(row);
      row = []; cell = "";
    } else cell += ch;
  }
  if (cell.length || row.length) {
    row.push(cell);
    if (row.some(v => v !== "")) rows.push(row);
  }
  return rows;
}

function convertValue(v) {
  if (v === "") return null;
  if (/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(v)) return Number(v);
  return v;
}

async function csvMatrix(name) {
  const text = await fs.readFile(path.join(outDir, name), "utf8");
  return parseCsv(text.replace(/^\uFEFF/, "")).map(r => r.map(convertValue));
}

function colName(n) {
  let s = "";
  while (n > 0) {
    const m = (n - 1) % 26;
    s = String.fromCharCode(65 + m) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function rangeAddress(rows, cols) {
  return `A1:${colName(cols)}${rows}`;
}

function sheetTable(workbook, name, matrix, tableName) {
  const sheet = workbook.worksheets.add(name);
  sheet.getRange(rangeAddress(matrix.length, matrix[0].length)).values = matrix;
  const used = sheet.getRange(rangeAddress(matrix.length, matrix[0].length));
  sheet.tables.add(rangeAddress(matrix.length, matrix[0].length), true, tableName);
  sheet.getRange(`A1:${colName(matrix[0].length)}1`).format = {
    fill: "#174A7C",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  used.format.borders = { preset: "outside", style: "thin", color: "#B7C9D9" };
  used.format.wrapText = true;
  used.format.font = { name: "Microsoft YaHei", size: 10 };
  used.format.autofitColumns();
  used.format.autofitRows();
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  for (let c = 1; c <= matrix[0].length; c++) {
    const letter = colName(c);
    let width = 16;
    if (c <= 6) width = 22;
    if (c === 7 || c === 8) width = 30;
    if (c > 10) width = 18;
    sheet.getRange(`${letter}:${letter}`).format.columnWidth = width;
  }
  return sheet;
}

const overview = await csvMatrix("第四步_三策略总览.csv");
const gains = await csvMatrix("第四步_相位跟踪增益扫描.csv");
const stateMetrics = await csvMatrix("第四步_逐状态收敛与振荡指标.csv");
const timeseries = await csvMatrix("第四步_控制时序明细.csv");
const response = await csvMatrix("第四步_LTspice响应表_场景特征.csv");

const wb = Workbook.create();
const summary = wb.worksheets.add("说明与结论");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["第四步：三种控制策略正式比较"]];
summary.getRange("A1").format = {
  fill: "#0F2F4F",
  font: { name: "Microsoft YaHei", bold: true, color: "#FFFFFF", size: 16 },
};

const headers = overview[0];
function idx(h) { return headers.indexOf(h); }
const rows = overview.slice(1);
const rowByStrategy = Object.fromEntries(rows.map(r => [r[idx("控制策略")], r]));
const fixed = rowByStrategy["固定频率固定幅度"];
const scan = rowByStrategy["周期性局部扫频"];
const phase = rowByStrategy["相位误差离散跟踪"];

const summaryRows = [
  ["项目", "结论"],
  ["LTspice验收", "24个case均重新调用 LTspice 26.0.2 批处理生成 RAW；控制仿真从 RAW 响应表查表/插值"],
  ["扰动序列", "基准 → 20个单因素扰动 → 3个组合扰动 → 恢复基准；每状态20步，共500步"],
  ["统一口径", "频率0.84–0.96 MHz；BVD端总峰值电流=abs(I(Rmot)+I(Cstatic))*sqrt(2)"],
  ["固定频率固定幅度", `平均功率恢复 ${fixed[idx("平均功率恢复_pct")].toFixed(2)}%；最差 ${fixed[idx("最差瞬时功率恢复_pct")].toFixed(2)}%；硬电压触发 ${fixed[idx("硬电压约束触发次数")]} 次`],
  ["周期性局部扫频", `平均功率恢复 ${scan[idx("平均功率恢复_pct")].toFixed(2)}%；最差 ${scan[idx("最差瞬时功率恢复_pct")].toFixed(2)}%；控制开销 ${scan[idx("总扫频测点数_控制开销代理")]} 个测点`],
  ["相位误差离散跟踪", `平均功率恢复 ${phase[idx("平均功率恢复_pct")].toFixed(2)}%；平均稳态相位误差 ${phase[idx("平均稳态相位误差_deg")].toFixed(2)}°；硬电压触发 ${phase[idx("硬电压约束触发次数")]} 次`],
  ["关键判断", "相位跟踪能压小相位误差，但不等价于功率最大化；周期性局部扫频在本扰动序列下功率恢复最好"],
  ["后续建议", "加入第四种策略：扫频选功率点 + 电压/电流约束限幅，才更接近安全可落地控制"],
];
summary.getRange(`A3:B${summaryRows.length + 2}`).values = summaryRows;
summary.getRange("A3:B3").format = { fill: "#174A7C", font: { bold: true, color: "#FFFFFF" } };
summary.getRange(`A3:B${summaryRows.length + 2}`).format = {
  font: { name: "Microsoft YaHei", size: 10 },
  wrapText: true,
  borders: { preset: "all", style: "thin", color: "#D5E0EA" },
};
summary.getRange(`A4:A${summaryRows.length + 2}`).format = { fill: "#EAF2F8", font: { bold: true } };
summary.getRange("A:A").format.columnWidth = 24;
summary.getRange("B:B").format.columnWidth = 110;

sheetTable(wb, "三策略总览", overview, "StrategyOverviewTable");
sheetTable(wb, "相位增益扫描", gains, "PhaseGainTable");
sheetTable(wb, "逐状态指标", stateMetrics, "StateMetricsTable");
sheetTable(wb, "控制时序明细", timeseries, "TimeseriesTable");
sheetTable(wb, "LTspice响应特征", response, "ResponseFeatureTable");

for (const sheetName of ["说明与结论", "三策略总览", "相位增益扫描", "逐状态指标", "LTspice响应特征"]) {
  const preview = await wb.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const inspect = await wb.inspect({
  kind: "workbook,sheet,table",
  maxChars: 6000,
  tableMaxRows: 5,
  tableMaxCols: 8,
});
console.log("OVERVIEW");
console.log(inspect.ndjson);

const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final workbook error scan",
  maxChars: 3000,
});
console.log("ERROR_SCAN");
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(wb);
const outPath = path.join(outDir, "第四步_三种控制策略_审核工作簿.xlsx");
await output.save(outPath);
console.log(outPath);
