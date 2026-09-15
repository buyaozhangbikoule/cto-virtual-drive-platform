import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const source = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24.pptx";
const output = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx";
const qaDir = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_fix_2026-08-24/qa";

await fs.mkdir(qaDir, { recursive: true });
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));

const before = await presentation.inspect({
  target: { id: "sl/gnmp4jqx", beforeLines: 0, afterLines: 50 },
  kind: "slide,textbox,shape,image,notes",
  maxChars: 12000,
});
await fs.writeFile(`${qaDir}/before-slide7.ndjson`, before.ndjson, "utf8");

const slide = presentation.resolve("sl/gnmp4jqx");
const image = presentation.resolve("im/tsze1szm");
const beforePng = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(`${qaDir}/slide7-before.png`, new Uint8Array(await beforePng.arrayBuffer()));

image.crop = { left: 0, top: 0.05, right: 0, bottom: 0 };
image.frame = { left: 80, top: 112, width: 717, height: 550 };

const afterPng = await slide.export({ format: "png", scale: 2 });
await fs.writeFile(`${qaDir}/slide7-after.png`, new Uint8Array(await afterPng.arrayBuffer()));
const afterLayout = await slide.export({ format: "layout" });
await fs.writeFile(`${qaDir}/slide7-after-layout.json`, new Uint8Array(await afterLayout.arrayBuffer()));

const after = await presentation.inspect({
  target: { id: "sl/gnmp4jqx", beforeLines: 0, afterLines: 50 },
  kind: "slide,textbox,shape,image,notes",
  maxChars: 12000,
});
await fs.writeFile(`${qaDir}/after-slide7.ndjson`, after.ndjson, "utf8");

for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const current = presentation.slides.items[index];
  const rendered = await current.export({ format: "png", scale: 1 });
  await fs.writeFile(
    `${qaDir}/final-slide-${String(index + 1).padStart(2, "0")}.png`,
    new Uint8Array(await rendered.arrayBuffer()),
  );
}
const montage = await presentation.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(`${qaDir}/final-montage.webp`, new Uint8Array(await montage.arrayBuffer()));

const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(output);
console.log(output);
