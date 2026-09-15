import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outDir = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\third_step_sweep_selection";
const previewDir = path.join(outDir, "workbook_previews");
await fs.mkdir(previewDir, { recursive: true });

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === '"') {
      if (inQuotes && next === '"') {
        cell += '"';
        i++;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (ch === "," && !inQuotes) {
      row.push(cell);
      cell = "";
    } else if ((ch === "\n" || ch === "\r") && !inQuotes) {
      if (ch === "\r" && next === "\n") i++;
      row.push(cell);
      if (row.some((v) => v !== "")) rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    if (row.some((v) => v !== "")) rows.push(row);
  }
  return rows;
}

function convertValue(v) {
  if (v === "") return null;
  if (/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(v)) {
    return Number(v);
  }
  return v;
}

async function readCsvMatrix(filename) {
  const text = await fs.readFile(path.join(outDir, filename), "utf8");
  const clean = text.replace(/^\uFEFF/, "");
  return parseCsv(clean).map((r) => r.map(convertValue));
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

function applyTableStyle(sheet, rows, cols, tableName) {
  const addr = rangeAddress(rows, cols);
  const used = sheet.getRange(addr);
  used.values; // touch for facade consistency
  sheet.tables.add(addr, true, tableName);
  sheet.getRange(`A1:${colName(cols)}1`).format = {
    fill: "#174A7C",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  used.format.borders = { preset: "outside", style: "thin", color: "#B7C9D9" };
  used.format.wrapText = true;
  used.format.autofitColumns();
  used.format.autofitRows();
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
}

function setWidths(sheet, cols) {
  for (let c = 0; c < cols; c++) {
    const letter = colName(c + 1);
    let width = 18;
    if (c === 0) width = 30;
    if (c === 2) width = 24;
    if (c === 5) width = 38;
    if (c >= 10) width = 22;
    sheet.getRange(`${letter}:${letter}`).format.columnWidth = width;
  }
}

function writeMatrixSheet(workbook, sheetName, matrix, tableName) {
  const sheet = workbook.worksheets.add(sheetName);
  sheet.getRange(rangeAddress(matrix.length, matrix[0].length)).values = matrix;
  applyTableStyle(sheet, matrix.length, matrix[0].length, tableName);
  setWidths(sheet, matrix[0].length);
  return sheet;
}

const comparison = await readCsvMatrix("第三步_初始0p84-0p96MHz_三准则频率对比.csv");
const selectedMetrics = await readCsvMatrix("第三步_初始扫频_候选点完整指标.csv");
const tradeSummary = await readCsvMatrix("第三步_步长窗口权衡汇总.csv");
const tradeoff = await readCsvMatrix("第三步_步长窗口逐场景误差.csv");
const registry = await readCsvMatrix("第三步_场景参数登记.csv");

const compHeaders = comparison[0];
const compRows = comparison.slice(1);
function get(row, header) {
  return row[compHeaders.indexOf(header)];
}
const baseline = compRows.find((r) => get(r, "case_id") === "CASE_000_BASELINE");
const high = compRows.find((r) => get(r, "case_id") === "CASE_402_COMBINED_HIGH");

const workbook = Workbook.create();

const summary = workbook.worksheets.add("说明与结论");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["第三步：三种扫频选点准则比较"]];
summary.getRange("A1").format = {
  fill: "#0F2F4F",
  font: { bold: true, color: "#FFFFFF", size: 16 },
};

const summaryRows = [
  ["项目", "结论"],
  ["模型边界", "当前虚拟BVD电学模型；不是实测换能器、声功率或CTO临床结论"],
  ["场景范围", "第二步21个单因素场景 + 组合扰动low/medium/high，共24个场景"],
  ["初始扫频", "0.84–0.96 MHz，步长0.5 kHz，共241点"],
  ["三种准则", "最大有功功率；最小绝对相位/相位零点；最小反射代理"],
  ["基准三点", `最大功率 ${get(baseline, "最大功率频率_MHz").toFixed(6)} MHz；最小相位 ${get(baseline, "最小绝对相位频率_MHz").toFixed(6)} MHz；最小反射 ${get(baseline, "最小反射频率_MHz").toFixed(6)} MHz`],
  ["高复杂度三点", `最大功率 ${get(high, "最大功率频率_MHz").toFixed(6)} MHz；最小相位 ${get(high, "最小绝对相位频率_MHz").toFixed(6)} MHz；最小反射 ${get(high, "最小反射频率_MHz").toFixed(6)} MHz`],
  ["关键判断", "高复杂度下功率准则与相位/反射准则分裂约37.6 kHz，不能假定相位零点就是功率最大点"],
  ["窗口建议", "若要覆盖全部场景，用±100 kHz；±50 kHz会漏掉Cp −10%边界相位点；±20 kHz不适合通用扫频"],
  ["步长建议", "0.5 kHz适合报告级离线扫频；1–2 kHz仅建议粗扫后局部细扫；0.1 kHz用于复核"],
];
summary.getRange(`A3:B${summaryRows.length + 2}`).values = summaryRows;
summary.getRange("A3:B3").format = {
  fill: "#174A7C",
  font: { bold: true, color: "#FFFFFF" },
};
summary.getRange(`A3:B${summaryRows.length + 2}`).format.borders = {
  preset: "all",
  style: "thin",
  color: "#D5E0EA",
};
summary.getRange(`A3:B${summaryRows.length + 2}`).format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 20;
summary.getRange("B:B").format.columnWidth = 100;
summary.getRange(`A3:A${summaryRows.length + 2}`).format = {
  fill: "#EAF2F8",
  font: { bold: true },
};

writeMatrixSheet(workbook, "初始三准则频率", comparison, "InitialCriteriaTable");
writeMatrixSheet(workbook, "候选点完整指标", selectedMetrics, "CandidateMetricsTable");
writeMatrixSheet(workbook, "步长窗口汇总", tradeSummary, "StepWindowSummaryTable");
writeMatrixSheet(workbook, "步长窗口逐场景", tradeoff, "StepWindowScenarioTable");
writeMatrixSheet(workbook, "场景参数登记", registry, "ScenarioRegistryTable");

// Apply numeric formats for readability.
for (const sheetName of ["初始三准则频率", "候选点完整指标", "步长窗口汇总", "步长窗口逐场景", "场景参数登记"]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  const used = sheet.getUsedRange();
  used.format.font = { name: "Microsoft YaHei", size: 10 };
}
summary.getUsedRange().format.font = { name: "Microsoft YaHei", size: 10 };
summary.getRange("A1").format.font = { name: "Microsoft YaHei", bold: true, color: "#FFFFFF", size: 16 };

// Compact visual QA renders.
for (const sheetName of ["说明与结论", "初始三准则频率", "步长窗口汇总", "候选点完整指标"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 6000,
  tableMaxRows: 4,
  tableMaxCols: 8,
});
console.log("OVERVIEW");
console.log(overview.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final workbook error scan",
  maxChars: 2000,
});
console.log("ERROR_SCAN");
console.log(errors.ndjson);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(path.join(outDir, "第三步_扫频选点准则_审核工作簿.xlsx"));
console.log(path.join(outDir, "第三步_扫频选点准则_审核工作簿.xlsx"));
