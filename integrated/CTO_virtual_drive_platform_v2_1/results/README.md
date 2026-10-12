# 结果目录

- `tables/`：摘要CSV、审核JSON和说明Markdown；
- `phase_ablation/`：相位误差闭环消融结果；
- `run_logs/`：统一入口重新执行时捕获的stdout/stderr；
- `manifests/`：证据清单和本次运行清单。

为控制交付体积，阶段三约21 MB的全频点总表不会复制到这里，其权威原始路径仍由项目原目录保留；场景摘要、趋势表和交叉验证表会被收集。
