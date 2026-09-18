#!/usr/bin/env python3
"""扫描失败分类补丁的前后对照，覆盖多个扫描周期与多个释放相位。

只读。在内存里跑 HISTORICAL_12 / PERIODIC_SCAN，不落盘，不写任何实现目录。

用法（两个实现目录都要给，各自是一份完整的 plan-three-strategy 实现）：

    python3 review/scan_taxonomy_study.py --baseline <原分支目录> --patched <打补丁后的目录>

单独看一个实现：

    python3 review/scan_taxonomy_study.py --root <目录>

审核报告 4.1 指出：整数微秒时钟上任意两个正整数周期都有公倍数，
所以不存在真正"不可公度"的扫描周期，只能做相位覆盖。本脚本因此不报单点，
而是报 (周期 × 相位) 网格上的分布与最差值。

审核报告 4.2 指出上一版复算脚本把相位目标传成了 0。本脚本一律使用
run_unified.py 的冻结口径：BASELINE 在 900 kHz 的 arg(V_input/I_source)。
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

PERIODS_US = (400000, 450000, 500000, 550000, 600000, 700000, 800000)
OFFSET_STEP_US = 100000
CLASSES = ('search', 'preemption', 'measurement', 'nonstationary')


# --------------------------------------------------------------------------
# 单个实现的运行（在子进程里跑，避免两份同名模块互相污染 sys.modules）
# --------------------------------------------------------------------------
def collect(root: Path) -> dict:
    """在 root 这份实现里跑完整网格，返回可 JSON 化的结果。"""
    import copy
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import model_v2_1 as model
    from engine import Engine, valid_measurement
    from controllers import Executor, STRATEGIES, scan, phase_update, run_policy
    from metrics import evaluate, references

    cfg0 = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    cases = model.scenario_map()
    refs = references(cfg0)
    # 冻结口径的相位目标，与 run_unified.py 一致。周期扫频不用它，
    # 但三策略共用一个入口，传错会让相位闭环的数值对不上。
    target_phase = float(model.response(cfg0['initial_frequency_Hz'],
                                        cases['CASE_000_BASELINE'])['phase_deg'][0])

    def next_release(t, offset, period):
        return offset if t < offset else offset + ((t - offset) // period + 1) * period

    def policy_with_offset(io, strategy, phase, offset, period):
        """原 run_policy 的逐行副本，只改两个释放时刻表达式。

        offset=0 时必须与原函数逐位一致，调用方会断言这一点。
        """
        from controllers import ScanBudget as _B          # 打补丁后的实现
        cfg = io.cfg
        strategy = 'PERIODIC_SCAN'
        target = float(cfg['initial_frequency_Hz'])
        next_scan = next_release(0, offset, period)
        retry = _B(cfg)
        last = None
        failed_episode = False
        while not io.finished:
            if strategy == 'PERIODIC_SCAN' and retry.exhausted:
                io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_LATCHED_HOLD')
                continue
            if strategy == 'PERIODIC_SCAN' and failed_episode and not retry.can_start(io.time):
                last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_RETRY_WAIT')
                continue
            scan_due = strategy == 'PERIODIC_SCAN' and (failed_episode or io.time >= next_scan)
            ready = (last is not None and valid_measurement(last)
                     and last.state == 'NORMAL' and not last.frozen)
            if scan_due and ready and retry.can_start(io.time):
                retry.start(io.time)
                io.event('SCAN_ATTEMPT_START', attempt=retry.attempts, trusted_frequency_Hz=target)
                result = scan(io, target)
                if result.ok:
                    target = float(result.frequency_Hz)
                    io.event('SCAN_SUCCESS', frequency_Hz=target, band_edge=result.band_edge)
                    retry.success()
                    failed_episode = False
                    next_scan = next_release(io.time, offset, period)
                else:
                    budget_class = retry.classify(result.status)
                    if budget_class is None:
                        io.event('SCAN_TRUNCATED_BY_RUN_END', reason=result.reason,
                                 status=result.status, trusted_frequency_unchanged_Hz=target)
                        continue
                    retry.fail(budget_class, io.time)
                    failed_episode = True
                    io.event('SCAN_FAILURE', reason=result.reason, status=result.status,
                             budget_class=budget_class,
                             trusted_frequency_unchanged_Hz=target,
                             episode_failures_in_class=retry.episode[budget_class],
                             class_limit=retry.limit[budget_class],
                             total_failures=retry.total_failures,
                             total_search=retry.total['search'],
                             total_preemption=retry.total['preemption'],
                             total_measurement=retry.total['measurement'],
                             total_nonstationary=retry.total['nonstationary'],
                             retry_not_before_us=retry.not_before)
                    if retry.exhausted:
                        io.event('SCAN_RETRIES_EXHAUSTED', budget_class=retry.exhausted_class)
                    if not io.finished:
                        last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_ROLLBACK')
                    continue
            if not io.finished:
                last = io.control(target, cfg['scan_amplitude'] if failed_episode else 1.)

    patched = hasattr(__import__('controllers'), 'ScanBudget')

    def one(period, offset):
        cfg = copy.deepcopy(cfg0)
        cfg['scan_period_us'] = period
        eng = Engine(cfg, cfg['historical_schedule'], 'PERIODIC_SCAN', 'HISTORICAL_12')
        io = Executor(eng)
        if offset == 0:
            run_policy(io, 'PERIODIC_SCAN', target_phase)
        elif patched:
            policy_with_offset(io, 'PERIODIC_SCAN', target_phase, offset, period)
        else:
            return None            # 未打补丁的实现只跑 offset=0，不改它的代码
        per, summary = evaluate(eng.rows, eng.events, cfg, refs)
        starts = [e['time_us'] for e in eng.events if e['event'] == 'SCAN_ATTEMPT_START']
        wasted = []
        classes = {k: 0 for k in CLASSES}
        reasons = {}
        for e in eng.events:
            if e['event'] != 'SCAN_FAILURE':
                continue
            classes[e.get('budget_class', 'search')] += 1
            reasons[e['reason']] = reasons.get(e['reason'], 0) + 1
            prior = [s for s in starts if s <= e['time_us']]
            if prior:
                wasted.append(e['time_us'] - prior[-1])
        return dict(period_us=period, offset_us=offset,
                    settled=summary['settled_segments'],
                    capture_pct=summary['energy_capture_pct'],
                    successes=sum(1 for e in eng.events if e['event'] == 'SCAN_SUCCESS'),
                    failures=summary['scan_failures'], classes=classes, reasons=reasons,
                    wasted_us=wasted,
                    nonstationary_detected=sum(1 for e in eng.events
                                               if e['event'] == 'SCAN_NONSTATIONARY_DETECTED'),
                    coarse_fallbacks=sum(1 for e in eng.events
                                         if e['event'] == 'SCAN_COARSE_FALLBACK'),
                    latched_rows=sum(1 for r in eng.rows
                                     if r['kind'] == 'FAILED_SCAN_LATCHED_HOLD'))

    # offset=0 一致性断言：带偏移的副本在零偏移下必须复现原程序。
    if patched:
        a = Engine(copy.deepcopy(cfg0), cfg0['historical_schedule'], 'PERIODIC_SCAN', 'CHK')
        run_policy(Executor(a), 'PERIODIC_SCAN', target_phase)
        b = Engine(copy.deepcopy(cfg0), cfg0['historical_schedule'], 'PERIODIC_SCAN', 'CHK')
        policy_with_offset(Executor(b), 'PERIODIC_SCAN', target_phase, 0,
                           cfg0['scan_period_us'])
        assert a.rows == b.rows and a.events == b.events, \
            'zero-offset copy diverges from run_policy; the grid would be meaningless'

    grid = []
    for period in PERIODS_US:
        for offset in range(0, period, OFFSET_STEP_US):
            row = one(period, offset)
            if row is not None:
                grid.append(row)
    return dict(root=str(root), patched=patched, target_phase_deg=target_phase, grid=grid)


# --------------------------------------------------------------------------
# 报告
# --------------------------------------------------------------------------
def summarise(tag: str, data: dict) -> None:
    grid = data['grid']
    print(f"\n### {tag}  ({'含分类补丁' if data['patched'] else '原实现'})  "
          f"相位目标 {data['target_phase_deg']:.9f} deg，{len(grid)} 组")
    print(f"  {'周期ms':>7}{'相位ms':>7}{'达标':>5}{'能量%':>9}{'失败':>5}"
          f"{'搜索':>5}{'抢占':>5}{'数据':>5}{'非平稳':>7}{'回退':>5}{'锁存行':>7}")
    for r in grid:
        c = r['classes']
        print(f"  {r['period_us']/1000:>7.0f}{r['offset_us']/1000:>7.0f}{r['settled']:>5}"
              f"{r['capture_pct']:>9.2f}{r['failures']:>5}{c['search']:>5}{c['preemption']:>5}"
              f"{c['measurement']:>5}{c['nonstationary']:>7}{r['coarse_fallbacks']:>5}"
              f"{r['latched_rows']:>7}")
    totals = {k: sum(r['classes'][k] for r in grid) for k in CLASSES}
    settled = [r['settled'] for r in grid]
    capture = [r['capture_pct'] for r in grid]
    print(f"  合计失败 {sum(totals.values())}：搜索 {totals['search']}，抢占 {totals['preemption']}，"
          f"数据 {totals['measurement']}，非平稳 {totals['nonstationary']}")
    print(f"  达标段 最差 {min(settled)} / 中位 {statistics.median(settled):.1f} / 最好 {max(settled)}；"
          f"能量 最差 {min(capture):.2f}% / 中位 {statistics.median(capture):.2f}% / 最好 {max(capture):.2f}%")
    wasted = [w for r in grid for w in r['wasted_us']]
    if wasted:
        print(f"  失败尝试耗时 {min(wasted)/1000:.1f} – {max(wasted)/1000:.1f} ms，"
              f"中位 {statistics.median(wasted)/1000:.1f} ms，合计 {sum(wasted)/1000:.1f} ms")
    else:
        print('  没有失败尝试')
    reasons = {}
    for r in grid:
        for k, v in r['reasons'].items():
            reasons[k] = reasons.get(k, 0)+v
    if reasons:
        print('  失败原因分布：' + '，'.join(f'{k} ×{v}' for k, v in sorted(reasons.items())))


def compare(base: dict, new: dict) -> None:
    print('\n### 前后对照（仅 offset=0，两侧都有的组）')
    bykey = {(r['period_us'], r['offset_us']): r for r in base['grid']}
    print(f"  {'周期ms':>7}{'达标 原→新':>14}{'能量% 原→新':>20}{'失败 原→新':>14}"
          f"{'失败尝试耗时 原→新 (ms)':>26}")
    for r in new['grid']:
        b = bykey.get((r['period_us'], r['offset_us']))
        if b is None:
            continue
        bw = sum(b['wasted_us'])/1000
        nw = sum(r['wasted_us'])/1000
        print(f"  {r['period_us']/1000:>7.0f}"
              f"{b['settled']:>7}→{r['settled']:<6}"
              f"{b['capture_pct']:>10.2f}→{r['capture_pct']:<9.2f}"
              f"{b['failures']:>7}→{r['failures']:<6}"
              f"{bw:>14.1f}→{nw:<10.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', help='单个实现目录')
    ap.add_argument('--baseline', help='原实现目录')
    ap.add_argument('--patched', help='打补丁后的实现目录')
    ap.add_argument('--emit-json', action='store_true', help='内部使用：子进程输出 JSON')
    args = ap.parse_args()

    if args.emit_json:
        print(json.dumps(collect(Path(args.root).resolve())))
        return 0

    def child(root: str) -> dict:
        out = subprocess.run([sys.executable, __file__, '--root', root, '--emit-json'],
                             capture_output=True, text=True)
        if out.returncode:
            sys.stderr.write(out.stderr)
            raise SystemExit(f'子进程失败：{root}')
        return json.loads(out.stdout)

    if args.root and not (args.baseline or args.patched):
        summarise(args.root, child(args.root))
        return 0
    if not (args.baseline and args.patched):
        ap.error('要么给 --root，要么同时给 --baseline 与 --patched')
    base, new = child(args.baseline), child(args.patched)
    summarise('原实现', base)
    summarise('分类补丁后', new)
    compare(base, new)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
