"""为 Qm≈21 的新基线重新设计三级扫描阶梯。

v2.1 的阶梯（±50k/5k → ±5k/1k → ±1k/0.1k，共 53 点）是在 Qm=800、
功率峰 FWHM = 1.74 kHz 的假设下定的：0.1 kHz 终扫步长约为峰宽的 1/17，
合理。空心圆柱基线的 FWHM 是 74.5 kHz，同一套阶梯的终扫步长变成峰宽的
1/745——把时间花在分辨一个根本不需要分辨的尺度上。

本脚本不靠断言，靠测量：对每个候选阶梯，在全部 34 个场景上模拟一次
「以 f0 起扫、逐级向最优点收拢」的搜索，记录捕获率与点数。

捕获率 = P_rm(找到的频率) / P_rm(窗内全局最优频率)，均在单位驱动幅度下
评估——因为 v3 的约束是功率，限幅后各场景功率恒等，必须看固定驱动下的
传输效率才有区分度。

    python3 workspace/disturbance_v3_20260916/scan_ladder_v3.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

import model_v3 as M

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
SCAN_POINT_DT = 1.5e-3          # 与 v2.1 的 SCAN_POINT_DT 一致（假设代理值）
FINE = np.arange(M.F_MIN, M.F_MAX + 0.1, 25.0)


def unit_power(f, s: M.Scenario) -> np.ndarray:
    return M.response(f, s, amplitude=1.0)["p_rm_W"]


def run_ladder(stages, s: M.Scenario, start_hz: float) -> tuple[float, int]:
    """逐级收拢。返回（找到的频率, 总点数）。"""
    centre, points = start_hz, 0
    for halfwidth, step in stages:
        grid = np.arange(centre - halfwidth, centre + halfwidth + step / 2, step)
        grid = grid[(grid >= M.F_MIN) & (grid <= M.F_MAX)]
        if grid.size == 0:
            continue
        points += grid.size
        centre = float(grid[int(np.argmax(unit_power(grid, s)))])
    return centre, points


LADDERS = {
    "v2_1_原样搬运": [(50e3, 5e3), (5e3, 1e3), (1e3, 100.0)],
    "v2_1_加宽粗扫": [(100e3, 5e3), (5e3, 1e3), (1e3, 100.0)],
    "v3_两级_80k20k": [(80e3, 20e3), (20e3, 5e3)],
    "v3_两级_80k16k": [(80e3, 16e3), (16e3, 4e3)],
    "v3_两级_100k25k": [(100e3, 25e3), (25e3, 6e3)],
    "v3_单级_80k10k": [(80e3, 10e3)],
    "v3_单级_100k10k": [(100e3, 10e3)],
    "v3_三级_100k25k6k": [(100e3, 25e3), (25e3, 6e3), (6e3, 1.5e3)],
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    scenarios = M.all_scenarios()

    # 窗内全局最优（25 Hz 细网格，作为捕获率的分母）
    best = {}
    for s in scenarios:
        p = unit_power(FINE, s)
        i = int(np.argmax(p))
        best[s.case_id] = (float(FINE[i]), float(p[i]))

    rows, per_case = [], []
    for name, stages in LADDERS.items():
        caps, pts = [], 0
        for s in scenarios:
            f_found, n = run_ladder(stages, s, M.F0)
            cap = float(unit_power(f_found, s)[0]) / best[s.case_id][1]
            caps.append(cap)
            pts = n
            per_case.append({
                "ladder": name, "case_id": s.case_id, "capture": cap,
                "f_found_Hz": f_found, "f_best_Hz": best[s.case_id][0],
                "error_Hz": f_found - best[s.case_id][0], "points": n,
            })
        caps = np.array(caps)
        rows.append({
            "ladder": name,
            "stages": " -> ".join(f"±{h/1e3:g}k/{st/1e3:g}k" for h, st in stages),
            "points_per_sweep": pts,
            "time_proxy_ms": pts * SCAN_POINT_DT * 1e3,
            "capture_min": float(caps.min()),
            "capture_mean": float(caps.mean()),
            "capture_p10": float(np.percentile(caps, 10)),
            "cases_below_90pct": int((caps < 0.90).sum()),
            "cases_below_99pct": int((caps < 0.99).sum()),
            "worst_case": scenarios[int(np.argmin(caps))].case_id,
        })

    with (OUT / "scan_ladder_v3.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    with (OUT / "scan_ladder_per_case_v3.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(per_case[0])); w.writeheader(); w.writerows(per_case)

    print("=" * 100)
    print("扫描阶梯候选对照（34 场景，捕获率 = 找到点功率 / 窗内全局最优功率，单位驱动幅度）")
    print("=" * 100)
    print(f"{'阶梯':<18}{'级配':<30}{'点数':>6}{'时间(ms)':>10}"
          f"{'最差':>8}{'均值':>8}{'<90%':>7}{'<99%':>7}  最差场景")
    for r in rows:
        print(f"{r['ladder']:<18}{r['stages']:<30}{r['points_per_sweep']:>6}"
              f"{r['time_proxy_ms']:>10.1f}{r['capture_min']:>8.3f}{r['capture_mean']:>8.3f}"
              f"{r['cases_below_90pct']:>7}{r['cases_below_99pct']:>7}  {r['worst_case']}")

    fwhm = [M.half_power_width(FINE, unit_power(FINE, s))[0] for s in scenarios]
    fwhm = [x for x in fwhm if np.isfinite(x)]
    fs_off = [abs(s.bvd.fs - M.F0) for s in scenarios]
    print()
    print(f"设计依据：FWHM 中位数 {np.median(fwhm)/1e3:.1f} kHz（最窄 {min(fwhm)/1e3:.1f} kHz，"
          f"出现在 Qm 取 2 倍基线的场景）；fs 最大偏移 {max(fs_off)/1e3:.1f} kHz。")
    print(f"  粗扫半宽须 >= {max(fs_off)/1e3:.1f} kHz；步长取最窄峰的 1/4 即 "
          f"{min(fwhm)/4/1e3:.1f} kHz 已足够。")
    print(f"  v2.1 的 0.1 kHz 终扫级步长相当于基线峰宽的 1/{np.median(fwhm)/100:.0f}，"
          f"在本基线下纯属浪费。")

    (OUT / "scan_ladder_v3.json").write_text(json.dumps({
        "batch": "disturbance_v3_20260916",
        "scan_point_dt_s": SCAN_POINT_DT,
        "design_basis": {
            "fwhm_median_Hz": float(np.median(fwhm)), "fwhm_min_Hz": float(min(fwhm)),
            "max_fs_offset_Hz": float(max(fs_off)),
            "required_coarse_halfwidth_Hz": float(max(fs_off)),
            "sufficient_step_Hz": float(min(fwhm) / 4),
        },
        "ladders": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {OUT}")


if __name__ == "__main__":
    main()
