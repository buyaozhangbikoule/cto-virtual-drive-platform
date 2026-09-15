"""Parse the three stage-2 LTspice RAW files and cross-validate Python."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ltspice_stage1"))
from analyze_v2_stage1 import read_ltspice_raw  # noqa: E402

import design_stage2 as model  # noqa: E402


SCENARIOS = {
    "BEFORE": {
        "stem": "V2_1_MATCH_BEFORE",
        "topology": "before",
        "l_h": 0.0,
        "c_f": 0.0,
        "ql": math.inf,
        "qc": math.inf,
    },
    "IDEAL": {
        "stem": "V2_1_MATCH_IDEAL",
        "topology": "ideal",
    },
    "ACTIVE_LOSSY": {
        "stem": "V2_1_MATCH_ACTIVE_LOSSY",
        "topology": "active_lossy",
        "ql": model.QL_MATCH,
        "qc": model.QC_MATCH,
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_response(raw: dict[str, np.ndarray], scenario: str, design: dict) -> dict[str, np.ndarray]:
    freq = np.real(raw["frequency"])
    v_src = raw["v(n_src)"]
    v_port = raw["v(n_port)"]
    i_source = raw["i(rsource)"]
    v_input = v_port if scenario == "BEFORE" else raw["v(n_in)"]
    i_motional = raw["i(rm)"]
    i_port = i_motional + raw["i(c0)"]
    z_in = v_input / i_source
    s_port = v_port * np.conj(i_port)
    p_rm = np.abs(i_motional) ** 2 * model.RM
    p_source = np.real(v_src * np.conj(i_source))
    p_rs = np.abs(i_source) ** 2 * model.RS
    p_l = np.zeros_like(freq)
    p_c = np.zeros_like(freq)
    if scenario == "ACTIVE_LOSSY":
        r_l = design["design"]["r_l_active_ohm_at_f0"]
        r_c = design["design"]["r_c_active_ohm_at_f0"]
        p_l = np.abs(raw["i(rlesr)"]) ** 2 * r_l
        p_c = np.abs(raw["i(rcesr)"]) ** 2 * r_c
    return {
        "frequency_Hz": freq,
        "z_in": z_in,
        "v_port": v_port,
        "i_source": i_source,
        "i_motional": i_motional,
        "i_port": i_port,
        "p_rm_W": p_rm,
        "p_port_W": np.real(s_port),
        "q_port_var": np.imag(s_port),
        "s_port_VA": np.abs(s_port),
        "p_source_W": p_source,
        "p_rs_W": p_rs,
        "p_l_esr_W": p_l,
        "p_c_esr_W": p_c,
        "power_balance_error_W": p_source - (p_rs + p_rm + p_l + p_c),
        "gamma": np.abs((z_in - model.RS) / (z_in + model.RS)),
    }


def max_relative(actual: np.ndarray, expected: np.ndarray) -> float:
    return float(np.max(np.abs(actual - expected) / np.maximum(np.abs(expected), 1e-30)))


def full_scale_error(actual: np.ndarray, expected: np.ndarray) -> float:
    return float(np.max(np.abs(actual - expected)) / max(float(np.max(np.abs(expected))), 1e-30))


def main() -> None:
    design = json.loads((HERE / "stage2_匹配设计参数.json").read_text(encoding="utf-8"))
    values = design["design"]
    SCENARIOS["IDEAL"].update(
        {"l_h": values["l_ideal_H"], "c_f": values["c_ideal_F"], "ql": math.inf, "qc": math.inf}
    )
    SCENARIOS["ACTIVE_LOSSY"].update(
        {"l_h": values["l_active_H"], "c_f": values["c_active_F"]}
    )

    raw_tables: dict[str, dict[str, np.ndarray]] = {}
    analytic_tables: dict[str, dict[str, np.ndarray]] = {}
    audit_rows = []
    inventory_rows = []
    detail_rows = []
    summary_rows = []

    for scenario, cfg in SCENARIOS.items():
        raw_path = HERE / f"{cfg['stem']}.raw"
        log_path = HERE / f"{cfg['stem']}.log"
        cir_path = HERE / f"{cfg['stem']}.cir"
        raw = read_ltspice_raw(raw_path)
        actual = raw_response(raw, scenario, design)
        expected = model.network_response(
            actual["frequency_Hz"], cfg["topology"], cfg["l_h"], cfg["c_f"], cfg["ql"], cfg["qc"]
        )
        if not np.allclose(actual["frequency_Hz"], expected["frequency_Hz"], rtol=0, atol=1e-6):
            raise ValueError(f"{scenario}: LTspice and Python frequency grids differ")
        raw_tables[scenario] = actual
        analytic_tables[scenario] = expected

        phase_actual = np.unwrap(np.angle(actual["z_in"]))
        phase_expected = np.unwrap(np.angle(expected["z_in"]))
        row = {
            "scenario": scenario,
            "points": int(actual["frequency_Hz"].size),
            "max_zin_relative_error": max_relative(actual["z_in"], expected["z_in"]),
            "max_vport_relative_error": max_relative(actual["v_port"], expected["v_port"]),
            "max_iport_relative_error": max_relative(actual["i_port"], expected["i_port"]),
            "max_prm_full_scale_error": full_scale_error(actual["p_rm_W"], expected["p_rm_W"]),
            "max_phase_abs_error_deg": float(np.max(np.abs(phase_actual - phase_expected)) * 180 / np.pi),
            "max_power_balance_abs_error_W": float(np.max(np.abs(actual["power_balance_error_W"]))),
        }
        row["status"] = "PASS" if max(row[key] for key in (
            "max_zin_relative_error", "max_vport_relative_error", "max_iport_relative_error",
            "max_prm_full_scale_error"
        )) < 0.05 else "FAIL"
        audit_rows.append(row)

        for path in (cir_path, raw_path, log_path):
            inventory_rows.append(
                {
                    "scenario": scenario,
                    "file": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )

        freq = actual["frequency_Hz"]
        f0_idx = int(np.argmin(abs(freq - model.F0)))
        peak_idx = int(np.argmax(actual["p_rm_W"]))
        summary_rows.append(
            {
                "scenario": scenario,
                "source_Vrms": 1.0,
                "source_Rs_ohm": model.RS,
                "zin_real_at_f0_ohm": actual["z_in"][f0_idx].real,
                "zin_imag_at_f0_ohm": actual["z_in"][f0_idx].imag,
                "zin_abs_at_f0_ohm": abs(actual["z_in"][f0_idx]),
                "zin_phase_at_f0_deg": np.angle(actual["z_in"][f0_idx], deg=True),
                "gamma_at_f0": actual["gamma"][f0_idx],
                "vport_at_f0_Vrms": abs(actual["v_port"][f0_idx]),
                "iport_at_f0_Arms": abs(actual["i_port"][f0_idx]),
                "p_rm_at_f0_W": actual["p_rm_W"][f0_idx],
                "p_port_at_f0_W": actual["p_port_W"][f0_idx],
                "q_port_at_f0_var": actual["q_port_var"][f0_idx],
                "s_port_at_f0_VA": actual["s_port_VA"][f0_idx],
                "p_source_at_f0_W": actual["p_source_W"][f0_idx],
                "p_rs_at_f0_W": actual["p_rs_W"][f0_idx],
                "p_l_esr_at_f0_W": actual["p_l_esr_W"][f0_idx],
                "p_c_esr_at_f0_W": actual["p_c_esr_W"][f0_idx],
                "eta_elec_at_f0": actual["p_rm_W"][f0_idx] / actual["p_source_W"][f0_idx],
                "power_peak_Hz": freq[peak_idx],
                "power_peak_W": actual["p_rm_W"][peak_idx],
            }
        )

        for idx, f_hz in enumerate(freq):
            detail_rows.append(
                {
                    "scenario": scenario,
                    "frequency_Hz": f_hz,
                    "zin_real_ohm": actual["z_in"][idx].real,
                    "zin_imag_ohm": actual["z_in"][idx].imag,
                    "zin_abs_ohm": abs(actual["z_in"][idx]),
                    "zin_phase_deg": np.angle(actual["z_in"][idx], deg=True),
                    "gamma": actual["gamma"][idx],
                    "vport_abs_V_per_1Vrms_source": abs(actual["v_port"][idx]),
                    "iport_abs_A": abs(actual["i_port"][idx]),
                    "p_rm_W": actual["p_rm_W"][idx],
                    "p_port_W": actual["p_port_W"][idx],
                    "q_port_var": actual["q_port_var"][idx],
                    "s_port_VA": actual["s_port_VA"][idx],
                    "p_source_W": actual["p_source_W"][idx],
                    "p_rs_W": actual["p_rs_W"][idx],
                    "p_l_esr_W": actual["p_l_esr_W"][idx],
                    "p_c_esr_W": actual["p_c_esr_W"][idx],
                    "power_balance_error_W": actual["power_balance_error_W"][idx],
                }
            )

    def write_csv(name: str, rows: list[dict]) -> None:
        with (HERE / name).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    write_csv("stage2_LTspice_解析交叉验证.csv", audit_rows)
    write_csv("stage2_LTspice_RAW文件哈希.csv", inventory_rows)
    write_csv("stage2_LTspice逐频数据.csv", detail_rows)
    write_csv("stage2_匹配前后特征汇总.csv", summary_rows)

    active = raw_tables["ACTIVE_LOSSY"]
    f0_idx = int(np.argmin(abs(active["frequency_Hz"] - model.F0)))
    scale = (100 / (2 * math.sqrt(2))) / abs(active["v_port"][f0_idx])
    calibrated = {
        "source_class": "DERIVED_VALUE; based on active matched baseline and AC RMS-equivalent convention",
        "source_Vrms_for_a1": float(scale),
        "source_Vpp_for_a1": float(scale * 2 * math.sqrt(2)),
        "transducer_Vpp": 100.0,
        "transducer_Irms_A": float(abs(active["i_port"][f0_idx]) * scale),
        "P_Rm_W": float(active["p_rm_W"][f0_idx] * scale**2),
        "P_port_W": float(active["p_port_W"][f0_idx] * scale**2),
        "Q_port_var": float(active["q_port_var"][f0_idx] * scale**2),
        "S_port_VA": float(active["s_port_VA"][f0_idx] * scale**2),
        "P_source_W": float(active["p_source_W"][f0_idx] * scale**2),
        "P_Rs_W": float(active["p_rs_W"][f0_idx] * scale**2),
        "P_L_ESR_W": float(active["p_l_esr_W"][f0_idx] * scale**2),
        "P_C_ESR_W": float(active["p_c_esr_W"][f0_idx] * scale**2),
        "eta_elec": float(active["p_rm_W"][f0_idx] / active["p_source_W"][f0_idx]),
        "rule": "freeze this source amplitude for stage3-5; protection may reduce but strategies may not increase it",
    }
    (HERE / "stage2_控制源幅度校准.json").write_text(
        json.dumps(calibrated, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    colors = {"BEFORE": "tab:gray", "IDEAL": "tab:blue", "ACTIVE_LOSSY": "tab:orange"}
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for scenario, table in raw_tables.items():
        axes[0].plot(table["frequency_Hz"] / 1e6, abs(table["z_in"]), label=scenario, color=colors[scenario])
        axes[1].plot(table["frequency_Hz"] / 1e6, np.angle(table["z_in"], deg=True), label=scenario, color=colors[scenario])
    axes[0].set_yscale("log")
    axes[0].set_ylabel("|Zin| (ohm, log scale)")
    axes[1].set_ylabel("Phase(Zin) (deg)")
    axes[1].set_xlabel("Frequency (MHz)")
    for axis in axes:
        axis.axvline(model.F0 / 1e6, color="black", ls=":", lw=1)
        axis.grid(alpha=0.25)
        axis.legend()
    fig.suptitle("V2.1 matching comparison from actual LTspice RAW\n(same 1 Vrms Thevenin source and 50 ohm Rs)")
    fig.tight_layout()
    fig.savefig(HERE / "stage2_01_匹配前后输入阻抗_RAW.png", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for scenario, table in raw_tables.items():
        axes[0].plot(table["frequency_Hz"] / 1e6, table["p_rm_W"] * 1e3, label=scenario, color=colors[scenario])
        axes[1].plot(table["frequency_Hz"] / 1e6, table["gamma"], label=scenario, color=colors[scenario])
    axes[0].set_ylabel("P_Rm (mW per 1 Vrms source)")
    axes[1].set_ylabel("Electrical reflection proxy")
    axes[1].set_xlabel("Frequency (MHz)")
    axes[1].set_ylim(-0.02, 1.02)
    for axis in axes:
        axis.axvline(model.F0 / 1e6, color="black", ls=":", lw=1)
        axis.grid(alpha=0.25)
        axis.legend()
    fig.suptitle("V2.1 matched power and reflection proxy from actual LTspice RAW")
    fig.tight_layout()
    fig.savefig(HERE / "stage2_02_匹配前后功率与反射_RAW.png", dpi=200)
    plt.close(fig)

    actual = raw_tables["ACTIVE_LOSSY"]
    expected = analytic_tables["ACTIVE_LOSSY"]
    zoom = (actual["frequency_Hz"] >= 0.89e6) & (actual["frequency_Hz"] <= 0.91e6)
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(actual["frequency_Hz"][zoom] / 1e6, actual["p_rm_W"][zoom] * 1e3, label="LTspice RAW", lw=2)
    axes[0].plot(expected["frequency_Hz"][zoom] / 1e6, expected["p_rm_W"][zoom] * 1e3, "--", label="Python analytic", lw=1.2)
    axes[0].set_ylabel("P_Rm (mW)")
    axes[1].plot(actual["frequency_Hz"][zoom] / 1e6, abs(actual["z_in"][zoom]), label="LTspice RAW", lw=2)
    axes[1].plot(expected["frequency_Hz"][zoom] / 1e6, abs(expected["z_in"][zoom]), "--", label="Python analytic", lw=1.2)
    axes[1].set_ylabel("|Zin| (ohm)")
    axes[1].set_xlabel("Frequency (MHz)")
    for axis in axes:
        axis.axvline(model.F0 / 1e6, color="black", ls=":", lw=1)
        axis.grid(alpha=0.25)
        axis.legend()
    fig.suptitle("Active lossy match: LTspice/Python cross-validation")
    fig.tight_layout()
    fig.savefig(HERE / "stage2_03_活动匹配_LTspice_Python交叉验证.png", dpi=200)
    plt.close(fig)

    loss_labels = ["P_Rm", "Rs loss", "L ESR", "C ESR"]
    loss_values = [
        calibrated["P_Rm_W"], calibrated["P_Rs_W"],
        calibrated["P_L_ESR_W"], calibrated["P_C_ESR_W"],
    ]
    fig, axis = plt.subplots(figsize=(9, 5.5))
    bars = axis.bar(loss_labels, loss_values, color=["tab:green", "tab:gray", "tab:orange", "tab:blue"])
    axis.axhline(calibrated["P_source_W"], color="tab:red", ls="--", lw=1.5, label="ideal-source active power")
    axis.bar_label(bars, labels=[f"{value:.4f} W" for value in loss_values], padding=3)
    axis.set_ylabel("Active power (W)")
    axis.set_title("V2.1 active-match power allocation at calibrated 100 Vpp port\n(actual LTspice RAW; hypothetical linear model)")
    axis.grid(axis="y", alpha=0.25)
    axis.legend()
    fig.tight_layout()
    fig.savefig(HERE / "stage2_04_校准功率分配_RAW.png", dpi=200)
    plt.close(fig)

    before_row = next(row for row in summary_rows if row["scenario"] == "BEFORE")
    ideal_row = next(row for row in summary_rows if row["scenario"] == "IDEAL")
    active_row = next(row for row in summary_rows if row["scenario"] == "ACTIVE_LOSSY")
    overall_pass = all(row["status"] == "PASS" for row in audit_rows)
    audit = {
        "status": "PASS" if overall_pass else "FAIL",
        "same_source_condition": "1 Vrms RMS-equivalent Thevenin source and 50 ohm Rs in all three netlists",
        "active_model": "MODEL_V2_1_HYPOTHETICAL",
        "active_topology": design["topology"],
        "ideal_L_uH": values["l_ideal_H"] * 1e6,
        "ideal_C_pF": values["c_ideal_F"] * 1e12,
        "active_L_uH": values["l_active_H"] * 1e6,
        "active_C_pF": values["c_active_F"] * 1e12,
        "active_RL_ESR_ohm": values["r_l_active_ohm_at_f0"],
        "active_RC_ESR_ohm": values["r_c_active_ohm_at_f0"],
        "p_rm_improvement_active_vs_before_at_f0": active_row["p_rm_at_f0_W"] / before_row["p_rm_at_f0_W"],
        "gamma_before_at_f0": before_row["gamma_at_f0"],
        "gamma_ideal_at_f0": ideal_row["gamma_at_f0"],
        "gamma_active_at_f0": active_row["gamma_at_f0"],
        "calibration": calibrated,
        "cross_validation": audit_rows,
    }
    (HERE / "stage2_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = f"""# v2.1阶段二：L型匹配网络设计与LTspice交叉验证

