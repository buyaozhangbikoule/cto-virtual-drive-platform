"""Export a versioned electrical-to-structural/acoustic data contract.

This exporter does not run COMSOL or ANSYS.  It converts verified electrical
operating points into voltage-driven harmonic excitation records and creates a
blank return template for future finite-element results.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT_ROOT = ROOT.parent
ACTIVE = PROJECT_ROOT / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5"
MODEL_PATH = ACTIVE / "model_v2_1.py"
SUMMARY_PATH = ACTIVE / "stage3_disturbance" / "stage3_scenario_registry_and_summary.csv"
OUT = ROOT / "interfaces" / "electro_acoustic_v1"
AUDIT_OUT = ROOT / "results" / "interfaces" / "electro_acoustic_v1"
VERSION = "EA_IF_V1.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_model():
    spec = importlib.util.spec_from_file_location("active_model_v2_1_for_interface", MODEL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load model: {MODEL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ELECTRICAL_FIELDS = [
    ("interface_version", "-", True, "Data-contract version", "interface metadata"),
    ("record_id", "-", True, "Unique key shared with the acoustic return file", "derived identifier"),
    ("scenario_id", "-", True, "Electrical disturbance scenario identifier", "scan variable registry"),
    ("operating_point_type", "-", True, "Reason for exporting the point", "derived simulation result"),
    ("parameter_source_class", "-", True, "假设基线值/扫描变量/派生仿真结果", "provenance label"),
    ("electrical_model_id", "-", True, "Electrical model version", "model metadata"),
    ("electrical_model_sha256", "-", True, "Hash of the Python electrical model", "generated evidence"),
    ("phasor_convention", "-", True, "RMS-equivalent phasor convention", "interface convention"),
    ("phase_reference", "-", True, "Ideal Thevenin source voltage is 0 deg", "interface convention"),
    ("excitation_mode", "-", True, "Quantity to impose in the FEM model", "interface convention"),
    ("frequency_Hz", "Hz", True, "Harmonic study frequency", "derived simulation result"),
    ("amplitude_command", "p.u.", True, "Electrical amplitude command in [0,1]", "derived simulation result"),
    ("source_Vrms_real", "V RMS", True, "Real part of ideal Thevenin source phasor", "derived simulation result"),
    ("source_Vrms_imag", "V RMS", True, "Imaginary part of ideal Thevenin source phasor", "derived simulation result"),
    ("vport_Vrms_real", "V RMS", True, "Terminal-voltage phasor real part; FEM voltage excitation", "derived simulation result"),
    ("vport_Vrms_imag", "V RMS", True, "Terminal-voltage phasor imaginary part; FEM voltage excitation", "derived simulation result"),
    ("vport_Vrms_abs", "V RMS", True, "Terminal-voltage phasor magnitude", "derived simulation result"),
    ("vport_phase_deg", "deg", True, "Terminal-voltage phase relative to ideal source", "derived simulation result"),
    ("vport_Vpp", "Vpp", True, "2*sqrt(2)*|Vport,RMS|", "derived simulation result"),
    ("iport_Arms_real", "A RMS", True, "Predicted terminal-current real part; validation only", "derived simulation result"),
    ("iport_Arms_imag", "A RMS", True, "Predicted terminal-current imaginary part; validation only", "derived simulation result"),
    ("iport_Arms_abs", "A RMS", True, "Predicted terminal-current magnitude", "derived simulation result"),
    ("iport_phase_deg", "deg", True, "Predicted terminal-current phase", "derived simulation result"),
    ("zport_ohm_real", "ohm", True, "Transducer terminal impedance real part Vport/Iport", "derived simulation result"),
    ("zport_ohm_imag", "ohm", True, "Transducer terminal impedance imaginary part", "derived simulation result"),
    ("zport_ohm_abs", "ohm", True, "Transducer terminal impedance magnitude", "derived simulation result"),
    ("zport_phase_deg", "deg", True, "Transducer terminal impedance phase", "derived simulation result"),
    ("zin_ohm_real", "ohm", True, "Lossy matching-network input impedance real part", "derived simulation result"),
    ("zin_ohm_imag", "ohm", True, "Lossy matching-network input impedance imaginary part", "derived simulation result"),
    ("zin_ohm_abs", "ohm", True, "Lossy matching-network input impedance magnitude", "derived simulation result"),
    ("matching_input_phase_deg", "deg", True, "arg(Zin); not the transducer-port phase", "derived simulation result"),
    ("p_source_W", "W", True, "Active power supplied by the ideal Thevenin source", "derived simulation result"),
    ("p_port_W", "W", True, "Electrical active power entering the transducer port", "derived simulation result"),
    ("q_port_var", "var", True, "Electrical reactive power at the transducer port", "derived simulation result"),
    ("s_port_VA", "VA", True, "Port apparent-power magnitude", "derived simulation result"),
    ("p_rm_W", "W", True, "BVD motional-branch dissipation; diagnostic, not acoustic power", "derived simulation result"),
    ("eta_elec", "p.u.", True, "Pport/Psource; electrical transfer efficiency only", "derived simulation result"),
    ("reflection_proxy_gamma", "p.u.", True, "|Zin-Rs|/|Zin+Rs|; mismatch proxy, not measured reflected power", "derived simulation result"),
    ("frequency_within_hard_bounds", "bool", True, "0.8-1.0 MHz check", "constraint check"),
    ("voltage_soft_exceeded", "bool", True, "Vport > 130 Vpp", "constraint check"),
    ("voltage_hard_exceeded", "bool", True, "Vport > 160 Vpp", "constraint check"),
    ("current_soft_exceeded", "bool", True, "|Iport| > 5.5 mA RMS", "constraint check"),
    ("current_hard_exceeded", "bool", True, "|Iport| > 6 mA RMS", "constraint check"),
    ("admissible_for_fem_run", "bool", True, "No simulated hard-limit violation", "constraint check"),
    ("electrical_status", "-", True, "Electrical-only record status", "generated evidence"),
]

RETURN_FIELDS = [
    ("interface_version", "-", True, "Must equal the excitation-file version", "interface metadata"),
    ("record_id", "-", True, "Foreign key to the electrical excitation record", "interface metadata"),
    ("solver_name", "-", True, "COMSOL Multiphysics or Ansys Mechanical/Acoustics", "solver metadata"),
    ("solver_version", "-", True, "Exact solver version", "solver metadata"),
    ("solver_model_id", "-", True, "Finite-element model identifier", "solver metadata"),
    ("solver_model_sha256", "-", False, "Hash of exported model/archive if available", "generated evidence"),
    ("mesh_id", "-", True, "Mesh level or mesh hash", "solver metadata"),
    ("frequency_Hz", "Hz", True, "Solved harmonic frequency", "solver input echo"),
    ("terminal_current_Arms_real", "A RMS", True, "FEM terminal-current phasor real part", "FEM solver output"),
    ("terminal_current_Arms_imag", "A RMS", True, "FEM terminal-current phasor imaginary part", "FEM solver output"),
    ("terminal_charge_C_real", "C", False, "Electrode charge phasor real part", "FEM solver output"),
    ("terminal_charge_C_imag", "C", False, "Electrode charge phasor imaginary part", "FEM solver output"),
    ("z_fem_ohm_real", "ohm", True, "Vport/Iterminal real part", "derived from FEM output"),
    ("z_fem_ohm_imag", "ohm", True, "Vport/Iterminal imaginary part", "derived from FEM output"),
    ("relative_acoustic_efficiency", "p.u.", False, "Relative acoustic metric normalized to a declared reference case", "derived from FEM lookup"),
    ("max_displacement_m", "m", True, "Maximum structural displacement magnitude", "FEM solver output"),
    ("reference_displacement_phase_deg", "deg", False, "Phase at a declared structural probe", "FEM solver output"),
    ("target_pressure_Pa_rms", "Pa RMS", True, "Pressure magnitude at a declared acoustic target probe", "FEM solver output"),
    ("target_pressure_phase_deg", "deg", False, "Pressure phase at the target probe", "FEM solver output"),
    ("wall_pressure_Pa_rms", "Pa RMS", False, "Pressure at a declared wall/off-target probe", "FEM solver output"),
    ("radiated_acoustic_power_W", "W", False, "Integrated acoustic intensity over a declared surface", "FEM solver output"),
    ("mesh_convergence_metric_pct", "%", True, "Declared mesh-convergence change", "FEM verification output"),
    ("solver_status", "-", True, "NOT_RUN/PASS/FAIL", "solver evidence"),
    ("solver_log_path", "-", True, "Path to the solver completion log", "solver evidence"),
]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    model = load_model()
    scenario_by_id = model.scenario_map()
    summary_rows = {
        row["case_id"]: row
        for row in csv.DictReader(SUMMARY_PATH.open(encoding="utf-8-sig", newline=""))
    }
    case_ids = ["CASE_000_BASELINE", "CASE_COMBINED_LOW", "CASE_COMBINED_MEDIUM", "CASE_COMBINED_HIGH"]
    model_hash = sha256(MODEL_PATH)

    electrical_rows: list[dict[str, object]] = []
    for case_id in case_ids:
        scenario = scenario_by_id[case_id]
        summary = summary_rows[case_id]
        frequency = float(summary["safe_power_peak_Hz"])
        amplitude = float(summary["safe_amplitude_at_peak"])
        q = model.response(frequency, scenario, amplitude=amplitude)
        source = complex(model.SOURCE_A1_VRMS * amplitude, 0.0)
        vport = complex(q["v_port"][0])
        iport = complex(q["i_port"][0])
        zport = vport / iport
        zin = complex(q["z_in"][0])
        p_source = float(q["p_source_W"][0])
        p_port = float(q["p_port_W"][0])
        vpp = float(q["vport_vpp"][0])
        irms = float(q["iport_irms_A"][0])
        hard_ok = (
            model.F_MIN <= frequency <= model.F_MAX
            and vpp <= model.VPP_HARD + 1e-12
            and irms <= model.IRMS_HARD + 1e-15
        )
        electrical_rows.append({
            "interface_version": VERSION,
            "record_id": f"EA_V1_{case_id}_SAFE_POWER_PEAK",
            "scenario_id": case_id,
            "operating_point_type": "SAFE_POWER_PEAK_FROM_STAGE3",
            "parameter_source_class": "假设基线值+扫描变量+派生仿真结果",
            "electrical_model_id": "MODEL_V2_1_HYPOTHETICAL",
            "electrical_model_sha256": model_hash,
            "phasor_convention": "RMS_EQUIVALENT_EXP_JWT",
            "phase_reference": "IDEAL_THEVENIN_SOURCE_VOLTAGE_0_DEG",
            "excitation_mode": "IMPOSE_COMPLEX_TERMINAL_VOLTAGE_ONLY",
            "frequency_Hz": frequency,
            "amplitude_command": amplitude,
            "source_Vrms_real": source.real,
            "source_Vrms_imag": source.imag,
            "vport_Vrms_real": vport.real,
            "vport_Vrms_imag": vport.imag,
            "vport_Vrms_abs": abs(vport),
            "vport_phase_deg": math.degrees(math.atan2(vport.imag, vport.real)),
            "vport_Vpp": vpp,
            "iport_Arms_real": iport.real,
            "iport_Arms_imag": iport.imag,
            "iport_Arms_abs": abs(iport),
            "iport_phase_deg": math.degrees(math.atan2(iport.imag, iport.real)),
            "zport_ohm_real": zport.real,
            "zport_ohm_imag": zport.imag,
            "zport_ohm_abs": abs(zport),
            "zport_phase_deg": math.degrees(math.atan2(zport.imag, zport.real)),
            "zin_ohm_real": zin.real,
            "zin_ohm_imag": zin.imag,
            "zin_ohm_abs": abs(zin),
            "matching_input_phase_deg": math.degrees(math.atan2(zin.imag, zin.real)),
            "p_source_W": p_source,
            "p_port_W": p_port,
            "q_port_var": float(q["q_port_var"][0]),
            "s_port_VA": float(q["s_port_VA"][0]),
            "p_rm_W": float(q["p_rm_W"][0]),
            "eta_elec": p_port / p_source if p_source > 0 else math.nan,
            "reflection_proxy_gamma": float(q["gamma"][0]),
            "frequency_within_hard_bounds": model.F_MIN <= frequency <= model.F_MAX,
            "voltage_soft_exceeded": vpp > model.VPP_SOFT,
            "voltage_hard_exceeded": vpp > model.VPP_HARD,
            "current_soft_exceeded": irms > model.IRMS_SOFT,
            "current_hard_exceeded": irms > model.IRMS_HARD,
            "admissible_for_fem_run": hard_ok,
            "electrical_status": "ELECTRICAL_ONLY_READY_FOR_FEM_INPUT" if hard_ok else "REJECT_HARD_CONSTRAINT",
        })

    OUT.mkdir(parents=True, exist_ok=True)
    AUDIT_OUT.mkdir(parents=True, exist_ok=True)
    electrical_path = OUT / "electrical_to_acoustic_operating_points.csv"
    electrical_names = [name for name, _, _, _, _ in ELECTRICAL_FIELDS]
    write_csv(electrical_path, electrical_rows, electrical_names)

    dictionary_rows = []
    for direction, fields in [("electrical_to_acoustic", ELECTRICAL_FIELDS), ("acoustic_to_electrical", RETURN_FIELDS)]:
        for name, unit, required, meaning, source in fields:
            dictionary_rows.append({
                "direction": direction,
                "field": name,
                "unit": unit,
                "required": required,
                "meaning": meaning,
                "source_class": source,
            })
    write_csv(
        OUT / "interface_field_dictionary.csv",
        dictionary_rows,
        ["direction", "field", "unit", "required", "meaning", "source_class"],
    )

    schema = {
        "interface_version": VERSION,
        "electrical_to_acoustic": [
            {"name": name, "unit": unit, "required": required, "meaning": meaning, "source_class": source}
            for name, unit, required, meaning, source in ELECTRICAL_FIELDS
        ],
        "acoustic_to_electrical": [
            {"name": name, "unit": unit, "required": required, "meaning": meaning, "source_class": source}
            for name, unit, required, meaning, source in RETURN_FIELDS
        ],
    }
    (OUT / "electro_acoustic_schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return_names = [name for name, _, _, _, _ in RETURN_FIELDS]
    return_rows = []
    for row in electrical_rows:
        blank = {name: "" for name in return_names}
        blank.update({
            "interface_version": VERSION,
            "record_id": row["record_id"],
            "frequency_Hz": row["frequency_Hz"],
            "solver_status": "NOT_RUN",
        })
        return_rows.append(blank)
    write_csv(OUT / "acoustic_results_return_template.csv", return_rows, return_names)

    # Compact table matching the fields requested by the month-one plan.  The
    # acoustic columns deliberately remain blank until an actual FEM lookup
    # table is supplied and solved.
    coupled_rows = []
    for row in electrical_rows:
        coupled_rows.append({
            "interface_version": VERSION,
            "record_id": row["record_id"],
            "scenario_id": row["scenario_id"],
            "frequency_Hz": row["frequency_Hz"],
            "drive_Vpp": row["vport_Vpp"],
            "drive_Vrms": row["vport_Vrms_abs"],
            "drive_phase_deg": row["vport_phase_deg"],
            "electrical_active_power_port_W": row["p_port_W"],
            "electrical_motional_power_P_Rm_W": row["p_rm_W"],
            "relative_acoustic_efficiency": "",
            "target_pressure_proxy_Pa_rms": "",
            "wall_pressure_proxy_Pa_rms": "",
            "acoustic_lookup_model_id": "",
            "acoustic_lookup_status": "NOT_AVAILABLE_NO_COMSOL_RESULT",
            "source_class": "电学=假设/扫描/派生；声学=待求解",
        })
    write_csv(
        OUT / "coupled_lookup_template.csv",
        coupled_rows,
        list(coupled_rows[0].keys()),
    )

    contract = {
        "interface_version": VERSION,
        "coupling_type": "file-based one-way excitation plus optional FEM-result return",
        "electrical_model_scope": "hypothetical small-signal BVD plus lossy L-match, discrete quasi-steady",
        "finite_element_status": "NOT_RUN",
        "recommended_excitation": "Apply frequency_Hz and complex terminal voltage Vport only. Do not impose both voltage and predicted current.",
        "phasor_translation": "Export uses RMS-equivalent exp(+j*omega*t). If the FEM solver uses the opposite time convention, conjugate the exported phasors and verify the terminal-current sign with one baseline case.",
        "validation_loop": "Compare FEM terminal current/impedance with iport/zport using the same record_id.",
        "forbidden_substitutions": [
            "Do not treat p_rm_W as radiated acoustic power.",
            "Do not treat reflection_proxy_gamma as measured reflected RF power.",
            "Do not convert electrical results into pressure without a solved and verified piezoelectric-structural-acoustic model.",
            "Do not report these values as measured device parameters or clinical safety limits.",
        ],
        "required_fem_evidence": [
            "solver name/version and model identifier",
            "geometry/material/electrode/polarization/boundary-condition record",
            "mesh identifier and convergence metric",
            "normal solver completion log",
            "terminal current/impedance, displacement and pressure outputs",
        ],
    }
    (OUT / "interface_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    residuals = []
    all_pass = True
    for row in electrical_rows:
        vr = complex(float(row["vport_Vrms_real"]), float(row["vport_Vrms_imag"]))
        ir = complex(float(row["iport_Arms_real"]), float(row["iport_Arms_imag"]))
        z = vr / ir
        s = vr * ir.conjugate()
        vpp_error = abs(float(row["vport_Vpp"]) - 2 * math.sqrt(2) * abs(vr))
        z_error = abs(z - complex(float(row["zport_ohm_real"]), float(row["zport_ohm_imag"])))
        p_error = abs(s.real - float(row["p_port_W"]))
        row_pass = (
            vpp_error < 1e-10
            and z_error < 1e-8
            and p_error < 1e-10
            and bool(row["admissible_for_fem_run"])
        )
        all_pass = all_pass and row_pass
        residuals.append({
            "record_id": row["record_id"],
            "vpp_identity_error_V": vpp_error,
            "zport_identity_error_ohm": z_error,
            "pport_identity_error_W": p_error,
            "hard_constraint_check": bool(row["admissible_for_fem_run"]),
            "status": "PASS" if row_pass else "FAIL",
        })

    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all_pass else "FAIL",
        "interface_version": VERSION,
        "electrical_record_count": len(electrical_rows),
        "finite_element_solver_was_run": False,
        "schema_validation": residuals,
        "input_hashes": {
            "model_v2_1.py": model_hash,
            "stage3_scenario_registry_and_summary.csv": sha256(SUMMARY_PATH),
        },
        "important_interpretation": "PASS means the electrical export is internally consistent and ready as an FEM input contract; it is not an acoustic-solver result.",
    }
    audit_path = AUDIT_OUT / "electro_acoustic_interface_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(
        AUDIT_OUT / "electro_acoustic_interface_validation.csv",
        residuals,
        list(residuals[0].keys()),
    )

    readme = f"""# 电学—结构/声场文件接口 {VERSION}

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
3. 使用`vport_Vrms_real/im​ag`或等价的幅值/相位作为端子电压激励；不要同时强制施加预测电流。
   导出采用RMS等效`exp(+jωt)`约定；若求解器采用相反时间因子，应对相量取共轭，并用基准端口电流检查符号。
4. 求解器输出端子电流后，计算FEM端口阻抗并与`zport_*`进行同工况校核。
5. 将位移、目标点声压、壁面声压和积分声功率写回返回模板。
6. 保留模型版本、网格ID、收敛指标和Solver Log。

## 严格边界

`p_rm_W`是BVD运动支路电阻耗散，不能直接当成辐射声功率；`eta_elec`是电学传输效率，不能当成声电转换效率；`reflection_proxy_gamma`不是实测反射功率。

接口审核：`{audit_path}`。审核PASS只证明电学导出内部一致，并不表示结构/声场计算已经完成。
"""
    # Remove a possible invisible character introduced by line wrapping in editors.
    readme = readme.replace("im\u200bag", "imag")
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    print(json.dumps({
        "status": audit["status"],
        "interface_dir": str(OUT),
        "audit": str(audit_path),
        "records": len(electrical_rows),
        "finite_element_solver_was_run": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
