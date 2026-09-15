from pathlib import Path
import csv
import re
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import third_step_sweep_selection as step3


DIR = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat\outputs\third_step_sweep_selection\ltspice_verification")


def read_ltspice_raw(path: Path):
    raw = path.read_bytes()
    marker = "Binary:\n".encode("utf-16-le")
    marker_at = raw.index(marker)
    data_at = marker_at + len(marker)
    header = raw[:marker_at].decode("utf-16-le")
    n_vars = int(re.search(r"No\. Variables:\s*(\d+)", header).group(1))
    n_points = int(re.search(r"No\. Points:\s*(\d+)", header).group(1))
    variables = []
    for line in header.split("Variables:\n", 1)[1].splitlines():
        match = re.match(r"\s*(\d+)\s+([^\s]+)\s+([^\s]+)", line)
        if match:
            variables.append(match.group(2).lower())
    if len(variables) != n_vars:
        raise ValueError(f"{path.name}: variable count mismatch {len(variables)} != {n_vars}")
    payload = raw[data_at:]
    expected_complex = n_points * n_vars * 16
    if len(payload) == expected_complex:
        values = np.asarray(struct.unpack(f"<{n_points * n_vars * 2}d", payload))
        values = values.reshape(n_points, n_vars, 2)
        complex_values = values[:, :, 0] + 1j * values[:, :, 1]
    else:
        # Some LTspice AC raw variants store frequency as real double and the
        # other variables as complex double pairs per point.
        per_point = 8 + (n_vars - 1) * 16
        if len(payload) != n_points * per_point:
            raise ValueError(f"{path.name}: payload length {len(payload)} not recognized")
        complex_values = np.empty((n_points, n_vars), dtype=complex)
        offset = 0
        for i in range(n_points):
            freq = struct.unpack_from("<d", payload, offset)[0]
            offset += 8
            complex_values[i, 0] = freq + 0j
            for j in range(1, n_vars):
                real, imag = struct.unpack_from("<dd", payload, offset)
                offset += 16
                complex_values[i, j] = real + 1j * imag
    return {name: complex_values[:, i] for i, name in enumerate(variables)}


def raw_quantities(case_id: str):
    data = read_ltspice_raw(DIR / f"{case_id}.raw")
    freq = np.real(data["frequency"])
    zin = data["v(n_s)"] / data["i(rlesr)"]
    vnode = data["v(n_in)"]
    imot = data["i(rmot)"]
    gamma_rs = next(meta["scenario"].rs for meta in step3.SCENARIO_ROWS if meta["case_id"] == case_id)
    return {
        "frequency": freq,
        "zin": zin,
        "phase_deg": np.angle(zin, deg=True),
        "power": np.real(vnode * np.conj(imot)),
        "gamma": np.abs((zin - gamma_rs) / (zin + gamma_rs)),
    }


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = []
    metric_rows = []
    for meta in step3.SCENARIO_ROWS:
        if meta["case_id"] not in {"CASE_000_BASELINE", "CASE_402_COMBINED_HIGH"}:
            continue
        case_id = meta["case_id"]
        raw_q = raw_quantities(case_id)
        analytic_q = step3.quantities(raw_q["frequency"], meta["scenario"])
        raw_sel = step3.select_points(raw_q["frequency"], raw_q)
        ana_sel = step3.select_points(raw_q["frequency"], analytic_q)
        rows.append({
            "case_id": case_id,
            "场景": meta["display_scenario"],
            "LTspice最大功率频率_MHz": raw_sel["max_power_freq_mhz"],
            "解析最大功率频率_MHz": ana_sel["max_power_freq_mhz"],
            "最大功率频率误差_kHz": abs(raw_sel["max_power_freq_hz"] - ana_sel["max_power_freq_hz"]) / 1e3,
            "LTspice最小相位频率_MHz": raw_sel["min_abs_phase_freq_mhz"],
            "解析最小相位频率_MHz": ana_sel["min_abs_phase_freq_mhz"],
            "最小相位频率误差_kHz": abs(raw_sel["min_abs_phase_freq_hz"] - ana_sel["min_abs_phase_freq_hz"]) / 1e3,
            "LTspice最小反射频率_MHz": raw_sel["min_reflection_freq_mhz"],
            "解析最小反射频率_MHz": ana_sel["min_reflection_freq_mhz"],
            "最小反射频率误差_kHz": abs(raw_sel["min_reflection_freq_hz"] - ana_sel["min_reflection_freq_hz"]) / 1e3,
            "LTspice三准则最大分裂_kHz": max(
                abs(raw_sel["min_abs_phase_freq_hz"] - raw_sel["max_power_freq_hz"]),
                abs(raw_sel["min_reflection_freq_hz"] - raw_sel["max_power_freq_hz"]),
                abs(raw_sel["min_reflection_freq_hz"] - raw_sel["min_abs_phase_freq_hz"]),
            ) / 1e3,
        })
        comparisons = {
            "zin_real": (np.real(raw_q["zin"]), np.real(analytic_q["zin"])),
            "zin_imag": (np.imag(raw_q["zin"]), np.imag(analytic_q["zin"])),
            "zin_mag": (np.abs(raw_q["zin"]), np.abs(analytic_q["zin"])),
            "phase_deg": (raw_q["phase_deg"], analytic_q["phase_deg"]),
            "active_power": (raw_q["power"], analytic_q["power"]),
            "reflection_proxy": (raw_q["gamma"], analytic_q["gamma"]),
        }
        for name, (actual, expected) in comparisons.items():
            abs_err = float(np.max(np.abs(actual - expected)))
            scale = max(float(np.max(np.abs(expected))), 1e-15)
            metric_rows.append({
                "case_id": case_id,
                "指标": name,
                "最大绝对误差": abs_err,
                "相对全量程误差": abs_err / scale,
                "审核阈值": 5e-5,
                "审核结论": "通过" if abs_err / scale < 5e-5 else "需复核",
            })

    write_csv(DIR / "LTspice第三步_RAW选点对比.csv", rows)
    write_csv(DIR / "LTspice第三步_RAW逐点误差审核.csv", metric_rows)
    failed = [r for r in metric_rows if r["审核结论"] != "通过"]
    print(f"cases={len(rows)} metric_rows={len(metric_rows)} failures={len(failed)}")
    for row in rows:
        print(row)
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
