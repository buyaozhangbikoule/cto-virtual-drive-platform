"""Step 4 formal controller comparison using LTspice RAW frequency-response data.

This script has three phases:
1) generate LTspice netlists for all disturbance states;
2) after LTspice batch execution, parse RAW files into response tables;
3) run three discrete controllers on the same disturbance time sequence.

The study remains an assumed virtual electrical BVD model. It is not measured
transducer or acoustic/clinical data.
"""

from __future__ import annotations

import csv
import json
import math
import re
import shutil
import struct
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
OUTDIR = ROOT / "outputs" / "fourth_step_control_strategies"
LT_DIR = OUTDIR / "ltspice_cases"
sys.path.insert(0, str(ROOT / "work"))
import third_step_sweep_selection as step3  # noqa: E402


F_MIN = 0.84e6
F_MAX = 0.96e6
F_FIXED = 0.9e6
RAW_STEP = 0.1e3
RAW_N = int(round((F_MAX - F_MIN) / RAW_STEP)) + 1
DWELL_STEPS = 20

LOCAL_SCAN_HALFWIDTH = 50e3
LOCAL_SCAN_STEP = 0.5e3
SCAN_INTERVAL_STEPS = 5

PHASE_TARGET_DEG = 0.0
PHASE_GAIN_CANDIDATES_HZ_PER_DEG = [50.0, 100.0, 200.0, 500.0]
PHASE_TRACKING_GAIN_HZ_PER_DEG = 100.0
PHASE_MAX_STEP_HZ = 5.0e3

VPP_HARD = 160.0
IPEAK_NOMINAL = 5.0e-3
IPEAK_SOFT = 5.5e-3
IPEAK_HARD = 8.0e-3

SETTLED_CAPTURE_THRESHOLD = 0.95
SETTLED_CONSECUTIVE_STEPS = 3


def label_from_meta(meta):
    if meta["case_id"] == "CASE_000_BASELINE":
        return "基准"
    return meta["display_scenario"]


def scenario_sequence():
    rows = []
    idx = 0
    for meta in step3.SCENARIO_ROWS:
        rows.append({**meta, "state_index": idx, "sequence_label": label_from_meta(meta)})
        idx += 1
    base = next(meta for meta in step3.SCENARIO_ROWS if meta["case_id"] == "CASE_000_BASELINE")
    rows.append({**base, "state_index": idx, "scenario_key": "RECOVERY::CASE_000_BASELINE", "sequence_label": "恢复基准"})
    return rows


