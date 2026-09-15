# 网页当前场景LTspice运行记录

本目录由Streamlit页面的“运行LTspice验证当前场景”按钮逐次创建。

每个`UI_LT_时间戳_参数哈希`目录包括：

- `UI_CURRENT_SCENARIO.cir`：由当次侧栏参数生成的独立网表；
- `UI_CURRENT_SCENARIO.raw/.log`：真实LTspice批处理输出；
- `scenario_parameters.json`：当次参数和频率设置；
- `LTspice_Python_frequency_comparison.csv`：逐频LTspice/Python对照；
- `LTspice_validation_audit.json`：返回码、误差、路径与SHA-256；
- `ltspice_stdout.txt/ltspice_stderr.txt`：外部进程输出。

这些运行记录用于交互验证，不会覆盖阶段一至三的正式验收证据。AC复相量按项目的RMS等效口径解释，不得将其称为真实功放时域波形或换能器实测数据。
