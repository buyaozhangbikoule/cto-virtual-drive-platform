# review/patches 目录索引

补丁按「作用对象」分组。状态以本文为准；被取代的补丁保留原文作审查记录，**不要再应用**。

## 正式平台 `integrated/CTO_virtual_drive_platform_v2_1/`（main）

| 文件 | 内容 | 状态 | 说明 |
|---|---|---|---|
| `platform_v2_1.p1_config_driven_parameters.patch` | 参数从配置与设计文件读取（数值不变）、网页限值线跟随批次配置、报告另列功放输出端电流、来源登记修正（5 mA 测点未定） | **待合入，第 1 个** | review/26；默认结果与原源码逐字节相同 |
| `platform_v2_1.p2_phase_centre_recovery_gate.patch` | 相位反馈中心恢复门控，配置开关，默认关 | **待合入，第 2 个**（在 P1 之上） | review/26；默认逐字节不变，开启时与 v2 候选逐字节相同 |
| `platform_v2_1.p3_synthetic_candidate_q13p8_3mA.patch` | 可选的合成候选配置 `candidates/synthetic_q13p8_3mA/`（Q≈13.8、3 mA、4.5/5.0 mA、门控开），不设为默认 | **待合入，第 3 个**（在 P2 之上） | review/26；候选批次与 55fbe6e 审查过的批次一致 |
| `platform_v2_1.p4_power_drop_capture_and_phase_newton_v2.patch` | 功率下降触发的全频带捕获程序；相位反馈第二定律 newton_v2（换能器端相位可选、目标可在捕获后重学、步长按实测斜率归一化）；`Measurement.phase_port_deg`；28 个新数值配置项及登记；配置开关，默认仍为原定律 | **待合入，第 4 个**（在 P3 之上） | review/27；原三种策略两种基线各 105 条逐字节不变 |
| `platform_v2_1.p5_capture_po_fourth_strategy.patch` | 第四种正式策略 CAPTURE_PO（捕获＋P&O 跟踪、停驻、记忆召回）；平台正式策略集合改为四个（证据核对、网页、测试） | **待合入，第 5 个**（在 P4 之上） | review/27；原三种策略逐字节不变；只有三种策略的旧批次判为不完整，合入后须 `run_project.py validate` |
| `platform_v2_1.p6_formal_phase_port_relearn.patch` | 只改配置：正式 PHASE_FEEDBACK 改为换能器端相位＋捕获后重学；原定律可由配置选回 | **待合入，第 6 个，可不打**（在 P5 之上） | review/27；FIXED、PERIODIC_SCAN 与 P3 相同，CAPTURE_PO 与 P5 相同，选回原定律时 PHASE_FEEDBACK 与 P3 相同 |
| `platform_v2_1.p7_user_current_limit_transducer_port.patch` | 用户 5 mA 上限的测点在换能器端：配置记录 `user_current_limit_Arms`，报告逐策略核对与 `user_current_limit_check.csv`，复核逐条重数，网页上限线，来源登记改绑；不改限值与控制行为 | **待合入，第 7 个**（在 P6 之上；不打 P6 时可直接打在 P5 之上） | review/28；两种基线四种策略 2×140 条时序与 P6（或 P5）逐字节相同 |
| `platform_v2_1.physical_baseline_3mA_phase_gate.patch` | 55fbe6e 的组合补丁：把 Q=13.8、3 mA 当成默认「物理基线」并改限值、加门控 | **已作废，勿应用** | review/25；审查意见与改正见 review/26 |

sha256：

```
26293d65ca648aac3a2548a746045b1703edb94181aaf6dc0457099ae3dab712  platform_v2_1.p1_config_driven_parameters.patch
adb206ae06a2d964ae6d5f02677a3d090ba54fe1c30fd192a6c909ccded36af2  platform_v2_1.p2_phase_centre_recovery_gate.patch
95b9553ede9a398ae2b96e81be935fc74ca44fc2b15fa40bcd6dca6b0aa4cffb  platform_v2_1.p3_synthetic_candidate_q13p8_3mA.patch
76a13949c0981c17cbce1220f0710e10e36de84b5dcd8ccccd7b5df55da2faed  platform_v2_1.p4_power_drop_capture_and_phase_newton_v2.patch
b92692df2a340f475899b491fbaed445a47d55a2aa1b46672934dac7eac41827  platform_v2_1.p5_capture_po_fourth_strategy.patch
4bceb56333d5b32578542ca6e6074e9426778fc3753e6742ecaea4e260d7f88c  platform_v2_1.p6_formal_phase_port_relearn.patch
d8e17ff6e69a8aedf28e8cfe15e95f0bb3e5a89709774593f2fe65c7ea6c8f2b  platform_v2_1.p7_user_current_limit_transducer_port.patch
7d7c8f9e08862d49e59ca95452f040b42e6ed2200086add0497cf3ee5e88b2ed  platform_v2_1.physical_baseline_3mA_phase_gate.patch（作废）
```

在仓库根目录按 P1→P2→P3→P4→P5→P6→P7 依次 `git apply`（P6 可不打，P7 可直接打在 P5 上），每步之后在 `integrated/CTO_virtual_drive_platform_v2_1/` 下运行
`python run_project.py validate`，并把补丁拷进 `current/patches/`、在 `current/integration_sources.json` 追加来源与哈希。

## 早期补丁

| 文件 | 作用对象 | 状态 | 说明 |
|---|---|---|---|
| `plan_three_strategy.scan_fault_taxonomy.patch` | 验证分支 `validation/plan-three-strategy-v1-20260917` 的三策略统一引擎 | 已在 2026-09-22 整合进正式平台 | review/13；见 main 的 `current/integration_sources.json` |
| `run_stage4_5_control.edge_aware_scan.patch` | 历史 workspace 的 `stage4_5_control`（工作副本） | 历史记录 | review/07 |
| `run_phase_hold_ablation.py` | 历史 workspace 的第四消融项脚本（新文件） | 历史记录 | review/08 |
