import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const source = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24.pptx";
const out = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_fix_2026-08-24/inspect-slide7.ndjson";

const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
const snapshot = await presentation.inspect({
  target: { id: "sl/gnmp4jqx", beforeLines: 0, afterLines: 50 },
  kind: "slide,textbox,shape,image,notes,layout",
  include: "id,slide,name,title,textPreview,bbox,bboxUnit,alt,isPlaceholder",
  maxChars: 12000,
});
await fs.writeFile(out, snapshot.ndjson, "utf8");
console.log(snapshot.ndjson);
const image = presentation.resolve("im/tsze1szm");
console.log(JSON.stringify({
  fit: image.fit,
  crop: image.crop,
  frame: image.frame,
  position: image.position,
  lockAspectRatio: image.lockAspectRatio,
  proto: image.toProto?.(),
}, null, 2));
