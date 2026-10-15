#!/usr/bin/env python3
"""以功率为被控量的频率跟踪原型（扰动观察 P&O），与固定频率、正式相位反馈、v2 并排比较。

只读：运行期在内存里替换场景表（与 physical_baseline_control_check.py 同一套重建与自证），
不改任何文件；--out 只写到给定目录，拒绝 workspace/ 与任何 outputs/ 目录。

    python review/power_tracking_prototype.py --root <unified 源目录> [--candidate <candidate.py 所在目录>] [--out <目录>]

控制器隔离：P&O 只用 Executor 返回的 Measurement，以及 cfg 里的频带与软限（经
engine.measured_score，正式周期扫频用的同一个函数）。不读场景 ID、段边界、参考表或验收计数。

参数在运行前声明，按物理峰宽定（k_eff 0.45、Q 13.81 时支路半峰宽约 65 kHz），不在 12 段日程上调：
  初始步长 1 kHz；最小 200 Hz（约半峰宽/300）；最大 8 kHz（约半峰宽/8）；
  比上一点好则同向、步长 ×1.5，否则反向、步长 ×0.5；初始方向向下（任意选定）。
  改频后若施加幅度 < 0.999，下一拍原地保持一次：保护器只有在频率不变时才走斜升分支，
  连续改频会让幅度只降不升（幅度棘轮，review/19）。保护非 NORMAL、冻结或测量无效时原地保持，
  比较基准作废，等它恢复再比。

对照组：
  FIXED、正式 PHASE_FEEDBACK（controllers.run_policy）；
  v2（给 --candidate 时）：原参数，以及「按物理峰重定」的一组——增益乘以冻结目标处相位斜率之比，
  探针偏移、单步限幅乘以 Q 之比，死区按同样的频率当量缩放。缩放规则在运行前声明，比例由名义模型
  在设计阶段算出，运行中控制器不读模型。
  P&O 另跑两组测量噪声：P、V、I 各乘以 (1+σ·N(0,1))，σ = 0.5% 与 2%，固定种子；
  噪声只进控制器看到的测量，不进被控对象与能量积分。相位法的噪声敏感性本脚本不测。

Q 取 13.81（主，k_eff 0.45）、35.46（k_eff 0.30）、800（登记基线：用于自证；P&O 参数不是为它设计的）。

自证（任一不满足即退出）：Q=800 时重建场景与 model.scenario_map() 逐字段相等；
FIXED 7/12 73.778340%、PHASE_FEEDBACK 6/12 57.337359%；给 --candidate 时 v2 7/12 70.104969%。
"""
from __future__ import annotations

import argparse
import collections
import csv
import dataclasses
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import physical_baseline_control_check as PB    # noqa: E402

V2_REGISTERED = (7, 70.104969)
# 已登记批次 registered34_target_segment_metrics.csv：34 条覆盖日程目标段（第 1 段）的达标数与能量合计
COVER_REGISTERED = {'FIXED': (18, 2170.7659962364924), 'PHASE_FEEDBACK': (17, 2186.7189992001495)}
COVER_ALIASES = ('CASE_000_BASELINE', 'CASE_QL_100', 'CASE_QM_800')   # 与基准完全相同的登记项
NOISE_SEEDS = tuple(range(1, 11))


@dataclasses.dataclass(frozen=True)
class POParams:
    step0_Hz: float = 1000.0
    step_min_Hz: float = 200.0
    step_max_Hz: float = 8000.0
    grow: float = 1.5
    shrink: float = 0.5
    full_amplitude: float = 0.999
    initial_direction: float = -1.0


