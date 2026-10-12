# LTspice GUI证据使用说明

## 可用于报告的最终截图

- `LTspice_GUI_waveform_mag_phase.png`：真实LTspice 26.0.2 GUI，从活动批处理RAW的证据副本载入`mag(V(n_port))`和`ph(V(n_port))`。
- `LTspice_SPICE_Error_Log.png`：同一证据副本的SPICE Output Log，包含版本、启动时间、求解器和总耗时。
- `LTspice_GUI_evidence_metadata.json`：记录活动源`.cir/.raw/.log`与GUI副本的SHA-256。`source_raw_sha256`和`source_log_sha256`应分别与`stage3_disturbance/stage3_audit.json`的基准案例一致。

## 不用于报告的自动化中间图

- `LTspice_GUI_waveform_V_n_port.png`：自动切换窗口时被桌面前景遮挡，保留作失败工作痕迹，不得插入报告。
- `LTspice_GUI_baseline_netlist.png`：文件名沿用早期脚本，本轮实际内容为波形页；最终报告统一使用重新命名的`LTspice_GUI_waveform_mag_phase.png`。

GUI截图是补充证据；正式数值仍以`.cir/.raw/.log`、交叉验证CSV和哈希清单为准。
