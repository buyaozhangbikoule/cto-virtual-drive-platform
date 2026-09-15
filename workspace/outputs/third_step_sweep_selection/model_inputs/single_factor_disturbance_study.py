"""Generate single-factor BVD disturbance cases and LTspice netlists.

All values are assumed virtual-study parameters. The source amplitude is held
fixed at the value calibrated for 100 Vpp across the baseline transducer at
0.9 MHz. Each non-baseline case changes exactly one model parameter.
"""

from dataclasses import asdict, replace
from pathlib import Path
import csv
import json

import numpy as np

from combination_disturbance_study import (
    BASE_BVD,
    BASE_MATCH,
    BASE_RS,
    F_FIXED,
    F_MAX,
    F_MIN,
    FREQUENCIES,
    IPEAK_HARD,
    IPEAK_NOMINAL,
    IPEAK_SOFT,
    N_FREQ,
    Scenario,
    VPP_HARD,
    VPP_NOMINAL,
    VS_RMS,
    circuit_quantities,
    shifted_fs,
)


def scenario(case_id, factor, level, value_label, bvd=BASE_BVD, rs=BASE_RS, matching=BASE_MATCH):
    return Scenario(
        case_id=case_id,
        label_zh=f"{factor}：{value_label}",
        complexity=level,
        bvd=bvd,
        rs=rs,
        matching=matching,
        description="除标明参数外，其余BVD、源阻抗和匹配网络参数保持基准值",
    )


def make_scenarios():
    cases = [
        scenario("CASE_000_BASELINE", "基准", "baseline", "无扰动"),
    ]
    for pct, code in ((10, 110), (20, 120), (30, 130)):
        cases.append(scenario(
            f"CASE_{code}_C0_P{pct}", "C0", f"+{pct}%", f"+{pct}%",
            bvd=replace(BASE_BVD, c0=BASE_BVD.c0 * (1 + pct / 100)),
        ))
    for pct, code in ((15, 210), (30, 220), (50, 230)):
        cases.append(scenario(
            f"CASE_{code}_RM_P{pct}", "Rm", f"+{pct}%", f"+{pct}%",
            bvd=replace(BASE_BVD, rm=BASE_BVD.rm * (1 + pct / 100)),
        ))
    for pct, code in ((1, 310), (3, 320), (5, 330)):
        cases.append(scenario(
            f"CASE_{code}_FS_M{pct}", "fs", f"-{pct}%", f"-{pct}%（仅改变Cm）",
            bvd=shifted_fs(BASE_BVD, 1 - pct / 100),
        ))
    for pct, code in ((5, 410), (10, 420), (20, 430)):
        cases.append(scenario(
            f"CASE_{code}_RS_P{pct}", "Rs", f"+{pct}%", f"+{pct}%",
            rs=BASE_RS * (1 + pct / 100),
        ))
    for pct, code in ((2, 510), (5, 520), (10, 530)):
        cases.append(scenario(
            f"CASE_{code}_LS_P{pct}", "Ls", f"+{pct}%", f"+{pct}%",
            matching=replace(BASE_MATCH, ls=BASE_MATCH.ls * (1 + pct / 100)),
        ))
    for pct, code in ((2, 610), (5, 620), (10, 630)):
        cases.append(scenario(
            f"CASE_{code}_CP_M{pct}", "Cp", f"-{pct}%", f"-{pct}%",
            matching=replace(BASE_MATCH, cp=BASE_MATCH.cp * (1 - pct / 100)),
        ))
    for q, code in ((50, 720), (20, 730)):
        cases.append(scenario(
            f"CASE_{code}_Q{q}", "电感Q", f"Q={q}", f"Q={q}",
            matching=replace(BASE_MATCH, q_inductor=float(q)),
        ))
    return cases


SCENARIOS = make_scenarios()


def factor_and_level(case):
    if case.case_id == "CASE_000_BASELINE":
        return "基准", "基准"
    return case.label_zh.split("：", 1)


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def parameter_rows():
    rows = []
    active_parameter = {
        "C0": "C0_F",
        "Rm": "Rm_ohm",
        "fs": "Cm_F",
        "Rs": "Rs_ohm",
        "Ls": "Ls_H",
        "Cp": "Cp_F",
        "电感Q": "inductor_Q",
    }
    for case in SCENARIOS:
        factor, level = factor_and_level(case)
        fs = 1 / (2 * np.pi * np.sqrt(case.bvd.lm * case.bvd.cm))
        values = {
            "C0_F": case.bvd.c0,
            "Rm_ohm": case.bvd.rm,
            "Lm_H": case.bvd.lm,
            "Cm_F": case.bvd.cm,
            "fs_derived_Hz": fs,
            "Rs_ohm": case.rs,
            "Ls_H": case.matching.ls,
            "Cp_F": case.matching.cp,
            "inductor_Q": case.matching.q_inductor,
            "inductor_ESR_at_0p9MHz_ohm": 2 * np.pi * F_FIXED * case.matching.ls / case.matching.q_inductor,
        }
        for name, value in values.items():
            changed = case.case_id != "CASE_000_BASELINE" and name == active_parameter.get(factor)
            derived = case.case_id != "CASE_000_BASELINE" and (
                (factor == "fs" and name == "fs_derived_Hz")
                or (factor in {"Ls", "电感Q"} and name == "inductor_ESR_at_0p9MHz_ohm")
            )
            rows.append({
                "case_id": case.case_id,
                "扰动参数": factor,
                "扰动等级": level,
                "参数": name,
                "数值": value,
                "是否为本场景主动改变项": int(changed),
                "是否为派生变化": int(derived),
                "参数身份": "假设基线值" if case.case_id == "CASE_000_BASELINE" else "扫描变量",
                "说明": case.description,
            })
    return rows


