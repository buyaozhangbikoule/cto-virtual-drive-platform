import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\third_step_sweep_selection\\第三步_扫频选点准则_审核工作簿.xlsx";
const previewDir = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\third_step_sweep_selection\\final_verify_previews";
await fs.mkdir(previewDir, { recursive: true });

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 5000,
  tableMaxRows: 4,
  tableMaxCols: 8,
});
console.log("OVERVIEW");
console.log(overview.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final imported workbook error scan",
  maxChars: 2000,
});
console.log("ERROR_SCAN");
console.log(errors.ndjson);

for (const sheetName of ["说明与结论", "初始三准则频率", "步长窗口汇总"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), new Uint8Array(await preview.arrayBuffer()));
  console.log(`RENDERED ${sheetName}`);
}