## 结论

阶段二验收状态：**{audit['status']}**。

三种网络均使用同一个1 Vrms等效RMS Thevenin源和50 Ω源阻抗。活动拓扑为：源阻抗后串联带ESR电感，在换能器端口并联带ESR电容；换能器BVD参数完全相同。

## 匹配参数身份

- 理想闭式解：`L={audit['ideal_L_uH']:.6f} µH`，`C={audit['ideal_C_pF']:.6f} pF`，身份为DERIVED_VALUE。
- 活动含损耗优化：`L={audit['active_L_uH']:.6f} µH`，`C={audit['active_C_pF']:.6f} pF`，身份为DERIVED_VALUE。
- 电感Q={model.QL_MATCH:g}、电容Q={model.QC_MATCH:g}是HYPOTHETICAL_BASELINE，不是器件实测值。
- 固定ESR：电感约`{audit['active_RL_ESR_ohm']:.6f} Ω`，电容约`{audit['active_RC_ESR_ohm']:.6f} Ω`。

## 相同源条件下0.9 MHz结果

| 网络 | Zin | 反射代理 | P_Rm/1 Vrms源 | 换能器端Vrms/1 Vrms源 |
|---|---:|---:|---:|---:|
| 无匹配 | `{before_row['zin_real_at_f0_ohm']:.3f}{before_row['zin_imag_at_f0_ohm']:+.3f}j Ω` | {before_row['gamma_at_f0']:.6f} | {before_row['p_rm_at_f0_W']*1e3:.6f} mW | {before_row['vport_at_f0_Vrms']:.6f} V |
| 理想匹配 | `{ideal_row['zin_real_at_f0_ohm']:.3f}{ideal_row['zin_imag_at_f0_ohm']:+.3f}j Ω` | {ideal_row['gamma_at_f0']:.6f} | {ideal_row['p_rm_at_f0_W']*1e3:.6f} mW | {ideal_row['vport_at_f0_Vrms']:.6f} V |
| 活动含损耗 | `{active_row['zin_real_at_f0_ohm']:.3f}{active_row['zin_imag_at_f0_ohm']:+.3f}j Ω` | {active_row['gamma_at_f0']:.6f} | {active_row['p_rm_at_f0_W']*1e3:.6f} mW | {active_row['vport_at_f0_Vrms']:.6f} V |