SEQUENCE = scenario_sequence()
UNIQUE_CASES = []
seen = set()
for meta in SEQUENCE:
    if meta["case_id"] not in seen:
        seen.add(meta["case_id"])
        UNIQUE_CASES.append(meta)


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def generate_netlists():
    LT_DIR.mkdir(parents=True, exist_ok=True)
    for old in LT_DIR.glob("*"):
        if old.is_file() and old.suffix.lower() in {".raw", ".op.raw", ".log", ".net", ".db"}:
            old.unlink()
    for meta in UNIQUE_CASES:
        s = meta["scenario"]
        r_esr = 2 * math.pi * step3.F_CENTER * s.matching.ls / s.matching.q_inductor
        text = f"""* Fourth-step control strategy RAW table: {meta["scenario_key"]}
* AC sweep: 0.84-0.96 MHz, 0.1 kHz step
V1 src 0 AC {step3.VS_RMS:.12g}
Rsrc src n_s {s.rs:.12g}
Rlesr n_s n_l {r_esr:.12g}
Lmatch n_l n_in {s.matching.ls:.12g}
Cmatch n_in 0 {s.matching.cp:.12g}
Cstatic n_in 0 {s.bvd.c0:.12g}
Rmot n_in n_m1 {s.bvd.rm:.12g}
Lmot n_m1 n_m2 {s.bvd.cm * 0 + s.bvd.lm:.12g}
Cmot n_m2 0 {s.bvd.cm:.12g}
.ac lin {RAW_N} {F_MIN:.12g} {F_MAX:.12g}
.options meascplxfmt=cartesian
.meas ac P_0p9 FIND re(V(n_in)*conj(I(Rmot))) AT={F_FIXED:.12g}
.meas ac Itrans_peak_0p9 FIND mag(I(Rmot)+I(Cstatic))*sqrt(2) AT={F_FIXED:.12g}
.meas ac Vpp_0p9 FIND mag(V(n_in))*2*sqrt(2) AT={F_FIXED:.12g}
.meas ac Phase_0p9 FIND ph(V(n_s)/I(Rlesr)) AT={F_FIXED:.12g}
.meas ac Gamma_0p9 FIND mag((V(n_s)/I(Rlesr)-{s.rs:.12g})/(V(n_s)/I(Rlesr)+{s.rs:.12g})) AT={F_FIXED:.12g}
.meas ac Pmax MAX re(V(n_in)*conj(I(Rmot)))
.end
"""
        (LT_DIR / f"{meta['case_id']}.cir").write_text(text, encoding="ascii")
    print(f"netlists={len(UNIQUE_CASES)} dir={LT_DIR}")


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
        raise ValueError(f"{path.name}: variable count mismatch")
    payload = raw[data_at:]
    expected_complex = n_points * n_vars * 16
    if len(payload) == expected_complex:
        values = np.asarray(struct.unpack(f"<{n_points * n_vars * 2}d", payload))
        values = values.reshape(n_points, n_vars, 2)
        complex_values = values[:, :, 0] + 1j * values[:, :, 1]
    else:
        per_point = 8 + (n_vars - 1) * 16
        if len(payload) != n_points * per_point:
            raise ValueError(f"{path.name}: unrecognized payload length")
        complex_values = np.empty((n_points, n_vars), dtype=complex)
        offset = 0
        for i in range(n_points):
            frequency = struct.unpack_from("<d", payload, offset)[0]
            offset += 8
            complex_values[i, 0] = frequency + 0j
            for j in range(1, n_vars):
                real, imag = struct.unpack_from("<dd", payload, offset)
                offset += 16
                complex_values[i, j] = real + 1j * imag
    return {name: complex_values[:, i] for i, name in enumerate(variables)}


def phase_zero_frequency(freq, phase):
    crossings = np.where(phase[:-1] * phase[1:] <= 0.0)[0]
    if len(crossings) == 0:
        idx = int(np.argmin(np.abs(phase)))
        return float(freq[idx]), False
    candidates = []
    for i in crossings:
        f0, f1 = freq[i], freq[i + 1]
        y0, y1 = phase[i], phase[i + 1]
        if y1 == y0:
            candidates.append(float(f0))
        else:
            candidates.append(float(f0 - y0 * (f1 - f0) / (y1 - y0)))
    return min(candidates, key=lambda f: abs(f - F_FIXED)), True


class ResponseTable:
    def __init__(self, meta, raw):
        self.meta = meta
        self.freq = np.real(raw["frequency"])
        self.rs = meta["scenario"].rs
        self.zin = raw["v(n_s)"] / raw["i(rlesr)"]
        self.vnode = raw["v(n_in)"]
        self.itrans = raw["i(rmot)"] + raw["i(cstatic)"]
        self.imot = raw["i(rmot)"]
        self.isource = raw["i(rlesr)"]
        self.power = np.real(self.vnode * np.conj(self.imot))
        self.phase = np.angle(self.zin, deg=True)
        self.gamma = np.abs((self.zin - self.rs) / (self.zin + self.rs))
        self.vpp = np.abs(self.vnode) * 2 * np.sqrt(2)
        self.itrans_peak = np.abs(self.itrans) * np.sqrt(2)
        self.imot_peak = np.abs(self.imot) * np.sqrt(2)
        self.isource_peak = np.abs(self.isource) * np.sqrt(2)
        self.zin_real = np.real(self.zin)
        self.zin_imag = np.imag(self.zin)
        self.zin_mag = np.abs(self.zin)
        self.power_freq = float(self.freq[int(np.argmax(self.power))])
        self.power_max = float(np.max(self.power))
        self.phase_freq, self.phase_crossed = phase_zero_frequency(self.freq, self.phase)
        self.reflection_freq = float(self.freq[int(np.argmin(self.gamma))])
        self.reflection_min = float(np.min(self.gamma))

    def interp(self, f_hz: float):
        f = float(np.clip(f_hz, F_MIN, F_MAX))
        def ip(arr):
            return float(np.interp(f, self.freq, arr))
        return {
            "frequency_hz": f,
            "active_power_w": ip(self.power),
            "phase_deg": ip(self.phase),
            "reflection_proxy": ip(self.gamma),
            "transducer_vpp": ip(self.vpp),
            "transducer_current_a_peak": ip(self.itrans_peak),
            "motional_current_a_peak": ip(self.imot_peak),
            "source_current_a_peak": ip(self.isource_peak),
            "zin_real_ohm": ip(self.zin_real),
            "zin_imag_ohm": ip(self.zin_imag),
            "zin_mag_ohm": ip(self.zin_mag),
        }

    def grid_best_power(self, center=None, halfwidth=None, step=LOCAL_SCAN_STEP):
        if center is None or halfwidth is None:
            lo, hi = F_MIN, F_MAX
        else:
            lo = max(F_MIN, center - halfwidth)
            hi = min(F_MAX, center + halfwidth)
        grid = np.arange(lo, hi + 0.1 * step, step)
        vals = np.interp(grid, self.freq, self.power)
        idx = int(np.argmax(vals))
        return float(grid[idx]), float(vals[idx]), int(len(grid))


