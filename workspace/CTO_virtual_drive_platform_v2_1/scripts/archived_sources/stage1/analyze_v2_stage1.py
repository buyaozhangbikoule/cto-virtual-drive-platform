"""Audit the actual LTspice RAW against the analytic v2 bare BVD model."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import struct
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
RAW_PATH = HERE / "V2_BARE_BVD_Q800.raw"
LOG_PATH = HERE / "V2_BARE_BVD_Q800.log"

FS = 0.9e6
C0 = 17.68388256576615e-12
RM = 10e3
LM = 1.4147106052612914
CM = 0.0221048532072077e-12


def read_ltspice_raw(path: Path) -> dict[str, np.ndarray]:
    raw = path.read_bytes()
    marker = "Binary:\n".encode("utf-16-le")
    marker_at = raw.index(marker)
    data_at = marker_at + len(marker)
    header = raw[:marker_at].decode("utf-16-le")
    n_vars = int(re.search(r"No\. Variables:\s*(\d+)", header).group(1))
    n_points = int(re.search(r"No\. Points:\s*(\d+)", header).group(1))
    variables: list[str] = []
    for line in header.split("Variables:\n", 1)[1].splitlines():
        match = re.match(r"\s*(\d+)\s+([^\s]+)\s+([^\s]+)", line)
        if match:
            variables.append(match.group(2).lower())
    if len(variables) != n_vars:
        raise ValueError("Variable count mismatch")
    payload = raw[data_at:]
    expected_complex = n_points * n_vars * 16
    if len(payload) == expected_complex:
        values = np.asarray(struct.unpack(f"<{n_points * n_vars * 2}d", payload))
        values = values.reshape(n_points, n_vars, 2)
        complex_values = values[:, :, 0] + 1j * values[:, :, 1]
    else:
        per_point = 8 + (n_vars - 1) * 16
        if len(payload) != n_points * per_point:
            raise ValueError("Unrecognized LTspice RAW payload")
        complex_values = np.empty((n_points, n_vars), dtype=complex)
        offset = 0
        for row in range(n_points):
            complex_values[row, 0] = struct.unpack_from("<d", payload, offset)[0]
            offset += 8
            for col in range(1, n_vars):
                real, imag = struct.unpack_from("<dd", payload, offset)
                offset += 16
                complex_values[row, col] = real + 1j * imag
    return {name: complex_values[:, i] for i, name in enumerate(variables)}


def analytic_impedance(freq: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    omega = 2 * np.pi * freq
    z_motional = RM + 1j * (omega * LM - 1 / (omega * CM))
    y_total = 1 / z_motional + 1j * omega * C0
    return 1 / y_total, z_motional


def main() -> None:
    raw = read_ltspice_raw(RAW_PATH)
    freq = np.real(raw["frequency"])
    voltage = raw["v(n)"]
    # LTspice defines source current into the positive source terminal.
    current = -raw["i(vdrive)"]
    z_lt = voltage / current
    z_py, zm_py = analytic_impedance(freq)
    imot_lt = raw["i(rm)"]
    conductance_lt = np.real(imot_lt / voltage)

    abs_error = np.abs(z_lt - z_py)
    rel_error = abs_error / np.maximum(np.abs(z_py), 1e-30)
    fs_idx = int(np.argmin(np.abs(freq - FS)))
    g_peak_idx = int(np.argmax(conductance_lt))
    mag_min_idx = int(np.argmin(np.abs(z_lt)))
    phase = np.angle(z_lt, deg=True)

    row = {
        "ltspice_raw": RAW_PATH.name,
        "raw_sha256": hashlib.sha256(RAW_PATH.read_bytes()).hexdigest(),
        "log_sha256": hashlib.sha256(LOG_PATH.read_bytes()).hexdigest(),
        "points": int(freq.size),
        "fs_grid_Hz": float(freq[fs_idx]),
        "conductance_peak_Hz": float(freq[g_peak_idx]),
        "conductance_peak_S": float(conductance_lt[g_peak_idx]),
        "absZ_min_Hz": float(freq[mag_min_idx]),
        "absZ_at_fs_ohm": float(abs(z_lt[fs_idx])),
        "ReZ_at_fs_ohm": float(np.real(z_lt[fs_idx])),
        "ImZ_at_fs_ohm": float(np.imag(z_lt[fs_idx])),
        "phase_at_fs_deg": float(phase[fs_idx]),
        "max_Z_relative_error": float(np.max(rel_error)),
        "mean_Z_relative_error": float(np.mean(rel_error)),
        "series_resonance_error_pct": float(abs(freq[g_peak_idx] - FS) / FS * 100),
    }

    with (HERE / "V2_STAGE1_LTspice_解析交叉验证.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    (HERE / "V2_STAGE1_audit.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(freq / 1e6, np.abs(z_lt) / 1e3, label="LTspice RAW", lw=1.7)
    axes[0].plot(freq / 1e6, np.abs(z_py) / 1e3, "--", label="Python analytic", lw=1.1)
    axes[0].axvline(FS / 1e6, color="black", ls=":", lw=1, label="fs = 0.9 MHz")
    axes[0].set_ylabel("|Z| (kΩ)")
    axes[0].grid(alpha=0.25)
    axes[0].legend()
    axes[1].plot(freq / 1e6, phase, label="LTspice RAW", lw=1.7)
    axes[1].plot(freq / 1e6, np.angle(z_py, deg=True), "--", label="Python analytic", lw=1.1)
    axes[1].axvline(FS / 1e6, color="black", ls=":", lw=1)
    axes[1].set_xlabel("Frequency (MHz)")
    axes[1].set_ylabel("Phase(Z) (deg)")
    axes[1].grid(alpha=0.25)
    axes[1].legend()
    fig.suptitle("V2 bare BVD: actual LTspice RAW vs analytic model\n(hypothetical baseline, not measured data)")
    fig.tight_layout()
    fig.savefig(HERE / "V2_STAGE1_LTspice_RAW交叉验证.png", dpi=200)
    plt.close(fig)
    print(json.dumps(row, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
