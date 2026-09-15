"""Actually execute LTspice batch AC checks. This is NOT a controller .tran run."""
import csv
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np
import run_experiments as exp


def main():
    exp.snapshot()
    m, c = exp.load_legacy()
    exe = Path("D:/LTspice.exe")
    out = exp.HERE / "ltspice_ac_verification"
    out.mkdir(exist_ok=True)
    parser_src = exp.ORIGINAL.parent / "ltspice_stage1/analyze_v2_stage1.py"
    parser = exp.SNAPSHOT / "read_raw_reference.py"
    if not parser.exists():
        shutil.copy2(parser_src, parser)
    spec = importlib.util.spec_from_file_location("raw_reader", parser)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    audit = []
    for case in ("CASE_000_BASELINE", "CASE_FS_M5", "CASE_LMATCH_P10", "CASE_COMBINED_HIGH"):
        s = m.scenario_map()[case]
        for a in (.25, .4, 1.0):
            stem = f"{case}_a{a:.2f}"
            cir = out / (stem + ".cir")
            assert not cir.with_suffix(".raw").exists(), "Use a new directory for new solver evidence"
            b, match = s.bvd, s.matching
            rl = 2 * math.pi * m.F0 * match.l_h / match.ql
            rc = 1 / (2 * math.pi * m.F0 * match.c_f * match.qc)
            cir.write_text(f"""* {case}; assumed BVD; independent AC verification; a={a}
Vdrive n_src 0 AC {m.SOURCE_A1_VRMS * a:.17g}
Rsource n_src n_in {s.rs:.17g}
Rlesr n_in n_l {rl:.17g}
Lmatch n_l n_port {match.l_h:.17g}
Cmatch n_port n_c {match.c_f:.17g}
Rcesr n_c 0 {rc:.17g}
C0 n_port 0 {b.c0:.17g}
Rm n_port n_m1 {b.rm:.17g}
Lm n_m1 n_m2 {b.lm:.17g}
Cm n_m2 0 {b.cm:.17g}
.ac lin 2001 800000 1000000
.options plotwinsize=0
.save V(n_src) V(n_in) V(n_port) I(Rsource) I(Rm) I(C0) I(Rlesr) I(Rcesr)
.end
""", encoding="ascii")
            start = time.perf_counter()
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run([str(exe), "-b", cir.name], cwd=out, capture_output=True, timeout=60, creationflags=flags)
            raw_path, log_path = cir.with_suffix(".raw"), cir.with_suffix(".log")
            if proc.returncode != 0 or not raw_path.exists() or not log_path.exists():
                raise RuntimeError(f"LTspice failed: {case}, return={proc.returncode}, stderr={proc.stderr!r}")
            raw = mod.read_ltspice_raw(raw_path)
            f = raw["frequency"].real
            z = raw["v(n_in)"] / raw["i(rsource)"]
            v = raw["v(n_port)"]
            i = raw["i(rm)"] + raw["i(c0)"]
            p = np.abs(raw["i(rm)"])**2 * b.rm
            q = m.response(f, s, a)
            rel = lambda actual, expected: float(np.max(np.abs(actual - expected) / np.maximum(np.abs(expected), 1e-20))) * 100
            row = {"case_id": case, "amplitude": a, "return_code": proc.returncode,
                   "elapsed_wall_s": time.perf_counter() - start, "frequency_points": len(f),
                   "max_zin_relative_error_pct": rel(z, q["z_in"]),
                   "max_vport_relative_error_pct": rel(v, q["v_port"]),
                   "max_iport_relative_error_pct": rel(i, q["i_port"]),
                   "max_prm_relative_error_pct": rel(p, q["p_rm_W"]),
                   "max_phase_abs_error_deg": float(np.max(np.abs(np.angle(z / q["z_in"], deg=True)))),
                   "cir_sha256": exp.sha(cir), "raw_sha256": exp.sha(raw_path), "log_sha256": exp.sha(log_path),
                   "raw_file": raw_path.name, "log_file": log_path.name}
            row["pass_5pct"] = all(row[k] < 5 for k in ("max_zin_relative_error_pct", "max_vport_relative_error_pct", "max_iport_relative_error_pct", "max_prm_relative_error_pct"))
            assert row["pass_5pct"], row
            exp.save_csv(out / (stem + "_comparison.csv"), [
                {"frequency_Hz": float(fi), "vport_lt_Vpp": float(abs(vi) * 2 * math.sqrt(2)),
                 "vport_python_Vpp": float(q["vport_vpp"][j]), "iport_lt_Arms": float(abs(ii)),
                 "iport_python_Arms": float(q["iport_irms_A"][j]), "prm_lt_W": float(pi), "prm_python_W": float(q["p_rm_W"][j])}
                for j, (fi, vi, ii, pi) in enumerate(zip(f, v, i, p))])
            audit.append(row)
            print(stem, "PASS", row["max_zin_relative_error_pct"], flush=True)
    exp.save_csv(out / "cross_validation.csv", audit)
    exp.save_json(out / "audit.json", {"LTspice_executed": True, "command": [str(exe), "-b", "<case>.cir"],
                  "executable_sha256": exp.sha(exe), "parser_sha256": exp.sha(parser),
                  "analysis": "AC, RMS-equivalent interpretation", "controller_transient_validated": False,
                  "GUI_screenshot_created": False, "runs": audit})


if __name__ == "__main__":
    main()
