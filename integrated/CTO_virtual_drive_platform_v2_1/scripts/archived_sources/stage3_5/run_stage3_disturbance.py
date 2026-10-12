"""Run active v2.1 single-factor/combined disturbance scans and LTspice checks."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from model_v2_1 import (
    F0, F_MIN, F_MAX, ROOT, SOURCE_A1_VRMS, Scenario, all_scenarios,
    allowed_amplitude, half_power_width, point_metrics, response, safe_power,
)


HERE = Path(__file__).resolve().parent
OUT = HERE / "stage3_disturbance"
LT_DIR = OUT / "ltspice_validation"
FREQ = np.arange(F_MIN, F_MAX + 0.1, 100.0)
LTSPICE = Path(r"D:\LTspice.exe")
SELECTED_LT = [
    "CASE_000_BASELINE", "CASE_C0_P30", "CASE_RM_P50", "CASE_FS_M5",
    "CASE_LM_P20", "CASE_CM_P20", "CASE_QL_20", "CASE_QM_500",
    "CASE_QM_1000", "CASE_COMBINED_LOW", "CASE_COMBINED_MEDIUM",
    "CASE_COMBINED_HIGH",
]

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'
plt.rcParams['pdf.fonttype'] = 42
plt.rcParams.update({
    "font.size": 8, "axes.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "legend.frameon": False,
})

COLORS = {
    "baseline": "#272727", "C0": "#3775BA", "Rm": "#B64342", "fs": "#42949E",
    "Lm": "#5E83B5", "Cm": "#C16B52", "Rs": "#767676",
    "Lmatch": "#9A4D8E", "Cmatch": "#E28E2C",
    "inductor_Q": "#5B7FCA", "Qm": "#7BAA5B", "combined": "#D24B40",
}


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def phase_zero(f: np.ndarray, phase: np.ndarray) -> tuple[float, str]:
    sign = np.sign(phase)
    crossings = np.where(sign[:-1] * sign[1:] <= 0)[0]
    if crossings.size:
        values = []
        for i in crossings:
            if phase[i + 1] == phase[i]:
                values.append((f[i] + f[i + 1]) / 2)
            else:
                values.append(f[i] - phase[i] * (f[i + 1] - f[i]) / (phase[i + 1] - phase[i]))
        return float(min(values, key=lambda x: abs(x - F0))), "ZERO_CROSSING"
    idx = int(np.argmin(np.abs(phase)))
    return float(f[idx]), "MIN_ABS_PHASE_ONLY"


def scenario_summary(s: Scenario, q: dict[str, np.ndarray]) -> dict:
    p = q["p_rm_W"]
    peak = int(np.argmax(p))
    width, width_status, left, right = half_power_width(FREQ, p)
    safe = safe_power(FREQ, s)
    safe_idx = int(np.argmax(safe))
    zmin = int(np.argmin(np.abs(q["z_in"])))
    zero_f, zero_status = phase_zero(FREQ, q["phase_deg"])
    fixed = point_metrics(F0, s)
    hard_a = allowed_amplitude(F0, s, use_soft_limits=False)[0]
    soft_a = allowed_amplitude(F0, s, use_soft_limits=True)[0]
    return {
        "case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level,
        "description": s.description, "C0_F": s.bvd.c0, "Rm_ohm": s.bvd.rm,
        "Lm_H": s.bvd.lm, "Cm_F": s.bvd.cm, "fs_Hz": s.bvd.fs, "Qm": s.bvd.qm,
        "Rs_ohm": s.rs, "Lmatch_H": s.matching.l_h, "Cmatch_F": s.matching.c_f,
        "inductor_Q": s.matching.ql, "capacitor_Q": s.matching.qc,
        "power_peak_Hz": float(FREQ[peak]), "power_peak_W": float(p[peak]),
        "power_FWHM_Hz": float(width), "power_FWHM_status": width_status,
        "power_half_left_Hz": float(left), "power_half_right_Hz": float(right),
        "safe_power_peak_Hz": float(FREQ[safe_idx]), "safe_power_peak_W": float(safe[safe_idx]),
        "safe_amplitude_at_peak": float(allowed_amplitude(FREQ[safe_idx], s, use_soft_limits=True)[0]),
        "zin_abs_min_Hz": float(FREQ[zmin]), "zin_abs_min_ohm": float(abs(q["z_in"][zmin])),
        "phase_zero_or_min_Hz": zero_f, "phase_feature_status": zero_status,
        "source_a1_Vrms": SOURCE_A1_VRMS,
        "soft_allowed_amplitude_at_0p9": float(soft_a),
        "hard_allowed_amplitude_at_0p9": float(hard_a),
        **{f"fixed_0p9_{k}": v for k, v in fixed.items() if k != "frequency_Hz"},
    }


def detailed_rows(s: Scenario, q: dict[str, np.ndarray]) -> list[dict]:
    safe_a = allowed_amplitude(FREQ, s, use_soft_limits=True)
    rows = []
    for i, f in enumerate(FREQ):
        z = q["z_in"][i]
        rows.append({
            "case_id": s.case_id, "family": s.family, "factor": s.factor, "level": s.level,
            "frequency_Hz": f, "zin_real_ohm": z.real, "zin_imag_ohm": z.imag,
            "zin_abs_ohm": abs(z), "phase_deg": q["phase_deg"][i], "gamma": q["gamma"][i],
            "vport_vpp": q["vport_vpp"][i], "iport_irms_A": q["iport_irms_A"][i],
            "p_rm_W": q["p_rm_W"][i], "p_port_W": q["p_port_W"][i],
            "q_port_var": q["q_port_var"][i], "s_port_VA": q["s_port_VA"][i],
            "p_source_W": q["p_source_W"][i], "p_rs_W": q["p_rs_W"][i],
            "p_l_esr_W": q["p_l_esr_W"][i], "p_c_esr_W": q["p_c_esr_W"][i],
            "safe_allowed_amplitude": safe_a[i], "safe_power_W": q["p_rm_W"][i] * safe_a[i] ** 2,
        })
    return rows


def qualitative(delta: float, moderate: float, strong: float) -> str:
    x = abs(delta)
    return "明显" if x >= strong else ("中等" if x >= moderate else "较小")


def trend_rows(summaries: list[dict]) -> list[dict]:
    base = next(r for r in summaries if r["case_id"] == "CASE_000_BASELINE")
    chosen = {
        "C0": "CASE_C0_P30", "Rm": "CASE_RM_P50", "fs": "CASE_FS_M5",
        "Lm": "CASE_LM_P20", "Cm": "CASE_CM_P20",
        "Rs": "CASE_RS_P20", "Lmatch": "CASE_LMATCH_P10",
        "Cmatch": "CASE_CMATCH_M10", "inductor_Q": "CASE_QL_20",
    }
    rows = []
    for factor, case_id in chosen.items():
        r = next(x for x in summaries if x["case_id"] == case_id)
        df_khz = (r["power_peak_Hz"] - base["power_peak_Hz"]) / 1e3
        dh_pct = (r["power_peak_W"] / base["power_peak_W"] - 1) * 100
        if math.isfinite(r["power_FWHM_Hz"]) and math.isfinite(base["power_FWHM_Hz"]):
            dw_pct = (r["power_FWHM_Hz"] / base["power_FWHM_Hz"] - 1) * 100
        else:
            dw_pct = math.nan
        rows.append({
            "parameter_change": f"{factor}: {r['level']}", "case_id": case_id,
            "peak_shift_kHz": df_khz, "peak_height_change_pct": dh_pct,
            "peak_width_change_pct": dw_pct,
            "主要影响峰位": qualitative(df_khz, 0.5, 2.0),
            "主要影响峰高": qualitative(dh_pct, 3.0, 10.0),
            "主要影响峰宽": "待扩展窗口" if not math.isfinite(dw_pct) else qualitative(dw_pct, 5.0, 15.0),
        })
    return rows


def save_figure(fig: plt.Figure, stem: str) -> None:
    fig.tight_layout(pad=1.2)
    for ext, kwargs in (("png", {"dpi": 300}), ("svg", {}), ("pdf", {})):
        fig.savefig(OUT / f"{stem}.{ext}", bbox_inches="tight", **kwargs)
    plt.close(fig)


def make_figures(scenarios: list[Scenario], tables: dict[str, dict], summaries: list[dict]) -> None:
    base = next(r for r in summaries if r["case_id"] == "CASE_000_BASELINE")
    single = [r for r in summaries if r["family"] == "single_factor" and not (
        r["factor"] == "inductor_Q" and r["level"] == "Q=100"
    ) and not (r["factor"] == "Qm" and r["level"] == "Qm=800")]
    labels = [f"{r['factor']}\n{r['level']}" for r in single]
    x = np.arange(len(single))
    fig, axes = plt.subplots(3, 1, figsize=(12.4, 7.4), sharex=True)
    axes[0].bar(x, [(r["power_peak_Hz"] - base["power_peak_Hz"]) / 1e3 for r in single], color="#3775BA")
    axes[1].bar(x, [(r["power_peak_W"] / base["power_peak_W"] - 1) * 100 for r in single], color="#B64342")
    width_delta = []
    for r in single:
        width_delta.append((r["power_FWHM_Hz"] / base["power_FWHM_Hz"] - 1) * 100 if math.isfinite(r["power_FWHM_Hz"]) else np.nan)
    axes[2].bar(x, width_delta, color="#42949E")
    axes[0].set_ylabel("Peak shift (kHz)"); axes[1].set_ylabel("Peak height change (%)")
    axes[2].set_ylabel("FWHM change (%)"); axes[2].set_xticks(x); axes[2].set_xticklabels(labels, rotation=60, ha="right", fontsize=6)
    for ax in axes: ax.axhline(0, color="#767676", lw=0.7)
    fig.suptitle("v2.1 single-factor sensitivity under the same frozen source")
    save_figure(fig, "stage3_01_single_factor_sensitivity")

    selected = [
        "CASE_000_BASELINE", "CASE_C0_P30", "CASE_RM_P50", "CASE_FS_M5",
        "CASE_LMATCH_P10", "CASE_QL_20", "CASE_COMBINED_HIGH",
    ]
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 6.0), sharex=True)
    for case_id in selected:
        s = next(s for s in scenarios if s.case_id == case_id)
        q = tables[case_id]
        color = COLORS.get(s.factor, COLORS["combined"])
        label = "baseline" if case_id == "CASE_000_BASELINE" else f"{s.factor} {s.level}"
        axes[0].plot(FREQ / 1e6, q["p_rm_W"] * 1e3, lw=1.1, label=label, color=color)
        axes[1].plot(FREQ / 1e6, q["phase_deg"], lw=1.0, label=label, color=color)
    axes[0].set_ylabel("Motional active power (mW)"); axes[1].set_ylabel("Input phase (deg)")
    axes[1].set_xlabel("Frequency (MHz)"); axes[0].legend(ncol=2, fontsize=7)
    axes[1].axhline(0, color="#767676", lw=0.7)
    fig.suptitle("Representative v2.1 disturbance responses")
    save_figure(fig, "stage3_02_representative_responses")

    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.8), sharex=True)
    for case_id, color in (("CASE_QM_500", "#3775BA"), ("CASE_QM_800", "#272727"), ("CASE_QM_1000", "#B64342")):
        q = tables[case_id]
        axes[0].plot(FREQ / 1e6, q["p_rm_W"] * 1e3, label=case_id.split("_")[-1], color=color)
        axes[1].plot(FREQ / 1e6, np.abs(q["z_in"]), label=case_id.split("_")[-1], color=color)
    axes[0].set_ylabel("Motional active power (mW)"); axes[1].set_ylabel("|Zin| (ohm)")
    axes[1].set_xlabel("Frequency (MHz)"); axes[0].legend(title="Qm")
    fig.suptitle("Formal Qm sensitivity: fs, Rm and C0 held fixed")
    save_figure(fig, "stage3_03_Qm_sensitivity")


def write_netlist(s: Scenario, path: Path) -> None:
    m, b = s.matching, s.bvd
    r_l = 2 * math.pi * F0 * m.l_h / m.ql
    r_c = 1 / (2 * math.pi * F0 * m.c_f * m.qc)
    text = f"""* {s.case_id}; MODEL_V2_1_HYPOTHETICAL; AC RMS-equivalent source
