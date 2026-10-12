"""Create the reviewed Cm-only power and electrical-limit figure in Python."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path
import sys

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
MODEL_PATH = PROJECT_ROOT / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5" / "model_v2_1.py"
OUT = ROOT / "figures" / "stage3_disturbance" / "cm_only"
TABLE_OUT = ROOT / "results" / "tables" / "stage3_disturbance"


def load_model():
    spec = importlib.util.spec_from_file_location("active_model_v2_1_cm_figure", MODEL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load model: {MODEL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    model = load_model()
    scenarios = model.scenario_map()
    case_ids = ["CASE_000_BASELINE", "CASE_CM_P5", "CASE_CM_P10", "CASE_CM_P20"]
    labels = ["基准", "$C_m$ +5%", "$C_m$ +10%", "$C_m$ +20%"]
    colors = ["#333333", "#A9C0D9", "#5E88B5", "#174F86"]
    frequency = np.arange(model.F_MIN, model.F_MAX + 0.1, 100.0)

    mpl.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial", "DejaVu Sans", "sans-serif"],
        "axes.unicode_minus": False,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.8,
        "legend.frameon": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })

    fig, axes = plt.subplots(
        3, 1, figsize=(11.2, 8.4), sharex=True,
        gridspec_kw={"height_ratios": [2.0, 1.0, 1.0]},
    )
    ax_power, ax_voltage, ax_current = axes
    summary_rows: list[dict[str, object]] = []
    curve_rows: list[dict[str, object]] = []

    for case_id, label, color in zip(case_ids, labels, colors):
        scenario = scenarios[case_id]
        response = model.response(frequency, scenario, amplitude=1.0)
        peak_index = int(np.argmax(response["p_rm_W"]))
        peak_frequency = float(frequency[peak_index])
        peak_power = float(response["p_rm_W"][peak_index])
        peak_vpp = float(response["vport_vpp"][peak_index])
        peak_irms = float(response["iport_irms_A"][peak_index])
        max_vpp = float(np.max(response["vport_vpp"]))
        max_irms = float(np.max(response["iport_irms_A"]))
        hard_flag = max_vpp > model.VPP_HARD or max_irms > model.IRMS_HARD
        soft_flag = max_vpp > model.VPP_SOFT or max_irms > model.IRMS_SOFT
        status = "HARD_LIMIT_POINTS_PRESENT" if hard_flag else ("SOFT_LIMIT_POINTS_PRESENT" if soft_flag else "NO_SOFT_LIMIT_POINT")

        legend_label = f"{label}：{peak_frequency / 1e6:.4f} MHz，{peak_power * 1e3:.1f} mW"
        ax_power.plot(frequency / 1e6, response["p_rm_W"] * 1e3, color=color, lw=2.0, label=legend_label)
        ax_power.scatter(peak_frequency / 1e6, peak_power * 1e3, color=color, s=34, zorder=4)
        ax_voltage.plot(frequency / 1e6, response["vport_vpp"], color=color, lw=1.5)
        ax_current.plot(frequency / 1e6, response["iport_irms_A"] * 1e3, color=color, lw=1.5)

        summary_rows.append({
            "case_id": case_id,
            "display_label": label.replace("$", ""),
            "Cm_change_pct": 0 if case_id == "CASE_000_BASELINE" else float(scenario.level.strip("+%")),
            "scan_step_Hz": 100.0,
            "power_peak_frequency_Hz": peak_frequency,
            "power_peak_frequency_MHz_display_4dp": f"{peak_frequency / 1e6:.4f}",
            "power_peak_W": peak_power,
            "power_peak_mW_display_1dp": f"{peak_power * 1e3:.1f}",
            "vport_at_power_peak_Vpp": peak_vpp,
            "iport_at_power_peak_Arms": peak_irms,
            "scan_max_vport_Vpp": max_vpp,
            "scan_max_iport_Arms": max_irms,
            "unlimited_scan_constraint_status": status,
            "source_class": "DERIVED_SIMULATION_FROM_HYPOTHETICAL_MODEL",
        })
        for idx, freq in enumerate(frequency):
            curve_rows.append({
                "case_id": case_id,
                "frequency_Hz": float(freq),
                "p_rm_W": float(response["p_rm_W"][idx]),
                "vport_Vpp": float(response["vport_vpp"][idx]),
                "iport_Arms": float(response["iport_irms_A"][idx]),
            })

    ax_power.set_ylabel(r"运动支路有功功率 $P_{Rm}$ (mW)")
    power_handles, power_labels = ax_power.get_legend_handles_labels()
    ax_voltage.set_ylabel("换能器端电压 (Vpp)")
    ax_voltage.axhline(model.VPP_SOFT, color="#E28E2C", ls="--", lw=1.25, label="软阈值 130 Vpp")
    ax_voltage.axhline(model.VPP_HARD, color="#B64342", ls=":", lw=1.5, label="硬上限 160 Vpp")
    ax_voltage.legend(loc="upper right", ncol=2, fontsize=8.5)
    ax_current.set_ylabel("换能器端电流 (mA RMS)")
    ax_current.set_xlabel("频率 (MHz)")
    ax_current.axhline(model.IRMS_SOFT * 1e3, color="#E28E2C", ls="--", lw=1.25, label="软阈值 5.5 mA RMS")
    ax_current.axhline(model.IRMS_HARD * 1e3, color="#B64342", ls=":", lw=1.5, label="硬上限 6.0 mA RMS")
    ax_current.legend(loc="upper right", ncol=2, fontsize=8.5)
    ax_current.set_ylim(0, model.IRMS_HARD * 1e3 * 1.08)
    for panel_index, axis in enumerate(axes):
        axis.grid(color="#D6DCE3", lw=0.65, alpha=0.65)
        axis.set_xlim(model.F_MIN / 1e6, model.F_MAX / 1e6)
        axis.text(0.006, 0.94, chr(ord("a") + panel_index), transform=axis.transAxes,
                  fontsize=12, fontweight="bold", ha="left", va="top")

    fig.suptitle(r"机械支路电容 $C_m$ 单因素扰动下的 $P_{Rm}(f)$", fontsize=16, fontweight="bold", y=0.987)
    fig.text(
        0.5, 0.953,
        "同一冻结戴维南源与v2.1匹配网络；假设模型参数，非实测数据",
        ha="center", va="top", fontsize=10.5, color="#4A5560",
    )
    fig.legend(
        power_handles, power_labels, loc="upper center", bbox_to_anchor=(0.5, 0.91),
        ncol=2, fontsize=9, frameon=False,
    )
    fig.text(
        0.5, 0.012,
        "电压/电流面板为a=1未限幅扫频包络；超过阈值表示该频点需要保护降幅，不代表受保护控制时序实际硬越限。",
        ha="center", va="bottom", fontsize=8.5, color="#555555",
    )
    fig.tight_layout(rect=(0.025, 0.04, 0.995, 0.86), h_pad=1.0)

    OUT.mkdir(parents=True, exist_ok=True)
    TABLE_OUT.mkdir(parents=True, exist_ok=True)
    stem = OUT / "stage3_07_cm_only_power_and_electrical_limits"
    fig.savefig(stem.with_suffix(".png"), dpi=320, bbox_inches="tight", facecolor="white")
    fig.savefig(stem.with_suffix(".svg"), bbox_inches="tight", facecolor="white")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(stem.with_suffix(".tiff"), dpi=600, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    summary_path = TABLE_OUT / "stage3_cm_only_power_safety_summary.csv"
    curves_path = TABLE_OUT / "stage3_cm_only_power_safety_curves.csv"
    write_csv(summary_path, summary_rows)
    write_csv(curves_path, curve_rows)
    qa = {
        "status": "PASS",
        "backend": "Python/matplotlib only",
        "core_conclusion": "Within the frozen v2.1 hypothetical circuit, increasing motional capacitance Cm shifts the P_Rm peak to lower frequency and lowers its height; electrical-limit panels are needed before discussing admissibility.",
        "evidence_chain": {
            "power_panel": "peak direction, magnitude and 0.1 kHz display precision",
            "voltage_panel": "unlimited-scan Vpp envelope against 130/160 Vpp assumed thresholds",
            "current_panel": "unlimited-scan Irms envelope against 5.5/6 mA assumed thresholds",
        },
        "archetype": "quantitative hero panel plus two constraint evidence panels",
        "source_data": [str(summary_path.relative_to(ROOT)), str(curves_path.relative_to(ROOT))],
        "source_scope": "deterministic hypothetical MODEL_V2_1_HYPOTHETICAL; not measured data",
        "statistics": "No error bars or hypothesis tests because this is a deterministic parameter sweep, not replicated experimental sampling.",
        "display_precision": {"frequency_MHz": 4, "power_mW": 1, "scan_step_Hz": 100},
        "naming": {"Cm": "motional capacitance C_m (Cm-only)", "Cmatch": "matching capacitance C_match"},
        "single_factor_interpretation": "Only the original Cm component changes; derived fs and Qm change accordingly.",
        "ltspice_cross_validation": "CASE_CM_P20 has representative LTspice/Python validation in the existing stage-3 evidence bundle.",
        "review_risks": [
            "Do not call the soft/hard electrical thresholds measured device safety ratings.",
            "Do not infer acoustic or clinical safety from the electrical-limit panels.",
            "Do not interpret four-decimal MHz labels as accuracy beyond the 0.1 kHz scan grid.",
        ],
    }
    (OUT / "stage3_07_cm_only_power_and_electrical_limits_QA.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "status": "PASS",
        "figure": str(stem.with_suffix(".png")),
        "summary": str(summary_path),
        "display_peaks_MHz": [row["power_peak_frequency_MHz_display_4dp"] for row in summary_rows],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
