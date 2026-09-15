"""Generate the active v2.1 baseline selected after the first LTspice audit."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path


OUT = Path(__file__).resolve().parent
FS_HZ = 0.9e6
VPP = 100.0
IRMS = 5.0e-3
P_ACTIVE = 0.170
QM_VALUES = (500.0, 800.0, 1000.0)


def main() -> None:
    vrms = VPP / (2 * math.sqrt(2))
    y_abs = IRMS / vrms
    g = P_ACTIVE / vrms**2
    b = math.sqrt(y_abs**2 - g**2)
    omega = 2 * math.pi * FS_HZ
    rm = 1 / g
    c0 = b / omega
    baseline = {
        "status": "v2.1 active hypothetical baseline",
        "source_class": "假设基线值（由目标端口量反推，非实测）",
        "fs_Hz": FS_HZ,
        "Vpp_V": VPP,
        "Vrms_V": vrms,
        "Irms_A": IRMS,
        "P_W": P_ACTIVE,
        "Q_var": vrms**2 * b,
        "S_VA": vrms * IRMS,
        "power_factor": P_ACTIVE / (vrms * IRMS),
        "Z_abs_ohm": 1 / y_abs,
        "Z_phase_deg": -math.degrees(math.atan2(b, g)),
        "Rm_ohm": rm,
        "C0_F": c0,
        "C0_pF": c0 * 1e12,
    }
    q_rows = []
    for qm in QM_VALUES:
        lm = qm * rm / omega
        cm = 1 / (omega**2 * lm)
        q_rows.append(
            {
                "source_class": "扫描变量（Qm敏感性）",
                "Qm": qm,
                "Lm_H": lm,
                "Cm_F": cm,
                "Cm_pF": cm * 1e12,
                "bandwidth_Hz_approx": FS_HZ / qm,
                "fp_Hz_ideal_BVD": FS_HZ * math.sqrt(1 + cm / c0),
            }
        )

    for path, rows in (
        (OUT / "v2_1_活动基线参数.csv", [baseline]),
        (OUT / "v2_1_Qm敏感性参数.csv", q_rows),
    ):
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    payload = {"baseline": baseline, "qm_sensitivity": q_rows}
    (OUT / "v2_1_活动参数清单.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
