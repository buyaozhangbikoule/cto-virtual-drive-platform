import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const B=path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1'));
const W=path.dirname(B);
const S='C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations';
const {finalizePresentation}=await import(pathToFileURL(`${S}/container_tools/artifact_tool_utils.mjs`).href);
await fs.mkdir(`${W}/output`,{recursive:true});
for(const [stem,count,filename] of [['single',1,'第15页_控制方法与阶段性结果_2026-09-15.pptx'],['full',28,'CTO组会汇报_仅第15页更新_2026-09-15.pptx']]){
 try{
  const r=await finalizePresentation({workspaceDir:W,candidatePath:`${B}/${stem}_candidate.pptx`,finalPath:`${W}/output/${filename}`,
    explicitTotalSlideCount:count,requiredNativeChartOwnerSlides:[],requiredNativeTableOwnerSlides:[],
    pythonExecutable:'C:/Users/24739/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe',
    integrityValidatorPath:`${S}/container_tools/inspect_presentation_package_integrity.py`,layoutValidatorPath:`${S}/container_tools/inspect_presentation_layout_geometry.py`,
    layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--validate-bullet-geometry'],
    fontPolicy:{basis:'design',families:['Calibri']},verifyArtifactToolImport:true,receiptPath:`${B}/${stem}_finalization_receipt.json`});
  console.log(JSON.stringify(r));
 }catch(e){await fs.writeFile(`${B}/${stem}_finalizer_error.txt`,String(e.stack));console.log(`${stem}: ${e.message}`);}
}
