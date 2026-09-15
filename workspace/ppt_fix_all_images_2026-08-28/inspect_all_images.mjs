import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const source = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_全部图像完整修正版_2026-08-28.pptx";
const outDir = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_fix_all_images_2026-08-28";

const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot = await presentation.inspect({
  kind: "slide,textbox,shape,image,notes,layout",
  include: "id,slide,name,title,text,textPreview,bbox,bboxUnit,alt,isPlaceholder",
  maxChars: 50000,
});
await fs.writeFile(`${outDir}/final-inspect.ndjson`, snapshot.ndjson, "utf8");

const records = snapshot.ndjson.split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
const images = [];
for (const record of records.filter((item) => item.kind === "image")) {
  const image = presentation.resolve(record.id);
  const proto = image.toProto?.();
  images.push({
    ...record,
    frame: image.frame,
    crop: image.crop,
    media: proto?.imageReference?.id,
    shapeId: proto?.id,
  });
}
await fs.writeFile(`${outDir}/final-image-inventory.json`, JSON.stringify(images, null, 2), "utf8");
console.log(JSON.stringify(images, null, 2));
