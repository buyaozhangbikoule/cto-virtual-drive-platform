import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import fs from "node:fs/promises";

const workbookPath = "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\fourth_step_control_strategies\\第四步_三种控制策略_审核工作簿.xlsx";
const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 5000,
  tableMaxRows: 4,
  tableMaxCols: 8,
});
console.log(overview.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "post-export error scan",
  maxChars: 2000,
});
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "三策略总览", autoCrop: "all", scale: 1, format: "png" });
await fs.writeFile("C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\fourth_step_control_strategies\\post_export_verify_三策略总览.png", new Uint8Array(await preview.arrayBuffer()));