def load_response_tables():
    missing = [meta["case_id"] for meta in UNIQUE_CASES if not (LT_DIR / f"{meta['case_id']}.raw").exists()]
    if missing:
        raise FileNotFoundError(f"Missing LTspice RAW files. Run generate + LTspice first: {missing[:5]}")
    tables = {}
    for meta in UNIQUE_CASES:
        raw = read_ltspice_raw(LT_DIR / f"{meta['case_id']}.raw")
        table = ResponseTable(meta, raw)
        if len(table.freq) != RAW_N:
            raise ValueError(f"{meta['case_id']}: expected {RAW_N} points, got {len(table.freq)}")
        tables[meta["case_id"]] = table
    return tables


def response_summary_rows(tables):
    rows = []
    for meta in SEQUENCE:
        table = tables[meta["case_id"]]
        p0 = table.interp(F_FIXED)
        rows.append({
            "state_index": meta["state_index"],
            "scenario_key": meta["scenario_key"],
            "case_id": meta["case_id"],
            "场景族": meta["scenario_family"],
            "扰动参数": meta["factor"],
            "扰动等级": meta["level"],
            "序列标签": meta["sequence_label"],
            "最大功率频率_MHz": table.power_freq / 1e6,
            "最大功率_mW": table.power_max * 1e3,
            "相位零点或最小相位频率_MHz": table.phase_freq / 1e6,
            "是否存在相位过零": int(table.phase_crossed),
            "最小反射频率_MHz": table.reflection_freq / 1e6,
            "最小反射代理": table.reflection_min,
            "固定0p9MHz功率_mW": p0["active_power_w"] * 1e3,
            "固定0p9MHz相位_deg": p0["phase_deg"],
            "固定0p9MHz反射代理": p0["reflection_proxy"],
            "固定0p9MHz电压_Vpp": p0["transducer_vpp"],
            "固定0p9MHz_BVD端总电流_mApeak": p0["transducer_current_a_peak"] * 1e3,
        })
    return rows


