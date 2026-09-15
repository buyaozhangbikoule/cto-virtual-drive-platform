# 电学—结构/声场文件接口 EA_IF_V1.0

本目录把v2.1电学结果整理为可被COMSOL或ANSYS谐波压电—结构—声场模型读取的**数据契约**。当前没有运行任何结构或声场求解器。

## 文件

- `electrical_to_acoustic_operating_points.csv`：基准及低/中/高组合场景的安全功率峰值电学工作点。
- `acoustic_results_return_template.csv`：未来结构/声场求解结果的回填模板，当前全部标记为`NOT_RUN`。
- `coupled_lookup_template.csv`：计划书要求的紧凑接口；频率、幅度和电学功率已填，声学效率及靶区/壁面压力代理保持空值。
- `interface_field_dictionary.csv`：字段、单位、是否必填和来源口径。
- `electro_acoustic_schema.json`：机器可读字段定义。
- `interface_contract.json`：耦合方式、禁止替代和所需求解证据。

## 在COMSOL/ANSYS中的使用原则

1. 以`record_id`为主键建立谐波工况。
2. 使用`frequency_Hz`设置求解频率。
3. 使用`vport_Vrms_real/imag`或等价的幅值/相位作为端子电压激励；不要同时强制施加预测电流。
   导出采用RMS等效`exp(+jωt)`约定；若求解器采用相反时间因子，应对相量取共轭，并用基准端口电流检查符号。
4. 求解器输出端子电流后，计算FEM端口阻抗并与`zport_*`进行同工况校核。
5. 将位移、目标点声压、壁面声压和积分声功率写回返回模板。
6. 保留模型版本、网格ID、收敛指标和Solver Log。

## 严格边界

`p_rm_W`是BVD运动支路电阻耗散，不能直接当成辐射声功率；`eta_elec`是电学传输效率，不能当成声电转换效率；`reflection_proxy_gamma`不是实测反射功率。

接口审核：`C:\Users\24739\Documents\Codex\2026-08-10\new-chat\CTO_virtual_drive_platform_v2_1\results\interfaces\electro_acoustic_v1\electro_acoustic_interface_audit.json`。审核PASS只证明电学导出内部一致，并不表示结构/声场计算已经完成。