def run_power_po(io, E, C, p: POParams = POParams(), max_pending_ticks: int = 15):
    """扰动观察 v1.1：每个 20 ms 控制格点比较本点与上一点的软限可行功率，决定方向与步长。

    与第一版的唯一区别是对「改频被保护器延后」的处理。保护器的规则是：新频率允许幅度更低时，
    先在原频率降幅、进入 100 ms 回退保持，之后才执行改频（engine.Protection.apply）。
    第一版把这段时间当作「保护忙」，回到原频率等待——这让幅度在原频率上又升回去，
    改频永远执行不了，方向与步长也永不更新（段 3 卡在 899.20 kHz、段 7 卡在 864.65 kHz）。
    v1.1 在此期间持续请求同一个目标，并保留比较基准；超过 max_pending_ticks 仍未执行才放弃并掉头。
    参数（POParams）与第一版相同。
    """
    cfg = io.cfg
    lo, hi = float(cfg['frequency_min_Hz']), float(cfg['frequency_max_Hz'])
    f_cmd = float(cfg['initial_frequency_Hz'])
    step, direction = p.step0_Hz, p.initial_direction
    s_prev = f_prev = None
    pending, waited = None, 0
    just_moved = False
    last = None
    while not io.finished:
        if last is not None:
            valid = C.valid_measurement(last)
            if not valid or last.state in ('HARD_TRIP', 'HOLD', 'DATA_INVALID'):
                if E.finite(last.frequency_Hz):
                    f_cmd = float(last.frequency_Hz)       # 硬跳闸或数据失效：原地等，基准作废
                pending, s_prev, f_prev, just_moved = None, None, None, False
            elif pending is not None and abs(last.frequency_Hz - pending) > 1e-7:
                waited += 1                                # 改频被延后：保护器正在原频率降幅
                if waited <= max_pending_ticks:
                    f_cmd = pending
                else:
                    io.event('PO_PENDING_ABANDONED', target_Hz=pending)
                    direction, step = -direction, max(step * p.shrink, p.step_min_Hz)
                    f_cmd, pending, just_moved = float(last.frequency_Hz), None, False
            elif last.state != 'NORMAL' or last.frozen:
                f_cmd, pending = float(last.frequency_Hz), None   # 斜升或负载变化引起的回退：等
            else:
                pending, waited = None, 0
                f_now = float(last.frequency_Hz)
                s = E.measured_score(last, cfg)
                if s_prev is not None and abs(f_now - f_prev) > 1e-7:
                    if s > s_prev:
                        step = min(step * p.grow, p.step_max_Hz)
                    else:
                        direction = -direction
                        step = max(step * p.shrink, p.step_min_Hz)
                s_prev, f_prev = s, f_now
                if just_moved and last.amplitude < p.full_amplitude:
                    f_cmd = f_now                          # 原地一拍，让保护器走同频斜升
                    just_moved = False
                    io.event('PO_HOLD_FOR_RAMP', frequency_Hz=f_now, amplitude=last.amplitude)
                else:
                    cand = min(max(f_now + direction * step, lo), hi)
                    if abs(cand - f_now) < 1e-7:           # 碰到频带边：掉头
                        direction = -direction
                        cand = min(max(f_now + direction * step, lo), hi)
                    f_cmd, pending, waited = cand, cand, 0
                    just_moved = True
                    io.event('PO_STEP', frequency_Hz=f_now, score_W=s, step_Hz=step,
                             direction=direction, next_frequency_Hz=f_cmd)
        if not io.finished:
            last = io.control(f_cmd, 1.0)


def run_power_po_v1(io, E, C, p: POParams = POParams()):
    """第一版（存档，有缺陷）：改频被保护器延后时回到原频率等待，见 run_power_po 的说明。"""
    cfg = io.cfg
    lo, hi = float(cfg['frequency_min_Hz']), float(cfg['frequency_max_Hz'])
    f_cmd = float(cfg['initial_frequency_Hz'])
    step, direction = p.step0_Hz, p.initial_direction
    s_prev = f_prev = None
    just_moved = False
    last = None
    while not io.finished:
        if last is not None:
            ok = C.valid_measurement(last) and last.state == 'NORMAL' and not last.frozen
            if not ok:
                if E.finite(last.frequency_Hz):
                    f_cmd = float(last.frequency_Hz)       # 保护占用：原地等，不叠加改频
                s_prev = f_prev = None
                just_moved = False
            else:
                f_now = float(last.frequency_Hz)
                s = E.measured_score(last, cfg)
                if s_prev is not None and abs(f_now - f_prev) > 1e-7:
                    if s > s_prev:
                        step = min(step * p.grow, p.step_max_Hz)
                    else:
                        direction = -direction
                        step = max(step * p.shrink, p.step_min_Hz)
                s_prev, f_prev = s, f_now
                if just_moved and last.amplitude < p.full_amplitude:
                    f_cmd = f_now                          # 原地一拍，让保护器走同频斜升
                    just_moved = False
                    io.event('PO_HOLD_FOR_RAMP', frequency_Hz=f_now, amplitude=last.amplitude)
                else:
                    cand = min(max(f_now + direction * step, lo), hi)
                    if abs(cand - f_now) < 1e-7:           # 碰到频带边：掉头
                        direction = -direction
                        cand = min(max(f_now + direction * step, lo), hi)
                    f_cmd = cand
                    just_moved = True
                    io.event('PO_STEP', frequency_Hz=f_now, score_W=s, step_Hz=step,
                             direction=direction, next_frequency_Hz=f_cmd)
        if not io.finished:
            last = io.control(f_cmd, 1.0)


