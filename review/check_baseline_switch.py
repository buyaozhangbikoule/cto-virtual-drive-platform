#!/usr/bin/env python3
"""换主基线补丁的独立核对：补丁不改旧行为、门控移植等于 v2、新批次等于 review/24 第十五节。

〔2026-10-16 起作为 55fbe6e 组合补丁的核对记录保留；该补丁已作废，拆分后的三个补丁用
review/check_split_patches.py 核对（它复用本文件的比较函数），见 review/26。〕

    python review/check_baseline_switch.py --orig <原 current/unified> --patched <补丁后 current/unified>
        --registered <旧登记批次目录> --new-batch <补丁树上正式运行器产出的新批次目录>
        --work <临时目录> [--candidate <v2 candidate.py 所在目录>] [--out <结果目录>]

O 原源码本机重跑：未打补丁的原目录在本机用同一入口跑完整批次，作为 A、B 的逐字节对照。旧登记批次
  是 Windows/Python 3.12/NumPy 2.2.4 产出的；本机与它的差别单独登记并限定：执行记录只允许
  phase_input_deg、phase_port_deg 末位不同（相对差 < 1e-14，atan2 库实现差异），逐段表只允许
  功率标准差两列末位不同（< 1e-12，pow 库实现差异），事件日志解析后数值相同（Windows 写文件
  用 CRLF），综合表与 12 段表逐字相同。
A 旧参数＋门控关：把补丁树复制一份，换回原 stage2 文件（设计文件补写 "Qm": 800.0）和旧电流限值
  5.5/6.0 mA、关门控，用平台自己的 run_unified.py --suite all 跑完整批次。105 条执行记录和事件日志
  必须与 O 逐字节相同，四张指标表去掉 batch_id 列后逐字相同。
B 旧参数＋门控开：同上但开门控。FIXED、PERIODIC_SCAN 逐字节等于 O；PHASE_FEEDBACK 的 12 段
  等于 v2 的登记值 7/12、70.104969%。给了 --candidate 时，再在原目录里直接运行 v2 候选的
  run_phase_recovery 全部 35 个日程，执行记录与事件日志必须逐字节相同。
C 新批次：FIXED 与 PHASE_FEEDBACK（门控开）的 12 段逐段、34 条覆盖日程逐项，等于
  review/results/design_current_20261015/design_current_study.json 中“3 mA、按需求 4.5/5.0 mA”的
  “固定频率”与“v2”（浮点完全相等）。
D 消融：新基线、门控关，跑完整批次。FIXED、PERIODIC_SCAN 必须与 C 逐字节相同；相位反馈逐条日程比较
  验收、电能、保护前峰值与硬跳闸，回答 v2 当初没有升格的那条顾虑（保护前电流峰值是否上升）。

只读 --orig、--patched 与两个批次；只写 --work 与 --out。任何一项不符即以非零码退出。
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import physical_baseline_control_check as PB    # noqa: E402
import power_tracking_prototype as PT           # noqa: E402

DESIGN_FILE = 'stage2_匹配设计参数.json'
CAL_FILE = 'stage2_控制源幅度校准.json'
TABLES = ('per_segment_metrics.csv', 'formal_three_strategy_summary.csv',
          'historical_12_three_strategy_table.csv', 'registered34_target_segment_metrics.csv')
REFERENCE = HERE / 'results' / 'design_current_20261015' / 'design_current_study.json'
REFERENCE_KEY = '3mA | 按需求 4.5/5.0 mA'
STRATEGIES = ('FIXED', 'PERIODIC_SCAN', 'PHASE_FEEDBACK')


def read_rows(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return [{k: v for k, v in r.items() if k != 'batch_id'} for r in csv.DictReader(f)]


def read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def proof_tree(patched, orig, dest, *, old_params, gate):
    shutil.copytree(patched, dest, ignore=shutil.ignore_patterns('outputs', 'audits', '__pycache__'))
    if old_params:
        for name in (DESIGN_FILE, CAL_FILE):
            shutil.copy2(orig / 'stage2_matching' / name, dest / 'stage2_matching' / name)
        design = read_json(dest / 'stage2_matching' / DESIGN_FILE)
        if 'Qm' in design['bvd']:
            raise SystemExit('--orig 不是原冻结基线')
        design['bvd']['Qm'] = 800.0                        # 原模型里写死的值
        (dest / 'stage2_matching' / DESIGN_FILE).write_text(
            json.dumps(design, ensure_ascii=False, indent=2), encoding='utf-8')
    cfg = read_json(dest / 'config.json')
    if old_params:
        old = read_json(orig / 'config.json')
        cfg['current_soft_Arms'], cfg['current_hard_Arms'] = old['current_soft_Arms'], old['current_hard_Arms']
    cfg['phase_centre_recovery_gate'] = gate
    (dest / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    return dest


def run_formal(tree):
    """平台自己的入口：先跑行为测试，失败即中止；成功时打印唯一的 OUTPUT 行。"""
    p = subprocess.run([sys.executable, '-B', '-X', 'utf8', 'run_unified.py', '--suite', 'all'],
                       cwd=tree, capture_output=True, text=True, encoding='utf-8')
    if p.returncode != 0:
        raise SystemExit(f'{tree} 正式运行失败：\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}')
    out = [line[7:] for line in p.stdout.splitlines() if line.startswith('OUTPUT ')]
    tests = [line for line in p.stdout.splitlines() if line.startswith('Ran ')]
    if len(out) != 1:
        raise SystemExit('必须收到唯一的 OUTPUT 路径')
    return pathlib.Path(out[0]), tests[-1] if tests else ''


def same_bytes(a, b, pattern, strategies=STRATEGIES):
    names = sorted(p.name for p in (a / pattern).iterdir()
                   if any(p.stem.endswith('_' + s) for s in strategies))
    bad = [n for n in names if (a / pattern / n).read_bytes() != (b / pattern / n).read_bytes()]
    return len(names), bad


def relative(a, b):
    try:
        x, y = float(a), float(b)
    except ValueError:
        return float('inf')
    return abs(x - y) / max(abs(x), 1e-300)


def walk(p, q, worst):
    """解析后的事件逐项比较：结构与非浮点值必须相同，浮点值返回最大相对差。"""
    if isinstance(p, dict):
        if p.keys() != q.keys():
            raise AssertionError('keys')
        return max([walk(p[k], q[k], worst) for k in p] + [worst])
    if isinstance(p, list):
        if len(p) != len(q):
            raise AssertionError('length')
        return max([walk(u, v, worst) for u, v in zip(p, q)] + [worst])
    if isinstance(p, float) and isinstance(q, float):
        return max(worst, abs(p - q) / max(abs(p), 1e-300))
    if p != q:
        raise AssertionError((p, q))
    return worst


def characterize(rows_a, rows_b):
    cols, worst = collections.Counter(), 0.0
    if len(rows_a) != len(rows_b):
        return dict(row_count_mismatch=True)
    for r, s in zip(rows_a, rows_b):
        for k in r:
            if r[k] != s[k]:
                cols[k] += 1
                worst = max(worst, relative(r[k], s[k]))
    return dict(differing_columns=dict(cols), max_relative_difference=worst)


ENV_EXECUTION_COLUMNS = {'phase_input_deg', 'phase_port_deg'}
ENV_TABLE_COLUMNS = {'whole_segment_power_std_W', 'whole_segment_power_cv_pct'}


def compare_platforms(local, registered):
    """本机重跑的原源码 vs 旧登记批次：只允许已登记的库实现末位差。"""
    cols, worst = collections.Counter(), 0.0
    for f in sorted((registered / 'executions').glob('*.csv')):
        c = characterize(read_rows(f), read_rows(local / 'executions' / f.name))
        if c.get('row_count_mismatch'):
            return dict(ok=False, reason='row count ' + f.name)
        cols.update(c['differing_columns'])
        worst = max(worst, c['max_relative_difference'])
    out = dict(executions=dict(differing_cells=dict(cols), max_relative_difference=worst))
    ev_worst, crlf, structural = 0.0, 0, []
    for f in sorted((registered / 'events').glob('*.json')):
        raw = f.read_bytes()
        crlf += b'\r\n' in raw
        try:
            ev_worst = walk(json.loads(raw), read_json(local / 'events' / f.name), ev_worst)
        except AssertionError:
            structural.append(f.name)
    out['events'] = dict(files_with_crlf_in_registered=crlf, structural_differences=structural,
                         max_relative_difference=ev_worst)
    for name in TABLES:
        out[name] = characterize(read_rows(registered / name), read_rows(local / name))
    out['ok'] = (set(cols) <= ENV_EXECUTION_COLUMNS and worst < 1e-14 and not structural and ev_worst < 1e-14
                 and all(not out[n].get('row_count_mismatch') for n in TABLES)
                 and not out['formal_three_strategy_summary.csv']['differing_columns']
                 and not out['historical_12_three_strategy_table.csv']['differing_columns']
                 and all(set(out[n]['differing_columns']) <= ENV_TABLE_COLUMNS
                         and out[n]['max_relative_difference'] < 1e-12
                         for n in ('per_segment_metrics.csv', 'registered34_target_segment_metrics.csv')))
    return out


def compare_registered(batch, registered, strategies=STRATEGIES):
    out = {}
    for pattern in ('executions', 'events'):
        n, bad = same_bytes(registered, batch, pattern, strategies)
        out[pattern] = dict(files=n, mismatches=bad)
    for name in TABLES:
        mine = [r for r in read_rows(batch / name) if r['strategy'] in strategies]
        ref = [r for r in read_rows(registered / name) if r['strategy'] in strategies]
        out[name] = dict(rows=len(ref), identical=mine == ref)
    for name in ('reference_optima.json', 'phase_calibration.json', 'schedules.json'):
        out[name] = dict(identical=read_json(batch / name) == read_json(registered / name))
    a = {r['case_id']: r for r in read_json(batch / 'scenario_registry.json')}
    b = {r['case_id']: r for r in read_json(registered / 'scenario_registry.json')}
    text_only = sorted(c for c in b if a[c] != b[c]
                       and {k: v for k, v in a[c].items() if k not in ('level', 'description')}
                       == {k: v for k, v in b[c].items() if k not in ('level', 'description')})
    physics = sorted(c for c in b if {k: v for k, v in a[c].items() if k not in ('level', 'description')}
                     != {k: v for k, v in b[c].items() if k not in ('level', 'description')})
    out['scenario_registry.json'] = dict(same_ids=set(a) == set(b), text_only_differences=text_only,
                                         physics_differences=physics)
    return out


def all_identical(result):
    ok = all(not v['mismatches'] for k, v in result.items() if k in ('executions', 'events'))
    ok &= all(v['identical'] for k, v in result.items() if k.endswith(('.csv', 'optima.json',
                                                                         'calibration.json', 'schedules.json')))
    reg = result['scenario_registry.json']
    return ok and reg['same_ids'] and not reg['physics_differences']


def candidate_replay(orig, batch, candidate):
    """在原目录里直接运行 v2 候选，逐字节比较补丁批次的 PHASE_FEEDBACK 执行记录与事件。"""
    E, C, Mx, model, cfg = PB.build(orig)
    sys.path.insert(0, str(candidate))
    import candidate as CAND                                   # noqa: E402
    phase = read_json(batch / 'phase_calibration.json')['target_deg']
    schedules = read_json(batch / 'schedules.json')
    bad = []
    for suite, segs in schedules.items():
        eng = E.Engine(cfg, [s['case_id'] for s in segs], 'PHASE_FEEDBACK', suite)
        CAND.run_phase_recovery(C.Executor(eng), phase)
        buf = io.StringIO(newline='')
        w = csv.DictWriter(buf, fieldnames=list(eng.rows[0]))
        w.writeheader()
        w.writerows(eng.rows)
        rows = ('﻿' + buf.getvalue()).encode('utf-8')
        events = json.dumps(eng.events, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if rows != (batch / 'executions' / f'{suite}_PHASE_FEEDBACK.csv').read_bytes():
            bad.append(suite + ':executions')
        if events != (batch / 'events' / f'{suite}_PHASE_FEEDBACK.json').read_bytes():
            bad.append(suite + ':events')
    return dict(schedules=len(schedules), mismatches=bad)


def segments(batch):
    out = {}
    for r in read_rows(batch / 'per_segment_metrics.csv'):
        out[(r['suite'], r['strategy'], int(r['segment_index']))] = r
    return out


def summaries(batch):
    return {(r['suite'], r['strategy']): r for r in read_rows(batch / 'formal_three_strategy_summary.csv')}


def check_against_study(batch):
    ref = read_json(REFERENCE)['results'][REFERENCE_KEY]
    seg, summ = segments(batch), summaries(batch)
    bad = []
    for strategy, name in (('FIXED', '固定频率'), ('PHASE_FEEDBACK', 'v2')):
        t = ref['twelve'][name]
        s = summ[('HISTORICAL_12', strategy)]
        if int(s['settled_segments']) != t['settled'] or float(s['energy_capture_pct']) != t['energy_pct']:
            bad.append(f'HISTORICAL_12/{strategy}')
        for i, (e, flag) in enumerate(zip(t['per_segment'], t['settled_flags'])):
            r = seg[('HISTORICAL_12', strategy, i)]
            if float(r['energy_capture_pct']) != e or (r['settled'] == 'True') != flag:
                bad.append(f'HISTORICAL_12/{strategy}/{i}')
        for cid, row in ref['cover'].items():
            suite = 'COVER_' + cid
            want = row[name]
            got = dict(target_settled=seg[(suite, strategy, 1)]['settled'] == 'True',
                       target_energy=float(seg[(suite, strategy, 1)]['energy_capture_pct']),
                       return_settled=seg[(suite, strategy, 2)]['settled'] == 'True',
                       return_energy=float(seg[(suite, strategy, 2)]['energy_capture_pct']),
                       total_energy=float(summ[(suite, strategy)]['energy_capture_pct']))
            if any(got[k] != want[k] for k in got):
                bad.append(f'{suite}/{strategy}')
    return dict(reference=f'{REFERENCE.relative_to(HERE.parent)} [{REFERENCE_KEY}]',
                checked=['固定频率→FIXED', 'v2→PHASE_FEEDBACK（门控开）'], mismatches=bad)


def strategy_table(batch, strategy):
    seg, summ = segments(batch), summaries(batch)
    h = summ[('HISTORICAL_12', strategy)]
    cover = {s[6:]: seg[(s, strategy, 1)] for (s, st) in summ if st == strategy and s.startswith('COVER_')}
    unique = {c: r for c, r in cover.items() if c not in PT.COVER_ALIASES}
    return dict(h12_settled=int(h['settled_segments']), h12_energy_pct=float(h['energy_capture_pct']),
                h12_peak_pre_guard_V=float(h['peak_pre_guard_voltage_Vpp']),
                h12_peak_current_mA=float(h['peak_current_mArms']),
                h12_hard_violation_ms=float(h['actual_hard_violation_duration_ms']),
                cover_target_settled=sum(r['settled'] == 'True' for r in cover.values()),
                cover_unique_target_settled=sum(r['settled'] == 'True' for r in unique.values()),
                cover_unique_target_energy_sum=sum(float(r['energy_capture_pct']) for r in unique.values()),
                cover_count=len(cover), cover_unique_count=len(unique))


def ablation(gate_on, gate_off):
    on, off = segments(gate_on), segments(gate_off)
    son, soff = summaries(gate_on), summaries(gate_off)
    rows = []
    for (suite, strategy) in sorted(son):
        if strategy != 'PHASE_FEEDBACK':
            continue
        idx = 1 if suite.startswith('COVER_') else None
        if idx is None:
            a, b = son[(suite, strategy)], soff[(suite, strategy)]
            settled = (int(a['settled_segments']), int(b['settled_segments']))
            pre_i = (float(a['peak_current_mArms']), float(b['peak_current_mArms']))
            pre_v = (float(a['peak_voltage_Vpp']), float(b['peak_voltage_Vpp']))
            trig = (int(a['protection_trigger_events']), int(b['protection_trigger_events']))
        else:
            a, b = on[(suite, strategy, idx)], off[(suite, strategy, idx)]
            settled = (a['settled'] == 'True', b['settled'] == 'True')
            pre_i = (float(a['peak_pre_guard_current_mArms']), float(b['peak_pre_guard_current_mArms']))
            pre_v = (float(a['peak_pre_guard_voltage_Vpp']), float(b['peak_pre_guard_voltage_Vpp']))
            trig = (int(a['protection_trigger_events']), int(b['protection_trigger_events']))
        rows.append(dict(suite=suite, settled_on=settled[0], settled_off=settled[1],
                         target_energy_on=float(a['energy_capture_pct']),
                         target_energy_off=float(b['energy_capture_pct']),
                         total_energy_on=float(son[(suite, strategy)]['energy_capture_pct']),
                         total_energy_off=float(soff[(suite, strategy)]['energy_capture_pct']),
                         pre_guard_current_mA_on=pre_i[0], pre_guard_current_mA_off=pre_i[1],
                         pre_guard_voltage_Vpp_on=pre_v[0], pre_guard_voltage_Vpp_off=pre_v[1],
                         trial_peak_current_mA_on=float(son[(suite, strategy)]['peak_current_mArms']),
                         trial_peak_current_mA_off=float(soff[(suite, strategy)]['peak_current_mArms']),
                         trial_peak_voltage_Vpp_on=float(son[(suite, strategy)]['peak_voltage_Vpp']),
                         trial_peak_voltage_Vpp_off=float(soff[(suite, strategy)]['peak_voltage_Vpp']),
                         protection_triggers_on=trig[0], protection_triggers_off=trig[1]))
    cover = [r for r in rows if r['suite'].startswith('COVER_') and r['suite'][6:] not in PT.COVER_ALIASES]
    tol = 1e-9
    summary = dict(
        unique_perturbations=len(cover),
        target_settled_on=sum(r['settled_on'] for r in cover),
        target_settled_off=sum(r['settled_off'] for r in cover),
        settled_gained=[r['suite'] for r in cover if r['settled_on'] and not r['settled_off']],
        settled_lost=[r['suite'] for r in cover if r['settled_off'] and not r['settled_on']],
        target_energy_higher=sum(r['target_energy_on'] > r['target_energy_off'] + tol for r in cover),
        target_energy_lower=sum(r['target_energy_on'] < r['target_energy_off'] - tol for r in cover),
        pre_guard_current_higher=[r['suite'] for r in cover
                                  if r['pre_guard_current_mA_on'] > r['pre_guard_current_mA_off'] + tol],
        pre_guard_current_lower=[r['suite'] for r in cover
                                 if r['pre_guard_current_mA_on'] < r['pre_guard_current_mA_off'] - tol],
        pre_guard_voltage_higher=[r['suite'] for r in cover
                                  if r['pre_guard_voltage_Vpp_on'] > r['pre_guard_voltage_Vpp_off'] + tol],
        max_pre_guard_current_mA_on=max(r['pre_guard_current_mA_on'] for r in cover),
        max_pre_guard_current_mA_off=max(r['pre_guard_current_mA_off'] for r in cover),
        # review/23 的协议口径：每条覆盖试验（三段）自身的含保护前峰值，逐场景比较
        trial_peak_current_higher=[r['suite'] for r in cover
                                   if r['trial_peak_current_mA_on'] > r['trial_peak_current_mA_off'] + tol],
        trial_peak_voltage_higher=[r['suite'] for r in cover
                                   if r['trial_peak_voltage_Vpp_on'] > r['trial_peak_voltage_Vpp_off'] + tol],
        max_trial_peak_current_mA_on=max(r['trial_peak_current_mA_on'] for r in cover),
        max_trial_peak_current_mA_off=max(r['trial_peak_current_mA_off'] for r in cover),
        max_trial_peak_voltage_Vpp_on=max(r['trial_peak_voltage_Vpp_on'] for r in cover),
        max_trial_peak_voltage_Vpp_off=max(r['trial_peak_voltage_Vpp_off'] for r in cover))
    return rows, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--orig', required=True)
    ap.add_argument('--patched', required=True)
    ap.add_argument('--registered', required=True)
    ap.add_argument('--new-batch', required=True)
    ap.add_argument('--work', required=True)
    ap.add_argument('--candidate', default=None)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    orig, patched = pathlib.Path(a.orig).resolve(), pathlib.Path(a.patched).resolve()
    registered, new = pathlib.Path(a.registered).resolve(), pathlib.Path(a.new_batch).resolve()
    work = pathlib.Path(a.work).resolve()
    out_dir = pathlib.Path(a.out).resolve() if a.out else None
    for d in (work, out_dir):
        if d is not None and {'workspace', 'outputs'} & set(d.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{d}')
    if work.exists():
        raise SystemExit(f'--work 必须是新目录：{work}')
    work.mkdir(parents=True)
    report, failures = {}, []

    tree = work / 'O_original_source'
    shutil.copytree(orig, tree, ignore=shutil.ignore_patterns('outputs', 'audits', '__pycache__'))
    batch_o, tests_o = run_formal(tree)
    meta = read_json(registered / 'run_metadata.json')
    report['O'] = dict(batch=batch_o.name, tests=tests_o,
                       registered_environment=dict(python=meta['python'], numpy=meta['numpy'],
                                                   platform=meta['platform']),
                       local_environment=read_json(batch_o / 'run_metadata.json')['platform'],
                       vs_registered=compare_platforms(batch_o, registered))
    if not report['O']['vs_registered']['ok']:
        failures.append('O：原源码本机重跑与旧登记批次的差别超出已登记的库实现末位差')

    tree = proof_tree(patched, orig, work / 'A_old_params_gate_off', old_params=True, gate=False)
    batch_a, tests_a = run_formal(tree)
    report['A'] = dict(batch=batch_a.name, tests=tests_a, vs_original_local=compare_registered(batch_a, batch_o))
    if not all_identical(report['A']['vs_original_local']):
        failures.append('A：旧参数＋门控关 未逐字节复现原源码本机批次')

    tree = proof_tree(patched, orig, work / 'B_old_params_gate_on', old_params=True, gate=True)
    batch_b, tests_b = run_formal(tree)
    b_fixed_scan = compare_registered(batch_b, batch_o, ('FIXED', 'PERIODIC_SCAN'))
    h = summaries(batch_b)[('HISTORICAL_12', 'PHASE_FEEDBACK')]
    got = (int(h['settled_segments']), round(float(h['energy_capture_pct']), 6))
    report['B'] = dict(batch=batch_b.name, tests=tests_b, fixed_and_scan_vs_original_local=b_fixed_scan,
                       phase_h12=got, v2_registered=PT.V2_REGISTERED,
                       phase_table=strategy_table(batch_b, 'PHASE_FEEDBACK'),
                       ablation_old_baseline=ablation(batch_b, batch_o)[1])
    if not all_identical(b_fixed_scan):
        failures.append('B：开门控改变了 FIXED 或 PERIODIC_SCAN')
    if got != PT.V2_REGISTERED:
        failures.append(f'B：门控开 12 段 {got} ≠ v2 登记值 {PT.V2_REGISTERED}')
    if a.candidate:
        replay = candidate_replay(orig, batch_b, pathlib.Path(a.candidate).resolve())
        report['B']['candidate_replay'] = replay
        if replay['mismatches']:
            failures.append('B：移植门控与 v2 候选的执行记录/事件不逐字节相同')
    else:
        report['B']['candidate_replay'] = '未给 --candidate，只核对了 12 段登记值'

    report['C'] = dict(batch=new.name, configuration={k: read_json(new / 'configuration.json')[k] for k in
                       ('version', 'current_soft_Arms', 'current_hard_Arms', 'voltage_soft_Vpp',
                        'voltage_hard_Vpp', 'phase_centre_recovery_gate')},
                       baseline=read_json(new / 'run_metadata.json').get('baseline_model_id'),
                       vs_study=check_against_study(new),
                       tables={s: strategy_table(new, s) for s in STRATEGIES},
                       registered_tables={s: strategy_table(registered, s) for s in STRATEGIES})
    if report['C']['vs_study']['mismatches']:
        failures.append('C：新批次与 review/24 第十五节的研究结果不逐值相同')
    if not report['C']['configuration']['phase_centre_recovery_gate']:
        failures.append('C：新批次没有开门控')

    tree = proof_tree(patched, orig, work / 'D_new_params_gate_off', old_params=False, gate=False)
    batch_d, tests_d = run_formal(tree)
    d_fixed_scan = {}
    for pattern in ('executions', 'events'):
        n, bad = same_bytes(new, batch_d, pattern, ('FIXED', 'PERIODIC_SCAN'))
        d_fixed_scan[pattern] = dict(files=n, mismatches=bad)
    rows, summary = ablation(new, batch_d)
    report['D'] = dict(batch=batch_d.name, tests=tests_d, fixed_and_scan_vs_new=d_fixed_scan,
                       phase_gate_off_table=strategy_table(batch_d, 'PHASE_FEEDBACK'),
                       ablation_summary=summary)
    if any(v['mismatches'] for v in d_fixed_scan.values()):
        failures.append('D：关门控改变了 FIXED 或 PERIODIC_SCAN')
    report['failures'] = failures

    o = report['O']['vs_registered']
    print(f"== O 原源码本机重跑 vs 旧登记批次（{report['O']['registered_environment']['platform']}）：可接受 {o['ok']}")
    print(f"   执行记录：{o['executions']}；事件：{o['events']}")
    for n in TABLES:
        print(f'   {n}: {o[n]}')
    print('== A 旧参数＋门控关 vs 原源码本机批次')
    for k, v in report['A']['vs_original_local'].items():
        print(f'  {k:42s} {v}')
    print(f"== B 旧参数＋门控开：12 段 {got}，v2 登记 {PT.V2_REGISTERED}；候选逐字节重放 {report['B']['candidate_replay']}")
    print(f"   旧基线上门控开/关（B 对 O）：{report['B']['ablation_old_baseline']}")
    print(f"   FIXED/PERIODIC_SCAN vs 原源码本机：{ {k: (v.get('mismatches'), v.get('identical')) for k, v in b_fixed_scan.items()} }")
    print(f"== C 新批次 {new.name}：与研究结果逐值比较，不符 {report['C']['vs_study']['mismatches']}")
    for s in STRATEGIES:
        t, r = report['C']['tables'][s], report['C']['registered_tables'][s]
        print(f"   {s:15s} 新：12段 {t['h12_settled']}/12 {t['h12_energy_pct']:.4f}%  覆盖 {t['cover_target_settled']}/34"
              f"（独立 {t['cover_unique_target_settled']}/31）  保护前峰 {t['h12_peak_pre_guard_V']:.2f} Vpp"
              f" | 旧：{r['h12_settled']}/12 {r['h12_energy_pct']:.4f}%  覆盖 {r['cover_target_settled']}/34"
              f"（独立 {r['cover_unique_target_settled']}/31）")
    t = report['D']['phase_gate_off_table']
    print(f"== D 新基线门控关：PHASE 12段 {t['h12_settled']}/12 {t['h12_energy_pct']:.4f}%  覆盖 {t['cover_target_settled']}/34"
          f"（独立 {t['cover_unique_target_settled']}/31）；FIXED/SCAN 与 C 逐字节相同：{not any(v['mismatches'] for v in d_fixed_scan.values())}")
    for k, v in summary.items():
        print(f'   {k}: {v}')
    print('\n' + ('全部核对通过' if not failures else '核对失败：' + '；'.join(failures)))

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'baseline_switch_check.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=list), encoding='utf-8')
        with open(out_dir / 'phase_gate_ablation.csv', 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
