"""Run an isolated LTspice AC validation for one interactive v2.1 scenario.

The generated run directory is append-only and separate from the formally
audited stage outputs.  AC phasors follow the project's RMS-equivalent
convention; this module does not model a switching power amplifier.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
RAW_PARSER_PATH = HERE / "archived_sources" / "stage1" / "analyze_v2_stage1.py"


def _load_raw_parser():
    spec = importlib.util.spec_from_file_location("platform_ltspice_raw_parser", RAW_PARSER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载LTspice RAW解析器：{RAW_PARSER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_ltspice_raw


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _max_relative(actual: np.ndarray, expected: np.ndarray) -> float:
    scale = np.maximum(np.abs(expected), np.max(np.abs(expected)) * 1e-12)
    return float(np.max(np.abs(actual - expected) / scale))


def _full_scale_error(actual: np.ndarray, expected: np.ndarray) -> float:
    return float(np.max(np.abs(actual - expected)) / max(float(np.max(np.abs(expected))), 1e-30))


def _scenario_payload(model: Any, scenario: Any, frequency_hz: np.ndarray, amplitude: float) -> dict[str, Any]:
    bvd = scenario.bvd
    matching = scenario.matching
    return {
        "model": "MODEL_V2_1_HYPOTHETICAL",
        "case_id": scenario.case_id,
        "description": scenario.description,
        "amplitude_command": float(amplitude),
        "source_Vrms_RMS_equivalent": float(model.SOURCE_A1_VRMS * amplitude),
        "frequency_start_Hz": float(frequency_hz[0]),
        "frequency_stop_Hz": float(frequency_hz[-1]),
        "frequency_points": int(frequency_hz.size),
        "Rs_ohm": float(scenario.rs),
        "C0_F": float(bvd.c0),
        "Rm_ohm": float(bvd.rm),
        "Lm_H": float(bvd.lm),
        "Cm_F": float(bvd.cm),
        "derived_fs_Hz": float(bvd.fs),
        "derived_Qm": float(bvd.qm),
        "Lmatch_H": float(matching.l_h),
        "Cmatch_F": float(matching.c_f),
        "inductor_Q": float(matching.ql),
        "capacitor_Q": float(matching.qc),
    }


def scenario_payload(model: Any, scenario: Any, frequency_hz: np.ndarray, amplitude: float) -> dict[str, Any]:
    """Return the canonical parameter record used to identify an interactive run."""
    return _scenario_payload(model, scenario, np.asarray(frequency_hz, dtype=float), amplitude)


def _write_netlist(
    path: Path,
    *,
    model: Any,
    scenario: Any,
    frequency_hz: np.ndarray,
    amplitude: float,
) -> None:
    bvd = scenario.bvd
    matching = scenario.matching
    r_l = 2 * math.pi * model.F0 * matching.l_h / matching.ql
    r_c = 1 / (2 * math.pi * model.F0 * matching.c_f * matching.qc)
    source_vrms = model.SOURCE_A1_VRMS * amplitude
    netlist = f"""* UI_LTSPICE_CURRENT_SCENARIO; MODEL_V2_1_HYPOTHETICAL; AC RMS-equivalent source
