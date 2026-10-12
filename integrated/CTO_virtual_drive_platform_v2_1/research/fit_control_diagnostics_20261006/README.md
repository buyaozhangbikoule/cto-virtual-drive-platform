# 独立研究版：外部拟合修正＋控制效率分账（2026-10-06）

本版不改正式引擎、不切换登记批次、不覆盖历史数据。不修改PPT，不推送GitHub。

## 先看结果

- [Janů拟合修正与验证](output/01_Janu拟合修正与验证.md)：连续定位、Jacobian、残差尺度、12初值及合成回收。
- [控制耗时与电能分解](output/02_控制耗时与电能分解.md)：105条时序总账复核；12段三策略逐阶段损失。
- [前瞻性调参/检验隔离协议](validation_protocol.json)：设计已冻结，候选尚未执行。不是未知器件盲测。

## 在平台根目录复算

```powershell
python -B -X utf8 research/fit_control_diagnostics_20261006/run_fitting.py
python -B -X utf8 research/fit_control_diagnostics_20261006/control_accounting.py --all-suites
python -B -X utf8 research/fit_control_diagnostics_20261006/make_reports.py
python -B -X utf8 -m unittest discover -s research/fit_control_diagnostics_20261006 -p "test_*.py" -v
python -B -X utf8 run_project.py verify
```

实际拟合环境：Python 3.12.10、NumPy 2.2.4、SciPy 1.17.1。控制分账脚本仅用标准库与平台只读目录模块。
数值实验所用版本另记于JSON。已有依赖时不必重新安装；独立环境可参考本目录requirements.txt。

`input_reference/`为原审核文件逐字副本，便于整个平台迁移；旧脚本的陈述是历史记录，不代表新结论。
旧脚本的旧目录依赖仅在内存中重绑定到冻结平台模型，原文件不被修补。原件仍在工作区
`report_0928/output/evidence/review/validate_against_janu2021.py` 与
`literature_project_review_20261006/02_当前模型参数迁移与代码核对.md`。

## 输出身份

|位置|身份|
|---|---|
|output/fitting/results.json|第一次合成门禁失败记录；不是交付候选|
|output/fitting_v2/results.json|最终完整对照；保留旧尺度失败与全部初值|
|output/control/results.json|登记批次105条时序的只读分账，不是新仿真|
|output/control/*_labelled.csv|原12段每行的阶段标签与功率；原始CSV不变|
|validation_protocol.json|今后的调参/检验划分，未执行新控制器|

## 不可越过的解释边界

- “0.223913%”是论文计算特征点复现差异，不是实测全谱拟合误差。
- 合成36/36回收只证明限定无噪声模型和初值设计内的数值回收，不证明参数真实性。
- 加强频率权重会牺牲其他特征，不能把目标权重称为测量不确定度。
- 分账反映损失发生在哪个执行阶段，不直接证明原因或可节省量。检测等待无独立记录，标NA。
- 现有12段和34登记场景过去都已被观察；新划分只用于今后调参隔离，不能包装为未知盲测。
- 当前没有新控制效率提升结论，仍保留正式7/12、1/12、6/12结果。下一步才做单变量候选对照。
