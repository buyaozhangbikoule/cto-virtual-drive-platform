"""Cross-validate the active v2.1 LTspice RAW against its analytic BVD."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from analyze_v2_stage1 import read_ltspice_raw


HERE = Path(__file__).resolve().parent
RAW_PATH = HERE / "V2_1_BARE_BVD_Q800.raw"
LOG_PATH = HERE / "V2_1_BARE_BVD_Q800.log"
FS = 0.9e6
C0 = 6.858064105198409e-12
RM = 7352.941176470586
LM = 1.0402283862215377
CM = 0.030062600361803386e-12


def main() -> None:
    raw = read_ltspice_raw(RAW_PATH)
    freq = np.real(raw["frequency"])
    voltage = raw["v(n)"]
    current = -raw["i(vdrive)"]
    z_lt = voltage / current
    omega = 2 * np.pi * freq
    z_m = RM + 1j * (omega * LM - 1 / (omega * CM))
    z_py = 1 / (1 / z_m + 1j * omega * C0)
    phase = np.angle(z_lt, deg=True)
    conductance = np.real(raw["i(rm)"] / voltage)

    fs_idx = int(np.argmin(abs(freq - FS)))
    g_idx = int(np.argmax(conductance))
    zmin_idx = int(np.argmin(abs(z_lt)))
    crossings = np.where(phase[:-1] * phase[1:] <= 0)[0]
    zero_hz = []
    for idx in crossings:
        f0, f1 = freq[idx], freq[idx + 1]
        p0, p1 = phase[idx], phase[idx + 1]
        zero_hz.append(float(f0 - p0 * (f1 - f0) / (p1 - p0)))
    rel = np.abs(z_lt - z_py) / np.maximum(abs(z_py), 1e-30)
    row = {
        "status": "PASS" if abs(freq[g_idx] - FS) / FS < 0.01 and np.max(rel) < 0.05 else "FAIL",
        "raw_sha256": hashlib.sha256(RAW_PATH.read_bytes()).hexdigest(),
        "log_sha256": hashlib.sha256(LOG_PATH.read_bytes()).hexdigest(),
        "points": int(freq.size),
        "conductance_peak_Hz": float(freq[g_idx]),
        "absZ_min_Hz": float(freq[zmin_idx]),
        "phase_zero_Hz": ";".join(f"{value:.3f}" for value in zero_hz),
        "absZ_at_fs_ohm": float(abs(z_lt[fs_idx])),
        "ReZ_at_fs_ohm": float(np.real(z_lt[fs_idx])),
        "ImZ_at_fs_ohm": float(np.imag(z_lt[fs_idx])),
        "phase_at_fs_deg": float(phase[fs_idx]),
        "max_Z_relative_error": float(np.max(rel)),
        "series_resonance_error_pct": float(abs(freq[g_idx] - FS) / FS * 100),
    }
    with (HERE / "V2_1_STAGE1_LTspice_解析交叉验证.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    (HERE / "V2_1_STAGE1_audit.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(freq / 1e6, abs(z_lt) / 1e3, label="LTspice RAW", lw=1.7)
    axes[0].plot(freq / 1e6, abs(z_py) / 1e3, "--", label="Python analytic", lw=1.0)
    axes[0].axvline(FS / 1e6, color="black", ls=":", lw=1)
    axes[0].scatter(freq[zmin_idx] / 1e6, abs(z_lt[zmin_idx]) / 1e3, s=28, zorder=3, label="|Z| minimum")
    axes[0].set_ylabel("|Z| (kΩ)")
    axes[0].grid(alpha=0.25)
    axes[0].legend()
    axes[1].plot(freq / 1e6, phase, label="LTspice RAW", lw=1.7)
    axes[1].plot(freq / 1e6, np.angle(z_py, deg=True), "--", label="Python analytic", lw=1.0)
    axes[1].axhline(0, color="gray", lw=0.8)
    axes[1].axvline(FS / 1e6, color="black", ls=":", lw=1)
    axes[1].set_xlabel("Frequency (MHz)")
    axes[1].set_ylabel("Phase(Z) (deg)")
    axes[1].grid(alpha=0.25)
    axes[1].legend()
    fig.suptitle("V2.1 active bare BVD: actual LTspice RAW vs analytic model\n(hypothetical baseline, not measured data)")
    fig.tight_layout()
    fig.savefig(HERE / "V2_1_STAGE1_LTspice_RAW交叉验证.png", dpi=200)
    plt.close(fig)

    zoom = (freq >= 0.895e6) & (freq <= 0.905e6)
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(freq[zoom] / 1e6, abs(z_lt[zoom]) / 1e3, label="LTspice RAW", lw=2)
    axes[0].axvline(FS / 1e6, color="black", ls=":", lw=1, label="max conductance fs")
    axes[0].scatter(freq[zmin_idx] / 1e6, abs(z_lt[zmin_idx]) / 1e3, color="tab:red", s=35, zorder=3, label="|Z| minimum")
    axes[0].set_ylabel("|Z| (kΩ)")
    axes[0].grid(alpha=0.25)
    axes[0].legend()
    axes[1].plot(freq[zoom] / 1e6, phase[zoom], label="LTspice RAW", lw=2)
    axes[1].axhline(0, color="gray", lw=0.8)
    axes[1].axvline(FS / 1e6, color="black", ls=":", lw=1)
    for number, value in enumerate(zero_hz):
        axes[1].axvline(value / 1e6, color="tab:green", ls="--", lw=1, label="phase zero" if number == 0 else None)
    axes[1].set_xlabel("Frequency (MHz)")
    axes[1].set_ylabel("Phase(Z) (deg)")
    axes[1].grid(alpha=0.25)
    axes[1].legend()
    fig.suptitle("V2.1 resonance close-up from actual LTspice RAW\n(max conductance, |Z| minimum and phase zeros are distinct)")
    fig.tight_layout()
    fig.savefig(HERE / "V2_1_STAGE1_谐振区放大_RAW证据.png", dpi=200)
    plt.close(fig)
    print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
