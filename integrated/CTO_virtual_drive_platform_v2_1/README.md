# CTO虚拟电学驱动平台：当前入口与历史分区

更新：2026-09-22（本地整合）。**已完成固定频率／周期扫频／相位误差闭环的同批次、同口径准稳态比较，并接入网页。**“尚无统一表”不再代表当前状态；不等于所有策略通过验收，也不是实物、声场或临床验证。本次不修改PPT、旧讲稿，不自动推送GitHub。

## 快速使用

在本目录打开终端：

```powershell
python -m pip install -r requirements-ui.txt
python run_project.py status
python run_project.py ui
```

浏览器打开 http://localhost:8501 。端口占用时执行 `python run_project.py ui --port 8502`。

```powershell
python run_project.py test       # 控制行为＋平台接入测试
python run_project.py validate   # 新建完整批次→逐日志复核→登记为当前结果
python run_project.py verify     # 复核当前哈希、覆盖、失败分类
```

每次validate创建新目录，失败不替换登记；`validate --suite historical`只做12段诊断，不替换完整批次。网页只读current/active_batch.json指定的结果，不根据日期猜测“最新”。证据缺失／哈希错误时停止展示，不回退旧表；代码与快照不一致时警示。

## 当前采用版本

|身份|位置|含义|
|---|---|---|
|正式命令入口|run_project.py|运行、测试、审核、登记、启动网页|
|正式网页入口|current_app.py|当前结果／版本证据／历史探索／LTspice实验|
|统一引擎|current/unified/|固定、周期扫频、相位反馈；统一执行与评分|
|采用补丁|current/patches/plan_three_strategy.scan_fault_taxonomy.patch|寻峰失败、保护抢占、测量失效、非平稳分类及有界预算|
|来源记录|current/integration_sources.json|上游提交、补丁哈希、排除范围|
|结果定位|current/active_batch.json|唯一明确批次及逐日志复核|
|历史平台|streamlit_app.py、run_all.py、results/tables/、figures/|保留旧数据；run_all是旧流水线，可能重写旧输出，本次未调用|
|负载研究原型|research/radiation_load_layer1/|参考快照，尚未接入正式控制链|

统一实现来自validation/plan-three-strategy-v1-20260917的 **650abdc87f3fcf10f5d4250aaf520efcfde3b56d**。审核分支检查至 **dd1a58eda1116e54835a97bc0afff519316bc735**，仅采用上述扫描分类补丁，不把整个审核分支视为已合并。补丁改config/controllers/metrics/tests；本次额外接入只改入口、网页、来源和报告说明，不调高限值、不延长扰动、不降低验收门槛。

## 网页可以看到

- 2026-10-06新增「参数来源登记」：参数身份、来源、单位、频段、条件与采用理由可展开；Saijo参考和待核实范围单列，文献数据不自动写回模型。见 [来源登记与使用边界](docs/参数来源登记与使用边界_20261006.md)。原BVD、控制参数及登记批次均不变。
- 原12段日程同批次三策略表，含全过程P_Rm电能、连续验收、保护前／后峰值。
- 34个登记条目×3策略的102个目标段；每条基准→目标→基准。含等价别名，不等于34种独立物理负载。
- 各日程、扰动段的频率、功率、捕获率、电压、电流、实际幅度；不删除扫描／试探／保护／渐升。
- 未通过稳态的误差及恢复时间留NA，固定尾窗诊断另列；CSV、事件、配置、报告和哈希可下载。
- 参数探索页仍可调滑块、显示源／端口功率、eta_elec、谐振特征及调用LTspice AC；不修改冻结控制批次。
- LTspice反馈页是独立固定负载接口实验，不是本批次三策略完整LTspice闭环验证。

## 科学口径

2026-10-06新增独立研究诊断：[外部拟合修正与控制效率分账](research/fit_control_diagnostics_20261006/README.md)。
Janů连续极值拟合完成合成回收、Jacobian和多初值对照；“0.22%”仅为论文计算特征点复现差异，非实测全谱误差。
统一批次105条时序已按实际时长拆分电能，正式控制参数与结果未变；未宣称新算法提高通过率。
调参/检验分组已单独登记，但既有场景过去已被观察，不是未知测试集。

假设BVD、有损L型匹配、戴维南源及Rs、小信号线性准稳态电学；不是完整射频功放、实测换能器、非线性、温升、空化、声场剂量或临床模型。

- P_source为源有功功率，P_port为端口功率，P_Rm为运动支路电阻功率；eta_elec=P_port/P_source不是电声效率。
- 相位反馈用匹配输入arg(V_input/I_source)，不是端口相位；目标基准标定后冻结，邻频试探执行记时。
- 周期扫频：±50 kHz/5 kHz → ±5 kHz/1 kHz → ±1 kHz/0.1 kHz，加有界重定位／粗扫回退。不是±100 kHz单级扫描；1.5 ms/点为时间代理假设。
- 连续验收：有效CONTROL、NORMAL、未冻结、≥98%、20 ms格点连续10样本；未通过不用回退样本。
- 参考为当前场景130 Vpp／5.5 mA软阈值、a≤1下100 Hz网格最大P_Rm；不是硬限最大值，不等于恢复基准功率。离散参考可能使比值略高于100%，不截断掩盖。
- 理想保护依赖精确当前模型。保护前预测可超过160 Vpp；保护后记录受限不证明真实动态硬限。反射代理只监测；未独立定义绝对功率上限。
- 最新5 mA RMS与50 Ω为用户推荐口径，不是实测器件额定值。本批次保留冻结假设BVD及源标定，未据此反推真实结构／模式。原配置中RMS假设文字留在快照供追溯。

## 历史保留与移交边界

静态AC、P&O、相位消融、算法组合、瞬态重放、五轮LTspice反馈、声场接口保留各自批次身份。已有真实GUI／日志截图按原版本引用，不冒充本次控制验证。旧文档“待统一”是当时状态；最新见 [当前入口与成果分区](docs/当前入口与成果分区_20260922.md)。旧PPT和讲稿不改写。

当前统一引擎可独立运行；历史探索仍依赖上级outputs/v2_self_consistent_rebuild/active_stage3_5。不能只复制本目录就宣称历史平台全功能可移植；依赖索引见current/artifact_registry.json。

本机验证Python3.12.10、NumPy2.2.4、pandas3.0.5、Streamlit1.62.0。正式准稳态运行不需LTspice，只有独立LTspice功能需本机程序及许可。
