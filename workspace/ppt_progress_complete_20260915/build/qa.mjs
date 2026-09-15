import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
const B=path.dirname(fileURLToPath(import.meta.url)),W=path.dirname(B);
const S='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations';
const p=await PresentationFile.importPptx(await FileBlob.load(`${B}/full_candidate.pptx`));
await fs.mkdir(`${B}/final-render`,{recursive:true});
await fs.writeFile(`${B}/final.inspect.ndjson`,(await p.inspect({kind:'slide,textbox,shape,image,table,notes',maxChars:1000000})).ndjson);
if(p.slides.items.length!==32)throw Error('Unexpected slide count');
for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i],n=String(i+1).padStart(2,'0');
 await fs.writeFile(`${B}/final-render/${n}.png`,new Uint8Array(await(await s.export({format:'png',scale:1})).arrayBuffer()));
 await fs.writeFile(`${B}/final-render/${n}.layout.json`,await(await s.export({format:'layout'})).text());
 console.log('Rendered '+n);
}
const {finalizePresentation}=await import(pathToFileURL(`${S}/container_tools/artifact_tool_utils.mjs`).href);
try{
 const result=await finalizePresentation({workspaceDir:W,candidatePath:`${B}/full_candidate.pptx`,finalPath:`${W}/output/CTO组会汇报_成果补全32页_2026-09-15.pptx`,explicitTotalSlideCount:32,
 requiredNativeTableOwnerSlides:[17,18,21,26,31],requiredNativeChartOwnerSlides:[],pythonExecutable:'C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:`${S}/container_tools/inspect_presentation_package_integrity.py`,layoutValidatorPath:`${S}/container_tools/inspect_presentation_layout_geometry.py`,
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--validate-bullet-geometry'],fontPolicy:{basis:'reference',families:['Calibri'],referencePath:path.resolve(W,'../ppt_control_progress_20260914/output/CTO组会汇报_仅第15页更新_2026-09-15.pptx'),referenceSha256:'9bb68d8eeeb4d14d5e8dd73e1aeba0c06f8f6910172528a0b028e98664e869a7'},verifyArtifactToolImport:true,receiptPath:`${B}/finalization_receipt.json`});
 console.log(JSON.stringify(result));
}catch(e){await fs.writeFile(`${B}/finalizer_error.txt`,String(e.stack));console.log('Finalizer: '+e.message);}
