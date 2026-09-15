# v2.1汇报工作痕迹索引

## 完成状态

- 电学BVD、L型匹配、单因素/组合扰动、Qm敏感性、选频比较、三种主策略、保护状态机、相位消融和第4周综合表：已完成并重跑。
- LTspice：已真实运行，保留`.cir/.raw/.log`、交叉验证表、GUI波形和Output Log。
- ANSYS/COMSOL结构—声场：未完成真实求解。本机无软件/许可证，几何和完整材料矩阵也未冻结。第08目录只保存未完成说明、建模规格、接口模板和以后需要补拍的截图清单。

## 文件夹说明

1. `01_项目口径与参数`：活动任务说明、基线/Qm参数和模型ID。
2. `02_LTspice真实运行`：阶段一裸BVD的`.cir/.raw/.log`、审核JSON和交叉验证CSV。
3. `03_匹配网络`：活动含损耗匹配网表/RAW/LOG、匹配审核和特征表。
4. `04_扰动与Qm`：28场景登记、趋势表、Qm结果、8个LTspice代表案例的`.cir/.raw/.log`。
5. `05_选频准则`：三准则、步长/窗口汇总和审核结果。
6. `06_控制与保护`：三策略综合表、逐场景指标、保护审核和相位增益扫描。
7. `07_汇报截图`：14张可直接用于PPT/报告的有效结果图，以及1个GUI元数据JSON。
8. `08_结构声场未完成说明`：明确不能宣称已完成ANSYS/COMSOL；包含后续模型规格和截图清单。
9. `09_复现脚本`：从参数冻结到扰动、选频、控制、相位消融和GUI取证的11个脚本。

## 汇报建议插入的14张图

|序号|文件|用途|建议级别|
|---:|---|---|---|
|1|`V2_1_STAGE1_LTspice_RAW交叉验证.png`|证明裸BVD的Python/LTspice一致性|必放|
|2|`stage2_01_匹配前后输入阻抗_RAW.png`|匹配前后输入阻抗变化|必放|
|3|`stage2_02_匹配前后功率与反射_RAW.png`|匹配前后功率和反射代理|必放|
|4|`LTspice_GUI_waveform_mag_phase.png`|真实LTspice GUI运行痕迹|必放/附录|
|5|`LTspice_SPICE_Error_Log.png`|LTspice版本、求解完成和耗时|必放/附录|
|6|`stage3_01_single_factor_sensitivity.png`|单因素扰动总趋势|必放|
|7|`stage3_02_representative_responses.png`|组合扰动与代表场景曲线|必放|
|8|`stage3_03_Qm_sensitivity.png`|Qm=500/800/1000峰宽变化|必放|
|9|`stage3_selection_01_criteria_examples.png`|最大功率/最小相位/最小反射不等价|必放|
|10|`stage3_selection_02_window_step_tradeoff.png`|步长、窗口和扫描时间权衡|必放|
|11|`stage4_01_three_strategy_timeline.png`|同扰动序列三策略频率与功率时序|必放|
|12|`stage4_02_protection_state_machine.png`|foldback、跳闸、恢复和限值|必放|
|13|`stage5_01_integrated_metrics.png`|第4周综合指标比较|必放|
|14|`phase_ablation_selected_gain.png`|相位控制消融及错误锁定风险|选放|

正式汇报正文建议使用其中10–12张；剩余LTspice GUI、Error Log、相位消融和详细交叉验证可放附录。若老师要求完整技术证据，则14张全部保留。

## 除图片外必须保留的证据

1. 活动参数与任务口径：证明所有数值属于假设基线或扫描变量。
2. `.cir/.raw/.log`：证明LTspice确实运行，而不是只画Python图。
3. Python/LTspice交叉验证CSV与审核JSON：证明两个模型在相同频率网格下相符。
4. 场景登记表和趋势表：证明每个单因素只改变一个变量。
5. 三策略统一扰动序列与综合CSV：证明比较条件相同。
6. 完整复现脚本和最终SHA-256清单：证明图表能够重建。
7. ANSYS/COMSOL未完成说明：防止把文献图或代理图误写为自己的有限元结果。

## 后续必须由用户补齐的结构—声场工作痕迹

只有在实际安装ANSYS/COMSOL并完成求解后，才新增以下13项截图：

1. 软件版本/About及许可证模块；
2. 完整Project/Model Builder模型树；
3. 几何和关键尺寸；
4. 压电材料矩阵、极化方向和坐标系；
5. 电极、机械支撑、耦合面和PML边界；
6. 粗/中/细三档网格及单元统计；
7. 0.8–1.0 MHz附近模态频率列表；
8. 关键轴向/径向模态形状；
9. 压电谐响应的端口阻抗/导纳曲线；
10. 位移幅值和相位结果；
11. 声压云图、轴向剖面和观察点曲线；
12. 网格收敛表；
13. Solver Log无错误结束页面。

在这13项出现以前，只能汇报“结构—声场建模方案已准备，尚未实际求解”。
