> **〔已作废的 L3 部分 2026-10-14〕本目录的四个 `L3 重冻结 *` 变体由带缺陷的脚本生成。**
> `run_hybrid` 在扫描成功后用 `PHASE_TARGET_CAPTURE` 刷新了相位目标 `tp`，却没有同步刷新 `last`，
> 于是下一次 `probe_update` 用**扫描前、旧中心**的测量算相位误差，却围绕**新中心**布置左右探针
> （全程 33 次，其中 19 次误差超死区而真正进入探针流程）。
> `hold=True` 时恢复门控恰好把这条路径挡住了，所以门控看起来值 +11.75 pp，
> 而它自身的贡献只有 +0.53 pp。该缺陷由 2026-10-14 的外部审核发现，复算成立。
>
> **L3 四行的通过段数、能量与保护前峰值一律改用
> `review/results/amplitude_recovery_20261014_freshness_fixed/`。**
> 本目录按仓库惯例保留，不被覆盖，仅作历史记录与缺陷证据。
> `A`、`L1 死区 *`、`L2 *` 六个纯相位变体不走扫描分支，不受此缺陷影响，数值与新目录逐位相同。
> 处置见 `review/21`。

# 幅度恢复门控对照批次（2026-10-13）

`review/19` §4 的全部数字由本目录支撑。由
`python review/amplitude_recovery_study.py --root <unified 源目录> --out review/results/amplitude_recovery_20261013`
生成。脚本默认只读；只有显式给 `--out` 才落盘，且拒绝写入任何 `workspace/` 或 `outputs/` 路径。

## 先核基线再比数字

`provenance.json` 的 `source_hashes` 与已登记批次
`UNIFIED_20260923T013352_476445Z_f442bcda` 的 `run_metadata.json` → `source_hashes`
**逐条相同**（`config.json` `7ec2b3a9…`、`controllers.py` `a416c98b…`、`engine.py` `54659dd6…`、
`metrics.py` `5234fdf8…`、`models/model_v2_1.py` `ecf0fdae…`）。
`provenance.json` 里的 `source_root` 指向一个临时解包目录，内容取自 `origin/main` 的
`integrated/CTO_virtual_drive_platform_v2_1/current/unified/`，以哈希为准，不以路径为准。

口径：日程 `cfg['historical_schedule']`（12 段 × 0.8 s）；评分一律
`metrics.evaluate(rows, events, cfg, metrics.references(cfg))`；
参考功率是 100 Hz 网格上 `p_rm_W·a²` 的峰值，`a = min(1, Vsoft/Vport, Isoft/Iport)`，
不是裸 `p_rm_W`。冻结相位目标 −1.0782096368565852°。

**自证条件：`A 原样 (死区 0.10°)` 必须是 6/12、57.34%。** 若复算不出这两个数，
本目录其余数字一律不作证据。

## 文件

| 文件 | 内容 |
|---|---|
| `provenance.json` | 源码哈希、日程、评分口径、冻结目标、Python/NumPy 版本 |
| `overall_metrics.csv` | 10 个变体的全局指标（含最大施加幅度、保护前峰值、实际硬越限） |
| `per_segment_metrics.csv` | 10 个变体 × 12 段的平台原生逐段指标，首列为 `variant` |
| `configuration.json` | 本次使用的完整 `config.json` |
| `<变体>_events.json` | 10 个变体的完整事件流 |
| `<变体>_executions.csv` | 6 个变体的完整执行行（格式同 `run_unified.py`） |

执行表只保留需要逐行追踪的六个：`A 原样`（口径自证与第 7 段棘轮轨迹）、
`L2 改频后等升幅停止`（建议本体）、以及四个 `L3 重冻结`（§4.3 的 0.88 pp / 11.75 pp 减法）。
`L1 死区 0.3°/1.0°/3.0°` 与 `L2 + 死区 1.0°` 的执行表已删除以控制体积，
它们的事件流与逐段指标仍完整保留。

## 关键行定位

- 第 7 段幅度棘轮：`A_原样_(死区_0.10_)_executions.csv` 中 `segment_index == 7`、
  `kind == CONTROL` 的行。`start_us` 5 600 000–6 400 000。
  看 `applied_amplitude` 从 `0.783118` 起 400 ms 不变，而 `protection_state` 报 `NORMAL`。
- L2 的释放：`L2_改频后等升幅停止_executions.csv` 同一段，
  配合 `L2_改频后等升幅停止_events.json` 里的 `AMPLITUDE_SETTLED` 事件。
- §4.3 的减法：`overall_metrics.csv` 四行 `L3 重冻结 *` 的 `energy_capture_pct`
  （30.57 / 41.73 / 31.45 / 43.20）。

## 边界

本目录是研究原型的对照批次，**不是正式批次**，没有执行 `protocol.md` 的
开发／冻结／检验分离流程，不能据此替换正式三策略。
数字限于本 12 段历史日程与 9 个已见场景，基于假设 BVD 参数的电学仿真；
非实测器件、非声学验证、无 LTspice 瞬态核对。