def simulate_strategy(tables, strategy, phase_gain=PHASE_TRACKING_GAIN_HZ_PER_DEG):
    rows = []
    f = F_FIXED
    last_selected_power_freq = None
    total_scan_points = 0
    global_step = 0
    for meta in SEQUENCE:
        table = tables[meta["case_id"]]
        for local_step in range(DWELL_STEPS):
            scan_performed = 0
            scan_points = 0
            if strategy == "固定频率固定幅度":
                f = F_FIXED
            elif strategy == "周期性局部扫频":
                if global_step == 0:
                    f, _, scan_points = table.grid_best_power(step=LOCAL_SCAN_STEP)
                    scan_performed = 1
                elif local_step == 0 or global_step % SCAN_INTERVAL_STEPS == 0:
                    f, _, scan_points = table.grid_best_power(center=f, halfwidth=LOCAL_SCAN_HALFWIDTH, step=LOCAL_SCAN_STEP)
                    scan_performed = 1
                total_scan_points += scan_points
            elif strategy == "相位误差离散跟踪":
                # Apply f_{k+1}=clip(f_k+K_f*(phi_target-phi_k)).
                current = table.interp(f)
                e = PHASE_TARGET_DEG - current["phase_deg"]
                df = np.clip(phase_gain * e, -PHASE_MAX_STEP_HZ, PHASE_MAX_STEP_HZ)
                f = float(np.clip(f + df, F_MIN, F_MAX))
            else:
                raise ValueError(strategy)

            point = table.interp(f)
            capture = point["active_power_w"] / table.power_max if table.power_max > 0 else np.nan
            frequency_saturated = int(f <= F_MIN + 1e-9 or f >= F_MAX - 1e-9)
            soft_current = int(point["transducer_current_a_peak"] > IPEAK_SOFT)
            hard_current = int(point["transducer_current_a_peak"] >= IPEAK_HARD)
            hard_voltage = int(point["transducer_vpp"] >= VPP_HARD)
            rows.append({
                "strategy": strategy,
                "phase_gain_hz_per_deg": phase_gain if strategy == "相位误差离散跟踪" else "",
                "global_step": global_step,
                "state_index": meta["state_index"],
                "local_step": local_step,
                "scenario_key": meta["scenario_key"],
                "case_id": meta["case_id"],
                "场景族": meta["scenario_family"],
                "扰动参数": meta["factor"],
                "扰动等级": meta["level"],
                "序列标签": meta["sequence_label"],
                "frequency_hz": f,
                "frequency_mhz": f / 1e6,
                "max_power_frequency_hz": table.power_freq,
                "phase_zero_frequency_hz": table.phase_freq,
                "min_reflection_frequency_hz": table.reflection_freq,
                "power_frequency_error_kHz": (f - table.power_freq) / 1e3,
                "phase_frequency_error_kHz": (f - table.phase_freq) / 1e3,
                "reflection_frequency_error_kHz": (f - table.reflection_freq) / 1e3,
                "active_power_w": point["active_power_w"],
                "active_power_mW": point["active_power_w"] * 1e3,
                "best_available_power_w": table.power_max,
                "power_capture_ratio": capture,
                "power_capture_pct": capture * 100,
                "phase_deg": point["phase_deg"],
                "reflection_proxy": point["reflection_proxy"],
                "transducer_vpp": point["transducer_vpp"],
                "transducer_current_a_peak": point["transducer_current_a_peak"],
                "transducer_current_mA_peak": point["transducer_current_a_peak"] * 1e3,
                "motional_current_mA_peak": point["motional_current_a_peak"] * 1e3,
                "source_current_mA_peak": point["source_current_a_peak"] * 1e3,
                "zin_mag_ohm": point["zin_mag_ohm"],
                "zin_real_ohm": point["zin_real_ohm"],
                "zin_imag_ohm": point["zin_imag_ohm"],
                "soft_current_limit_triggered": soft_current,
                "hard_current_limit_triggered": hard_current,
                "hard_voltage_limit_triggered": hard_voltage,
                "any_hard_constraint_triggered": int(hard_current or hard_voltage),
                "frequency_saturated": frequency_saturated,
                "scan_performed": scan_performed,
                "scan_points_this_step": scan_points,
                "total_scan_points_so_far": total_scan_points,
            })
            global_step += 1
    return rows


def transition_metrics(rows):
    metrics = []
    for state_idx in sorted(set(r["state_index"] for r in rows)):
        seg = [r for r in rows if r["state_index"] == state_idx]
        settle_step = None
        for i in range(len(seg) - SETTLED_CONSECUTIVE_STEPS + 1):
            if all(seg[j]["power_capture_ratio"] >= SETTLED_CAPTURE_THRESHOLD for j in range(i, i + SETTLED_CONSECUTIVE_STEPS)):
                settle_step = i
                break
        if settle_step is None:
            settle_step = DWELL_STEPS
        tail = seg[-5:]
        freqs = np.array([r["frequency_hz"] for r in tail])
        deltas = np.diff([r["frequency_hz"] for r in seg])
        nonzero = deltas[np.abs(deltas) > 1e-9]
        sign_changes = 0
        if len(nonzero) >= 2:
            sign_changes = int(np.sum(np.sign(nonzero[:-1]) * np.sign(nonzero[1:]) < 0))
        metrics.append({
            "strategy": rows[0]["strategy"],
            "state_index": state_idx,
            "case_id": seg[0]["case_id"],
            "序列标签": seg[0]["序列标签"],
            "收敛步数_达到95pct连续3步": settle_step,
            "该状态平均功率捕获_pct": float(np.mean([r["power_capture_pct"] for r in seg])),
            "该状态最低功率捕获_pct": float(np.min([r["power_capture_pct"] for r in seg])),
            "稳态功率捕获_pct": float(np.mean([r["power_capture_pct"] for r in tail])),
            "稳态功率频率误差_kHz_abs": float(np.mean([abs(r["power_frequency_error_kHz"]) for r in tail])),
            "稳态相位误差_deg_abs": float(np.mean([abs(r["phase_deg"]) for r in tail])),
            "稳态反射代理": float(np.mean([r["reflection_proxy"] for r in tail])),
            "稳态频率抖动_kHz": float(np.std(freqs) / 1e3),
            "频率方向反转次数": sign_changes,
            "频率饱和步数": int(sum(r["frequency_saturated"] for r in seg)),
            "软电流约束触发步数": int(sum(r["soft_current_limit_triggered"] for r in seg)),
            "硬电流约束触发步数": int(sum(r["hard_current_limit_triggered"] for r in seg)),
            "硬电压约束触发步数": int(sum(r["hard_voltage_limit_triggered"] for r in seg)),
        })
    return metrics


