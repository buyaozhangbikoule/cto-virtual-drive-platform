"""Package real evidence and presentation guidance without copying multi-GB RAWs."""
from pathlib import Path
import csv,hashlib,json,shutil,zipfile,xml.etree.ElementTree as ET
from PIL import Image,ImageOps,ImageDraw
B=Path(__file__).resolve().parent;W=B.parent;R=W.parent;O=W/'output';E=O/'汇报证据'
E.mkdir(exist_ok=True)
PL=R/'CTO_virtual_drive_platform_v2_1';RP=R/'ltspice_transient_replay_20260911_continue'
CL=PL/'results/ltspice_closed_loop/CL_20260914_124949_410d5f9d'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
session=json.loads((CL/'session.json').read_text(encoding='utf-8'))
chain=[]
for i,r in enumerate(session['records']):
    step=CL/f'step_{i:03d}';ex=json.loads((step/'execution.json').read_text(encoding='utf-8'))
    assert ex['return_code']==0
    for ext,k in [('raw','raw_sha256'),('cir','cir_sha256'),('log','log_sha256')]:
        assert sha(step/f'circuit.{ext}')==ex[k],(i,ext)
    stim=json.loads((step/'stimulus.json').read_text(encoding='utf-8'))
    assert stim['commands'][-1]==r['command']
    if i:
        assert stim['parent_feedback_sha256']==sha(CL/f'step_{i-1:03d}/feedback.json')
        assert r['command']==session['records'][i-1]['next_command']
    chain.append({'round':i+1,'raw_hash_verified':True,'command_handoff_verified':True})
(B/'feedback_chain_recheck.json').write_text(json.dumps(chain,indent=2),encoding='utf-8')
manifest=[]
def add(src,name):
    assert src.is_file(),src
    dest=E/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
    manifest.append({'file':name,'source':str(src),'sha256':sha(src),'bytes':src.stat().st_size})
add(B/'assets/platform_home.jpg','网页_2026-09-15/平台主页.jpg')
add(B/'assets/feedback_five_rounds.jpg','网页_2026-09-15/五轮历史反馈只读页面.jpg')
for name in ['GUI_20260912_replay_full.png','GUI_20260912_LTspice_Error_Log.png','GUI_20260912_tail_carrier.png','运行与核查报告.md','transient_summary.json','baseline_convergence.csv','finer_step_spotchecks.json','replay_contract.json','PO_FS_M5_REPLAY_DT2NS_execution.json','PO_FS_M5_REPLAY_DT2NS.cir','PO_FS_M5_REPLAY_DT2NS.log','RAW_replay_vs_quasisteady.png','RAW_tail_carrier.png']:
    add(RP/name,'瞬态重放/'+name)
for name in ['session.json','config.json','reversal_acceptance.json']:
    add(CL/name,'五轮反馈/'+name)
for i in range(5):
    for name in ['feedback.json','stimulus.json','execution.json','circuit.cir','circuit.log']:
        add(CL/f'step_{i:03d}'/name,f'五轮反馈/step_{i:03d}/{name}')
