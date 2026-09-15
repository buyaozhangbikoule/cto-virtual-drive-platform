import fs from "node:fs/promises";
import { PresentationFile, FileBlob } from "@oai/artifact-tool";

const source = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_edit_slide11_20260828/source_deck.pptx";
const outDir = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_edit_slide11_20260828/artifact_inspect";

async function saveBlob(path, blob) {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  await fs.writeFile(path, bytes);
}

async function main() {
  await fs.mkdir(outDir, { recursive: true });
  const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
  const snapshot = await presentation.inspect({
    kind: "slide,textbox,shape,image,chart,table,notes,layout",
    maxChars: 100000,
  });
  await fs.writeFile(`${outDir}/source-inspect.ndjson`, snapshot.ndjson, "utf8");
  const montage = await presentation.export({ format: "webp", montage: true, scale: 0.6 });
  await saveBlob(`${outDir}/source-montage.webp`, montage);
  const slide = presentation.slides.getItem(10);
  await saveBlob(`${outDir}/slide-11.png`, await presentation.export({ slide, format: "png", scale: 1.5 }));
  await fs.writeFile(`${outDir}/slide-11.layout.json`, await (await slide.export({ format: "layout" })).text(), "utf8");
  const deckInfo = { slideCount: presentation.slides.items.length, slideSize: presentation.slideSize };
  await fs.writeFile(`${outDir}/deck-info.json`, JSON.stringify(deckInfo, null, 2), "utf8");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