def analytic_rows():
    rows = []
    for case in SCENARIOS:
        factor, level = factor_and_level(case)
        q = circuit_quantities(FREQUENCIES, case, VS_RMS)
        for i, frequency in enumerate(FREQUENCIES):
            zin = q["zin"][i]
            rows.append({
                "case_id": case.case_id,
                "扰动参数": factor,
                "扰动等级": level,
                "frequency_hz": frequency,
                "zin_real_ohm": np.real(zin),
                "zin_imag_ohm": np.imag(zin),
                "zin_mag_ohm": np.abs(zin),
                "phase_deg": q["phase_deg"][i],
                "active_power_w": q["power"][i],
                "reflection_proxy": q["gamma"][i],
                "transducer_vpp": q["vpp"][i],
                "transducer_current_a_peak": q["current_peak"][i],
                "motional_current_a_peak": q["motional_current_peak"][i],
                "source_current_a_peak": q["source_current_peak"][i],
                "matching_loss_w": q["match_loss"][i],
            })
    return rows


def write_netlists(outdir):
    netdir = outdir / "ltspice_cases"
    netdir.mkdir(parents=True, exist_ok=True)
    for case in SCENARIOS:
        r_esr = 2 * np.pi * F_FIXED * case.matching.ls / case.matching.q_inductor
        text = f"""* {case.case_id}: assumed single-factor BVD disturbance case
* All unlisted parameters remain at baseline.
* AC amplitudes are RMS phasors. Current limits use BVD total terminal peak current.
V1 src 0 AC {VS_RMS:.12g}
Rsrc src n_s {case.rs:.12g}
Rlesr n_s n_l {r_esr:.12g}
Lmatch n_l n_in {case.matching.ls:.12g}
Cmatch n_in 0 {case.matching.cp:.12g}
Cstatic n_in 0 {case.bvd.c0:.12g}
Rmot n_in n_m1 {case.bvd.rm:.12g}
Lmot n_m1 n_m2 {case.bvd.lm:.12g}
Cmot n_m2 0 {case.bvd.cm:.12g}
.ac lin {N_FREQ} {F_MIN:.12g} {F_MAX:.12g}
.options meascplxfmt=cartesian
.meas ac Zin_mag_fixed FIND mag(V(n_s)/I(Rlesr)) AT={F_FIXED:.12g}
.meas ac Zin_real_fixed FIND re(V(n_s)/I(Rlesr)) AT={F_FIXED:.12g}
.meas ac Zin_imag_fixed FIND im(V(n_s)/I(Rlesr)) AT={F_FIXED:.12g}
.meas ac Phase_fixed FIND ph(V(n_s)/I(Rlesr)) AT={F_FIXED:.12g}
.meas ac Vpp_fixed FIND mag(V(n_in))*2*sqrt(2) AT={F_FIXED:.12g}
.meas ac Itrans_peak_fixed FIND mag(I(Rmot)+I(Cstatic))*sqrt(2) AT={F_FIXED:.12g}
.meas ac Imot_peak_fixed FIND mag(I(Rmot))*sqrt(2) AT={F_FIXED:.12g}
.meas ac Isource_peak_fixed FIND mag(I(Rlesr))*sqrt(2) AT={F_FIXED:.12g}
.meas ac P_fixed FIND re(V(n_in)*conj(I(Rmot))) AT={F_FIXED:.12g}
.meas ac Gamma_fixed FIND mag((V(n_s)/I(Rlesr)-{case.rs:.12g})/(V(n_s)/I(Rlesr)+{case.rs:.12g})) AT={F_FIXED:.12g}
.meas ac Pmax MAX re(V(n_in)*conj(I(Rmot)))
.end
"""
        (netdir / f"{case.case_id}.cir").write_text(text, encoding="ascii")


def main():
    outdir = Path(__file__).resolve().parent / "single_factor_disturbance_results"
    outdir.mkdir(parents=True, exist_ok=True)
    write_csv(outdir / "单因素扰动_参数登记.csv", parameter_rows())
    write_csv(outdir / "单因素扰动_解析逐频数据.csv", analytic_rows())
    write_netlists(outdir)
    manifest = {
        "model_scope": "assumed virtual electrical BVD model; no measured transducer parameters",
        "source_voltage_rms_fixed": VS_RMS,
        "baseline_target_voltage_vpp_at_0p9MHz": VPP_NOMINAL,
        "voltage_hard_limit_vpp": VPP_HARD,
        "current_nominal_a_peak": IPEAK_NOMINAL,
        "current_soft_a_peak": IPEAK_SOFT,
        "current_hard_a_peak": IPEAK_HARD,
        "current_measurement": "mag(I(Rmot)+I(Cstatic))*sqrt(2)",
        "source_current_policy": "record separately; do not apply the 5 mA constraint",
        "active_power": "re(V(n_in)*conj(I(Rmot)))",
        "signed_phase": "Cartesian phase of V(n_s)/I(Rlesr)",
        "frequency_start_hz": F_MIN,
        "frequency_stop_hz": F_MAX,
        "frequency_points": N_FREQ,
        "scenarios": [
            {**asdict(case), "bvd": asdict(case.bvd), "matching": asdict(case.matching),
             "factor": factor_and_level(case)[0], "level": factor_and_level(case)[1]}
            for case in SCENARIOS
        ],
    }
    (outdir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"output_dir={outdir}")
    print(f"scenario_count={len(SCENARIOS)}")
    for case in SCENARIOS:
        print(case.case_id, case.label_zh)


if __name__ == "__main__":
    main()