def summarize_strategy(rows, state_metrics):
    tail_metrics = state_metrics
    return {
        "控制策略": rows[0]["strategy"],
        "Kf_Hz_per_deg": rows[0]["phase_gain_hz_per_deg"] if rows[0]["strategy"] == "相位误差离散跟踪" else "",
        "平均功率恢复_pct": float(np.mean([r["power_capture_pct"] for r in rows])),
        "最差瞬时功率恢复_pct": float(np.min([r["power_capture_pct"] for r in rows])),
        "平均收敛步数": float(np.mean([m["收敛步数_达到95pct连续3步"] for m in tail_metrics])),
        "未收敛状态数": int(sum(m["收敛步数_达到95pct连续3步"] >= DWELL_STEPS for m in tail_metrics)),
        "平均稳态功率频率误差_kHz": float(np.mean([m["稳态功率频率误差_kHz_abs"] for m in tail_metrics])),
        "平均稳态相位误差_deg": float(np.mean([m["稳态相位误差_deg_abs"] for m in tail_metrics])),
        "平均稳态反射代理": float(np.mean([m["稳态反射代理"] for m in tail_metrics])),
        "最大稳态频率抖动_kHz": float(max(m["稳态频率抖动_kHz"] for m in tail_metrics)),
        "频率方向反转总次数": int(sum(m["频率方向反转次数"] for m in tail_metrics)),
        "频率上下限饱和步数": int(sum(r["frequency_saturated"] for r in rows)),
        "软电流约束触发次数": int(sum(r["soft_current_limit_triggered"] for r in rows)),
        "硬电流约束触发次数": int(sum(r["hard_current_limit_triggered"] for r in rows)),
        "硬电压约束触发次数": int(sum(r["hard_voltage_limit_triggered"] for r in rows)),
        "任一硬约束触发次数": int(sum(r["any_hard_constraint_triggered"] for r in rows)),
        "总扫频测点数_控制开销代理": int(sum(r["scan_points_this_step"] for r in rows)),
    }


def phase_gain_scan(tables):
    gain_rows = []
    for gain in PHASE_GAIN_CANDIDATES_HZ_PER_DEG:
        rows = simulate_strategy(tables, "相位误差离散跟踪", phase_gain=gain)
        metrics = transition_metrics(rows)
        summary = summarize_strategy(rows, metrics)
        summary["控制策略"] = f"相位跟踪_Kf={gain:g}"
        gain_rows.append(summary)
    return gain_rows


