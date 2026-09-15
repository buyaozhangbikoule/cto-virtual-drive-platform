import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const W='C:/Users/24739/Documents/Codex/2026-08-10/new-chat/ppt_full_audit_20260911';
const S='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations';
const source='C:/Users/24739/Documents/Codex/2026-08-10/new-chat/project_audit_20260910/output/CTO组会汇报_计划书口径与验收缺口修订_2026-09-10.pptx';
const {finalizePresentation}=await import(pathToFileURL(`${S}/container_tools/artifact_tool_utils.mjs`).href);
await fs.mkdir(`${W}/output`,{recursive:true});
try{
 const result=await finalizePresentation({workspaceDir:W,candidatePath:`${W}/build/candidate.pptx`,finalPath:`${W}/output/CTO组会汇报_全28页图文核查版_2026-09-11.pptx`,
 pythonExecutable:'C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
 integrityValidatorPath:`${S}/container_tools/inspect_presentation_package_integrity.py`,layoutValidatorPath:`${S}/container_tools/inspect_presentation_layout_geometry.py`,
 explicitTotalSlideCount:28,requiredNativeTableOwnerSlides:[6,7,15,19,20,21,22,24,26],requiredNativeChartOwnerSlides:[],
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[6,7,15,19,20,21,22,24,26].flatMap(n=>['--require-native-table-slide',String(n)])],
 fontPolicy:{basis:'reference',families:['Calibri'],referencePath:source,referenceSha256:'91ef28cc9a284a6bc3880639e1bf2b795386d1a100ca6ae44ee58a3fd0c4bbc0'},
 verifyArtifactToolImport:true,receiptPath:`${W}/build/finalization_receipt.json`});
 console.log(JSON.stringify(result));
}catch(e){await fs.writeFile(`${W}/build/finalizer_failure.txt`,String(e.stack));throw e;}