Vdrive n_src 0 AC {SOURCE_A1_VRMS:.17g}
Rsource n_src n_in {s.rs:.17g}
Rlesr n_in n_l {r_l:.17g}
Lmatch n_l n_port {m.l_h:.17g}
Cmatch n_port n_c {m.c_f:.17g}
Rcesr n_c 0 {r_c:.17g}
C0 n_port 0 {b.c0:.17g}
Rm n_port n_m1 {b.rm:.17g}
Lm n_m1 n_m2 {b.lm:.17g}
Cm n_m2 0 {b.cm:.17g}
.ac lin {len(FREQ)} {F_MIN:.17g} {F_MAX:.17g}
.options plotwinsize=0
.save V(n_src) V(n_in) V(n_port) I(Rsource) I(Rm) I(C0) I(Rlesr) I(Rcesr)
.end
"""
    path.write_text(text, encoding="ascii")


def max_relative(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.max(np.abs(a - b) / np.maximum(np.abs(b), 1e-30)))


def run_ltspice_validation(scenario_by_id: dict[str, Scenario]) -> tuple[list[dict], dict[str, dict]]:
    LT_DIR.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "ltspice_stage1"))
    from analyze_v2_stage1 import read_ltspice_raw

    audits = []
    actual_tables = {}
    for case_id in SELECTED_LT:
        s = scenario_by_id[case_id]
        cir = LT_DIR / f"{case_id}.cir"
        write_netlist(s, cir)
        proc = subprocess.run([str(LTSPICE), "-b", cir.name], cwd=LT_DIR, capture_output=True, text=True, timeout=120)
        raw_path = cir.with_suffix(".raw")
        log_path = cir.with_suffix(".log")
        if proc.returncode != 0 or not raw_path.exists():
            raise RuntimeError(f"LTspice failed for {case_id}: {proc.stdout}\n{proc.stderr}")
        raw = read_ltspice_raw(raw_path)
        f = np.real(raw["frequency"])
        expected = response(f, s, 1.0)
        i_source = raw["i(rsource)"]
        z_candidate = raw["v(n_in)"] / i_source
        if np.mean(np.abs(z_candidate - expected["z_in"])) > np.mean(np.abs(-z_candidate - expected["z_in"])):
            i_source = -i_source
            z_candidate = -z_candidate
        vport = raw["v(n_port)"]
        iport = raw["i(rm)"] + raw["i(c0)"]
        p_rm = np.abs(raw["i(rm)"]) ** 2 * s.bvd.rm
        gamma = np.abs((z_candidate - s.rs) / (z_candidate + s.rs))
        actual_tables[case_id] = {"frequency_Hz": f, "z_in": z_candidate, "v_port": vport, "i_port": iport, "p_rm_W": p_rm, "gamma": gamma}
        audits.append({
            "case_id": case_id, "points": len(f), "ltspice_return_code": proc.returncode,
            "max_zin_relative_error": max_relative(z_candidate, expected["z_in"]),
            "max_vport_relative_error": max_relative(vport, expected["v_port"]),
            "max_iport_relative_error": max_relative(iport, expected["i_port"]),
            "max_prm_full_scale_error": float(np.max(np.abs(p_rm - expected["p_rm_W"])) / np.max(expected["p_rm_W"])),
            "max_gamma_abs_error": float(np.max(np.abs(gamma - expected["gamma"]))),
            "raw_bytes": raw_path.stat().st_size, "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
            "status": "PASS",
        })
    for row in audits:
        worst = max(row["max_zin_relative_error"], row["max_vport_relative_error"], row["max_iport_relative_error"], row["max_prm_full_scale_error"])
        row["status"] = "PASS" if worst < 0.05 else "FAIL"
    return audits, actual_tables


def plot_ltspice_validation(scenario_by_id: dict[str, Scenario], actual: dict[str, dict]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(8.0, 5.6), sharex=True)
    for case_id, color in (("CASE_000_BASELINE", "#272727"), ("CASE_COMBINED_HIGH", "#B64342"), ("CASE_QM_500", "#3775BA"), ("CASE_QM_1000", "#7BAA5B")):
        a = actual[case_id]
        e = response(a["frequency_Hz"], scenario_by_id[case_id])
        label = case_id.replace("CASE_", "")
        axes[0, 0].plot(a["frequency_Hz"] / 1e6, a["p_rm_W"] * 1e3, color=color, lw=1.1, label=label)
        axes[0, 0].plot(a["frequency_Hz"] / 1e6, e["p_rm_W"] * 1e3, color=color, lw=0.8, ls="--")
        axes[0, 1].plot(a["frequency_Hz"] / 1e6, np.abs(a["z_in"]), color=color, lw=1.1)
        axes[0, 1].plot(a["frequency_Hz"] / 1e6, np.abs(e["z_in"]), color=color, lw=0.8, ls="--")
        axes[1, 0].plot(a["frequency_Hz"] / 1e6, np.angle(a["z_in"], deg=True), color=color, lw=1.1)
        axes[1, 0].plot(a["frequency_Hz"] / 1e6, np.angle(e["z_in"], deg=True), color=color, lw=0.8, ls="--")
        axes[1, 1].plot(a["frequency_Hz"] / 1e6, a["gamma"], color=color, lw=1.1)
        axes[1, 1].plot(a["frequency_Hz"] / 1e6, e["gamma"], color=color, lw=0.8, ls="--")
    axes[0, 0].set_ylabel("P_Rm (mW)"); axes[0, 1].set_ylabel("|Zin| (ohm)")
    axes[1, 0].set_ylabel("Phase (deg)"); axes[1, 1].set_ylabel("Reflection proxy")
    axes[1, 0].set_xlabel("Frequency (MHz)"); axes[1, 1].set_xlabel("Frequency (MHz)")
    axes[0, 0].legend(fontsize=6, ncol=2)
    fig.suptitle("Actual LTspice RAW (solid) vs Python analytic (dashed)")
    save_figure(fig, "stage3_04_LTspice_cross_validation")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = all_scenarios()
    scenario_by_id = {s.case_id: s for s in scenarios}
    tables = {}
    summaries = []
    details = []
    for s in scenarios:
        q = response(FREQ, s)
        tables[s.case_id] = q
        summaries.append(scenario_summary(s, q))
        details.extend(detailed_rows(s, q))
    trends = trend_rows(summaries)
    qm = [r for r in summaries if r["factor"] == "Qm"]
    write_csv(OUT / "stage3_scenario_registry_and_summary.csv", summaries)
    write_csv(OUT / "stage3_frequency_response_all_cases.csv", details)
    write_csv(OUT / "stage3_trend_table.csv", trends)
    write_csv(OUT / "stage3_Qm_500_800_1000_summary.csv", qm)
    make_figures(scenarios, tables, summaries)

    audits, actual = run_ltspice_validation(scenario_by_id)
    write_csv(OUT / "stage3_LTspice_cross_validation.csv", audits)
    plot_ltspice_validation(scenario_by_id, actual)

    audit = {
        "model_id": "MODEL_V2_1_HYPOTHETICAL", "status": "PASS" if all(r["status"] == "PASS" for r in audits) else "FAIL",
        "scenario_count": len(scenarios), "frequency_points_per_case": len(FREQ),
        "frequency_range_Hz": [float(FREQ[0]), float(FREQ[-1])], "frequency_step_Hz": 100.0,
        "source_Vrms_frozen": SOURCE_A1_VRMS, "ltspice_executable": str(LTSPICE),
        "ltspice_validation_cases": SELECTED_LT, "ltspice_audit": audits,
        "limits_are_hypothetical": {"Vpp_soft": 130.0, "Vpp_hard": 160.0, "Irms_soft_A": 0.0055, "Irms_hard_A": 0.006},
        "scope": "linear small-signal electrical model; no measured, acoustic, thermal or clinical result",
    }
    (OUT / "stage3_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": audit["status"], "scenarios": len(scenarios), "ltspice_cases": len(audits)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
