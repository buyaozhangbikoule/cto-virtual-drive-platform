"""Produce source-linked reports and freeze a prospective non-blind holdout split."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from control_accounting import ROOT,HERE,load_active,read_json,sha

def table(headers,rows):
    return '\n'.join(['|'+'|'.join(headers)+'|','|'+'|'.join(['---']*len(headers))+'|']+
                     ['|'+'|'.join(map(str,row))+'|' for row in rows])

def main():
    f=read_json(HERE/'output/fitting_v2/results.json')
    c=read_json(HERE/'output/control/results.json')
    out=HERE/'output'
    syn=[]
    for s in f['synthetic']:
        syn.append([s['name'],s['scale'],f"{sum(r['recovery_pass'] for r in s['runs'])}/12",
                    f"{max(r['parameter_max_relative_error'] for r in s['runs']):.3g}"])
    comparisons=[]
    for v in f['measured_summary_fit']:
        b=v['runs'][v['best_index']]
        comparisons.append([v['name'].split('_')[0]]+[f'{n:.4f}' for n in b['percent_errors']]+
                           [f"{min(r['cost'] for r in v['runs']):.6g}–{max(r['cost'] for r in v['runs']):.6g}"])
    worst=max(max(r['grid_percent_errors']) for r in f['published_forward_checks'])
    old=f['historical_function_replay']
    text='''# Janů 外部特征点拟合独立版：修正与验证

## 结论和身份

这是独立研究版，不更改 0.9 MHz 平台基线、不覆盖历史脚本、不重新登记正式控制结果。
对象是论文约40 kHz空气耦合换能器的裸BVD；不是CTO器件辨识。
已完成连续特征点定位、Jacobian检查、多初值对照、无噪声合成参数回收，随后才运行论文表格拟合。
所有“拟合误差”均限于六个摘要特征点，未获得/拟合原始实测全谱。

## 1. 纠正 0.22% 的含义

论文的三组已发表参数 → BVD计算 → 与论文 Table 4 的 **计算特征点行** 比较。
旧格点算法对18个标量的最大差异为 WORST%；包含阻抗、频率和相位，不能称为“实测阻抗全谱误差0.22%”。
这也不是参数拟合精度、真实硬件验证或0.9 MHz模型真实性证明。

数据：DOI 10.1016/j.ultras.2020.106341，Table 4；
冻结转录：`report_0928/output/evidence/review/validate_against_janu2021.py`（工作区相对路径）。
本版保留输入哈希和原函数只读复跑结果；原审核材料的逐字副本放在 `input_reference/`，便于迁移。

## 2. 方法：分离格点、差分和权重的作用

- A：0.5 Hz格点 + 相对残差 + 默认二点差分。
- B：连续极值 + 相同相对残差 + 相同二点差分。A/B只替换定位方法。
- C：连续极值 + 相对残差 + log参数中心差分，步长1e-5。B/C只替换差分。
- D：在C上将三个频率残差分母从各自约40 kHz，改为实测特征间隔 fP−fS=1226 Hz。
  其他分母不变。这是**假设的数值权重**，不是测量不确定度或真实半高宽，不能暗称统计最优。

A–D均用相同12个初值、优化容差1e-12和400次函数评估预算；随机种子20261006。
初始R、L、C0取±0.5对数扰动，同时保持初始理论fs在±0.015对数范围内。
这验证有限局部初值范围，不证明任意初值或全局最优。参数采用正值对数坐标，未强加器件范围。
原函数复跑保留原1e-14容差，单独记录，不与标准化A/B试验混为同一个输出。

连续定位：用裸BVD幅值导数的多项式实根定位候选区间，再用直接复阻抗导数和Brent法细化；
相位极值用解析驻点。边界极值明确标记；不把边界值冒充带内谐振点。
`phim` 是最大相位/最不负相位；`fS/fP` 是阻抗极小/极大频率，不等于无损理论谐振定义。
前向阻抗表达式另与冻结平台代码逐点核对。

## 3. 合成数据回收：先过此关再处理论文

同一BVD数学模型生成无噪声六特征，再从每组12个初值反演。另用标量极值搜索核验极值位置。
回收门槛：四参数最大相对误差 <1e-5，且三个特征点不在边界；门槛不在失败后放宽。
这是数值自洽测试，**不是独立物理验证**，也尚未测试测量噪声、频散和模型失配。

SYN_TABLE

旧尺度在高Q合成例中有3次失败，未删除；首次门禁失败记录保留在 `output/fitting/results.json`。
仅去掉量化并不保证良好数值条件。D尺度的36/36通过只适用于上述合成例与初值设计。

## 4. Jacobian与论文六特征对照

初值处，旧格点方法三个频率残差行范数均为0；连续法对应为 JAC。
这说明原局部差分确实看不到频率变化；不是“六个特征必然无法辨识四参数”的证明。
结果JSON保存1e-3、1e-4、1e-5、1e-6中心步长的Jacobian，以及每次拟合的奇异值、秩和条件数。
秩与条件数是在log参数、所选残差尺度下的局部量；不能据此证明全局唯一性。

以下每行选同一目标函数下12个初值中cost最低者；所有初值的结果均保留。
不同权重下的cost不能横向排名。百分比均相对论文 **Measured六个标量**，不是全谱误差。

FIT_TABLE

原历史函数复跑，六项误差依次为 OLD_ERRORS%。
连续法提高初值稳定性；D加强频率拟合，但阻抗和相位误差会增大，不能宣称六项全面改善。
论文数据包含舍入、测量误差和潜在模型不充分，本次没有不确定度数据，不能把剩余误差全部归因于任一项。
多初值趋于同一代价也不是全局可辨识性的证明。

## 5. 复算与未完成

在平台根目录运行：
`python -B -X utf8 research/fit_control_diagnostics_20261006/run_fitting.py`

机器结果：`output/fitting_v2/results.json`；实现：`fitting.py`；全部初值、终止原因、边界、Jacobian均可追溯。
下一步需要原始实测复阻抗全谱、频率分辨率、重复测量及误差模型；再做噪声/模型失配测试与置信区间。
本版未把拟合参数迁移到0.9 MHz器件，也未实现论文原作者的完整辨识流程。

数值接口依据：[SciPy least_squares](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html)、
[SciPy brentq](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.brentq.html)。本次实际版本见结果JSON。
'''
    text=text.replace('WORST',f'{worst:.6f}').replace('SYN_TABLE',table(['合成例','尺度','回收通过','最大参数相对误差（比例）'],syn))
    text=text.replace('JAC',' / '.join(f'{x:.6f}' for x in f['jacobian_at_seed']['continuous']['frequency_row_norms']))
    text=text.replace('FIT_TABLE',table(['版本','ZS %','fS %','ZP %','fP %','phim %','fphim %','12初值cost范围'],comparisons))
    text=text.replace('OLD_ERRORS',' / '.join(f"{old['percent_errors'][k]:.4f}" for k in f['feature_order']))
    (out/'01_Janu拟合修正与验证.md').write_text(text,encoding='utf-8')

    reports=[r for r in c['reports'] if r['suite']=='HISTORICAL_12']
    summary=[];details=[]
    for r in reports:
        t=r['totals']; summary.append([r['strategy'],f"{sum(s['settled'] for s in r['segments'])}/12",f"{t['energy_J']:.6f}",f"{100*t['energy_J']/t['reference_energy_J']:.2f}%"])
        details.append('\n### '+r['strategy']+'\n\n'+table(['执行阶段','时间 s','P_Rm电能 J','参考电能缺口 J','占本策略总缺口'],[
            [k,f"{v['duration_us']/1e6:.4f}",f"{v['energy_J']:.6f}",f"{v['signed_deficit_J']:.6f}",f"{100*v['signed_deficit_J']/t['signed_deficit_J']:.2f}%"]
            for k,v in r['stages'].items() if v['duration_us']]))
    control='''# 控制效率诊断：先分账，再改算法

## 身份与复核

只读批次 `BATCH`，对105条时序逐段复算。
所有时长、电能、连续合格计数、进入与完成确认时刻，与原统一指标表一致。
未运行新控制器，未改变正式参数、保护、0.8秒段长、98%门槛或连续10样本规则。
原始CSV、事件、配置、来源哈希均保留；新增逐行分类表位于本研究目录而不是原批次。

SUMMARY

12段总长9.6秒，三策略安全参考电能相同（浮点累加误差除外）。不能据本日程推断固定频率普遍最好。
这里P_Rm电能是机械支路电阻的电学耗散，不是声能或声学效率。

## 分账方法与不能拆出的部分

每行按实际 `duration_us` 积分，不以行数代替时长；段边界已拆分，不删除保护、试探或失败记录。
同一行只进入一个主分类，优先级：保护 → 预备降幅 → 升幅 → 扫描/试探 → 失败处理 → 确认/普通运行。
保护与扫描可能同时出现，JSON另保留 `kind × protection_state` 交叉账，避免归因被优先级隐藏。
缺口=同时间段policy安全参考电能−实际电能；保留带符号差额，并单列正缺口与超参考余量，不能截零后冒充总差额。
参考只是100 Hz网格上的模型参考。略超参考不自动等于保护失效。

**检测等待：NA。** 正式周期控制没有单独的扰动检测器时间戳；普通低功率控制可能包含调度等待或偏频，无法仅靠这些日志分离。
逐段另列“段起点后首个扫描开始的时间差”，它可能包含保护等待且基于已知评估段界，不能命名为检测延迟。
**连续确认不是额外停机命令。** 它只是评分器观察连续样本；10个20 ms采样时刻首尾相隔180 ms。
若包含邻频试探，确认样本实际占用时间可能少于200 ms；试探时间独立计入，不双算。
表中“已确认后合格”只是仍合格的样本，不意味着此前通过后永不失锁。

DETAILS

## 当前可采取的研究方向

1. 周期扫频先研究升幅恢复与再次扫描的衔接，而不是仅缩短采点时间。升幅恢复占时最多；不能未经验证直接提高升幅速度或撤掉保持。
2. 将“复用已验证候选/缩短局部搜索”作为独立候选，仍记录全部测量与保护过程；负载改变时缓存必须失效。
3. 相位策略保护/降额与普通未达标占较大缺口，先看逐段的保护事件和目标相位适用性，不能仅靠加增益。
4. 事件触发应另列候选，保留原周期扫频对照；需记录检测器测量、确认、冷却与触发时刻。

**此处为模糊推测内容：** 恢复衔接或扫描复用可能降低重复降幅损失，尚无本轮候选对照试验证明。
这些分账是执行阶段关联，不是因果可节省量；不能宣称消除某阶段即可追回全部缺口。

## 调参/验证隔离与下一步入口

`validation_protocol.json`冻结今后的调参/检验场景，扰动ID及物理参数指纹均不重叠；共有基准除外。
原12段日程只作已观察的诊断与回归，不能再称盲测。检验组的旧结果过去也已观察，因此此分组是**前瞻性调参隔离、非真正未知测试集**。
新候选须先冻结代码/参数哈希，才运行检验组；看完检验再改参数须声明新一轮开发，不能继续沿用“未见验证”。
所有方案用相同执行器、时间、测点、幅度与评分器。比较连续通过、全过程电能、越限及故障全账；不以单一通过数排名。
当前**没有**新算法通过率或效率提升的结果。

复算：`python -B -X utf8 research/fit_control_diagnostics_20261006/control_accounting.py --all-suites`
机器结果：`output/control/results.json`；12段逐行表：`output/control/HISTORICAL_12_*_labelled.csv`。
'''
    control=control.replace('BATCH',c['batch_id']).replace('SUMMARY',table(['策略','连续通过','电能 J','电能捕获'],summary)).replace('DETAILS','\n'.join(details))
    (out/'02_控制耗时与电能分解.md').write_text(control,encoding='utf-8')
    freeze_protocol()

def freeze_protocol():
    ev=load_active();folder=ev['folder'];cfg=read_json(folder/'configuration.json')
    registry=read_json(folder/'scenario_registry.json')
    byid={r['case_id']:r for r in registry}
    base='CASE_000_BASELINE'
    def fingerprint(r):
        # Independent component values only; exclude labels and derived fs/Q.
        b=r['bvd']
        return json.dumps([b[k] for k in ('c0','rm','lm','cm')]+[r['matching'],r['rs']],sort_keys=True)
    baseline_fp=fingerprint(byid[base])
    tune=['CASE_C0_P10','CASE_RM_P15','CASE_FS_M1','CASE_LM_P5','CASE_CM_P5','CASE_RS_P5',
          'CASE_LMATCH_P2','CASE_CMATCH_M2','CASE_QL_50','CASE_QM_500','CASE_COMBINED_LOW']
    tunefp={fingerprint(byid[k]) for k in tune}
    verify=[k for k,r in byid.items() if k not in tune and fingerprint(r)!=baseline_fp and fingerprint(r) not in tunefp]
    protocol={'status':'FROZEN_DESIGN_NOT_EXECUTED','identity':'prospective tuning separation, NOT unseen physical validation',
              'source_batch':folder.name,'source_config_sha256':sha(folder/'configuration.json'),
              'source_registry_sha256':sha(folder/'scenario_registry.json'),
              'assumed_protocol_choices':'low disturbance levels for development, remaining non-alias cases for evaluation; not literature-derived',
              'baseline_shared':base,'tuning_cases':tune,'validation_cases':verify,
              'case_ids_disjoint':not set(tune)&set(verify),
              'physical_parameter_fingerprints_disjoint':not tunefp&{fingerprint(byid[k]) for k in verify},
              'schedules':{'tuning':[[base,k,base] for k in tune],'validation':[[base,k,base] for k in verify]},
              'segment_us':cfg['segment_us'],'capture_threshold':cfg['capture_threshold'],
              'continuous_samples':cfg['continuous_samples'],
              'protection_must_remain':{k:v for k,v in cfg.items() if any(s in k for s in ('voltage_','current_','hold_us'))},
              'original_12':'diagnostic/regression only; preserve unchanged segment length/order for comparison',
              'candidate_freeze_before_validation':['candidate source SHA256','full configuration SHA256','tuning run manifest','decision rule'],
              'not_yet_covered':['noise','delay','continuous transients','new unknown physical device','unseen disturbance magnitudes/order'],
              'no_promotion_until':'baseline/candidate common engine comparison, all failures and hard violations retained'}
    dest=HERE/'validation_protocol.json'
    payload=json.dumps(protocol,ensure_ascii=False,indent=2)+'\n'
    if dest.exists() and dest.read_text(encoding='utf-8')!=payload:
        raise RuntimeError('Frozen protocol changed: create a new version, never overwrite')
    if not dest.exists(): dest.write_text(payload,encoding='utf-8')

if __name__=='__main__': main()
