import { PresentationFile, FileBlob } from "@oai/artifact-tool";

const source = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_edit_slide11_20260828/source_deck.pptx";
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
for (const query of ["delete shape", "remove element", "shape collection", "scatter chart", "chart series markers", "z order", "shape position", "chart position", "text style line spacing"]) {
  const result = presentation.help("*", { search: query, include: ["index", "examples", "notes"], maxChars: 8000 });
  console.log(`===== ${query} =====`);
  console.log(result);
}
