import fs from "node:fs/promises";
import JSZip from "jszip";

const args = process.argv.slice(2);
if (args.length < 2 || !["-Z1", "-p"].includes(args[0])) {
  process.stderr.write("usage: unzip -Z1 file | unzip -p file entry\n");
  process.exit(2);
}

const data = await fs.readFile(args[1]);
const zip = await JSZip.loadAsync(data);

if (args[0] === "-Z1") {
  process.stdout.write(Object.keys(zip.files).join("\n") + "\n");
} else {
  const entry = zip.file(args[2]);
  if (!entry) {
    process.stderr.write(`entry not found: ${args[2]}\n`);
    process.exit(1);
  }
  const bytes = await entry.async("nodebuffer");
  process.stdout.write(bytes);
}
