# 当前活动项目入口

活动模型：`MODEL_V2_1_HYPOTHETICAL`  
总体状态：`INCOMPLETE`  
当前完成：修订版任务说明、活动参数登记、阶段一裸BVD，以及阶段二L型匹配网络的真实LTspice与解析交叉验证。

## 应优先阅读

1. `03_Codex任务说明_修订版_v2_1.md`：后续唯一活动任务说明。
2. `05_修订后当前项目重新审核报告.md`：当前完成度、缺口和执行顺序。
3. `v2_1_活动参数清单.json`：活动假设基线和Qm敏感性参数。
4. `run_manifest.json`：已完成阶段的软件、命令、单位和文件哈希。
5. `ltspice_stage1/V2_1_STAGE1_audit.json`：阶段一数值验收。
6. `stage2_matching/stage2_audit.json`：阶段二同源条件匹配与交叉验证验收。

## 版本隔离规则

- 本目录中名称含 `V2_1` 或 `v2_1` 的文件属于活动模型。
- `V2_BARE_BVD_Q800.*`、`freeze_parameters_v2.py`和不带`v2_1`的参数表属于被否决的0.125 W候选，状态为 `PRELIMINARY/REJECTED`，只保留为审核痕迹。
- 上级 `outputs` 中的 `single_factor_disturbance_results`、`third_step_sweep_selection`、`fourth_step_control_strategies`、`fourth_fifth_rebuild`和`fifth_step_week4_synthesis`属于旧模型 `LEGACY`。
- legacy目录中的数值图表不得复制到活动v2.1综合表；可以在报告的“方法演变/工作痕迹”部分引用，并必须标注旧模型。

## 当前可验收证据

- 真实LTspice 26.0.2命令行AC运行生成的`.cir/.raw/.log`；
- 100001点RAW；
- RAW与Python解析阻抗最大相对误差约`1.36e-7`；
- 串联谐振识别误差0%；
- 全频图、谐振区放大图、CSV、JSON和SHA-256。
- 阶段二无匹配/理想匹配/活动含损耗匹配三组真实RAW、相同源条件对比和控制源幅度校准。

## 尚未完成

- v2.1单因素、Qm敏感性与组合扰动；
- v2.1三种选频准则；
- v2.1固定/周期扫频/P&O三策略和保护状态机；
- v2.1第五步综合比较表和PPT图表；
- 最终报告要求的LTspice GUI手工截图。

在上述阶段完成前，不得把当前项目写成“全部任务完成”。
