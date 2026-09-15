"""Fresh real LTspice AC runs, including binding-current diagnostic models."""
import importlib.util
import math
from pathlib import Path
import subprocess
import time

import numpy as np
import run_factorial as r
from run_diagnostics import stress_scenarios


def main():
    out = r.HERE / "ltspice"
    out.mkdir(exist_ok=False)
    base, model, legacy = r.load()
    parser_path = r.FROZEN / "snapshot/read_raw_reference.py"
    spec = importlib.util.spec_from_file_location("factorial_raw_reader", parser_path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    executable = Path("D:/LTspice.exe")
    scenarios = {k: model.scenario_map()[k] for k in ("CASE_000_BASELINE", "CASE_COMBINED_HIGH")}
    scenarios.update(stress_scenarios(model))
    frequency = np.arange(800000., 1000000.1, 100.)
    runs = []
    for key, scenario in scenarios.items():
        i = int(np.argmax(model.safe_power(frequency, scenario)))
        operating_a = float(model.allowed_amplitude(frequency[i], scenario, use_soft_limits=True)[0])
        for tag, a in (("LOW025", .25), ("SCAN040", .4), ("SOFT_OPTIMUM", operating_a)):
            stem = f"{key}_{tag}"
            p, match = scenario.bvd, scenario.matching
            net = out / f"{stem}.cir"
            net.write_text(f"""* Hypothetical model; AC RMS-equivalent source; not a controller transient
Vdrive src 0 AC {model.SOURCE_A1_VRMS*a:.17g}
Rsource src vin {scenario.rs:.17g}
Rlesr vin nl {2*math.pi*model.F0*match.l_h/match.ql:.17g}
Lmatch nl port {match.l_h:.17g}
Cmatch port nc {match.c_f:.17g}
Rcesr nc 0 {1/(2*math.pi*model.F0*match.c_f*match.qc):.17g}
C0 port 0 {p.c0:.17g}
Rm port nm1 {p.rm:.17g}
Lm nm1 nm2 {p.lm:.17g}
Cm nm2 0 {p.cm:.17g}
.ac lin 2001 800000 1000000
.options plotwinsize=0
.save V(vin) V(port) I(Rsource) I(Rm) I(C0)
.end
""", encoding="ascii")
            start = time.perf_counter()
            process = subprocess.run([str(executable), "-b", net.name], cwd=out, capture_output=True,
                                     timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            raw, log = net.with_suffix(".raw"), net.with_suffix(".log")
            assert process.returncode == 0 and raw.is_file() and log.is_file()
            data = reader.read_ltspice_raw(raw)
            f = data["frequency"].real
            expected = model.response(f, scenario, a)
            z = data["v(vin)"] / data["i(rsource)"]
            v, current = data["v(port)"], data["i(rm)"] + data["i(c0)"]
            power = abs(data["i(rm)"])**2*p.rm
            error = lambda actual, ref: float(np.max(abs(actual-ref)/np.maximum(abs(ref), 1e-20))*100)
            record = {"case_id": key, "amplitude_tag": tag, "amplitude": a, "return_code": process.returncode,
                      "points": len(f), "duration_wall_s": time.perf_counter()-start,
                      "zin_error_pct": error(z, expected["z_in"]), "vport_error_pct": error(v, expected["v_port"]),
                      "iport_error_pct": error(current, expected["i_port"]), "prm_error_pct": error(power, expected["p_rm_W"]),
                      "phase_absolute_error_deg": float(np.max(abs(np.angle(z/expected["z_in"], deg=True)))),
                      "cir": net.name, "raw": raw.name, "log": log.name,
                      "cir_sha256": r.sha(net), "raw_sha256": r.sha(raw), "log_sha256": r.sha(log)}
            record["pass_5pct"] = max(record[k] for k in ("zin_error_pct", "vport_error_pct", "iport_error_pct", "prm_error_pct")) < 5
            assert record["pass_5pct"]
            base.save_csv(out / f"{stem}_comparison.csv", [{"frequency_Hz": float(ff), "ltspice_prm_W": float(power[j]),
                          "python_prm_W": float(expected["p_rm_W"][j]), "ltspice_vport_Vpp": float(abs(v[j])*2*math.sqrt(2)),
                          "python_vport_Vpp": float(expected["vport_vpp"][j]), "ltspice_current_Arms": float(abs(current[j])),
                          "python_current_Arms": float(expected["iport_irms_A"][j])} for j, ff in enumerate(f)])
            runs.append(record)
            print(stem, "PASS", flush=True)
    base.save_csv(out / "cross_validation.csv", runs)
    r.save_json(out / "audit.json", {"LTspice_actually_executed": True, "command": [str(executable), "-b", "<case>.cir"],
                "exe_sha256": r.sha(executable), "parser_sha256": r.sha(parser_path), "runs": runs,
                "controller_transient_validated": False, "GUI_screenshots_created": False,
                "all_frequency_points_safe": False, "scope": "AC solver agreement, not closed-loop safety"})


if __name__ == "__main__":
    main()
