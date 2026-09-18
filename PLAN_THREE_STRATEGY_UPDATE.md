# 计划书三策略统一验证：独立版本更新

本分支新增 `workspace/CTO_plan_three_strategy_v1_20260917/`，不替换原平台入口、不覆盖旧结果，也不合并或改写 Claude 工作分支。
根目录原有交接清单、SHA256SUMS 等仍对应原交接快照；本次新增证据使用下方独立批次的 manifest，不将旧清单冒充本分支全部文件清单。

## 本轮完成与限制

- 正式比较为固定频率＋共同保护、周期扫频＋共同保护、相位误差闭环＋共同保护；P&O保留在历史扩展研究，不替代计划书三策略。
- 共用模型、绝对日程、保护入口、实际幅度记录、测点和指标函数。
- 相位目标由基准输入相位标定后冻结；邻频斜率通过实际执行试探取得，计入时间与保护成本。
- 无效扫描拒收、失败不更新可信目标；重试间隔/预算/耗尽锁存生效；稳态指标不使用回退样本。
- 27项行为测试通过；原12段日程加34个登记场景独立覆盖，共105条时序。登记场景包含与基准重复的条目，不代表34种真实器件负载。
- **统一比较已完成，不等于所有控制策略通过验收。** 原12段日程的通过段数为固定7/12、周期扫频1/12、相位闭环6/12。参数尚未在统一框架下完成性能整定。
- 保护前旧指令在新负载下的准稳态预测最高约188.2 Vpp；不能声称守住全过程160 Vpp硬限。该数值不是实测或LTspice瞬态尖峰。
- 本轮没有重跑LTspice或COMSOL，也不代表硬件、声场、组织或临床安全验证。

## 先读这些文件

1. [交付说明与未解决问题](workspace/CTO_plan_three_strategy_v1_20260917/audits/交付说明_先读这个.md)
2. [运行方法、参数口径与参考资料](workspace/CTO_plan_three_strategy_v1_20260917/README.md)
3. [正式批次统一验证报告](workspace/CTO_plan_three_strategy_v1_20260917/outputs/UNIFIED_20260918T023347_827212Z_ff539c2c/统一验证报告.md)
4. [原12段日程三策略综合表](workspace/CTO_plan_three_strategy_v1_20260917/outputs/UNIFIED_20260918T023347_827212Z_ff539c2c/historical_12_three_strategy_table.csv)
5. [全部逐段指标](workspace/CTO_plan_three_strategy_v1_20260917/outputs/UNIFIED_20260918T023347_827212Z_ff539c2c/per_segment_metrics.csv)
6. [独立日志复算审计](workspace/CTO_plan_three_strategy_v1_20260917/audits/UNIFIED_20260918T023347_827212Z_ff539c2c_20260918T023513_221045Z.json)

## 复现

```powershell
cd workspace/CTO_plan_three_strategy_v1_20260917
python -m pip install -r requirements.txt
python run_unified.py --test-only
python run_unified.py --verify outputs/UNIFIED_20260918T023347_827212Z_ff539c2c
python run_unified.py --suite all
```

每次运行生成新批次，不覆盖已上传结果。Python 3.12 / NumPy 2.2.4 已在本机验证。
本分支上传新代码、测试、两份模型/源配置，以及**一个最终批次**的完整执行CSV、事件JSON、报告、源码快照和哈希清单；未上传重复中间批次或大型RAW。

正式批次：`UNIFIED_20260918T023347_827212Z_ff539c2c`（UTC编号）。
来源电路模型为第二轮审核冻结的v2.1模型，具体哈希见批次 `run_metadata.json` 和 `manifest.json`。

**此处为模糊推测内容**：协调重扫周期与渐升、调整相位增益/步长可能改善通过率；必须保持原扰动长度和验收门槛，另立批次验证，不能将建议当作已证实结果。
