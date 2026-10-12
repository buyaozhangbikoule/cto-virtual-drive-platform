# 2026-10-12 分层同步说明

## 正式交付内容

`main` 与 `release/verified-integration-20261012` 提供同一份已核验整合快照，入口为
`integrated/CTO_virtual_drive_platform_v2_1/run_project.py`。旧 `workspace/`、`review/`、`reports/`
及现有历史分支均不覆盖；旧主分支首页另存 `docs/history/README_main_20260915.md`。

本次交付包括：统一三策略引擎及已采用的扫描失败分类补丁、网页整合、参数来源登记、
当前批次与审计、已完成的拟合数值诊断与控制电能分账、历史页面所需轻量依赖。
拟合/分账属于完成核查的独立研究诊断，**不是新增控制算法，也不改变正式批次**。
负载层参考快照仍标为未接入，P&O/PI/去嵌相位不成为正式三策略。

## 研究候选单独保存

恢复—再次扫描候选只放在 `research/recovery-scan-handoff-unvalidated-20261012` 分支，
状态为 **UNVALIDATED_DRAFT**。尚无完整实验驱动、行为回归、开发/检验冻结及结果；
不能把候选代码存在、能导入或已上传作为性能改善证据。正式入口不导入该候选。

## 版本与验证口径

- 正式结果仍是 `UNIFIED_20260923T013352_476445Z_f442bcda`；本次不调参、不重跑新控制批次、不更新批次登记。
- `verification.json` 与同目录日志记录本次在发布副本中重新执行的证据校验、测试及105条时序分账复算。
- `source_manifest.json` 对复制的源码与已有结果逐文件校验；SHA256只证明快照完整，不证明模型真实或物理安全。
- 既有 `current/integration_sources.json` 中 `github_pushed: false`、旧README中“不推送GitHub”等文字保留为当时的历史记录。本次发布身份以仓库根目录 `CURRENT_RELEASE.json` 为准，不反写旧批次证据。
- “已验证正式交付”指软件测试、证据完整性和限定范围复算，不表示所有控制策略通过连续稳态，不证明硬件瞬态、采样间隙或临床安全。
- 既有源/匹配/BVD与控制阈值保持原假设身份。没有引入实测器件标定或声学结论。

## 有意不重复上传

本次新增快照不含大型RAW、TIFF、数据库缓存、PDF/Word文献、PPT、安装包、凭据及临时环境。
历史RAW请按历史Release说明取得；缺失的RAW不由本次轻量副本替代。页面可运行不代表LTspice已安装，
LTspice实验需要接收方另行配置本机可执行文件；本次也未重跑LTspice。

`integrated/` 下的模型、历史结果和依赖必须保持相对布局。请勿只复制一个入口脚本。
旧流程脚本与旧生成日志仍保留绝对路径作出处；正式使用以 `run_project.py` 为入口。
