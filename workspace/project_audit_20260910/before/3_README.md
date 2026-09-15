# CTO超声换能器虚拟阻抗建模与自适应驱动控制平台原型 v2.1

## 1. 这是什么

这是对现有成果的统一封装和证据索引，不是商业软件，也不是实物控制器。平台由LTspice电路仿真、Python解析模型、扰动与控制脚本、表格、图片和证据清单构成。

研究范围严格限定为：**假设BVD参数、有损L型匹配网络、戴维南电压源及串联源阻抗、小信号线性电路、离散准稳态控制仿真**。这里的源阻抗不是完整功放模型；没有换能器实测数据，也不包含功放开关与反馈、温升、空化、组织热效应、声场剂量或临床结论。

## 2. 目录

```text
CTO_virtual_drive_platform_v2_1/
├─ config.yaml                 统一口径、执行步骤和证据收集规则
├─ run_all.py                  一键运行、收集和哈希登记入口
├─ streamlit_app.py            可选的假设参数交互扫描界面
├─ scripts/ltspice_bridge.py   网页当前场景→LTspice批处理→RAW解析桥接
├─ interfaces/electro_acoustic_v1/ 电学→结构/声场文件接口与空白回传模板
├─ requirements.txt            Python依赖
├─ models/                     BVD模型与LTspice网表副本
├─ scenarios/                  扰动场景登记表
├─ scripts/archived_sources/   本次整理时的脚本快照
├─ evidence/ltspice/           RAW、LOG及交叉验证证据
├─ results/                    CSV、报告、运行日志和manifest
└─ figures/                    可用于论文/PPT的数据派生图
```

`scripts/archived_sources`用于审阅和归档；统一入口执行的是`config.yaml`中登记的原始权威脚本，从而避免归档副本与当前计算链分叉。

## 3. 快速使用

在本目录打开PowerShell：

```powershell
python run_all.py --list
python run_all.py --collect-only
python run_all.py --dry-run
python run_all.py
```

- `--collect-only`：不重跑仿真，只把现有结果整理进统一目录并生成SHA-256证据清单。
- `--dry-run`：显示完整的一键运行顺序，不执行。
- 不带参数：重新运行阶段一至五和相位闭环消融，然后重新收集结果。
- 只运行部分步骤示例：

```powershell
python run_all.py --steps stage3_selection,stage4_5_control
```

可选启动轻量参数界面：

```powershell
python -m pip install -r requirements-ui.txt
python -m streamlit run streamlit_app.py
```

该界面读取权威v2.1解析模型，允许交互改变扫描变量、查看曲线和导出CSV。点击“运行LTspice验证当前场景”后，会在`results/interactive_ltspice/`新建独立运行目录，保存网表、RAW、LOG、逐频对照CSV和审核JSON；不会覆盖阶段一至三的正式验收结果，也不是硬件实时控制界面。

网页LTspice验证的输出分为四页：端口电压/电流，匹配网络输入与换能器端口阻抗，端口/运动支路有功功率与反射代理，以及误差/返回码/路径/SHA-256。实线为真实LTspice RAW，虚线为相同参数下的Python解析结果。这里仍是AC扫频复相量，不是`.tran`时域波形。

## 4. 软件要求

- Python 3.10或以上；
- numpy、scipy、matplotlib；
- LTspice命令行程序，当前登记路径为`D:/LTspice.exe`。

安装Python依赖：

```powershell
python -m pip install -r requirements.txt
```

如LTspice路径不同，修改`config.yaml`中的`runtime.ltspice_executable`。`config.yaml`使用JSON语法；JSON本身是合法的YAML 1.2，因此入口只依赖Python标准库，不需要PyYAML。

## 5. 正式计算链

1. 裸BVD网表重新运行，并用Python解析式核对阻抗与相位；
2. 重建v2.1有损L型匹配，统一源条件后重跑匹配前、理想匹配和活动匹配；
3. 完成单因素、组合扰动和Qm=500/800/1000敏感性；单因素正式登记中包括机械支路电感`L_m（Lm-only）`与机械支路电容`C_m（Cm-only）`各+5%、+10%、+20%；低、中、高三档组合扰动均已完成LTspice/Python交叉验证；
4. 比较最大有功功率、最小绝对相位、最小反射代理三种选频准则，以及步长/窗口权衡；
5. 在同一绝对时间扰动序列下比较固定频率、周期扫频、扫描辅助P&O，并执行保护状态机；扫描辅助P&O只使用端口可观测量和安全限事件触发，不读取场景切换时刻或真实最优功率；
6. 单独运行相位误差闭环消融，不把它混入正式三策略排名；
7. 自动收集表格、图片、RAW、LOG，并登记源路径和SHA-256。
8. 审核控制约束，并导出基准及低/中/高组合场景的结构—声场谐波激励接口。

## 6. 结果口径

