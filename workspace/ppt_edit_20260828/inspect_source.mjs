import fs from 'node:fs/promises';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';

const source = process.argv[2];
const out = process.argv[3];
const presentation = await PresentationFile.importPptx(await FileBlob.load(source));
const all = await presentation.inspect({
  kind: 'slide,textbox,shape,image,table,chart,notes,layout',
  maxChars: 1000000,
});
await fs.writeFile(out, all.ndjson ?? '', 'utf8');
const slide11 = presentation.slides.getItem(10);
await fs.writeFile(out.replace('.ndjson', '-slide11.layout.json'), await (await slide11.export({format:'layout'})).text(), 'utf8');
