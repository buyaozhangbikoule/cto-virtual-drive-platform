"""Generate the frozen v2 hypothetical BVD baseline.

All values in this file are simulation assumptions derived from the requested
terminal operating point.  They are not measured transducer parameters.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


OUT = Path(__file__).resolve().parent

FS_HZ = 0.9e6
VPP_NOMINAL = 100.0
IRMS_NOMINAL = 5.0e-3
P_ACTIVE_NOMINAL = 0.125
QM_VALUES = (500.0, 800.0, 1000.0)


def derive_baseline() -> tuple[dict[str, float | str], list[dict[str, float | str]]]:
    omega = 2.0 * math.pi * FS_HZ
    vrms = VPP_NOMINAL / (2.0 * math.sqrt(2.0))
    y_abs = IRMS_NOMINAL / vrms
    conductance = P_ACTIVE_NOMINAL / vrms**2
    if conductance > y_abs:
        raise ValueError("Requested active power exceeds the apparent-power limit")

    susceptance = math.sqrt(max(0.0, y_abs**2 - conductance**2))
    rm = 1.0 / conductance
    c0 = susceptance / omega
    z_abs = 1.0 / y_abs
    z_phase_deg = -math.degrees(math.atan2(susceptance, conductance))
    apparent_power = vrms * IRMS_NOMINAL
    reactive_power = vrms**2 * susceptance

    baseline: dict[str, float | str] = {
        "source_class": "假设基线值（由目标端口量反推，非实测）",
        "fs_Hz": FS_HZ,
        "Vpp_nominal_V": VPP_NOMINAL,
        "Vrms_nominal_V": vrms,
        "Irms_nominal_A": IRMS_NOMINAL,
        "P_active_nominal_W": P_ACTIVE_NOMINAL,
        "S_apparent_nominal_VA": apparent_power,
        "Q_reactive_nominal_var": reactive_power,
        "Z_abs_nominal_ohm": z_abs,
        "Z_phase_nominal_deg": z_phase_deg,
        "Rm_ohm": rm,
        "C0_F": c0,
        "C0_pF": c0 * 1e12,
        "Rs_ohm": 50.0,
        "Vpp_soft_V": 130.0,
        "Vpp_hard_V": 160.0,
        "Irms_soft_A": 5.5e-3,
        "Irms_hard_A": 6.0e-3,
        "f_min_Hz": 0.8e6,
        "f_max_Hz": 1.0e6,
    }

    q_rows: list[dict[str, float | str]] = []
    for qm in QM_VALUES:
        lm = qm * rm / omega
        cm = 1.0 / (omega**2 * lm)
        fp = FS_HZ * math.sqrt(1.0 + cm / c0)
        q_rows.append(
            {
                "source_class": "扫描变量（Qm敏感性）",
                "Qm": qm,
                "Lm_H": lm,
                "Cm_F": cm,
                "Cm_pF": cm * 1e12,
                "bare_bandwidth_Hz_approx": FS_HZ / qm,
                "fp_Hz_ideal_BVD": fp,
                "fp_minus_fs_Hz": fp - FS_HZ,
            }
        )
    return baseline, q_rows


def write_csv(path: Path, rows: list[dict[str, float | str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    baseline, q_rows = derive_baseline()
    write_csv(OUT / "v2_基线参数.csv", [baseline])
    write_csv(OUT / "v2_Qm敏感性参数.csv", q_rows)
    payload = {
        "warning": "All values are hypothetical simulation assumptions, not measurements.",
        "baseline": baseline,
        "qm_sensitivity": q_rows,
    }
    (OUT / "v2_参数冻结清单.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
