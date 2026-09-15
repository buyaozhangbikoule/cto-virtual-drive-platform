import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const root = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_update_20260902";
const deck = await PresentationFile.importPptx(await FileBlob.load(`${root}/source.pptx`));
const snapshot = await deck.inspect({
  kind: "slide,textbox,shape,image,table,chart,notes,layout",
  maxChars: 100000,
});
await fs.writeFile(`${root}/source-full-inspect.ndjson`, snapshot.ndjson, "utf8");
const montage = await deck.export({ format: "png", montage: true, scale: 0.75 });
await fs.writeFile(`${root}/source-montage.png`, new Uint8Array(await montage.arrayBuffer()));
console.log(snapshot.ndjson.split(/\r?\n/).filter((line) => line.includes('"kind":"slide"')).join("\n"));
