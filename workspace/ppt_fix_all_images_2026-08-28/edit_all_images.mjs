import fs from "node:fs/promises";
import { FileBlob, PresentationFile } from "@oai/artifact-tool";

const source = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx";
const output = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_全部图像完整修正版_2026-08-28.pptx";
const qaDir = "C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_fix_all_images_2026-08-28/qa";

function setFrame(object, frame) {
  object.frame = frame;
  object.position = frame;
}

function unclipImage(presentation, id, frame) {
  const image = presentation.resolve(id);
  image.crop = { left: 0, top: 0, right: 0, bottom: 0 };
  setFrame(image, frame);
}

await fs.mkdir(qaDir, { recursive: true });
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));

const before = await presentation.inspect({
  kind: "slide,textbox,shape,image,notes,layout",
  maxChars: 50000,
});
await fs.writeFile(`${qaDir}/before.ndjson`, before.ndjson, "utf8");

unclipImage(presentation, "im/q9876pkv", { left: 100, top: 112, width: 743, height: 520 });
unclipImage(presentation, "im/srmx0vmd", { left: 72, top: 116, width: 714, height: 500 });
unclipImage(presentation, "im/jmdw3qlg", { left: 830, top: 132, width: 350, height: 245 });
unclipImage(presentation, "im/tsze1szm", { left: 98, top: 112, width: 682, height: 550 });
unclipImage(presentation, "im/hcz65kbq", { left: 72, top: 106, width: 1136, height: 481 });
unclipImage(presentation, "im/8jmtobq9", { left: 380, top: 110, width: 735, height: 535 });
unclipImage(presentation, "im/21cnihkf", { left: 145, top: 105, width: 722, height: 560 });

setFrame(presentation.resolve("sh/o761ov2t"), { left: 890, top: 535, width: 290, height: 82 });

setFrame(presentation.resolve("sh/ofq5svm5"), { left: 814, top: 594, width: 360, height: 78 });
const recommendation = presentation.resolve("sh/bih4na5w");
recommendation.text = "推荐：±50 kHz / 1 kHz / 101点\n扫描时间代理：151.5 ms";
recommendation.text.style = {
  fontFamily: "Microsoft YaHei",
  fontSize: 20,
  bold: true,
  color: "#17324D",
  alignment: "center",
  verticalAlignment: "middle",
};
setFrame(recommendation, { left: 838, top: 603, width: 312, height: 58 });
setFrame(presentation.resolve("sh/ah8nu54b"), { left: 86, top: 598, width: 310, height: 32 });
setFrame(presentation.resolve("sh/oza1gfyh"), { left: 86, top: 635, width: 650, height: 30 });

setFrame(presentation.resolve("sh/xwnupgvy"), { left: 340, top: 648, width: 790, height: 24 });

const after = await presentation.inspect({
  kind: "slide,textbox,shape,image,notes,layout",
  maxChars: 50000,
});
await fs.writeFile(`${qaDir}/after.ndjson`, after.ndjson, "utf8");

for (let index = 0; index < presentation.slides.items.length; index += 1) {
  const slide = presentation.slides.items[index];
  const png = await slide.export({ format: "png", scale: 1 });
  await fs.writeFile(`${qaDir}/final-slide-${String(index + 1).padStart(2, "0")}.png`, new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(`${qaDir}/final-slide-${String(index + 1).padStart(2, "0")}.layout.json`, new Uint8Array(await layout.arrayBuffer()));
}

const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(output);
console.log(output);