def run_control_study():
    tables = load_response_tables()
    response_rows = response_summary_rows(tables)
    gain_rows = phase_gain_scan(tables)
    all_rows = []
    all_state_metrics = []
    summaries = []
    strategies = [
        ("固定频率固定幅度", None),
        ("周期性局部扫频", None),
        ("相位误差离散跟踪", PHASE_TRACKING_GAIN_HZ_PER_DEG),
    ]
    for strategy, gain in strategies:
        rows = simulate_strategy(tables, strategy, phase_gain=gain or PHASE_TRACKING_GAIN_HZ_PER_DEG)
        metrics = transition_metrics(rows)
        all_rows.extend(rows)
        all_state_metrics.extend(metrics)
        summaries.append(summarize_strategy(rows, metrics))

    write_csv(OUTDIR / "第四步_LTspice响应表_场景特征.csv", response_rows)
    write_csv(OUTDIR / "第四步_相位跟踪增益扫描.csv", gain_rows)
    write_csv(OUTDIR / "第四步_控制时序明细.csv", all_rows)
    write_csv(OUTDIR / "第四步_逐状态收敛与振荡指标.csv", all_state_metrics)
    write_csv(OUTDIR / "第四步_三策略总览.csv", summaries)
    write_report(response_rows, gain_rows, summaries)
    manifest = {
        "model_scope": "assumed virtual BVD electrical model; control uses freshly generated LTspice RAW frequency response tables",
        "ltspice_version_expected_from_logs": "LTspice 26.0.2 for Windows if run on current machine",
        "frequency_range_hz": [F_MIN, F_MAX],
        "raw_step_hz": RAW_STEP,
        "dwell_steps_per_state": DWELL_STEPS,
        "sequence_states": len(SEQUENCE),
        "unique_ltspice_cases": len(UNIQUE_CASES),
        "fixed_frequency_hz": F_FIXED,
        "periodic_scan": {
            "interval_steps": SCAN_INTERVAL_STEPS,
            "local_halfwidth_hz": LOCAL_SCAN_HALFWIDTH,
            "step_hz": LOCAL_SCAN_STEP,
        },
        "phase_tracking": {
            "equation": "f[k+1]=clip(f[k]+Kf*(phi_target-phi[k]), f_min, f_max)",
            "phi_target_deg": PHASE_TARGET_DEG,
            "selected_Kf_hz_per_deg": PHASE_TRACKING_GAIN_HZ_PER_DEG,
            "max_step_hz": PHASE_MAX_STEP_HZ,
            "gain_candidates_hz_per_deg": PHASE_GAIN_CANDIDATES_HZ_PER_DEG,
        },
        "constraints": {
            "current_measurement": "BVD total terminal peak current: abs(I(Rmot)+I(Cstatic))*sqrt(2)",
            "current_nominal_peak_a": IPEAK_NOMINAL,
            "current_soft_peak_a": IPEAK_SOFT,
            "current_hard_peak_a": IPEAK_HARD,
            "voltage_hard_vpp": VPP_HARD,
        },
        "scenarios": [
            {
                "state_index": meta["state_index"],
                "scenario_key": meta["scenario_key"],
                "case_id": meta["case_id"],
                "sequence_label": meta["sequence_label"],
                "bvd": asdict(meta["scenario"].bvd),
                "rs": meta["scenario"].rs,
                "matching": asdict(meta["scenario"].matching),
            }
            for meta in SEQUENCE
        ],
    }
    (OUTDIR / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"timeseries_rows={len(all_rows)}")
    for row in summaries:
        print(row)


