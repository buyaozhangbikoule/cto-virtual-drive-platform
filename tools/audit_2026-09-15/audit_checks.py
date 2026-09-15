"""Independent re-derivation of the audit numbers in docs/04_代码审核_2026-09-15.md.

Loads the ACTIVE model (workspace/outputs/v2_self_consistent_rebuild/active_stage3_5)
and recomputes every claim in the audit from scratch. Prints PASS/FAIL per check.

    python3 tools/audit_2026-09-15/audit_checks.py

Requires numpy only. Does not write to any results directory and does not
overwrite any historical batch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ROOT / "workspace" / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5"
sys.path.insert(0, str(ACTIVE))
import model_v2_1 as m  # noqa: E402

FINE = np.arange(m.F_MIN, m.F_MAX + 0.1, 100.0)   # the model's own oracle grid
DENSE = np.linspace(m.F_MIN, m.F_MAX, 400001)     # 0.5 Hz, for peak geometry
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}\n       {detail}")


def probe_power(freqs, scenario, amplitude=0.40):
    """What local_scan() observes: port power at the fixed probe amplitude."""
    return m.response(np.atleast_1d(freqs), scenario, amplitude)["p_port_W"]


def three_stage_scan(start_f, scenario):
    """Exact reimplementation of run_stage4_5_control.local_scan()."""
    coarse = np.arange(max(m.F_MIN, start_f - 50e3), min(m.F_MAX, start_f + 50e3) + 1, 5e3)
    cb = max(zip(probe_power(coarse, scenario), coarse))[1]
    fine = np.arange(max(m.F_MIN, cb - 5e3), min(m.F_MAX, cb + 5e3) + 1, 1e3)
    fb = max(zip(probe_power(fine, scenario), fine))[1]
    ultra = np.arange(max(m.F_MIN, fb - 1e3), min(m.F_MAX, fb + 1e3) + 1, 0.1e3)
    return max(zip(probe_power(ultra, scenario), ultra))[1]


# --- A. operating point is the one the handoff specifies ----------------------
base = m.scenario_map()["CASE_000_BASELINE"]
z = abs(complex(m.response(0.9e6, base, 1.0)["z_bvd"][0]))
pt = m.point_metrics(0.9e6, base, 1.0)
check(
    "A1 operating point |Z(0.9MHz)| = 7.071 kohm",
    abs(z - 7071.07) < 1.0,
    f"|Z_bvd| = {z:.2f} ohm; V = {pt['vport_vpp']:.3f} Vpp, I = {pt['iport_irms_A']*1e3:.4f} mA rms",
)
check(
    "A2 power balance closes",
    abs(float(m.response(0.9e6, base, 1.0)["power_balance_error_W"][0])) < 1e-12,
    f"residual = {float(m.response(0.9e6, base, 1.0)['power_balance_error_W'][0]):.3e} W",
)

# --- B. FINDING 1: the V/I compliance limits never bind -----------------------
cap_bound = 0
for s in m.all_scenarios():
    a = m.allowed_amplitude(FINE, s, use_soft_limits=True)
    p = m.response(FINE, s, 1.0)["p_rm_W"] * a**2
    if float(a[int(np.argmax(p))]) >= 1.0 - 1e-9:
        cap_bound += 1
check(
    "B1 amplitude is source-capped (a=1), not V/I-capped, in every scenario",
    cap_bound == len(m.all_scenarios()),
    f"{cap_bound}/{len(m.all_scenarios())} scenarios bind on a<=1; V/I protection never activates at the optimum",
)

u = m.response(FINE, base, 1.0)
a_hard = np.minimum(m.VPP_HARD / u["vport_vpp"], m.IRMS_HARD / u["iport_irms_A"])
p_now = (u["p_rm_W"] * m.allowed_amplitude(FINE, base, use_soft_limits=True) ** 2).max()
p_vi = (u["p_rm_W"] * a_hard**2).max()
check(
    "B2 headroom left on the table by the frozen source amplitude",
    p_vi > p_now,
    f"baseline best {p_now*1e3:.1f} mW now vs {p_vi*1e3:.1f} mW if driven to the hard V/I envelope "
    f"({p_vi/p_now:.2f}x)",
)

# --- C. FINDING 2: two scenarios lie outside the +/-50 kHz scan window --------
unreachable = [s.case_id for s in m.all_scenarios() if abs(s.bvd.fs - m.F0) > 50e3]
check(
    "C1 every scenario's fs is reachable by the +/-50 kHz coarse window",
    not unreachable,
    f"outside the window: {unreachable or 'none'} "
    f"(offsets: {[f'{abs(m.scenario_map()[c].bvd.fs-m.F0)/1e3:.1f} kHz' for c in unreachable]})",
)

low = []
for s in m.all_scenarios():
    p = m.safe_power(FINE, s)
    oracle = p.max()
    got = float(m.safe_power(np.array([three_stage_scan(m.F0, s)]), s)[0])
    if got / oracle < 0.90:
        low.append((s.case_id, round(got / oracle * 100, 2)))
check(
    "C2 3-stage scan meets the >=90% power-capture criterion in all 34 scenarios",
    not low,
    f"below floor: {low or 'none'}",
)

# --- D. FINDING 3: cable capacitance is not modelled --------------------------
check(
    "D1 BVD exposes a cable-capacitance term",
    any("cab" in f.lower() or "cable" in f.lower() for f in m.BVD.__dataclass_fields__),
    f"BVD fields = {list(m.BVD.__dataclass_fields__)}; no C_cable node exists anywhere in the model",
)

# --- E. FINDING 4: phase-zero and max-power are different points --------------
r = m.response(DENSE, base, 1.0)
ph = r["phase_deg"]
p = r["p_rm_W"] * m.allowed_amplitude(DENSE, base, use_soft_limits=True) ** 2
crossings = DENSE[np.where(np.diff(np.sign(ph)))[0]]
check(
    "E1 input phase has a single zero crossing in band",
    len(crossings) <= 1,
    f"{len(crossings)} crossings at {[f'{c/1e6:.5f} MHz' for c in crossings]}; "
    f"power there = {[f'{float(m.safe_power(np.array([c]), base)[0])/p.max()*100:.2f}%' for c in crossings]} of peak",
)

viol = []
for s in m.all_scenarios():
    rr = m.response(DENSE, s, 1.0)
    pp = rr["p_rm_W"] * m.allowed_amplitude(DENSE, s, use_soft_limits=True) ** 2
    phi = float(rr["phase_deg"][int(np.argmax(pp))])
    if abs(phi) > 5.0:
        viol.append((s.case_id, round(phi, 1)))
check(
    "E2 |phase| <= 5 deg is satisfiable AT the max-power frequency in all scenarios",
    not viol,
    f"{len(viol)}/34 scenarios cannot meet both criteria at once; worst = {max(viol, key=lambda x: abs(x[1])) if viol else '-'}",
)

# --- F. the parts that are solid ---------------------------------------------
fixed_match = all(
    s.matching == m.BASE_MATCH
    for s in m.all_scenarios()
    if s.factor not in ("Lmatch", "Cmatch", "inductor_Q", "combined")
)
check(
    "F1 matching network stays fixed under load disturbance (not re-optimised)",
    fixed_match,
    "only the explicit Lmatch/Cmatch/inductor_Q/combined scans perturb the network, as they should",
)

rm50 = m.scenario_map()["CASE_RM_P50"]
pr = m.safe_power(FINE, rm50)
check(
    "F2 Rm-type loss disturbance is NOT recoverable by frequency tracking",
    abs(pr.max() / pr[int(np.argmin(abs(FINE - m.F0)))] - 1.0) < 1e-3,
    f"tracking gain = {pr.max()/pr[int(np.argmin(abs(FINE-m.F0)))]:.4f}x (confirms the handoff's negative result)",
)

print("\n" + "=" * 74)
bad = [n for n, ok, _ in results if not ok]
print(f"{len(results)-len(bad)}/{len(results)} checks passed.")
print("Failing checks are the audit's findings, not regressions:")
for n in bad:
    print(f"  - {n}")