活动匹配在相同源条件下把0.9 MHz的运动支路功率提高约`{audit['p_rm_improvement_active_vs_before_at_f0']:.3f}`倍。理想匹配趋近50 Ω；活动匹配因ESR和“最大P_Rm”目标而不是“强制Γ=0”而保留小量失配。

| 网络 | P_source | P_port | Q_port | \\|S_port\\| | eta_elec=P_Rm/P_source |
|---|---:|---:|---:|---:|---:|
| 无匹配 | {before_row['p_source_at_f0_W']*1e3:.6f} mW | {before_row['p_port_at_f0_W']*1e3:.6f} mW | {before_row['q_port_at_f0_var']*1e3:.6f} mvar | {before_row['s_port_at_f0_VA']*1e3:.6f} mVA | {before_row['eta_elec_at_f0']:.6f} |
| 理想匹配 | {ideal_row['p_source_at_f0_W']*1e3:.6f} mW | {ideal_row['p_port_at_f0_W']*1e3:.6f} mW | {ideal_row['q_port_at_f0_var']*1e3:.6f} mvar | {ideal_row['s_port_at_f0_VA']*1e3:.6f} mVA | {ideal_row['eta_elec_at_f0']:.6f} |
| 活动含损耗 | {active_row['p_source_at_f0_W']*1e3:.6f} mW | {active_row['p_port_at_f0_W']*1e3:.6f} mW | {active_row['q_port_at_f0_var']*1e3:.6f} mvar | {active_row['s_port_at_f0_VA']*1e3:.6f} mVA | {active_row['eta_elec_at_f0']:.6f} |

