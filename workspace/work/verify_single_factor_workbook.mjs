import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\single_factor_disturbance_results\\单因素扰动_审核工作簿.xlsx";
const previewDir = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\work\\workbook_verify_previews";
await fs.mkdir(previewDir, { recursive: true });

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const sheetInfo = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 4000,
});
console.log("SHEETS");
console.log(sheetInfo.ndjson);

const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 7000,
  tableMaxRows: 5,
  tableMaxCols: 8,
  tableMaxCellChars: 80,
});
console.log("OVERVIEW");
console.log(overview.ndjson);

const errorScan = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "formula/value error scan",
  maxChars: 4000,
});
console.log("ERROR_SCAN");
console.log(errorScan.ndjson);

const sheetsToRender = ["说明", "趋势表", "固定0p9MHz", "特征汇总", "交叉验证"];
for (const sheetName of sheetsToRender) {
  const rendered = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const bytes = new Uint8Array(await rendered.arrayBuffer());
  await fs.writeFile(path.join(previewDir, `${sheetName}.png`), bytes);
  console.log(`RENDERED ${sheetName} ${bytes.length}`);
}
