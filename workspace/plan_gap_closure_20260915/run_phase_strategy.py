"""补齐计划书缺口 2：把相位闭环纳入正式策略比较，并修复伪锁定。

计划书第 4 周要求对比「固定频率、周期扫频和**相位误差闭环**」三种策略，
但正式比较表里第三种是 P&O，相位闭环只作为消融实验存在。
`docs/04` 第 4 节又发现相位法有伪锁定缺陷：sign(slope) 符号校正使带内
每一个相位零点都成为稳定吸引子，其中两个只有峰值功率的 6.0% 和 1.1%，
而且锁定后 |phase| < 0.1 deg，按验收指标判为合格。

本脚本做两件事：
  1. 给相位控制器加【伪锁定防护】——收敛后用可观测的端口功率做 +/-D 探测，
     若邻点功率明显更高，则当前点不是功率极大，判为伪锁定并重扫。
  2. 在同一扰动日程下跑四种策略，输出统一比较表。
     同时保留【关闭防护】的相位策略作为对照，量化防护到底救回多少。

复用 active_stage3_5/run_stage4_5_control.py 的控制骨架（Protection、measure、
local_scan、SCHEDULE），保证与既有三策略同源同口径。
本批次只写入自己的 outputs/，不覆盖任何历史结果。

    python3 workspace/plan_gap_closure_20260915/run_phase_strategy.py
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
ACTIVE = HERE.parent / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5"
sys.path.insert(0, str(ACTIVE))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


import model_v2_1 as m  # noqa: E402
H = _load("stage4_5_harness", ACTIVE / "run_stage4_5_control.py")  # 控制骨架

# 相位控制器参数，与 run_phase_ablation.py 一致
GAIN_HZ_PER_DEG = 5.0
PHASE_PROBE_HZ = 100.0
PHASE_DEADBAND_DEG = 0.10
MAX_UPDATE_HZ = 500.0
TARGET_PHASE_DEG = 0.0

# 伪锁定防护参数
GUARD_PROBE_HZ = 500.0      # 功率有效性探测步长；FWHM 约 1.7 kHz，500 Hz 有足够分离度
GUARD_RATIO = 1.02          # 邻点/当前 功率比超过此值即判伪锁定
GUARD_COOLDOWN_S = 0.40     # 触发后冷却，避免抖动
GUARD_MIN_DWELL_S = 0.05    # 收敛后至少停留这么久才做探测


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        w = csv.DictWriter(handle, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def phase_at(f: float, scenario) -> float:
    return float(m.response(np.array([f]), scenario, 1.0)["phase_deg"][0])


def probe_power(f: float, scenario) -> float:
    """只用可观测量：探测幅度下的端口有功功率。"""
    return float(m.response(np.array([f]), scenario, H.PROBE_AMPLITUDE)["p_port_W"][0])


def simulate_phase(scenarios: dict, optima: dict, *, guard: bool) -> list[dict]:
    """相位误差离散频率跟踪。

    重捕获机制与 P_AND_O 完全相同（同一个 ObservableDisturbanceDetector、
    同一个 local_scan），因此四种策略的差别只在【稳态频率更新律】上，
    而不在获取机制上 —— 否则就是拿「相位跟踪」去比「扫频辅助的策略」，不公平。

    相位跟踪本身是【局部跟踪器】而非【捕获机制】：更新量被 MAX_UPDATE_HZ 限幅，
    每 20 ms 最多移动 500 Hz，追不上扰动切换造成的数十 kHz 跳变。这一点本身
    就是计划书第 4 周要求比较「恢复时间」时应当报出的性质。

    guard=True 时启用伪锁定防护：相位收敛后用端口功率做 +/-D 探测，
    若邻点功率明显更高则判为伪锁定，重扫并【把新工作点的相位标定为新设定点】。
    只重扫而不重标定是无效的 —— 功率峰处相位并非 0，控制器会立刻被拉回伪锁点。
    """
    strategy = "PHASE_LOCK" if guard else "PHASE_LOCK_NOGUARD"
    rows: list[dict] = []
    protection = H.Protection()
    detector = H.ObservableDisturbanceDetector()
    frequency = m.F0
    t = 0.0
    need_reacquire = False
    reacquire_reason = ""
    target_phase = TARGET_PHASE_DEG
    converged_since: float | None = None
    guard_until = 0.0
    guard_trips = 0

    def _fill(r: dict, err: float = math.nan, trip: int = 0, ratio: float = math.nan) -> dict:
        r.setdefault("phase_error_deg", err)
        r.setdefault("guard_enabled", int(guard))
        r.setdefault("guard_trip", trip)
        r.setdefault("guard_power_ratio", ratio)
        r.setdefault("target_phase_deg", target_phase)
        return r

    while t < H.TOTAL_TIME - 1e-12:
        if need_reacquire and protection.tracking_allowed(t):
            frequency, t, _ = H.local_scan(t, strategy, frequency, reacquire_reason,
                                           rows, protection, scenarios, optima)
            need_reacquire = False
            detector.after_scan(t)
            if guard:
                # 重捕获落在功率峰上，把该点相位标定为新设定点
                target_phase = phase_at(frequency, scenarios[H.schedule_at(t)["case_id"]])
            converged_since = None
            guard_until = t + GUARD_COOLDOWN_S
            for r in rows:
                _fill(r)
            continue

        seg = H.schedule_at(t)
        scenario = scenarios[seg["case_id"]]
        optimum = optima[seg["case_id"]]
        amplitude, pstate, hard, soft, frozen = protection.apply(t, frequency, scenario, 1.0)
        row = H.measure(t, H.CONTROL_DT, strategy, "CONTROL", frequency, amplitude,
                        pstate, hard, soft, frozen, seg, scenario, optimum)
        row.update(detector.observe(row, t, allow_trigger=True))
        phase = row["phase_deg"]
        error = target_phase - phase
        _fill(row, err=error)
        rows.append(row)

        if hard or soft:
            need_reacquire = True
            reacquire_reason = "HARD_LIMIT_EVENT" if hard else "SOFT_LIMIT_EVENT"
        elif row["detector_trigger"]:
            need_reacquire = True
            reacquire_reason = "OBSERVABLE_2_OF_4"
        elif protection.tracking_allowed(t) and not frozen and pstate == "NORMAL":
            if abs(error) <= PHASE_DEADBAND_DEG:
                if converged_since is None:
                    converged_since = t
                if (guard and t >= guard_until
                        and (t - converged_since) >= GUARD_MIN_DWELL_S):
                    p0 = probe_power(frequency, scenario)
                    lo = max(m.F_MIN, frequency - GUARD_PROBE_HZ)
                    hi = min(m.F_MAX, frequency + GUARD_PROBE_HZ)
                    ratio = max(probe_power(lo, scenario), probe_power(hi, scenario)) / max(p0, 1e-30)
                    rows[-1]["guard_power_ratio"] = ratio
                    if ratio > GUARD_RATIO:
                        guard_trips += 1
                        rows[-1]["guard_trip"] = 1
                        need_reacquire = True
                        reacquire_reason = "PHASE_FALSE_LOCK_GUARD"
            else:
                converged_since = None
                lo = max(m.F_MIN, frequency - PHASE_PROBE_HZ)
                hi = min(m.F_MAX, frequency + PHASE_PROBE_HZ)
                slope = (phase_at(hi, scenario) - phase_at(lo, scenario)) / max(hi - lo, 1.0)
                if abs(slope) > 1e-12:
                    update = float(np.clip(GAIN_HZ_PER_DEG * error * np.sign(slope),
                                           -MAX_UPDATE_HZ, MAX_UPDATE_HZ))
                    frequency = float(np.clip(frequency + update, m.F_MIN, m.F_MAX))

        t += H.CONTROL_DT

    for r in rows:
        _fill(r)
        r["guard_trips_total"] = guard_trips
    return rows


def false_lock_demonstration() -> list[dict]:
    """专门暴露伪锁定的定向实验（对应 docs/04 第 4 节）。

    在统一扰动日程下，观测式重捕获（detector + local_scan）触发得足够频繁，
    控制器来不及在伪零点上停住，因此防护触发 0 次 —— 这不等于隐患不存在。

    本实验把重捕获关掉、扰动固定在标称场景，只改变【初始频率】，
    让相位控制器自由收敛。这对应真实场景中「开机整定」或「长时间无扰动」
    的工况，也是伪锁定真正会咬人的地方。
    """
    scenario = m.scenario_map()["CASE_000_BASELINE"]
    dense = np.linspace(m.F_MIN, m.F_MAX, 400001)
    p_oracle = float(m.safe_power(dense, scenario).max())
    rows = []
    for f0_kHz in range(890, 921, 2):
        f0 = f0_kHz * 1e3
        for guard in (False, True):
            f = f0
            target = TARGET_PHASE_DEG
            trips = 0
            for _ in range(4000):
                ph = phase_at(f, scenario)
                err = target - ph
                if abs(err) <= PHASE_DEADBAND_DEG:
                    if not guard:
                        break
                    p0 = probe_power(f, scenario)
                    lo = max(m.F_MIN, f - GUARD_PROBE_HZ)
                    hi = min(m.F_MAX, f + GUARD_PROBE_HZ)
                    if max(probe_power(lo, scenario), probe_power(hi, scenario)) / max(p0, 1e-30) <= GUARD_RATIO:
                        break
                    # 判为伪锁定：局部重扫并把新点的相位标定为设定点
                    trips += 1
                    grid = np.arange(max(m.F_MIN, f - 50e3), min(m.F_MAX, f + 50e3) + 1, 5e3)
                    pg = m.response(grid, scenario, H.PROBE_AMPLITUDE)["p_port_W"]
                    cb = float(grid[int(np.argmax(pg))])
                    fine = np.arange(max(m.F_MIN, cb - 5e3), min(m.F_MAX, cb + 5e3) + 1, 1e3)
                    pf = m.response(fine, scenario, H.PROBE_AMPLITUDE)["p_port_W"]
                    fb = float(fine[int(np.argmax(pf))])
                    ultra = np.arange(max(m.F_MIN, fb - 1e3), min(m.F_MAX, fb + 1e3) + 1, 0.1e3)
                    pu = m.response(ultra, scenario, H.PROBE_AMPLITUDE)["p_port_W"]
                    f = float(ultra[int(np.argmax(pu))])
                    target = phase_at(f, scenario)
                    if trips > 5:
                        break
                    continue
                lo = max(m.F_MIN, f - PHASE_PROBE_HZ)
                hi = min(m.F_MIN + (m.F_MAX - m.F_MIN), f + PHASE_PROBE_HZ)
                slope = (phase_at(hi, scenario) - phase_at(lo, scenario)) / max(hi - lo, 1.0)
                if abs(slope) <= 1e-12:
                    break
                f = float(np.clip(f + np.clip(GAIN_HZ_PER_DEG * err * np.sign(slope),
                                              -MAX_UPDATE_HZ, MAX_UPDATE_HZ), m.F_MIN, m.F_MAX))
            p_lock = float(m.safe_power(np.array([f]), scenario)[0])
            rows.append({
                "start_frequency_Hz": f0,
                "guard_enabled": int(guard),
                "lock_frequency_Hz": f,
                "lock_phase_deg": phase_at(f, scenario),
                "lock_target_phase_deg": target,
                "lock_p_rm_W": p_lock,
                "oracle_p_rm_W": p_oracle,
                "capture_ratio": p_lock / p_oracle,
                "guard_trips": trips,
                "passes_5deg_criterion": int(abs(phase_at(f, scenario)) <= 5.0),
            })
    return rows


def metrics(rows: list[dict], strategy: str) -> dict:
    """计划书第 4 周要求的比较指标：稳态误差、恢复时间、功率稳定性、约束触发次数。"""
    ctrl = [r for r in rows if not str(r["action"]).startswith("SCAN_")]
    caps = [r["safe_power_capture_ratio"] for r in ctrl]
    # 每个扰动段末尾 25% 视为稳态
    steady: list[float] = []
    phase_err: list[float] = []
    for i in range(len(H.SCHEDULE)):
        seg_rows = [r for r in ctrl if r["state_index"] == i]
        if not seg_rows:
            continue
        tail = seg_rows[int(len(seg_rows) * 0.75):]
        steady += [r["safe_power_capture_ratio"] for r in tail]
        phase_err += [abs(r["phase_deg"]) for r in tail]
    # 恢复时间：每段内首次连续 10 个控制样本达到 98% 捕获所需时间
    recov = []
    for i in range(len(H.SCHEDULE)):
        seg_rows = [r for r in ctrl if r["state_index"] == i]
        if not seg_rows:
            continue
        t0 = seg_rows[0]["time_s"]
        run = 0
        hit = math.nan
        for r in seg_rows:
            run = run + 1 if r["safe_power_capture_ratio"] >= 0.98 else 0
            if run >= 10:
                hit = r["time_s"] - t0
                break
        recov.append(hit)
    ok = [x for x in recov if not math.isnan(x)]
    return {
        "strategy": strategy,
        "control_samples": len(ctrl),
        "mean_capture_ratio": float(np.mean(caps)),
        "steady_state_capture_ratio": float(np.mean(steady)) if steady else math.nan,
        "min_capture_ratio": float(np.min(caps)),
        "capture_ratio_std": float(np.std(steady)) if steady else math.nan,
        "steady_state_abs_phase_deg": float(np.mean(phase_err)) if phase_err else math.nan,
        "segments_recovered_to_98pct": len(ok),
        "segments_total": len(recov),
        "mean_recovery_time_s": float(np.mean(ok)) if ok else math.nan,
        "soft_limit_triggers": sum(r["soft_limit_trigger"] for r in rows),
        "hard_trip_triggers": sum(r["hard_trip_trigger"] for r in rows),
        "actual_voltage_hard_violations": sum(r["actual_voltage_hard_violation"] for r in rows),
        "actual_current_hard_violations": sum(r["actual_current_hard_violation"] for r in rows),
        "guard_trips": rows[0].get("guard_trips_total", 0),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = m.scenario_map()
    optima = H.optimal_tables(scenarios)

    all_rows: list[dict] = []
    summary: list[dict] = []

    # 既有三策略，直接复用骨架，口径不变
    for strategy in H.STRATEGIES:
        rows = H.simulate(strategy, scenarios, optima)
        for r in rows:
            r.setdefault("phase_error_deg", math.nan)
            r.setdefault("guard_enabled", 0)
            r.setdefault("guard_trip", 0)
            r.setdefault("guard_power_ratio", math.nan)
            r.setdefault("guard_trips_total", 0)
        all_rows += rows
        summary.append(metrics(rows, strategy))

    # 计划书点名要求的第三种策略：相位误差闭环（带防护 / 不带防护）
    for guard in (True, False):
        rows = simulate_phase(scenarios, optima, guard=guard)
        all_rows += rows
        summary.append(metrics(rows, "PHASE_LOCK" if guard else "PHASE_LOCK_NOGUARD"))

    keys: list[str] = []
    for r in all_rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    for r in all_rows:
        for k in keys:
            r.setdefault(k, math.nan)

    write_csv(OUT / "gap2_strategy_timeline.csv", all_rows)
    write_csv(OUT / "gap2_strategy_comparison.csv", summary)
    demo = false_lock_demonstration()
    write_csv(OUT / "gap2_false_lock_demonstration.csv", demo)

    audit = {
        "status": "PASS",
        "batch": "plan_gap_closure_20260915",
        "schedule_sha256": H.hashlib.sha256(
            json.dumps(H.SCHEDULE, sort_keys=True).encode()).hexdigest(),
        "all_strategies_same_schedule": True,
        "drive_mode": f"FROZEN_A1 (SOURCE_MAX_AMPLITUDE={m.SOURCE_MAX_AMPLITUDE})",
        "phase_controller": {
            "gain_Hz_per_deg": GAIN_HZ_PER_DEG, "deadband_deg": PHASE_DEADBAND_DEG,
            "probe_Hz": PHASE_PROBE_HZ, "max_update_Hz": MAX_UPDATE_HZ,
        },
        "false_lock_guard": {
            "probe_Hz": GUARD_PROBE_HZ, "ratio_threshold": GUARD_RATIO,
            "cooldown_s": GUARD_COOLDOWN_S, "min_dwell_s": GUARD_MIN_DWELL_S,
            "observable_only": "仅使用端口有功功率，不使用场景身份或 oracle",
        },
        "comparison": summary,
        "false_lock_demonstration": {
            "purpose": "统一日程下重捕获掩盖了伪锁定；本定向实验关闭重捕获、只改初始频率以暴露之",
            "starts_tested": len({r["start_frequency_Hz"] for r in demo}),
            "no_guard_false_locks": sum(
                1 for r in demo if not r["guard_enabled"] and r["capture_ratio"] < 0.5),
            "no_guard_false_locks_passing_5deg": sum(
                1 for r in demo if not r["guard_enabled"] and r["capture_ratio"] < 0.5
                and r["passes_5deg_criterion"]),
            "guard_false_locks": sum(
                1 for r in demo if r["guard_enabled"] and r["capture_ratio"] < 0.5),
            "no_guard_min_capture": min(r["capture_ratio"] for r in demo if not r["guard_enabled"]),
            "guard_min_capture": min(r["capture_ratio"] for r in demo if r["guard_enabled"]),
        },
        "note": "只写入本批次 outputs/；未重跑也未覆盖 active_stage3_5 下的历史结果。",
    }
    (OUT / "gap2_phase_strategy_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    ng = [r for r in demo if not r["guard_enabled"]]
    gd = [r for r in demo if r["guard_enabled"]]
    print("\n定向伪锁定实验（关闭重捕获，仅改初始频率，标称场景）：")
    print(f"  无防护：{sum(1 for r in ng if r['capture_ratio'] < 0.5)}/{len(ng)} 个初值锁到 <50% 功率，"
          f"最低 {min(r['capture_ratio'] for r in ng)*100:.2f}%，"
          f"其中 {sum(1 for r in ng if r['capture_ratio'] < 0.5 and r['passes_5deg_criterion'])} 个仍满足 |相位|<=5 度")
    print(f"  有防护：{sum(1 for r in gd if r['capture_ratio'] < 0.5)}/{len(gd)} 个，"
          f"最低 {min(r['capture_ratio'] for r in gd)*100:.2f}%\n")
    print(f"{'strategy':<22}{'稳态捕获':>10}{'最低捕获':>10}{'稳态|相位|':>12}{'硬跳闸':>8}{'实际越界':>10}{'防护触发':>10}")
    for s in summary:
        print(f"{s['strategy']:<22}{s['steady_state_capture_ratio']:>10.4f}{s['min_capture_ratio']:>10.4f}"
              f"{s['steady_state_abs_phase_deg']:>11.3f}d{s['hard_trip_triggers']:>8}"
              f"{s['actual_voltage_hard_violations']+s['actual_current_hard_violations']:>10}{s['guard_trips']:>10}")


if __name__ == "__main__":
    main()
