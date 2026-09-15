"""Design the v2.1 L network and generate analytic data plus LTspice netlists.

The AC phasor magnitude is interpreted as an RMS-equivalent value in all power
post-processing.  The circuit itself is linear, so this is a normalization
convention rather than an LTspice transient-voltage claim.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize


HERE = Path(__file__).resolve().parent

F0 = 0.9e6
RS = 50.0
C0 = 6.858064105198409e-12
RM = 7352.941176470586
LM = 1.0402283862215378
CM = 3.006260036180247e-14
QL_MATCH = 100.0
QC_MATCH = 1000.0
VS_RMS = 1.0


def bvd_impedances(freq: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    freq_array = np.asarray(freq, dtype=float)
    omega = 2 * np.pi * freq_array
    z_m = RM + 1j * (omega * LM - 1 / (omega * CM))
    z_load = 1 / (1 / z_m + 1j * omega * C0)
    return z_load, z_m


def network_response(
    freq: np.ndarray | float,
    topology: str,
    l_match_h: float = 0.0,
    c_match_f: float = 0.0,
    ql: float = math.inf,
    qc: float = math.inf,
) -> dict[str, np.ndarray]:
    freq_array = np.atleast_1d(np.asarray(freq, dtype=float))
    omega = 2 * np.pi * freq_array
    z_load, z_m = bvd_impedances(freq_array)

    if topology == "before":
        z_in = z_load
        z_parallel = z_load
        z_cap = np.full(freq_array.shape, np.inf + 0j)
        r_l = np.zeros_like(freq_array)
        r_c = np.zeros_like(freq_array)
    else:
        # The active LTspice netlist uses explicit, frequency-independent ESR
        # calculated from the stated Q at f0.  Match that exact model here.
        r_l = (
            np.zeros_like(freq_array)
            if math.isinf(ql)
            else np.full_like(freq_array, 2 * np.pi * F0 * l_match_h / ql)
        )
        r_c = (
            np.zeros_like(freq_array)
            if math.isinf(qc)
            else np.full_like(freq_array, 1 / (2 * np.pi * F0 * c_match_f * qc))
        )
        z_cap = r_c + 1 / (1j * omega * c_match_f)
        z_parallel = 1 / (1 / z_load + 1 / z_cap)
        z_in = r_l + 1j * omega * l_match_h + z_parallel

    i_source = VS_RMS / (RS + z_in)
    v_input = i_source * z_in
    v_port = i_source * z_parallel
    i_motional = v_port / z_m
    i_c0 = 1j * omega * C0 * v_port
    i_port = i_motional + i_c0
    i_match_c = np.zeros_like(v_port) if topology == "before" else v_port / z_cap

    p_rm = np.abs(i_motional) ** 2 * RM
    s_port = v_port * np.conj(i_port)
    p_source = np.real(VS_RMS * np.conj(i_source))
    p_rs = np.abs(i_source) ** 2 * RS
    p_l = np.abs(i_source) ** 2 * r_l
    p_c = np.abs(i_match_c) ** 2 * r_c
    balance = p_source - (p_rs + p_rm + p_l + p_c)
    gamma = np.abs((z_in - RS) / (z_in + RS))

    return {
        "frequency_Hz": freq_array,
        "z_load": z_load,
        "z_in": z_in,
        "v_input": v_input,
        "v_port": v_port,
        "i_source": i_source,
        "i_motional": i_motional,
        "i_port": i_port,
        "i_match_c": i_match_c,
        "p_rm_W": p_rm,
        "p_port_W": np.real(s_port),
        "q_port_var": np.imag(s_port),
        "s_port_VA": np.abs(s_port),
        "p_source_W": p_source,
        "p_rs_W": p_rs,
        "p_l_esr_W": p_l,
        "p_c_esr_W": p_c,
        "power_balance_error_W": balance,
        "gamma": gamma,
        "r_l_ohm": r_l,
        "r_c_ohm": r_c,
    }


def design_values() -> dict[str, float]:
    omega0 = 2 * np.pi * F0
    z_load0, _ = bvd_impedances(F0)
    y_load0 = 1 / complex(z_load0)
    conductance = y_load0.real
    susceptance = y_load0.imag
    total_b = math.sqrt(conductance / RS - conductance**2)
    c_ideal = (total_b - susceptance) / omega0
    z_parallel = 1 / (conductance + 1j * total_b)
    l_ideal = -z_parallel.imag / omega0

    def objective(values_micro_pico: np.ndarray) -> float:
        l_h = values_micro_pico[0] * 1e-6
        c_f = values_micro_pico[1] * 1e-12
        response = network_response(F0, "active_lossy", l_h, c_f, QL_MATCH, QC_MATCH)
        return -float(response["p_rm_W"][0])

    fit = minimize(
        objective,
        np.array([l_ideal * 1e6, c_ideal * 1e12]),
        method="Nelder-Mead",
        options={"xatol": 1e-11, "fatol": 1e-16, "maxiter": 10000},
    )
    if not fit.success:
        raise RuntimeError(f"Matching optimization failed: {fit.message}")
    l_active = float(fit.x[0] * 1e-6)
    c_active = float(fit.x[1] * 1e-12)
    return {
        "l_ideal_H": l_ideal,
        "c_ideal_F": c_ideal,
        "l_active_H": l_active,
        "c_active_F": c_active,
        "r_l_active_ohm_at_f0": 2 * math.pi * F0 * l_active / QL_MATCH,
        "r_c_active_ohm_at_f0": 1 / (2 * math.pi * F0 * c_active * QC_MATCH),
        "optimizer_iterations": int(fit.nit),
        "optimizer_success": bool(fit.success),
    }


def write_netlists(values: dict[str, float]) -> None:
    common_bvd = f"""C0 n_port 0 {C0:.17g}\nRm n_port n_m1 {RM:.17g}\nLm n_m1 n_m2 {LM:.17g}\nCm n_m2 0 {CM:.17g}"""
    footer = ".ac lin 20001 800k 1Meg\n.options plotwinsize=0\n.end\n"

    before = f"""* V2.1 before matching; AC 1 interpreted as 1 Vrms equivalent\nVdrive n_src 0 AC 1\nRsource n_src n_port {RS:.17g}\n{common_bvd}\n.save V(n_src) V(n_port) I(Vdrive) I(Rsource) I(Rm) I(C0)\n{footer}"""
    ideal = f"""* V2.1 ideal L match; same 1 Vrms Thevenin source\nVdrive n_src 0 AC 1\nRsource n_src n_in {RS:.17g}\nLmatch n_in n_port {values['l_ideal_H']:.17g} Rser=0\nCmatch n_port 0 {values['c_ideal_F']:.17g} Rser=0\n{common_bvd}\n.save V(n_src) V(n_in) V(n_port) I(Vdrive) I(Rsource) I(Lmatch) I(Cmatch) I(Rm) I(C0)\n{footer}"""
    active = f"""* V2.1 active lossy L match; same 1 Vrms Thevenin source\n* QL={QL_MATCH:g}, QC={QC_MATCH:g}; ESR values fixed at f0={F0:g} Hz\nVdrive n_src 0 AC 1\nRsource n_src n_in {RS:.17g}\nRlesr n_in n_l {values['r_l_active_ohm_at_f0']:.17g}\nLmatch n_l n_port {values['l_active_H']:.17g} Rser=0\nCmatch n_port n_c {values['c_active_F']:.17g} Rser=0\nRcesr n_c 0 {values['r_c_active_ohm_at_f0']:.17g}\n{common_bvd}\n.save V(n_src) V(n_in) V(n_port) I(Vdrive) I(Rsource) I(Rlesr) I(Lmatch) I(Cmatch) I(Rcesr) I(Rm) I(C0)\n{footer}"""

    (HERE / "V2_1_MATCH_BEFORE.cir").write_text(before, encoding="utf-8")
    (HERE / "V2_1_MATCH_IDEAL.cir").write_text(ideal, encoding="utf-8")
    (HERE / "V2_1_MATCH_ACTIVE_LOSSY.cir").write_text(active, encoding="utf-8")


def main() -> None:
    values = design_values()
    write_netlists(values)
    freq = np.linspace(0.8e6, 1.0e6, 20001)
    configs = {
        "BEFORE": ("before", 0.0, 0.0, math.inf, math.inf),
        "IDEAL": ("ideal", values["l_ideal_H"], values["c_ideal_F"], math.inf, math.inf),
        "ACTIVE_LOSSY": (
            "active_lossy",
            values["l_active_H"],
            values["c_active_F"],
            QL_MATCH,
            QC_MATCH,
        ),
    }

    responses = {name: network_response(freq, *cfg) for name, cfg in configs.items()}
    fieldnames = [
        "scenario", "frequency_Hz", "zin_real_ohm", "zin_imag_ohm", "zin_abs_ohm",
        "zin_phase_deg", "gamma", "vport_abs_V_per_1Vrms_source", "vport_phase_deg",
        "iport_abs_A", "imotional_abs_A", "p_rm_W", "p_port_W", "q_port_var",
        "s_port_VA", "p_source_W", "p_rs_W", "p_l_esr_W", "p_c_esr_W",
        "power_balance_error_W",
    ]
    with (HERE / "stage2_解析逐频数据.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for scenario, response in responses.items():
            for idx, f_hz in enumerate(freq):
                writer.writerow(
                    {
                        "scenario": scenario,
                        "frequency_Hz": f_hz,
                        "zin_real_ohm": response["z_in"][idx].real,
                        "zin_imag_ohm": response["z_in"][idx].imag,
                        "zin_abs_ohm": abs(response["z_in"][idx]),
                        "zin_phase_deg": np.angle(response["z_in"][idx], deg=True),
                        "gamma": response["gamma"][idx],
                        "vport_abs_V_per_1Vrms_source": abs(response["v_port"][idx]),
                        "vport_phase_deg": np.angle(response["v_port"][idx], deg=True),
                        "iport_abs_A": abs(response["i_port"][idx]),
                        "imotional_abs_A": abs(response["i_motional"][idx]),
                        "p_rm_W": response["p_rm_W"][idx],
                        "p_port_W": response["p_port_W"][idx],
                        "q_port_var": response["q_port_var"][idx],
                        "s_port_VA": response["s_port_VA"][idx],
                        "p_source_W": response["p_source_W"][idx],
                        "p_rs_W": response["p_rs_W"][idx],
                        "p_l_esr_W": response["p_l_esr_W"][idx],
                        "p_c_esr_W": response["p_c_esr_W"][idx],
                        "power_balance_error_W": response["power_balance_error_W"][idx],
                    }
                )

    f0_idx = int(np.argmin(abs(freq - F0)))
    summary_rows = []
    for scenario, response in responses.items():
        peak_idx = int(np.argmax(response["p_rm_W"]))
        summary_rows.append(
            {
                "scenario": scenario,
                "source_Vrms": VS_RMS,
                "source_Rs_ohm": RS,
                "f0_Hz": F0,
                "zin_real_at_f0_ohm": response["z_in"][f0_idx].real,
                "zin_imag_at_f0_ohm": response["z_in"][f0_idx].imag,
                "gamma_at_f0": response["gamma"][f0_idx],
                "vport_at_f0_Vrms": abs(response["v_port"][f0_idx]),
                "p_rm_at_f0_W": response["p_rm_W"][f0_idx],
                "p_source_at_f0_W": response["p_source_W"][f0_idx],
                "p_rs_at_f0_W": response["p_rs_W"][f0_idx],
                "p_l_esr_at_f0_W": response["p_l_esr_W"][f0_idx],
                "p_c_esr_at_f0_W": response["p_c_esr_W"][f0_idx],
                "power_peak_Hz": freq[peak_idx],
                "power_peak_W": response["p_rm_W"][peak_idx],
                "max_abs_balance_error_W": np.max(np.abs(response["power_balance_error_W"])),
            }
        )
    with (HERE / "stage2_解析特征汇总.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    active_f0 = responses["ACTIVE_LOSSY"]
    scale = (100 / (2 * math.sqrt(2))) / abs(active_f0["v_port"][f0_idx])
    calibration = {
        "source_class": "DERIVED_VALUE from active matched baseline; not a hardware rating",
        "calibration_frequency_Hz": F0,
        "target_transducer_Vpp": 100.0,
        "unit_source_Vrms": 1.0,
        "vport_per_unit_source_Vrms": float(abs(active_f0["v_port"][f0_idx])),
        "a1_source_Vrms": float(scale),
        "a1_source_Vpp": float(scale * 2 * math.sqrt(2)),
        "expected_p_rm_W": float(active_f0["p_rm_W"][f0_idx] * scale**2),
        "expected_total_iport_Arms": float(abs(active_f0["i_port"][f0_idx]) * scale),
        "rule": "freeze this Thevenin source amplitude for all future scenarios; protection may only reduce it",
    }
    design = {
        "model_id": "MODEL_V2_1_HYPOTHETICAL",
        "topology": "Rs -> series (R_L_ESR + Lmatch) -> port; shunt (Cmatch + R_C_ESR) across BVD port",
        "comparison_source": "1 Vrms Thevenin source with fixed 50 ohm Rs for BEFORE/IDEAL/ACTIVE_LOSSY",
        "bvd": {"C0_F": C0, "Rm_ohm": RM, "Lm_H": LM, "Cm_F": CM, "fs_Hz": F0},
        "matching_loss_assumptions": {
            "source_class": "HYPOTHETICAL_BASELINE",
            "inductor_Q_at_f0": QL_MATCH,
            "capacitor_Q_at_f0": QC_MATCH,
            "esr_model": "fixed series R calculated at f0",
        },
        "design": values,
        "calibration": calibration,
    }
    (HERE / "stage2_匹配设计参数.json").write_text(
        json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(design, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