* Generated from Streamlit controls; not a measured transducer or switching-amplifier model.
Vdrive n_src 0 AC {source_vrms:.17g}
Rsource n_src n_in {scenario.rs:.17g}
Rlesr n_in n_l {r_l:.17g}
Lmatch n_l n_port {matching.l_h:.17g}
Cmatch n_port n_c {matching.c_f:.17g}
Rcesr n_c 0 {r_c:.17g}
C0 n_port 0 {bvd.c0:.17g}
Rm n_port n_m1 {bvd.rm:.17g}
Lm n_m1 n_m2 {bvd.lm:.17g}
Cm n_m2 0 {bvd.cm:.17g}
.ac lin {frequency_hz.size} {frequency_hz[0]:.17g} {frequency_hz[-1]:.17g}
.options plotwinsize=0
.save V(n_src) V(n_in) V(n_port) I(Rsource) I(Rm) I(C0) I(Rlesr) I(Rcesr)
.end
"""
    path.write_text(netlist, encoding="ascii")


def run_ltspice_current_scenario(
    *,
    model: Any,
    scenario: Any,
    frequency_hz: np.ndarray,
    amplitude: float,
    ltspice_executable: str | Path,
    output_root: str | Path,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Run LTspice, parse RAW, compare against Python, and persist evidence."""
    executable = Path(ltspice_executable)
    if not executable.is_file():
        raise FileNotFoundError(f"找不到LTspice可执行文件：{executable}")
    frequency_hz = np.asarray(frequency_hz, dtype=float)
    if frequency_hz.ndim != 1 or frequency_hz.size < 2:
        raise ValueError("频率数组必须是一维且至少包含两个点")

    payload = _scenario_payload(model, scenario, frequency_hz, amplitude)
    signature = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:10]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = Path(output_root) / f"UI_LT_{timestamp}_{signature}"
    run_dir.mkdir(parents=True, exist_ok=False)

    cir_path = run_dir / "UI_CURRENT_SCENARIO.cir"
    raw_path = cir_path.with_suffix(".raw")
    log_path = cir_path.with_suffix(".log")
    _write_netlist(
        cir_path,
        model=model,
        scenario=scenario,
        frequency_hz=frequency_hz,
        amplitude=amplitude,
    )
    (run_dir / "scenario_parameters.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    completed = subprocess.run(
        [str(executable), "-b", cir_path.name],
        cwd=run_dir,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    (run_dir / "ltspice_stdout.txt").write_text(completed.stdout or "", encoding="utf-8")
    (run_dir / "ltspice_stderr.txt").write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode != 0 or not raw_path.is_file():
        raise RuntimeError(
            f"LTspice运行失败：returncode={completed.returncode}；"
            f"RAW存在={raw_path.is_file()}；目录={run_dir}"
        )

    read_ltspice_raw = _load_raw_parser()
    raw = read_ltspice_raw(raw_path)
    f = np.real(raw["frequency"])
    expected = model.response(f, scenario, amplitude=amplitude)

    i_source = raw["i(rsource)"]
    z_in = raw["v(n_in)"] / i_source
    if np.mean(np.abs(z_in - expected["z_in"])) > np.mean(np.abs(-z_in - expected["z_in"])):
        i_source = -i_source
        z_in = -z_in

    v_source = raw["v(n_src)"]
    v_port = raw["v(n_port)"]
    i_motional = raw["i(rm)"]
    i_port = i_motional + raw["i(c0)"]
    z_port = np.divide(v_port, i_port, out=np.full_like(v_port, np.nan), where=np.abs(i_port) > 1e-30)
    p_port = np.real(v_port * np.conj(i_port))
    p_rm = np.abs(i_motional) ** 2 * scenario.bvd.rm
    p_source = np.real(v_source * np.conj(i_source))
    gamma = np.abs((z_in - scenario.rs) / (z_in + scenario.rs))

    actual = {
        "frequency_Hz": f,
        "v_port": v_port,
        "i_port": i_port,
        "z_port": z_port,
        "z_in": z_in,
        "p_port_W": p_port,
        "p_rm_W": p_rm,
        "p_source_W": p_source,
        "gamma": gamma,
    }
    expected_z_port = expected["v_port"] / expected["i_port"]
    errors = {
        "max_Zin_relative_error": _max_relative(z_in, expected["z_in"]),
        "max_Zport_relative_error": _max_relative(z_port, expected_z_port),
        "max_Vport_relative_error": _max_relative(v_port, expected["v_port"]),
        "max_Iport_relative_error": _max_relative(i_port, expected["i_port"]),
        "max_Pport_full_scale_error": _full_scale_error(p_port, expected["p_port_W"]),
        "max_Prm_full_scale_error": _full_scale_error(p_rm, expected["p_rm_W"]),
        "max_gamma_absolute_error": float(np.max(np.abs(gamma - expected["gamma"]))),
    }
    relative_worst = max(
        errors["max_Zin_relative_error"],
        errors["max_Zport_relative_error"],
        errors["max_Vport_relative_error"],
        errors["max_Iport_relative_error"],
        errors["max_Pport_full_scale_error"],
        errors["max_Prm_full_scale_error"],
    )
    status = "PASS" if relative_worst < 0.05 and errors["max_gamma_absolute_error"] < 0.05 else "FAIL"

    detail = pd.DataFrame({
        "frequency_Hz": f,
        "LT_Vport_abs_Vrms": np.abs(v_port),
        "PY_Vport_abs_Vrms": np.abs(expected["v_port"]),
        "LT_Iport_abs_Arms": np.abs(i_port),
        "PY_Iport_abs_Arms": np.abs(expected["i_port"]),
        "LT_Zin_abs_ohm": np.abs(z_in),
        "PY_Zin_abs_ohm": np.abs(expected["z_in"]),
        "LT_Zin_phase_deg": np.angle(z_in, deg=True),
        "PY_Zin_phase_deg": np.angle(expected["z_in"], deg=True),
        "LT_Zport_abs_ohm": np.abs(z_port),
        "PY_Zport_abs_ohm": np.abs(expected_z_port),
        "LT_Zport_phase_deg": np.angle(z_port, deg=True),
        "PY_Zport_phase_deg": np.angle(expected_z_port, deg=True),
        "LT_Pport_W": p_port,
        "PY_Pport_W": expected["p_port_W"],
        "LT_PRm_W": p_rm,
        "PY_PRm_W": expected["p_rm_W"],
        "LT_reflection_proxy": gamma,
        "PY_reflection_proxy": expected["gamma"],
    })
    detail_csv_path = run_dir / "LTspice_Python_frequency_comparison.csv"
    detail.to_csv(detail_csv_path, index=False, encoding="utf-8-sig")

    audit = {
        "status": status,
        "ltspice_return_code": int(completed.returncode),
        "ltspice_executable": str(executable.resolve()),
        "run_directory": str(run_dir.resolve()),
        "cir_path": str(cir_path.resolve()),
        "raw_path": str(raw_path.resolve()),
        "log_path": str(log_path.resolve()),
        "detail_csv_path": str(detail_csv_path.resolve()),
        "points": int(f.size),
        "raw_bytes": raw_path.stat().st_size,
        "raw_sha256": _sha256(raw_path),
        "log_sha256": _sha256(log_path) if log_path.is_file() else None,
        "errors": errors,
        "note": "AC phasors use the project's RMS-equivalent convention; not a transient switching waveform.",
    }
    audit_path = run_dir / "LTspice_validation_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    audit["audit_path"] = str(audit_path.resolve())

    return {
        "actual": actual,
        "expected": expected,
        "expected_z_port": expected_z_port,
        "audit": audit,
        "comparison_csv": detail.to_csv(index=False).encode("utf-8-sig"),
        "scenario": payload,
    }
