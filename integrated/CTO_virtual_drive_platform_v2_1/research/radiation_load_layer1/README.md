# 第一层负载参考：未接入正式控制链

本目录是审核分支负载原型及处置说明的逐字快照，来源与SHA-256见source_manifest.json。不是当前BVD模型的替换，也未改变统一34条目的参数。

在平台根目录只读运行参考程序：

```powershell
python research/radiation_load_layer1/radiation_load_layer1_reference.py --model current/unified/models
```

特殊函数检查可用 `--self-check-only --cross-check`。研究脚本参数均为声明／假设；未指定真实结构、极化、模式、介质边界和热工况。数值自洽不等于物理器件已辨识，辐射分量不等于验证过的靶区声功率。

`test_radiation_load_audit_regression.py`保留上游原件，依赖原仓库workspace相对布局；其保存日志为历史2026-09-22审核证据，本次不冒充再次运行。正式入口不会导入或执行本目录。
