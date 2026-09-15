import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from 'file:///C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';

const source = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/CTO超声换能器第一月教授组会汇报_2026-08-24_图像完整修正版.pptx';
const work = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_slide4_revision_2026-08-25/final';
const output = 'C:/Users/24739/Documents/Codex/2026-08-10/new-chat/outputs/v2_self_consistent_rebuild/report_evidence_final/第4页_Python_LTspice交叉验证_严谨修订版.pptx';
await fs.mkdir(work, { recursive: true });

const p = await PresentationFile.importPptx(await FileBlob.load(source));
const keep = p.slides.getItem(3);

// Keep exactly source slide 4, preserving its master/layout relationship.
for (const slide of [...p.slides.items]) {
  if (slide.id !== keep.id) slide.delete();
}

p.resolve('sh/x8vaxsfe').text = '10 Hz网格下，Python与LTspice结果数值一致';
p.resolve('sh/sna103ap').text = '0.5–1.5 MHz';
p.resolve('sh/3ihk3et8').text = '100001点｜Δf=10 Hz';
p.resolve('sh/5cva1cfq').text = '< 10 Hz';
p.resolve('sh/i94r6xgz').text = '峰位差（网格分辨率内）';
p.resolve('im/sbm5cbix').delete();

const boundary = p.resolve('sh/w72947yt');
boundary.text = 'LTspice：.cir→.raw\nPython：解析模型\n同网格逐点比较\n实现一致 ≠ 参数真实';
boundary.position = { left: 912, top: 448, width: 282, height: 142 };

keep.speakerNotes.textFrame.setText([
  '讲述口径：同一BVD拓扑、同一组假设基线参数、同一0.5–1.5 MHz频率网格下，分别由LTspice生成.raw结果、由Python计算解析结果，再逐点比较。',
  '扫描设置：0.5–1.5 MHz，等间隔100001点，步长10 Hz。',
  '结果：最大|Z|相对误差为1.36×10⁻⁷；两种实现识别的串联谐振位置均落在0.900000 MHz网格点，因此只能表述为峰位差小于10 Hz网格分辨率，不应表述为连续频域的绝对0误差。',
  '结论边界：该页只验证Python公式与LTspice网表的数值实现一致，不证明假设BVD参数代表真实换能器。',
  '',
  '[Sources]',
  '- C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\v2_self_consistent_rebuild\\report_evidence_final\\02_LTspice真实运行\\V2_1_STAGE1_LTspice_解析交叉验证.csv',
  '- C:\\Users\\24739\\Documents\\Codex\\2026-08-10\\new-chat\\outputs\\v2_self_consistent_rebuild\\report_evidence_final\\07_汇报截图\\V2_1_STAGE1_LTspice_RAW交叉验证.png',
  '- LTspice Error Log截图作为独立运行证据保留，不在本页缩小展示。'
].join('\n'));
keep.speakerNotes.setVisible(true);

const png = await keep.export({ format: 'png', scale: 2 });
await fs.writeFile(`${work}/slide4-revised.png`, new Uint8Array(await png.arrayBuffer()));
const layout = await keep.export({ format: 'layout' });
await fs.writeFile(`${work}/slide4-revised.layout.json`, await layout.text(), 'utf8');

const snapshot = await p.inspect({ kind: 'slide,textbox,shape,image,notes,layout', maxChars: 30000 });
await fs.writeFile(`${work}/final-inspect.ndjson`, snapshot.ndjson, 'utf8');

const pptx = await PresentationFile.exportPptx(p);
await pptx.save(output);
console.log(output);