add(R/'control_factorial_20260907/results/summary.csv','算法消融/summary.csv')
add(R/'control_factorial_20260907/deliverables/第二轮控制消融验证报告.md','算法消融/第二轮控制消融验证报告.md')
add(B/'build.mjs','PPT生成脚本/build.mjs');add(B/'page_map.json','PPT生成脚本/page_map.json')
add(PL/'streamlit_app.py','平台代码/streamlit_app.py');add(PL/'pages/03_LTspice闭环验证.py','平台代码/03_LTspice闭环验证.py')
add(PL/'evidence/ltspice/stage2/stage2_audit.json','静态引用/stage2_audit.json')
(E/'文件来源及SHA256.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
raws=[RP/'PO_FS_M5_REPLAY_DT2NS.raw',*[CL/f'step_{i:03d}/circuit.raw' for i in range(5)]]
(E/'大型RAW原始路径.txt').write_text('为避免重复复制数GB文件，本包只附网表、日志、截图与摘要。RAW仍保留在以下原路径。五轮RAW的哈希本次已重新校核，瞬态RAW哈希见execution凭据。\n\n'+'\n'.join(map(str,raws)),encoding='utf-8')
with (E/'五轮反馈/汇报数值表.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['round','frequency_MHz','amplitude','P_port_mW','next_frequency_MHz','next_command_executed'])
    for i,r in enumerate(session['records']):w.writerow([i+1,r['command']['frequency_hz']/1e6,r['command']['amplitude'],r['measurement']['p_port_W']*1000,r['next_command']['frequency_hz']/1e6,i<4])
pages=json.loads((B/'page_map.json').read_text(encoding='utf-8'))
guide='''# 汇报使用说明与截图清单

更新日期：2026-09-15。正文1–21页，备份22–32页。原28页PPT未覆盖，生成了独立32页版本。

## 本次新增及更新

- 新增第3页：真实网页平台与操作流程。
- 新增第17页：真实LTspice瞬态重放，所选尾段差异0.635%。
- 新增第18页：五轮因果反馈，突出第4轮决策与第5轮实际执行。
- 新增第26页：8组组合及2组去相位对照，保留失败与电能代价。
- 原第18、25、27页更新后为第21、29、31页。同步封面日期、页码、页间引用及备注。
- 逐页讲稿包含新增页讲稿，也保留既有页的讲解与限制；PPT每页备注有相同内容。

## 正式汇报顺序

正文按“研究问题 → 平台 → 模型与匹配 → 扰动与选频 → 控制原型 → 新LTspice证据 → 接口与完成度”讲述。
21页全部详细讲解预计18–20分钟，备份不主动逐页读。
若限定12–15分钟，重点讲第1、2、3、4、5、6、8、11、12、13、16、17、18、19、21页；第7、9、10、14、15、20页只用一句话过渡或在提问时返回。不要靠加速朗读所有备注来压缩时间。
问到“算法有没有改进”时翻第26–27页；问到“全过程损失”时翻第28页；问到“真实LTspice证据”时翻第29、31页；问到结构声场时翻第32页。

## 现在需要你额外截图吗？

本次新增页所需截图已取得并插入或归档，不需要你为了这次补页重新运行LTspice。
1. 平台主页：本次实际浏览器截图，未改写像素。
2. 五轮反馈页面：本次只读打开2026-09-14历史会话截图，没有启动新求解。侧栏显示的是下一次新会话默认2ms；主区冻结配置为历史会话实际1ms，汇报按1ms。
3. LTspice完整波形、载波放大与Error Log：使用2026-09-12已留存真实截图，对应9月11日瞬态求解。完整波形入第17页，日志入第29页，载波放大在证据包中。

仍需你在后续真正完成工作后再补的证据：
- 如果要逐一证明当前所有AC场景的GUI显示，需要打开对应批次RAW及LOG再截图；不能拿本次瞬态截图替代。现有AC数值校核可引用网表、RAW、LOG和误差表，本次无需为补页重跑。
- ANSYS/COMSOL模型尚未完成，不能现在补声压或模态“结果截图”。后续真正建模、求解后保留版本与许可证、模型树、几何尺寸、材料与极化、边界、网格、模态/谐响应、声压及收敛和Solver Log。
- 汇报前请用你实际使用的PowerPoint/WPS打开一次，检查字体替换与投影显示。本次经过文件导入、逐页渲染核查，不声称已在你的投影或PowerPoint GUI中验收。

## 不能混用的口径

- 第13–16页以及第28页历史结果，与第26–27页改进版本不同批次。旧版未通过成绩没有被新成绩覆盖。
- 第17页是开环片段重放，固定fs−5%负载。第18页是固定基准负载的五轮反馈。两者都不是完整动态扰动三策略验收。
- 第18页功率是RAW平均端口P_port。历史主控制与电能页以P_Rm为主要指标，瞬态下二者不能直接互换。
- 0.635%是特定223–224ms尾段功率差异，不是所有瞬态误差上限。
- 网页η_elec为P_port/P_source，电能捕获率相对场景最优功率积分，两者均非声学效率。
- “会话达到5轮上限”不是“稳态通过”；第5轮生成的第6条指令没有执行证据。
- 全部结论限于假设BVD及所测扰动范围，没有实物、功放非线性、临床或声场验证。

## 新旧页码索引

|新版页|原页|用途|标题|
|---|---|---|---|
'''
for p in pages:guide+=f"|{p['page']}|{p['old_page'] or '新增'}|{p['role']}|{p['title']}|\n"
(O/'汇报顺序与截图说明.md').write_text(guide,encoding='utf-8')
# Evidence paths referenced in new notes are checked by explicit list above.
# Contact sheets are QA thumbnails; they never replace scientific source images.
images=sorted((B/'final-render').glob('*.png'))
if len(images)==32:
    sheet=Image.new('RGB',(1280,8*195),'white');d=ImageDraw.Draw(sheet)
    for i,impath in enumerate(images):
        im=Image.open(impath).convert('RGB');im.thumbnail((310,175));x=(i%4)*320;y=(i//4)*195
        sheet.paste(im,(x,y));d.text((x+5,y+178),str(i+1),fill='#17324D')
    sheet.save(B/'contact.png')
    for n in [3,17,18,26,29]:shutil.copy2(B/f'final-render/{n:02d}.png',O/f'第{n}页_预览.png')
with zipfile.ZipFile(O/'补充成果_真实截图与证据.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in E.rglob('*'):
        if f.is_file():z.write(f,f.relative_to(E))
print('Evidence files',len(manifest),'Five-round RAW/causal hashes all checked.')