def write_report(response_rows, gain_rows, summaries):
    summary_by = {row["控制策略"]: row for row in summaries}
    fixed = summary_by["固定频率固定幅度"]
    scan = summary_by["周期性局部扫频"]
    phase = summary_by["相位误差离散跟踪"]
    high = next(row for row in response_rows if row["case_id"] == "CASE_402_COMBINED_HIGH")
    lines = [
        "# 第四步：三种控制策略正式比较",
        "",
        "## 1. 数据口径",
        "",
        "- 本轮控制策略不再使用旧原型直连 BVD 模型，而是使用统一 BVD + L 型匹配网络。",
        "- 每个扰动状态先由 LTspice 批处理生成 0.84–0.96 MHz、0.1 kHz 的 RAW 频率响应表。",
        "- 控制仿真只从 LTspice RAW 响应表插值/查表，不直接使用解析曲线作为验收数据。",
        "- 电流约束统一为 BVD 端总峰值电流：`abs(I(Rmot)+I(Cstatic))*sqrt(2)`；源侧电流只记录，不套用 5 mA 约束。",
        "",
        "## 2. 扰动时间序列",
        "",
        f"- 序列：基准 → 20 个单因素扰动 → 3 个组合扰动 → 恢复基准，共 {len(SEQUENCE)} 个状态。",
        f"- 每个状态驻留 {DWELL_STEPS} 个离散控制步，共 {len(SEQUENCE) * DWELL_STEPS} 步。",
        "- 频率上下限：0.84–0.96 MHz。",
        "",
        "## 3. 三种控制策略",
        "",
        "| 策略 | 规则 |",
        "|---|---|",
        "| 固定频率、固定幅度 | 始终 `f=0.9 MHz`，源幅值保持基准校准值 |",
        f"| 周期性局部扫频 | 每 {SCAN_INTERVAL_STEPS} 步或状态切换时，在当前频率 ±{LOCAL_SCAN_HALFWIDTH/1e3:.0f} kHz 内以 {LOCAL_SCAN_STEP/1e3:.1f} kHz 步长寻找最大有功功率点 |",
        f"| 相位误差离散跟踪 | `f[k+1]=clip(f[k]+Kf*(phi_target-phi[k]), f_min, f_max)`；本轮默认 `Kf={PHASE_TRACKING_GAIN_HZ_PER_DEG:g} Hz/deg`，`phi_target=0 deg` |",
        "",
        "## 4. 总览结果",
        "",
        "| 策略 | 平均功率恢复 | 最差瞬时功率恢复 | 平均收敛步数 | 未收敛状态数 | 平均稳态功率频率误差 | 平均稳态相位误差 | 频率饱和步数 | 软电流触发 | 硬电流触发 | 硬电压触发 | 控制开销测点 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            f"| {row['控制策略']} | {row['平均功率恢复_pct']:.2f}% | {row['最差瞬时功率恢复_pct']:.2f}% | "
            f"{row['平均收敛步数']:.2f} | {row['未收敛状态数']} | {row['平均稳态功率频率误差_kHz']:.2f} kHz | "
            f"{row['平均稳态相位误差_deg']:.2f}° | {row['频率上下限饱和步数']} | {row['软电流约束触发次数']} | "
            f"{row['硬电流约束触发次数']} | {row['硬电压约束触发次数']} | {row['总扫频测点数_控制开销代理']} |"
        )
    lines.extend([
        "",
        "## 5. 相位跟踪增益扫描",
        "",
        "| Kf | 平均功率恢复 | 最差功率恢复 | 平均稳态相位误差 | 最大稳态频率抖动 | 频率饱和步数 |",
        "|---:|---:|---:|---:|---:|---:|",
    ])
    for row in gain_rows:
        lines.append(
            f"| {row['Kf_Hz_per_deg']} | {row['平均功率恢复_pct']:.2f}% | {row['最差瞬时功率恢复_pct']:.2f}% | "
            f"{row['平均稳态相位误差_deg']:.2f}° | {row['最大稳态频率抖动_kHz']:.3f} kHz | {row['频率上下限饱和步数']} |"
        )
    lines.extend([
        "",
        "## 6. 关键验收结论",
        "",
        f"- 高复杂度组合扰动的 LTspice 响应表显示：最大功率点 {high['最大功率频率_MHz']:.6f} MHz，"
        f"相位零点 {high['相位零点或最小相位频率_MHz']:.6f} MHz，最小反射点 {high['最小反射频率_MHz']:.6f} MHz。",
        "- 因此，相位跟踪即使能把相位误差压小，也不等价于功率恢复最大；这是本轮正式验收最重要的结论。",
        f"- 固定频率策略开销最低，但在 fs 漂移和高复杂度扰动下功率恢复明显变差，平均功率恢复 {fixed['平均功率恢复_pct']:.2f}%。",
        f"- 周期性局部扫频以额外扫频测点换取最高功率恢复，平均功率恢复 {scan['平均功率恢复_pct']:.2f}%，平均稳态功率频率误差 {scan['平均稳态功率频率误差_kHz']:.2f} kHz。",
        f"- 相位跟踪的平均相位误差最低，但平均功率恢复为 {phase['平均功率恢复_pct']:.2f}%，说明它更像阻抗相位控制而非功率最大化控制。",
        "- 本轮没有引入自动降幅控制；若电压/电流约束触发，记录为约束事件，不在当前策略内主动削幅。",
        "",
        "## 7. 后续建议",
        "",
        "下一步可以加入第四种策略：`扫频选功率点 + 约束限幅`，即先选最大有功功率频率，再按 Vpp/BVD 端峰值电流约束缩放源幅值。这才更接近可落地的安全控制逻辑。",
        "",
    ])
    (OUTDIR / "第四步_三种控制策略正式比较报告.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "generate-netlists":
        generate_netlists()
        return
    run_control_study()


if __name__ == "__main__":
    main()
