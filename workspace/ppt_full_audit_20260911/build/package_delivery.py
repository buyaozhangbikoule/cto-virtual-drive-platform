"""Package this audit's real traces. Existing simulation files stay in place."""
from pathlib import Path
import hashlib,json,zipfile
B=Path(__file__).resolve().parent;D=B.parent;O=D/'output';R=D.parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
final=O/'CTO组会汇报_全28页图文核查版_2026-09-11.pptx'
assert sha(final)==sha(B/'candidate.pptx')
rendered=[]
for n in range(1,29):
    p=B/'final-render'/f'{n:02}.png';prior=B/'draft-render-v2'/p.name
    assert p.is_file() and sha(p)==sha(prior),(n,'final render differs from reviewed draft')
    rendered.append({'page':n,'png_sha256':sha(p),'same_as_reviewed_draft':True})
receipt={'final_sha256':sha(final),'slides':28,'embedded_notes':28,'native_editable_tables':9,'Python_replotted_pages':[4,6,8,9,10,11,14],
 'source_unchanged':True,'new_LTspice_simulation':False,'new_control_simulation':False,'new_GUI_capture':False,'new_FEM_simulation':False,
 'rendering_engine':'Artifact Tool, not PowerPoint GUI','all_final_slides_rendered':True,'individual_visual_review':True,'rendered':rendered,
 'finalizer_note':'Node finalizePresentation could not spawn Python (EPERM). Same bundled validators executed unmodified in-process; see fallback_validation_receipt.json. No PowerPoint GUI verification.'}
(O/'交付核查摘要.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
readme='''# 本次PPT图文审核工作痕迹

## 交付内容

- output：28页PPT、完全同步逐页TXT讲稿、逐页审查报告、来源索引及电能复算表。
- build/figures：7组由现存RAW/CSV重绘的PNG、SVG和PDF。它们不是软件截图。
- build/final-render：最终PPT逐页渲染图，它们也不是LTspice或COMSOL截图。
- build中的脚本、唯一讲稿源content.json、图表来源合同、数据复核和文件校验记录。

本次未运行新的LTspice、控制器或结构声场仿真，未新增实物实验。

## 来源与复现

原项目路径：C:/Users/24739/Documents/Codex/2026-08-10/new-chat。
逐页证据索引给出原始数据、脚本、哈希的绝对路径，原RAW/CSV/Log保留在原项目。
该包是本次审核留痕包，不是包含所有历史RAW的完整项目迁移包。换电脑运行需要原项目数据和相应Python/Node依赖。
plot_verified_data.py只读取已有数据并复核裸BVD公式，不调用LTspice或控制器。
content.py生成唯一讲稿源；update.mjs生成候选PPT；verify_and_report.py复核数据、备注与讲稿。
这些脚本按本机原项目目录设计，原始数据路径见索引。
最终文件采用独立文件名。validate_fallback.py --publish拒绝覆盖已存在的最终文件，不要对同一输出重复发布。

## 验证方式与限制

28页均经渲染并逐页检查，讲稿和备注逐页比对。
常规最终封装工具遇到Windows子进程EPERM，改为直接调用同一套未修改的官方文件完整性、字体、几何及表格检查脚本，记录保留在build中。
这不等于在PowerPoint GUI中逐页放映验证，也不等于仿真项目验收全部通过。
结构校验只检查包关系；几何校验不证明科学正确；表格算术门检查没有适用的总计行。
关键科研数据另外进行来源与明确代数/积分复核，详见scientific_checks.json。

## 尚需用户补留的真实截图

第25页历史GUI原截图缺横轴下沿，现有图片无法真实补全。
请在LTspice重新打开对应历史RAW和Error Log，保留完整窗口、场景文件名、变量名、坐标及日志。
结构声场尚未求解，没有可交付的模型树、网格、模态或声压软件截图。
不得用渲染图、AI图或后处理图冒充软件运行截图。
'''
(O/'工作痕迹说明.md').write_text(readme,encoding='utf-8-sig')
report=O/'全28页图文审核报告.md'
original=report.read_text(encoding='utf-8-sig')
addition='\n\n## 文件验证方式补充\n\n常规最终封装工具因Windows子进程EPERM未能完成。已直接调用同一套未修改的随附验证器，PPT包关系、28页尺寸/几何及字体检查无发现项，保留9个可编辑表格。表格自动算术门没有适用的总计行，不将其写成数值已全量验证。16项独立来源与代数/积分核查另记。最终28页均已渲染，逐页图像与已审阅候选一致；未进行PowerPoint原生GUI放映验证。\n'
if '## 文件验证方式补充' not in original:report.write_text(original+addition,encoding='utf-8-sig')
manifest=[]
for p in sorted(O.iterdir()):
    if p.is_file() and p.suffix!='.zip':manifest.append({'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)})
(O/'交付文件_SHA256.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
bundle=O/'PPT图文审核_工作痕迹包.zip'
with zipfile.ZipFile(bundle,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(O.iterdir()):
        if p.is_file() and p.suffix!='.zip':z.write(p,'output/'+p.name)
    for p in sorted(B.iterdir()):
        if p.is_file() and p.suffix in ['.py','.mjs','.json','.txt']:z.write(p,'build/'+p.name)
    for folder in ['figures','final-render']:
        for p in sorted((B/folder).iterdir()):
            if p.is_file():z.write(p,'build/'+folder+'/'+p.name)
print(json.dumps({'pptx':str(final),'bytes':final.stat().st_size,'zip':str(bundle),'zip_bytes':bundle.stat().st_size,'final_hash':sha(final)},ensure_ascii=False))