def noise_filter(C, sigma, seed):
    rng = np.random.default_rng(seed)

    def f(m, kind):
        if not C.valid_measurement(m):
            return m
        g = rng.standard_normal(3)
        return dataclasses.replace(m, p_port_W=m.p_port_W * (1 + sigma * g[0]),
                                   vpp=m.vpp * (1 + sigma * g[1]),
                                   irms=m.irms * (1 + sigma * g[2]))
    return f


def summarize(Mx, cfg, eng, refs):
    per, s = Mx.evaluate(eng.rows, eng.events, cfg, refs)
    rows = eng.rows
    low = sum(r['duration_us'] for r in rows if r['applied_amplitude'] < 0.999) / 1000
    hard = sum(r['duration_us'] for r in rows if r['actual_hard_violation']) / 1000
    pre = [r for r in rows if r.get('pre_guard_sample_here', r['start_us'] == r['action_start_us'])]
    ev = collections.Counter(e['event'] for e in eng.events)
    seg_end = []
    for k in range(len(per)):
        ctl = [r for r in rows if r['segment_index'] == k and r['kind'] == 'CONTROL']
        seg_end.append(dict(frequency_Hz=ctl[-1]['frequency_Hz'] if ctl else None,
                            amplitude=ctl[-1]['applied_amplitude'] if ctl else None,
                            min_amplitude=min(r['applied_amplitude'] for r in ctl) if ctl else None))
    return dict(settled=s['settled_segments'], energy_pct=s['energy_capture_pct'],
                below_full_amplitude_ms=low, actual_hard_violation_ms=hard,
                pre_guard_peak_Vpp=max(r['pre_guard_vport_Vpp'] for r in pre),
                pre_guard_peak_mArms=1e3 * max(r['pre_guard_iport_Arms'] for r in pre),
                per_segment=[r['energy_capture_pct'] for r in per],
                settled_flags=[bool(r['settled']) for r in per],
                first_qualified_ms=[r['first_qualified_sample_ms'] for r in per],
                segment_end=seg_end, events=dict(ev))


def why_table(model, cfg, smap, ids):
    """各场景 98% 软限可行功率窗口、最优点离 900 kHz 多远、停在 900 kHz 拿多少。"""
    grid = np.arange(cfg['frequency_min_Hz'], cfg['frequency_max_Hz'] + 1, 10.0)
    out = {}
    for cid in dict.fromkeys(ids):
        u = model.response(grid, smap[cid], 1.0)
        a = np.minimum.reduce([np.ones_like(grid), cfg['voltage_soft_Vpp'] / u['vport_vpp'],
                               cfg['current_soft_Arms'] / u['iport_irms_A']])
        p = u['p_rm_W'] * a * a
        k = int(np.argmax(p))
        lo = k
        while lo > 0 and p[lo - 1] >= 0.98 * p[k]:
            lo -= 1
        hi = k
        while hi < len(grid) - 1 and p[hi + 1] >= 0.98 * p[k]:
            hi += 1
        i900 = int(np.argmin(np.abs(grid - cfg['initial_frequency_Hz'])))
        out[cid] = dict(optimum_Hz=float(grid[k]), window98_Hz=float(grid[hi] - grid[lo]),
                        stay_at_900k_pct=float(100 * p[i900] / p[k]))
    return out


