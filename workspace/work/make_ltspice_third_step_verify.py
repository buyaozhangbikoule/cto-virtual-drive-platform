from pathlib import Path
import math
import shutil
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import third_step_sweep_selection as step3


OUT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat\outputs\third_step_sweep_selection\ltspice_verification")
OUT.mkdir(parents=True, exist_ok=True)


def write_case(meta):
    s = meta["scenario"]
    r_esr = 2 * math.pi * step3.F_CENTER * s.matching.ls / s.matching.q_inductor
    n_points = int(round((step3.INITIAL_STOP - step3.INITIAL_START) / step3.INITIAL_STEP)) + 1
    text = f"""* Third-step LTspice verification: {meta["scenario_key"]}
* Fresh batch run target: 0.84-0.96 MHz, 0.5 kHz step
* Source amplitude is the calibrated RMS phasor from the assumed BVD model.
V1 src 0 AC {step3.VS_RMS:.12g}
Rsrc src n_s {s.rs:.12g}
Rlesr n_s n_l {r_esr:.12g}
Lmatch n_l n_in {s.matching.ls:.12g}
Cmatch n_in 0 {s.matching.cp:.12g}
Cstatic n_in 0 {s.bvd.c0:.12g}
Rmot n_in n_m1 {s.bvd.rm:.12g}
Lmot n_m1 n_m2 {s.bvd.lm:.12g}
Cmot n_m2 0 {s.bvd.cm:.12g}
.ac lin {n_points} {step3.INITIAL_START:.12g} {step3.INITIAL_STOP:.12g}
.options meascplxfmt=cartesian
.meas ac Zin_mag_0p9 FIND mag(V(n_s)/I(Rlesr)) AT={step3.F_CENTER:.12g}
.meas ac Zin_real_0p9 FIND re(V(n_s)/I(Rlesr)) AT={step3.F_CENTER:.12g}
.meas ac Zin_imag_0p9 FIND im(V(n_s)/I(Rlesr)) AT={step3.F_CENTER:.12g}
.meas ac Phase_0p9 FIND ph(V(n_s)/I(Rlesr)) AT={step3.F_CENTER:.12g}
.meas ac P_0p9 FIND re(V(n_in)*conj(I(Rmot))) AT={step3.F_CENTER:.12g}
.meas ac Gamma_0p9 FIND mag((V(n_s)/I(Rlesr)-{s.rs:.12g})/(V(n_s)/I(Rlesr)+{s.rs:.12g})) AT={step3.F_CENTER:.12g}
.meas ac Pmax MAX re(V(n_in)*conj(I(Rmot)))
.end
"""
    path = OUT / f"{meta['case_id']}.cir"
    path.write_text(text, encoding="ascii")
    return path


targets = [
    meta for meta in step3.SCENARIO_ROWS
    if meta["case_id"] in {"CASE_000_BASELINE", "CASE_402_COMBINED_HIGH"}
]

for old in OUT.glob("*"):
    if old.is_file() and old.suffix.lower() in {".raw", ".log", ".net", ".op.raw"}:
        old.unlink()

for meta in targets:
    p = write_case(meta)
    print(p)
