# LTspice 第三步复核说明

## 复核方式

本次不是只用解析模型，而是实际调用本机 `D:\LTspice.exe` 批处理运行：

- `CASE_000_BASELINE.cir`
- `CASE_402_COMBINED_HIGH.cir`

运行命令形式：

```text
D:\LTspice.exe -b <case>.cir
```

LTspice 版本：`LTspice 26.0.2 for Windows`。两个 case 均返回 `exit=0`，并重新生成 `.raw`、`.log`、`.op.raw` 和 `.db`。

扫频设置：

- 范围：0.84–0.96 MHz
- 步长：0.5 kHz
- 点数：241

## RAW 选点复核结果

| case | 最大功率频率 | 最小相位频率 | 最小反射频率 | 三准则最大分裂 |
|---|---:|---:|---:|---:|
| CASE_000_BASELINE | 0.900000 MHz | 0.899997 MHz | 0.899500 MHz | 0.500 kHz |
| CASE_402_COMBINED_HIGH | 0.872000 MHz | 0.909571 MHz | 0.908500 MHz | 37.571 kHz |

结论：LTspice RAW 复核确认，高复杂度组合扰动下，“最大功率点”和“相位/反射最优点”明显不是同一个频率点。

## 固定 0.9 MHz 的 LTspice `.meas` 摘要

### CASE_000_BASELINE

- `|Z| = 57.0554339427 Ω`
- `ReZ = 57.0554324291 Ω`
- `ImZ = -0.0131420949605 Ω`
- `phase = -0.0131974560497 deg`
- `P = 0.124997663595 W`
- `Gamma = 0.0659045921882`
- `Pmax = 0.125012777293 W`

### CASE_402_COMBINED_HIGH

- `|Z| = 46.9222186033 Ω`
- `ReZ = 42.8656498125 Ω`
- `ImZ = -19.0848281315 Ω`
- `phase = -23.9997894143 deg`
- `P = 0.0152729510711 W`
- `Gamma = 0.245150723251`
- `Pmax = 0.0578792089548 W`

## 解析模型交叉验证

对 LTspice RAW 的 `zin_real、zin_imag、zin_mag、phase_deg、active_power、reflection_proxy` 做逐点对比：

- 审核行数：12
- 失败行数：0
- 阈值：相对全量程误差 `< 5e-5`

详见：

- `LTspice第三步_RAW选点对比.csv`
- `LTspice第三步_RAW逐点误差审核.csv`

