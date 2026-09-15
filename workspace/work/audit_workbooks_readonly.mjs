import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const files = [
  "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\single_factor_disturbance_results\\单因素扰动_审核工作簿.xlsx",
  "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\third_step_sweep_selection\\第三步_扫频选点准则_审核工作簿.xlsx",
  "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\fourth_step_control_strategies\\第四步_三种控制策略_审核工作簿.xlsx",
  "C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\fifth_step_week4_synthesis\\第五步_第4周综合比较_审核工作簿.xlsx",
];

for (const file of files) {
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
  const sheets = await workbook.inspect({ kind: "sheet", include: "id,name", maxChars: 5000 });
  const formulas = await workbook.inspect({
    kind: "formula",
    options: { maxResults: 200 },
    maxChars: 12000,
  });
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    maxChars: 3000,
  });
  console.log(JSON.stringify({ file, sheets: sheets.ndjson, formulas: formulas.ndjson, errors: errors.ndjson }));
}
