# P8 的结果（review/32）

补丁：`review/patches/platform_v2_1.p8_direct_drive_current_points_admittance_track.patch`（在 P7 之上）。
本目录的数字都在复原的平台副本（main 的 `integrated/` 加 P1–P8）上算出。这是线性 BVD 的准稳态电学结果，不是器件、声学或临床结论。

| 子目录 | 内容 | 由谁生成 |
|---|---|---|
| `codex_L1747/` | Codex 候选推导，长度改为 1.7467 mm 的运行记录；物理候选的 BVD 取自这里 | Codex 的 `derive_candidates.py`（见该目录 README） |
| `study_run1/` | 平台内对比第一轮。之后 ADMITTANCE_TRACK 又改了三处（review/32 第三节），这一轮只作记录，**被 study_run2 取代** | `review/p8_admittance_track_study.py` |
| `study_run2/` | 平台内对比的最终一轮：判据不变，代码为补丁里的最终版 | 同上 |
| `tick_sensitivity/` | 补充，不在预登记判据内：物理候选上控制采样周期 20/10/5 ms | `review/p8_tick_sensitivity.py --study study_run2` |
| `patch_check/` | 补丁核对：P7、P8 的测试与参数登记；物理候选文件逐字节复核；四种正式策略 2×140 条时序与 P7 逐字节相同 | `review/check_p8_patch.py` |
| `batches/` | 两个带 ADMITTANCE_TRACK 的完整批次的汇总文件（报告、汇总表、复核收据、清单），与 P7 的存档方式相同；执行记录与事件太大，未存 | `run_unified.py --extra-strategy ADMITTANCE_TRACK`、`audit_batch.py` |

两个批次：

- `UNIFIED_20261018T002408_829457Z_01da8553`：物理候选（`--config candidates/physical_apc880_d05_L1747/config.json`）。
- `UNIFIED_20261018T002428_639225Z_01da8553`：默认配置。

两者的复核都通过，各 175 条时序。批次标识末尾的 `01da8553` 是源码摘要，两批相同。

sha256：

```
d7ac11626ac88cd471a773266cb3bd58ed86d15b8f7a5a20ebc00f3f68177121  study_run1/p8_study.json
eb6c97565279df3d9faebe74d50d1806fe0a1ce2b94f6b95b2026b83bc28be8e  study_run1/segments.csv
508d5672b99b5d02dfd3963734ea1c1cc9f29e4665aa1d81a2aeb4d620b827a6  study_run2/p8_study.json
5ab5c5e1e80015bd31704f098c1f850c3be8c79a23509bbf029e550e3ecab596  study_run2/segments.csv
f2afed480228326f49d42080e7aed70ce1d8f2e07b17701fb3e39171bb9acbcb  tick_sensitivity/tick_sensitivity.json
be12644a20624e0c9707847bd129286eb3209c4949ed58c3520b2f2a96c5bf5a  patch_check/patch_check_p8.json
774ab237fd8fc8f69a24c722779b34bf0211b894762186751212f85a9ae7d0cc  ../../patches/platform_v2_1.p8_direct_drive_current_points_admittance_track.patch
```