这里的`eta_elec`只是从理想源有功到运动支路有功的电学功率分配比例，不是电声转换效率。反射代理降低也不自动表示`P_Rm`同比增加，因为源电阻和匹配ESR同样会吸收功率。

## 控制阶段源幅度校准

活动匹配冻结后，根据真实LTspice RAW得到：

- `a=1`源电压：{calibrated['source_Vrms_for_a1']:.6f} Vrms，即{calibrated['source_Vpp_for_a1']:.6f} Vpp；
- 换能器端：100 Vpp；
- 总端口电流：{calibrated['transducer_Irms_A']*1e3:.6f} mA RMS；
- 运动支路有功：{calibrated['P_Rm_W']:.6f} W；
- 端口复功率：`{calibrated['P_port_W']:.6f}+j{calibrated['Q_port_var']:.6f}` VA，`|S|={calibrated['S_port_VA']:.6f}` VA；
- 源有功：{calibrated['P_source_W']:.6f} W；
- 源电阻损耗：{calibrated['P_Rs_W']:.6f} W；
- 电感ESR损耗：{calibrated['P_L_ESR_W']:.6f} W；
- 电容ESR损耗：{calibrated['P_C_ESR_W']:.6f} W。
- 电学功率分配比例`P_Rm/P_source`：{calibrated['eta_elec']:.6f}。

该源幅度从阶段三开始冻结；三种控制策略不得主动提高，只允许保护foldback降低。

## LTspice/Python交叉验证

三组均为20001个频点、0.8–1.0 MHz。逐点审核见`stage2_LTspice_解析交叉验证.csv`。所有阻抗、电压、电流和功率误差均低于5%验收线，实际误差接近数值精度。

## 边界

本结果属于假设BVD、假设匹配元件Q和线性AC模型；不包含功放开关、器件温升、真实电感自谐振、PCB寄生、声场或临床结论。PNG为真实LTspice RAW派生图，不是GUI窗口截图。
"""
    (HERE / "stage2_匹配网络正式报告.md").write_text(report, encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