- 控制目标：当前扰动场景下的**安全最大运动支路有功功率**；
- 源模型：理想正弦电压源串联`Rs`的戴维南等效，不代表完整功放；
- 功率定义：`P_source`为理想戴维南源给出的有功功率，`P_port`为换能器端口吸收的有功功率，`P_Rm`为BVD运动支路电阻吸收的有功功率；
- 电学传输效率：`eta_elec=P_port/P_source`，只是戴维南源至换能器电端口的有功功率比例，不是电声转换效率；`P_Rm/P_source`如需使用必须另行标成运动支路功率比例；
- 换能器端口相位定义：`arg(Vport/Iport)`，正值表示感性；
- 匹配网络输入相位定义：`arg(Z_in)`，表示戴维南源所见输入阻抗的相位；
- 谐振状态采用多特征描述：至少并列报告运动支路功率峰值、输入阻抗幅值极值、匹配网络输入相位 `arg(Z_in)` 的零点/最小绝对相位和最小反射代理点；这些频率不要求重合；
- 当前页面中的相位量统一指匹配网络输入端、戴维南源所见的 `arg(Z_in)`，不是换能器端口相位 `arg(V_port/I_port)`；
- 反射量是基于指定参考阻抗计算的电学代理，不等同于实测反射功率；
- 100%功率捕获率表示达到当前场景自身的安全最优值，不表示恢复基准场景的绝对功率；
- 保护阈值全部是本轮假设控制阈值，不是器件或临床安全额定值。
- 扰动检测量：`P_port/a²`、复阻抗变化、相位变化、反射代理以及电压/电流限值事件；
- 扰动触发：四项状态变化中至少两项连续3个20 ms控制样本异常，或发生软/硬限事件；扫描后冷却0.4 s；
- 稳定参考：仅在NORMAL、幅度稳定且非扫描/非P&O试探条件下建立或以`alpha=0.02`缓慢更新，其余状态冻结；
- 上述10%、15%、5°、反射代理0.20等检测阈值均为假设控制阈值，尚未通过实测噪声和硬件延迟整定。

## 7. 必须保留的严谨表述

当前正式三策略是：固定0.9 MHz、周期局部扫频、扫描辅助P&O。原计划中的相位误差闭环已保留为独立消融验证，但没有替代正式最大功率策略，也不应把“零相位”写成必然等于“最大功率”。

为补齐计划书原始“固定—周期扫频—相位闭环”口径，另从相同代表扰动时间表的保存时序重算了恢复时间、峰值电流和功率指标，输出为`results/tables/stage4_5/plan_fixed_periodic_phase_*.csv`。这些文件明确标成补充比较，不改变正式三策略集合，也不声称覆盖全部34个扰动场景。

控制器信息边界已经拆开：扰动时间表只负责驱动仿真对象，`P*`、场景编号和真实扰动边界只用于事后评分；P&O的重捕获入口只接受可观测2-of-4检测结果或安全限事件。当前P&O比较的是幅度平方归一化的端口有功功率，不再使用模型内部的真实最优功率作为触发条件。

`Lm-only`表示只改变机械支路电感`L_m`并冻结`C_0/R_m/C_m`；`Cm-only`表示只改变机械支路电容`C_m`并冻结`C_0/R_m/L_m`。匹配电容始终另记为`C_match`，不得与`C_m`混写。两种only扰动的`f_s`和`Q_m`均作为派生量重新计算。它们与既有`f_s`扫描不是同一扰动口径：后者指定`f_s`变化，并在保持`R_m、Q_m`时联合反推`L_m、C_m`。

所有PNG/PDF/SVG均为脚本从仿真数据生成的图，不得称为LTspice GUI截图。真正的软件操作截图仍需在LTspice窗口中由使用者截取；RAW、LOG、网表和哈希清单则属于可计算核验的工作痕迹。

## 8. 从哪里看工作痕迹

- `results/manifests/evidence_manifest.csv`：每个整理文件的原始路径、类别、状态、大小和SHA-256；
- `results/manifests/platform_run_manifest.json`：本次整理/运行模式、总体审核状态；
- `evidence/ltspice`：真实LTspice RAW和LOG；
- `figures`：由RAW或Python计算数据生成的正式图；
- `results/tables`：扰动、选频、控制与综合比较表。
- `results/interactive_ltspice`：网页按钮产生的逐次独立LTspice网表、RAW、LOG、对照CSV与审核JSON；
- `results/audits/constrained_control_audit.json`：证明频率边界、电压/电流硬限、幅度降额和保护状态机实际进入保存时序的审核；
- `results/audits/plan_control_coupling_audit.json`：按计划书逐条标记完成、部分完成和未开始；
- `interfaces/electro_acoustic_v1`：复端口电压激励、字段字典、耦合查找表空模板及声场结果回传模板。

新增的参数—有功功率峰值折线图位于`figures/stage3_disturbance/parameter_peak_trends/`：

- `stage3_05_parameter_peak_trends_absolute`：共享mW纵轴，用于正式比较影响强弱；
- `stage3_06_parameter_peak_trends_relative_zoom`：各面板独立纵轴，用于观察微小相对变化；
- 生成脚本：`scripts/plot_parameter_peak_trends.py`；
- 源数据：`results/tables/stage3_disturbance/stage3_parameter_peak_trends_source.csv`。

机械支路电容`C_m（Cm-only）`专项图位于`figures/stage3_disturbance/cm_only/`，同时给出`P_Rm(f)`、未限幅端口电压和端口电流，并标出130/160 Vpp与5.5/6 mA RMS假设阈值。峰值频率按0.1 kHz扫描网格显示为4位MHz小数，PPT功率值保留0.1 mW；原始CSV继续保留完整浮点数。

如果证据清单出现`WARNING`，必须在汇报前阅读其`note`字段，不应删除或隐藏异常记录。
