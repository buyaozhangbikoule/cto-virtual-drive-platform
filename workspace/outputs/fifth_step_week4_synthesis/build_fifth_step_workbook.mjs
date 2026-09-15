import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outDir = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\fifth_step_week4_synthesis";
const previewDir = path.join(outDir, "workbook_previews");
await fs.mkdir(previewDir, { recursive: true });

function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", inQuotes = false;
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
function convert(v) {
  if (v === "") return null;
  if (/^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/.test(v)) return Number(v);
  return v;
}
async function matrix(name) {
  const text = await fs.readFile(path.join(outDir, name), "utf8");
  return parseCsv(text.replace(/^\uFEFF/, "")).map(r => r.map(convert));
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
function addr(rows, cols) { return `A1:${colName(cols)}${rows}`; }
function addSheet(wb, name, mat, tableName) {
  const sh = wb.worksheets.add(name);
  sh.getRange(addr(mat.length, mat[0].length)).values = mat;
  sh.tables.add(addr(mat.length, mat[0].length), true, tableName);
  sh.getRange(`A1:${colName(mat[0].length)}1`).format = {
    fill: "#174A7C",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
  };
  const used = sh.getRange(addr(mat.length, mat[0].length));
  used.format = {
    font: { name: "Microsoft YaHei", size: 10 },
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#B7C9D9" },
  };
  used.format.autofitColumns();
  used.format.autofitRows();
  sh.freezePanes.freezeRows(1);
  sh.showGridLines = false;
  for (let c = 1; c <= mat[0].length; c++) {
    const letter = colName(c);
    let width = 18;
    if (c === 1) width = 24;
    if (c >= 18) width = 28;
    sh.getRange(`${letter}:${letter}`).format.columnWidth = width;
  }
  return sh;
}

const synth = await matrix("第五步_第4周综合比较表.csv");
const wrong = await matrix("第五步_错误锁定明细.csv");
const prereq = await matrix("第五步_单因素扫描前置验收表.csv");
const gains = await matrix("第五步_相位增益扫描复核表.csv");

const wb = Workbook.create();
const summary = wb.worksheets.add("说明与结论");
summary.showGridLines = false;
summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["第五步：第4周综合比较"]];
summary.getRange("A1").format = {
  fill: "#0F2F4F",
  font: { name: "Microsoft YaHei", bold: true, color: "#FFFFFF", size: 16 },
};

const headers = synth[0];
const rows = synth.slice(1);
function idx(h) { return headers.indexOf(h); }
const scan = rows.find(r => r[idx("策略")] === "周期性局部扫频");
const phase = rows.find(r => r[idx("策略")] === "相位误差离散跟踪");
const fixed = rows.find(r => r[idx("策略")] === "固定频率固定幅度");

const summaryRows = [
  ["项目", "结论"],
  ["前置任务", "C0、Rm、fs、Rs/匹配参数、ESR 的单因素三等级扫描已经完成；本工作簿引用第二步结果作为前置验收"],
  ["综合对象", "三种策略经历完全相同扰动序列：基准→20个单因素→3个组合→恢复基准"],
  ["固定频率", `平均功率恢复 ${fixed[idx("平均功率恢复_pct")]}%；无振荡，但对漂移/失配恢复不足`],
  ["周期扫频", `平均功率恢复 ${scan[idx("平均功率恢复_pct")]}%；无错误锁定；当前综合最优，但有扫频开销`],
  ["相位跟踪", `平均功率恢复 ${phase[idx("平均功率恢复_pct")]}%；错误锁定状态数 ${phase[idx("错误锁定状态数")]}；不能单独作为功率最大化控制`],
  ["判据", "错误锁定：稳态|phase|≤2°且功率恢复<80%或偏离最大功率频率≥10 kHz"],
  ["建议", "第4周报告采用周期性局部扫频作为当前最佳策略；下一轮加入“功率点扫频+约束限幅”"],
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
summary.getRange("B:B").format.columnWidth = 115;

addSheet(wb, "综合比较表", synth, "Week4SynthesisTable");
addSheet(wb, "错误锁定明细", wrong, "WrongLockTable");
addSheet(wb, "单因素前置验收", prereq, "SingleFactorPrereqTable");
addSheet(wb, "相位增益扫描", gains, "PhaseGainCheckTable");

for (const sheetName of ["说明与结论", "综合比较表", "错误锁定明细", "单因素前置验收"]) {
  const preview = await wb.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const overview = await wb.inspect({
  kind: "workbook,sheet,table",
  maxChars: 5000,
  tableMaxRows: 5,
  tableMaxCols: 8,
});
console.log("OVERVIEW");
console.log(overview.ndjson);
const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
  maxChars: 2000,
});
console.log("ERROR_SCAN");
console.log(errors.ndjson);
const output = await SpreadsheetFile.exportXlsx(wb);
const outPath = path.join(outDir, "第五步_第4周综合比较_审核工作簿.xlsx");
await output.save(outPath);
console.log(outPath);
