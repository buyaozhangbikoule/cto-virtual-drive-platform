from pathlib import Path
import json
import re
import sys

import numpy as np

ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
sys.path.insert(0, str(ROOT / "work"))
from fourth_step_control_strategies import read_ltspice_raw  # noqa: E402

fresh_dir = ROOT / "work" / "audit_ltspice_recheck"
orig_single = ROOT / "outputs" / "single_factor_disturbance_results" / "ltspice_cases"
orig_control = ROOT / "outputs" / "fourth_step_control_strategies" / "ltspice_cases"

rows = []
for case_id in ["CASE_000_BASELINE", "CASE_330_FS_M5", "CASE_730_Q20", "CASE_402_COMBINED_HIGH"]:
    original_dir = orig_control if case_id == "CASE_402_COMBINED_HIGH" else orig_single
    fresh = read_ltspice_raw(fresh_dir / f"{case_id}.raw")
    original = read_ltspice_raw(original_dir / f"{case_id}.raw")
    common = sorted(set(fresh) & set(original))
    max_abs = 0.0
    max_rel = 0.0
    worst_var = ""
    for name in common:
        diff = np.abs(fresh[name] - original[name])
        scale = max(float(np.max(np.abs(original[name]))), 1e-30)
        local_abs = float(np.max(diff))
        local_rel = local_abs / scale
        if local_rel > max_rel:
            max_rel = local_rel
            max_abs = local_abs
            worst_var = name
    freq = np.real(fresh["frequency"])
    zin = fresh["v(n_s)"] / fresh["i(rlesr)"]
    power = np.real(fresh["v(n_in)"] * np.conj(fresh["i(rmot)"]))
    phase = np.angle(zin, deg=True)
    rs = 60.0 if case_id == "CASE_402_COMBINED_HIGH" else 50.0
    gamma = np.abs((zin - rs) / (zin + rs))
    log_text = (fresh_dir / f"{case_id}.log").read_text(encoding="utf-8", errors="replace")
    version = re.search(r"LTspice[^\r\n]*for Windows", log_text)
    rows.append({
        "case_id": case_id,
        "points": len(freq),
        "f_start_hz": float(freq[0]),
        "f_stop_hz": float(freq[-1]),
        "power_peak_hz": float(freq[int(np.argmax(power))]),
        "min_reflection_hz": float(freq[int(np.argmin(gamma))]),
        "phase_at_0p9_deg": float(np.interp(900000.0, freq, phase)),
        "max_relative_difference_vs_original_raw": max_rel,
        "max_absolute_difference_vs_original_raw": max_abs,
        "worst_variable": worst_var,
        "ltspice_version": version.group(0) if version else "not found",
    })

print(json.dumps(rows, ensure_ascii=False, indent=2))
