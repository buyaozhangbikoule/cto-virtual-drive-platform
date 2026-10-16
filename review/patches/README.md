# review/patches 目录索引

补丁按「作用对象」分组。状态以本文为准；被取代的补丁保留原文作审查记录，**不要再应用**。

## 正式平台 `integrated/CTO_virtual_drive_platform_v2_1/`（main）

| 文件 | 内容 | 状态 | 说明 |
|---|---|---|---|
| `platform_v2_1.p1_config_driven_parameters.patch` | 参数从配置与设计文件读取（数值不变）、网页限值线跟随批次配置、报告另列功放输出端电流、来源登记修正（5 mA 测点未定） | **待合入，第 1 个** | review/26；默认结果与原源码逐字节相同 |
| `platform_v2_1.p2_phase_centre_recovery_gate.patch` | 相位反馈中心恢复门控，配置开关，默认关 | **待合入，第 2 个**（在 P1 之上） | review/26；默认逐字节不变，开启时与 v2 候选逐字节相同 |
| `platform_v2_1.p3_synthetic_candidate_q13p8_3mA.patch` | 可选的合成候选配置 `candidates/synthetic_q13p8_3mA/`（Q≈13.8、3 mA、4.5/5.0 mA、门控开），不设为默认 | **待合入，第 3 个**（在 P2 之上） | review/26；候选批次与 55fbe6e 审查过的批次一致 |
| `platform_v2_1.physical_baseline_3mA_phase_gate.patch` | 55fbe6e 的组合补丁：把 Q=13.8、3 mA 当成默认「物理基线」并改限值、加门控 | **已作废，勿应用** | review/25；审查意见与改正见 review/26 |

sha256：

```
26293d65ca648aac3a2548a746045b1703edb94181aaf6dc0457099ae3dab712  platform_v2_1.p1_config_driven_parameters.patch
adb206ae06a2d964ae6d5f02677a3d090ba54fe1c30fd192a6c909ccded36af2  platform_v2_1.p2_phase_centre_recovery_gate.patch
95b9553ede9a398ae2b96e81be935fc74ca44fc2b15fa40bcd6dca6b0aa4cffb  platform_v2_1.p3_synthetic_candidate_q13p8_3mA.patch
7d7c8f9e08862d49e59ca95452f040b42e6ed2200086add0497cf3ee5e88b2ed  platform_v2_1.physical_baseline_3mA_phase_gate.patch（作废）
```

在仓库根目录按 P1→P2→P3 依次 `git apply`，每步之后在 `integrated/CTO_virtual_drive_platform_v2_1/` 下运行
`python run_project.py validate`，并把补丁拷进 `current/patches/`、在 `current/integration_sources.json` 追加来源与哈希。

## 早期补丁

| 文件 | 作用对象 | 状态 | 说明 |
|---|---|---|---|
| `plan_three_strategy.scan_fault_taxonomy.patch` | 验证分支 `validation/plan-three-strategy-v1-20260917` 的三策略统一引擎 | 已在 2026-09-22 整合进正式平台 | review/13；见 main 的 `current/integration_sources.json` |
| `run_stage4_5_control.edge_aware_scan.patch` | 历史 workspace 的 `stage4_5_control`（工作副本） | 历史记录 | review/07 |
| `run_phase_hold_ablation.py` | 历史 workspace 的第四消融项脚本（新文件） | 历史记录 | review/08 |