def use_q(PBm, model, Mx, cfg, base, match, rs, q):
    """在内存里把场景表换成以 Q 为基准重建的那一套，返回场景表、参考与冻结相位目标。"""
    b = model.changed_qm(base, q)
    cases = PBm.registry(model, b, match, rs, qm_scale=q / 800.0)
    smap = {c.case_id: c for c in cases}
    model.scenario_map = lambda sm=smap: dict(sm)
    model.all_scenarios = lambda cs=cases: list(cs)
    refs = Mx.references(cfg)
    tp = float(model.response(cfg['initial_frequency_Hz'], smap['CASE_000_BASELINE'])['phase_deg'][0])
    return smap, refs, tp


def cover_runs(E, C, Mx, cfg, smap, refs, strategies):
    """每条登记项跑「基准 → 该项 → 基准」三段覆盖日程，取目标段（第 1 段）与返回段（第 2 段）。"""
    out = {}
    for cid in smap:
        sched = ['CASE_000_BASELINE', cid, 'CASE_000_BASELINE']
        row = {}
        for name, label, fn in strategies:
            eng = E.Engine(cfg, sched, label, 'COVER_' + cid)
            fn(C.Executor(eng))
            per, s = Mx.evaluate(eng.rows, eng.events, cfg, refs)
            row[name] = dict(target_settled=bool(per[1]['settled']),
                             target_energy=per[1]['energy_capture_pct'],
                             return_settled=bool(per[2]['settled']),
                             return_energy=per[2]['energy_capture_pct'],
                             total_energy=s['energy_capture_pct'])
        out[cid] = row
    return out


