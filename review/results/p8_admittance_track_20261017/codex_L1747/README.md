# Codex 候选推导，长度改为 1.7467 mm（review/32）

物理候选 B 的 BVD 来自这次运行，平台参数文件由 `review/physical_candidate_parameters.py` 从 `candidate_parameters.json` 生成。

- 脚本：Codex 的 `derive_candidates.py`，原样，不另存一份。
  - 位置：`../../codex_baseline_review_20261016/codex_inputs/derive_candidates.py`
  - sha256：183f76411b15945031248c50daa3cbedd85f5a1f7732421d40c3f0ed36951a23
- 假设文件 `assumptions_20261016.json`：与 codex_inputs 里本仓库重建的那份只差两处，
  - `geometry.length_m` 0.0018 → 0.0017467；
  - `purpose` 一行。
- 运行：把脚本与本目录的假设文件放进一个新的空目录，执行 `python -I derive_candidates.py > run.log`。
  脚本从自身目录读假设文件，把 `candidate_parameters.json` 写在同一目录。
  2026-10-17 重跑一次，两个输出与本目录逐字节相同。
- 候选标识沿用 Codex 的 `APC880_D0.5_L1.8_front_BMF`（标识里的 1.8 mm 是它的默认长度）。
  本次运行的长度是 1.7467 mm，见 `element.length`。

sha256：

```
97346acea825c721d1b831f9aa8ce881c3330b1b446f90ed8ce004c0b0022b16  assumptions_20261016.json
574fb9c873753f41a1bd077e2a2509cc88b5839373acd202109dff58f90b0c2b  candidate_parameters.json
81e912dc94a4df6934d044d0a3d1e075a787fc4788373cf5bb232e0aa46225fe  run.log
```
