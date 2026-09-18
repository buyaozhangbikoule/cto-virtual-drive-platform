#!/usr/bin/env python3
"""复算 review/12 的每一个数字：周期扫频失败的根因与格点公度问题。

只读。本脚本不写入本仓库的任何目录，也不写入被审分支的 outputs/。
它在内存里跑 HISTORICAL_12 / PERIODIC_SCAN，不落盘。

被审对象是独立分支 validation/plan-three-strategy-v1-20260917 里的
workspace/CTO_plan_three_strategy_v1_20260917/，把该目录路径传给 --root。

    python3 review/scan_failure_lattice_study.py --root /path/to/CTO_plan_three_strategy_v1_20260917

输出四节，对应 review/12 的第二、三、四、七、八节。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

SEGMENT_TRIP_CANDIDATES = (
    'CASE_000_BASELINE', 'CASE_C0_P30', 'CASE_RM_P50', 'CASE_FS_M5',
    'CASE_LMATCH_P10', 'CASE_QL_20', 'CASE_COMBINED_HIGH',
    'CASE_LM_P20', 'CASE_CM_P20',
)

PERIOD_SWEEP_US = (400000, 450000, 500000, 550000, 600000, 700000, 800000, 900000, 1000000)


def load(root: Path):
    """把被审分支挂到 sys.path 上并导入它自己的引擎、策略、模型。"""
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import model_v2_1 as model            # noqa: E402
    from engine import Engine             # noqa: E402
    from controllers import Executor, run_policy  # noqa: E402
    cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    return model, Engine, Executor, run_policy, cfg


def run_periodic_scan(Engine, Executor, run_policy, cfg, scan_period_us=None):
    local = copy.deepcopy(cfg)
    if scan_period_us is not None:
        local['scan_period_us'] = scan_period_us
    engine = Engine(local, local['historical_schedule'], 'PERIODIC_SCAN', 'HISTORICAL_12')
    run_policy(Executor(engine), 'PERIODIC_SCAN', 0.0)
    return engine


def section_hard_limit_headroom(model, cfg):
    """第三节：900 kHz、满幅下，哪些场景一上来就越硬限。"""
    print('== 1. 900 kHz 单位幅度响应与硬限余量（hard_old = min(1, Vhard/v, Ihard/i)）')
    print(f"{'场景':<22}{'Vpp':>10}{'Arms':>13}{'hard_old':>10}  old_a=1.0")
    cases = model.scenario_map()
    tripping = []
    for name in SEGMENT_TRIP_CANDIDATES:
        q = model.response(float(cfg['initial_frequency_Hz']), cases[name])
        v, i = float(q['vport_vpp'][0]), float(q['iport_irms_A'][0])
        hard = min(1.0, cfg['voltage_hard_Vpp'] / v, cfg['current_hard_Arms'] / i)
        trip = 1.0 > hard + 1e-12
        if trip:
            tripping.append(name)
        print(f'{name:<22}{v:10.3f}{i:13.4e}{hard:10.4f}  {"跳闸" if trip else "正常"}')
    print(f'  会跳闸的场景：{tripping}')
    return tripping


def section_baseline_failure(Engine, Executor, run_policy, cfg):
    """第二节：分支自带参数下那唯一一次失败的完整时间线。"""
    print('\n== 2. 分支自带参数（scan_period 500 ms）下的失败时间线')
    engine = run_periodic_scan(Engine, Executor, run_policy, cfg)
    fails = [e for e in engine.events if e['event'] == 'SCAN_FAILURE']
    print(f'  SCAN_FAILURE 共 {len(fails)} 条')
    for e in fails:
        seg = e['time_us'] // cfg['segment_us']
        print(f"  t={e['time_us']} us  段 {seg} = {cfg['historical_schedule'][seg]}  原因 {e['reason']}")
    lo = min(e['time_us'] for e in fails) - 2000 if fails else 0
    hi = lo + 340000
    print(f'  ---- 事件流 [{lo}, {hi}] ----')
    for e in engine.events:
        if lo <= e['time_us'] <= hi:
            rest = {k: v for k, v in e.items()
                    if k not in ('time_us', 'event', 'strategy', 'suite', 'action_id')}
            print(f"  {e['time_us']:>9} {e['event']:<28} {rest}")
    print('  ---- 执行行（SCAN_POINT 只报条数）----')
    points = 0
    for r in engine.rows:
        if not lo <= r['start_us'] <= hi:
            continue
        if r['kind'] == 'SCAN_POINT':
            points += 1
            continue
        if r['kind'] == 'CONTROL' and r['start_us'] % 100000:
            continue
        print(f"  {r['start_us']:>9} {r['kind']:<24} {r['case_id']:<18} "
              f"amp={r['applied_amplitude']:<6.4g} {r['protection_state']:<10} "
              f"Vpp={r['vport_Vpp']:<9.4f} valid={r['measurement_valid']}")
    print(f'  窗口内 SCAN_POINT 共 {points} 个，全部属于第二次尝试')
    return engine


def section_cross_strategy(Engine, Executor, run_policy, cfg):
    """第四节：三个策略的硬跳闸时刻对照，证明 8.0 s 不是扫描独有的。"""
    print('\n== 3. 三策略硬跳闸时刻对照')
    for strategy in ('FIXED', 'PERIODIC_SCAN', 'PHASE_FEEDBACK'):
        engine = Engine(copy.deepcopy(cfg), cfg['historical_schedule'], strategy, 'HISTORICAL_12')
        run_policy(Executor(engine), strategy, 0.0)
        trips = [(e['time_us'], e.get('kind')) for e in engine.events
                 if e['event'] == 'OBSERVED_HARD_TRIP']
        print(f'  {strategy:<16} {len(trips)} 次: ' +
              ' | '.join(f'{t} {k}' for t, k in trips))


def section_period_sweep(Engine, Executor, run_policy, cfg):
    """第七节：失败数对扫描周期的敏感性。其余参数一律不动。"""
    print('\n== 4. 扫描周期敏感性（其余参数不变）')
    print(f"{'周期(ms)':>10}{'成功':>6}{'失败':>6}{'锁定保持行':>12}  失败明细")
    for period in PERIOD_SWEEP_US:
        engine = run_periodic_scan(Engine, Executor, run_policy, cfg, period)
        ok = sum(1 for e in engine.events if e['event'] == 'SCAN_SUCCESS')
        fails = [(e['time_us'], e['reason']) for e in engine.events
                 if e['event'] == 'SCAN_FAILURE']
        latched = sum(1 for r in engine.rows if r['kind'] == 'FAILED_SCAN_LATCHED_HOLD')
        detail = '; '.join(f'{t/1e6:.4f}s 段{t//cfg["segment_us"]} {why}' for t, why in fails)
        print(f'{period/1000:10.0f}{ok:6d}{len(fails):6d}{latched:12d}  {detail}')


def section_straddle(Engine, Executor, run_policy, cfg):
    """第八节：跨段扫描导致第三级边缘行走。"""
    print('\n== 5. 跨段扫描与第三级边缘行走')
    for period, window in ((450000, (3100000, 3500000)), (550000, (7100000, 7500000))):
        engine = run_periodic_scan(Engine, Executor, run_policy, cfg, period)
        print(f'  ---- scan_period {period/1000:.0f} ms，窗口 {window} ----')
        for e in engine.events:
            if window[0] <= e['time_us'] <= window[1] and e['event'].startswith('SCAN'):
                rest = {k: v for k, v in e.items()
                        if k not in ('time_us', 'event', 'strategy', 'suite')}
                print(f"    {e['time_us']:>9} {e['event']:<24} {rest}")
        seen: dict[str, list[int]] = {}
        for r in engine.rows:
            if window[0] <= r['start_us'] <= window[1] and r['kind'].startswith('SCAN'):
                seen.setdefault(r['case_id'], []).append(r['start_us'])
        for case_id, times in seen.items():
            print(f'    扫描点落在 {case_id}: n={len(times)}  {min(times)}..{max(times)}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', required=True,
                        help='被审分支的 CTO_plan_three_strategy_v1_20260917 目录')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not (root / 'config.json').is_file():
        print(f'找不到 {root}/config.json', file=sys.stderr)
        return 2
    model, Engine, Executor, run_policy, cfg = load(root)
    print(f'被审目录 {root}')
    print(f"scan_period_us={cfg['scan_period_us']}  segment_us={cfg['segment_us']}  "
          f"gcd 与 lcm 见 review/12 第四节")
    section_hard_limit_headroom(model, cfg)
    section_baseline_failure(Engine, Executor, run_policy, cfg)
    section_cross_strategy(Engine, Executor, run_policy, cfg)
    section_period_sweep(Engine, Executor, run_policy, cfg)
    section_straddle(Engine, Executor, run_policy, cfg)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