def phase_slope(model, cfg, scen):
    f = np.array([cfg['initial_frequency_Hz'] - 100.0, cfg['initial_frequency_Hz'] + 100.0])
    ph = model.response(f, scen)['phase_deg']
    return float((ph[1] - ph[0]) / 200.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, help='统一源目录（current/unified 的副本）')
    ap.add_argument('--candidate', default=None, help='candidate.py 所在目录（可选，用于 v2）')
    ap.add_argument('--out', default=None, help='可选输出目录；拒绝 workspace/ 与 outputs/')
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve()
    out_dir = None
    if args.out:
        out_dir = pathlib.Path(args.out).resolve()
        if {'workspace', 'outputs'} & set(out_dir.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out_dir}')
        out_dir.mkdir(parents=True, exist_ok=True)

    E, C, Mx, model, cfg = PB.build(root)
    CAND = None
    if args.candidate:
        sys.path.insert(0, str(pathlib.Path(args.candidate).resolve()))
        import candidate as CAND                                   # noqa: E402
    original = model.scenario_map()
    base, match, rs = model.BASE_BVD, model.BASE_MATCH, model.BASE_RS
    w = 2 * math.pi * base.fs
    kq = (1 / (w * base.c0)) / base.rm
    ids = cfg['historical_schedule']
    rebuilt = PB.registry(model, base, match, rs)
    assert [c.case_id for c in rebuilt] == list(original)
    assert all(c == original[c.case_id] for c in rebuilt), '重建场景与模块场景表不等'
    print('自证 1 通过：34 条重建场景与 model.scenario_map() 逐字段相等')
    slope800 = phase_slope(model, cfg, original['CASE_000_BASELINE'])

    qs = [('k_eff 0.45', kq / (0.45 ** 2 / (1 - 0.45 ** 2))),
          ('k_eff 0.30', kq / (0.30 ** 2 / (1 - 0.30 ** 2))),
          ('登记基线', 800.0)]
    params = POParams()
    results, why = {}, {}
    for label, q in qs:
        b = model.changed_qm(base, q)
        cases = PB.registry(model, b, match, rs, qm_scale=q / 800.0)
        smap = {c.case_id: c for c in cases}
        model.scenario_map = lambda sm=smap: dict(sm)
        model.all_scenarios = lambda cs=cases: list(cs)
        refs = Mx.references(cfg)
        tp = float(model.response(cfg['initial_frequency_Hz'], smap['CASE_000_BASELINE'])['phase_deg'][0])
        why[label] = dict(q=q, table=why_table(model, cfg, smap, ids))
        slope_q = phase_slope(model, cfg, smap['CASE_000_BASELINE'])
        r_s, r_w = abs(slope800 / slope_q), 800.0 / q
        cfg_v2r = dict(cfg, phase_gain_Hz_per_deg=cfg['phase_gain_Hz_per_deg'] * r_s,
                       phase_probe_offset_Hz=cfg['phase_probe_offset_Hz'] * r_w,
                       phase_max_step_Hz=cfg['phase_max_step_Hz'] * r_w,
                       phase_deadband_deg=cfg['phase_deadband_deg'] * r_w / r_s)
        res = {}

        def run(name, strategy_label, fn, run_cfg=cfg, filt=None):
            eng = E.Engine(run_cfg, ids, strategy_label, 'POWER_PROTO')
            eng.measurement_filter = filt
            fn(C.Executor(eng))
            res[name] = summarize(Mx, cfg, eng, refs)

        run('固定频率', 'FIXED', lambda io: C.run_policy(io, 'FIXED', tp))
        run('正式相位反馈', 'PHASE_FEEDBACK', lambda io: C.run_policy(io, 'PHASE_FEEDBACK', tp))
        if CAND is not None:
            run('v2', 'PHASE_FEEDBACK', lambda io: CAND.run_phase_recovery(io, tp))
            if q != 800.0:
                run('v2 按物理峰重定', 'PHASE_FEEDBACK',
                    lambda io: CAND.run_phase_recovery(io, tp), run_cfg=cfg_v2r)
        run('功率 P&O 第一版(缺陷)', 'POWER_PO', lambda io: run_power_po_v1(io, E, C, params))
        run('功率 P&O', 'POWER_PO', lambda io: run_power_po(io, E, C, params))
        for sigma, seed in ((0.005, 20261015), (0.02, 20261016)):
            run(f'功率 P&O 噪声{sigma*100:.1f}%', 'POWER_PO',
                lambda io: run_power_po(io, E, C, params), filt=noise_filter(C, sigma, seed))
        results[label] = dict(q=q, phase_target_deg=tp, slope_deg_per_Hz=slope_q,
                              v2_retune=dict(slope_ratio=r_s, q_ratio=r_w,
                                             gain_Hz_per_deg=cfg_v2r['phase_gain_Hz_per_deg'],
                                             probe_offset_Hz=cfg_v2r['phase_probe_offset_Hz'],
                                             max_step_Hz=cfg_v2r['phase_max_step_Hz'],
                                             deadband_deg=cfg_v2r['phase_deadband_deg']),
                              strategies=res)
        if q == 800.0:
            for name, key in (('固定频率', 'FIXED'), ('正式相位反馈', 'PHASE_FEEDBACK')):
                n, e = PB.REGISTERED[key]
                assert res[name]['settled'] == n and abs(res[name]['energy_pct'] - e) < 1e-6, (name, res[name])
            if CAND is not None:
                n, e = V2_REGISTERED
                assert res['v2']['settled'] == n and abs(res['v2']['energy_pct'] - e) < 1e-5, res['v2']
            print('自证 2 通过：Q=800 时 FIXED 7/12 73.778340%、PHASE 6/12 57.337359%'
                  + ('、v2 7/12 70.104969%' if CAND is not None else ''))
    # ---- 多种子噪声（12 段日程，主基线）
    q_main = qs[0][1]
    smap, refs, tp = use_q(PB, model, Mx, cfg, base, match, rs, q_main)
    noise_stats = {}
    for sigma in (0.005, 0.02):
        vals = []
        for seed in NOISE_SEEDS:
            eng = E.Engine(cfg, ids, 'POWER_PO', 'POWER_PROTO_NOISE')
            eng.measurement_filter = noise_filter(C, sigma, seed)
            run_power_po(C.Executor(eng), E, C, params)
            _, s = Mx.evaluate(eng.rows, eng.events, cfg, refs)
            vals.append((s['settled_segments'], s['energy_capture_pct']))
        e = np.array([v[1] for v in vals])
        n = np.array([v[0] for v in vals])
        noise_stats[f'{sigma*100:.1f}%'] = dict(seeds=list(NOISE_SEEDS), settled=n.tolist(),
                                                energy_pct=e.tolist(), energy_mean=float(e.mean()),
                                                energy_std=float(e.std(ddof=1)),
                                                energy_min=float(e.min()), energy_max=float(e.max()),
                                                settled_mean=float(n.mean()))

    # ---- 覆盖日程：先在 Q=800 自证，再在主基线比较
    cover = {}
    for label, q in (('登记基线', 800.0), ('k_eff 0.45', q_main)):
        smap, refs, tp = use_q(PB, model, Mx, cfg, base, match, rs, q)
        strategies = [('固定频率', 'FIXED', lambda io: C.run_policy(io, 'FIXED', tp)),
                      ('正式相位反馈', 'PHASE_FEEDBACK', lambda io: C.run_policy(io, 'PHASE_FEEDBACK', tp))]
        if CAND is not None:
            strategies.append(('v2', 'PHASE_FEEDBACK', lambda io: CAND.run_phase_recovery(io, tp)))
        strategies.append(('功率 P&O', 'POWER_PO', lambda io: run_power_po(io, E, C, params)))
        cover[label] = cover_runs(E, C, Mx, cfg, smap, refs, strategies)
        if q == 800.0:
            for name, key in (('固定频率', 'FIXED'), ('正式相位反馈', 'PHASE_FEEDBACK')):
                n_ok = sum(cover[label][c][name]['target_settled'] for c in cover[label])
                e_sum = sum(cover[label][c][name]['target_energy'] for c in cover[label])
                rn, re_ = COVER_REGISTERED[key]
                assert n_ok == rn and abs(e_sum - re_) < 1e-6, (name, n_ok, e_sum, rn, re_)
            print('自证 3 通过：Q=800 时 34 条覆盖日程目标段逐位复现已登记批次 '
                  '(FIXED 18/34、Σ2170.766；PHASE 17/34、Σ2186.719)')
    model.scenario_map = lambda: dict(original)
    model.all_scenarios = lambda: list(original.values())

    print(f'\nP&O 参数（运行前声明）：{dataclasses.asdict(params)}')
    print('\n== 一、为什么峰宽决定「慢」的代价（软限可行功率；100 Hz 级别以 10 Hz 栅格求窗口）')
    uniq = list(dict.fromkeys(ids))
    for label, d in why.items():
        print(f"  {label}（Q={d['q']:.2f}）")
        print(f"    {'场景':<16}{'最优(kHz)':>10}{'离900k':>9}{'98%窗口':>10}{'停900k得%':>11}")
        for cid in uniq:
            t = d['table'][cid]
            print(f"    {cid.replace('CASE_', ''):<16}{t['optimum_Hz']/1e3:>10.2f}"
                  f"{(t['optimum_Hz']-cfg['initial_frequency_Hz'])/1e3:>+8.1f}k"
                  f"{t['window98_Hz']:>9.0f}Hz{t['stay_at_900k_pct']:>11.2f}")

    print('\n== 二、并排比较（12 段日程，正式口径）')
    for label, d in results.items():
        r = d['v2_retune']
        print(f"\n  {label}（Q={d['q']:.2f}；冻结目标处相位斜率 {d['slope_deg_per_Hz']:+.6f} °/Hz）")
        if label != '登记基线' and CAND is not None:
            print(f"    v2 重定：斜率比 {r['slope_ratio']:.1f}、Q 比 {r['q_ratio']:.1f} → 增益 "
                  f"{r['gain_Hz_per_deg']:.0f} Hz/°、探针 ±{r['probe_offset_Hz']:.0f} Hz、"
                  f"限幅 {r['max_step_Hz']:.0f} Hz、死区 {r['deadband_deg']:.4f}°")
        print(f"    {'策略':<18}{'达标':>6}{'能量':>9}{'非满幅ms':>9}{'硬越限ms':>9}"
              f"{'预测峰V':>9}{'预测峰mA':>9}   逐段能量 %")
        for name, s in d['strategies'].items():
            print(f"    {name:<18}{s['settled']:>3}/12{s['energy_pct']:>8.2f}%"
                  f"{s['below_full_amplitude_ms']:>9.0f}{s['actual_hard_violation_ms']:>9.3f}"
                  f"{s['pre_guard_peak_Vpp']:>9.2f}{s['pre_guard_peak_mArms']:>9.4f}   "
                  + ' '.join(f'{v:5.1f}' for v in s['per_segment']))
    print('\n== 三、段末频率 (kHz) / 段末幅度')
    for label in ('k_eff 0.45', '登记基线'):
        d = results[label]
        print(f"  {label}（Q={d['q']:.2f}）  各场景最优 (kHz): "
              + ' '.join(f"{why[label]['table'][c]['optimum_Hz']/1e3:6.1f}" for c in ids))
        for name, s in d['strategies'].items():
            if '噪声' in name:
                continue
            print(f"    {name:<16}" + ' '.join(f"{x['frequency_Hz']/1e3:6.1f}" for x in s['segment_end']))
            print(f"    {'':<16}" + ' '.join(f"{x['amplitude']:6.3f}" for x in s['segment_end']))

    print('\n== 四、P&O 测量噪声：12 段日程、主基线、10 个种子')
    for k, d in noise_stats.items():
        print(f"  σ={k}: 能量 均值 {d['energy_mean']:.2f}% ± {d['energy_std']:.2f}"
              f"（{d['energy_min']:.2f}–{d['energy_max']:.2f}），达标段均值 {d['settled_mean']:.1f}/12"
              f"；逐种子 {' '.join(f'{x:.1f}' for x in d['energy_pct'])}")

    print('\n== 五、31 个去重扰动的覆盖日程（基准 → 扰动 → 基准，各 0.8 s）')
    for label, rows in cover.items():
        uniq = [c for c in rows if c not in COVER_ALIASES]
        names = list(rows[uniq[0]])
        print(f"  {label}（{len(uniq)} 个去重扰动）")
        print(f"    {'策略':<12}{'扰动段达标':>10}{'扰动段能量':>11}{'返回段达标':>10}{'返回段能量':>11}{'三段总能量':>11}"
              f"{'扰动段胜/负固定':>14}")
        for name in names:
            t_ok = sum(rows[c][name]['target_settled'] for c in uniq)
            t_e = np.mean([rows[c][name]['target_energy'] for c in uniq])
            r_ok = sum(rows[c][name]['return_settled'] for c in uniq)
            r_e = np.mean([rows[c][name]['return_energy'] for c in uniq])
            tot = np.mean([rows[c][name]['total_energy'] for c in uniq])
            win = sum(rows[c][name]['target_energy'] > rows[c]['固定频率']['target_energy'] + 0.5 for c in uniq)
            lose = sum(rows[c][name]['target_energy'] < rows[c]['固定频率']['target_energy'] - 0.5 for c in uniq)
            print(f"    {name:<12}{t_ok:>7}/{len(uniq)}{t_e:>10.2f}%{r_ok:>7}/{len(uniq)}{r_e:>10.2f}%{tot:>10.2f}%"
                  f"{win:>8}/{lose}")
        big = [c for c in uniq if rows[c]['固定频率']['target_energy'] < 90]
        if big:
            print(f"    固定频率扰动段 < 90% 的 {len(big)} 个场景（扰动段能量 %，固定/" + '/'.join(names[1:]) + '）：')
            for c in big:
                print(f"      {c.replace('CASE_', ''):<16}" + ' '.join(f"{rows[c][n]['target_energy']:6.1f}" for n in names))

    if out_dir is not None:
        flat = []
        for label, d in results.items():
            for name, s in d['strategies'].items():
                flat.append(dict(baseline=label, Q=d['q'], strategy=name, settled=s['settled'],
                                 energy_pct=s['energy_pct'],
                                 below_full_amplitude_ms=s['below_full_amplitude_ms'],
                                 actual_hard_violation_ms=s['actual_hard_violation_ms'],
                                 pre_guard_peak_Vpp=s['pre_guard_peak_Vpp'],
                                 pre_guard_peak_mArms=s['pre_guard_peak_mArms'],
                                 **{f'seg{i:02d}': v for i, v in enumerate(s['per_segment'])}))
        with (out_dir / 'power_tracking_comparison.csv').open('w', encoding='utf-8-sig', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(flat[0]))
            wr.writeheader()
            wr.writerows(flat)
        (out_dir / 'power_tracking_comparison.json').write_text(json.dumps(dict(
            po_params=dataclasses.asdict(params), schedule=ids, why_slow=why, results=results,
            noise_multi_seed=noise_stats, cover=cover, cover_aliases=COVER_ALIASES,
            registered_batch='UNIFIED_20260923T013352_476445Z_f442bcda'),
            ensure_ascii=False, indent=2, default=float), encoding='utf-8')
        print(f'\n已写入 {out_dir}')


if __name__ == '__main__':
    main()
