"""Build an evidence index from completed, real solver outputs."""
from pathlib import Path
import datetime,hashlib,json

D=Path(__file__).resolve().parent

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    read=lambda name:json.loads((D/name).read_text(encoding='utf-8'))
    c=read('replay_contract.json');s=read('transient_summary.json');tail=read('replay_tail_check.json')
    execution=read('PO_FS_M5_REPLAY_DT2NS_execution.json');conv=read('baseline_convergence.json')
    finer=read('finer_step_spotchecks.json');screens=sorted(D.glob('GUI_*.png'))
    report=['# LTspice真实瞬态验证记录','',f'报告生成：{datetime.datetime.now().astimezone().isoformat()}','',
        '## 结论范围','',
        '**已实际调用本机LTspice求解，不是把Python曲线改名为LTspice结果。** 本次是历史P&O指令的开环瞬态重放，不是LTspice反馈闭环控制；没有修改原PPT或原控制数据。','',
        '只覆盖原时序2.838–3.059 s，固定fs−5%负载，重放61条相交指令记录。未重放2.4 s负载切换、完整0.8 s扰动段或另外两种策略。不能直接把原页三条曲线全部替换并声称它们都来自LTspice。','',
        '## 真正执行了什么','',
        f'- LTspice日志版本26.0.2；可执行文件FileVersion 26.0.2.1。返回码 {execution["return_code"]}。',
        f'- 本次片段批处理耗时 {execution["elapsed_seconds"]:.1f} s；RAW {execution["raw"]["bytes"]/1e9:.3f} GB，{s["raw_points"]:,} 个时间点。',
        '- 最大积分时间步长2 ns，关闭波形压缩；相位由频率指令积分得到，切换时载波相位连续。',
        '- 保留原始驻留时间，无加速、无时间压缩。前3 ms为新增电路建立时间，不计入正式片段统计。',
        '- 幅度阶跃采用1 ns线性边沿，是明确的数值假设，并非功放测量参数。',
        '- 戴维南源Rs=50 Ω，源电压a=1时6.2173609 V RMS；匹配元件、损耗与历史v2.1配置相同。',
        '- 原始CSV与本次RAW的SHA256均保存在运行凭据、重放约定和哈希清单中。','',
        '## 先做步长核查，保留失败结果','',
        '原50 ns基准运行未通过，不能用作可信基准。保持电路与容差不变，缩小最大步长后结果收敛。该现象支持“高Q窄带模型对积分步长敏感”的数值解释，不应误称真实负载变化。','',
        '| 最大步长 | 端口Vpp (V) | 端口电流 (mA RMS) | Rm有功功率 (mW) |',
        '|---:|---:|---:|---:|']
    for r in conv['results']:
        q=r['LTspice_transient'];report.append(f'| {r["max_step_ns"]:g} ns | {q["vport_vpp"]:.3f} | {q["iport_irms_A"]*1000:.4f} | {q["p_rm_W"]*1000:.3f} |')
    report+=['','Python基准：约100 Vpp、5 mA RMS、170 mW。上表统计1.8–2.0 ms。',
        '另补做1 ns、3 ms长度的基准检查，以及新峰位0.8548 MHz的2 ns/1 ns检查；各自与解析稳态比较均小于0.7%。这些是选定稳态点的数值一致性检查，不是全部瞬态的统一误差上界。','',
        '## 重放尾段：与相同指令的解析稳态比较','',
        '| 指标 | LTspice瞬态尾段 | Python解析稳态 | 相对误差 |','|---|---:|---:|---:|']
    for key,label,mul in [('vport_vpp','端口电压/Vpp',1),('iport_irms_A','端口电流/mA RMS',1000),('p_rm_W','Rm有功功率/mW',1000)]:
        report.append(f'| {label} | {tail["LTspice_transient"][key]*mul:.4f} | {tail["Python_steady_state"][key]*mul:.4f} | {tail["relative_error_percent"][key]:.3f}% |')
    report+=['','尾段频率0.8548 MHz、幅度a=1，统计LTspice 223–224 ms。`.log`中也有LTspice自己的`.meas`结果；RAW后处理与`.meas`允许有采样/积分末位差异。','',
        '## 整个片段的实际瞬态统计','',
        f'- 50 μs不重叠窗口Vpp最大值：{s["maximum_50us_vpp_V"]:.3f} Vpp（原时序约{s["time_of_max_vpp_original_s"]:.6f} s）。',
        f'- 50 μs窗口电流有效值最大值：{s["maximum_50us_irms_mA"]:.4f} mA RMS（原时序约{s["time_of_max_irms_original_s"]:.6f} s）。',
        f'- Vpp>160 V的窗口：{s["windows_vpp_above_160"]}；Irms>6 mA的窗口：{s["windows_irms_above_6mA"]}。',
        f'- 记录的瞬时绝对电压峰值：{s["maximum_absolute_instantaneous_voltage_V"]:.3f} V；瞬时绝对电流峰值：{s["maximum_absolute_instantaneous_current_mA"]:.3f} mA。',
        f'- 本片段Rm有功电能：{s["motional_energy_J"]:.6f} J。不是声学效率，也不是原0.8–6.4 s综合指标。','',
        '**安全口径：** 160 Vpp与6 mA RMS本来针对正弦稳态；本次瞬态采用50 μs统计窗口作为显式分析约定。瞬时电流峰值不能直接与6 mA RMS比较。没有越限窗口也不能证明窗口内、步长之间或硬件中绝不越限。若发现越限，重放不会自动重新降幅，因为并未接入实时控制反馈。','',
        '## 工作痕迹在哪里','',
        '- `PO_FS_M5_REPLAY_DT2NS.cir/.raw/.log`：真实片段网表、二进制波形、日志。',
        '- `PO_FS_M5_REPLAY_DT2NS_execution.json`：命令、起止时间、返回码、文件大小与SHA256。',
        '- `replay_contract.json`、`replayed_original_rows.csv`：场景、时间映射、源记录和局限。',
        '- `baseline_convergence.json`、`finer_step_spotchecks.json`及相关网表/RAW/日志：步长与稳态检查。',
        '- `transient_50us_windows.csv`、`transient_summary.json`：完整窗口统计。',
        '- `RAW_replay_vs_quasisteady.png/.svg/.pdf`：真实RAW后处理与原准稳态预测比较。',
        '- `RAW_tail_carrier.png/.svg/.pdf`：真实RAW载波，非软件截图。',
        '- `run_validation.py`、`postprocess.py`、`build_report.py`：本次运行、绘图与报告生成脚本。','']
    if screens:
        report+=['真实GUI截图已保存：']+[f'- [{p.name}]({p.name})' for p in screens]
    else:
        report+=['**尚未取得真实GUI截图。** LTspice窗口最小化，窗口恢复请求被工具以“user input was detected in this window”阻止；已经请求用户手动恢复。现有PNG后处理图不能冒充截图。按`GUI截图操作说明.md`打开真实RAW/日志即可补截。']
    report+=['','## 可复现与汇报用语','',
        '网表是自包含电路输入；可在LTspice里打开`.cir`运行，或执行`D:\\LTspice.exe -b <网表绝对路径>`。完整221 ms片段开销较大，保留约4 GB空余空间以上；不要覆盖本次证据文件，建议复制到另一个新目录再运行。',
        'Python脚本依赖本工作区的历史模型与源时序，依赖路径已登记在`source_traceability.json`；若迁移电脑，首先保留这些依赖，或者直接使用已导出的自包含网表重跑LTspice。','',
        '> 我们对历史P&O调频、降幅指令的一段进行了真实LTspice瞬态重放，并做了积分步长和稳态数值核查。该验证覆盖电路瞬态响应，不代表三种控制策略的完整闭环验收，也不证明硬件安全性。','',
        '全部结论只限于本假设线性BVD及该指令片段。未涉及实物、非线性功放、温升、结构声场、人体或临床。','']
    (D/'运行与核查报告.md').write_text('\n'.join(report),encoding='utf-8')
    sources=[D.parent/'ltspice_transient_replay_20260911_side/run_replay.py',
        D.parent/'outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py',
        D.parent/'outputs/v2_self_consistent_rebuild/stage2_matching/stage2_匹配设计参数.json',
        D.parent/'outputs/v2_self_consistent_rebuild/stage2_matching/stage2_控制源幅度校准.json',Path(c['source_file'])]
    (D/'source_traceability.json').write_text(json.dumps([{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size} for p in sources],ensure_ascii=False,indent=2),encoding='utf-8')
    files=[p for p in sorted(D.iterdir()) if p.is_file() and p.name!='SHA256_manifest.json']
    receipt_hashes={r.get('path'):r.get('sha256') for name in D.glob('*_execution.json') for r in read(name.name).values() if isinstance(r,dict) and 'sha256' in r}
    manifest=[{'file':p.name,'bytes':p.stat().st_size,'sha256':receipt_hashes.get(str(p)) or sha(p)} for p in files]
    (D/'SHA256_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report and manifest generated.')

if __name__=='__main__':main()
