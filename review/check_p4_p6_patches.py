#!/usr/bin/env python3
"""P4–P6 补丁的独立核对（review/27）：在已打 P1–P3 的仓库副本上依次 git apply，逐级检查。

    python review/check_p4_p6_patches.py --base <已打 P1–P3 的仓库根目录> --work <新的空临时目录>
                                         [--orig <main 原样 current/unified>] [--out <结果目录>]

每一级（P3 原样、+P4、+P5、+P6）：
  · unified 行为测试全部通过（run_unified.py --test-only）；参数来源登记核对 ok（current.parameter_sources）；
  · 给了 --orig 时，候选配置可由 review/baseline_3mA_parameters.py 从原冻结文件逐值复核；
  · 两种基线（默认、合成候选）× 35 个日程，按 run_unified.py 的写法生成执行记录 CSV 与事件 JSON 的 sha256。
判据：
  · P4、P5：FIXED、PERIODIC_SCAN、PHASE_FEEDBACK 三者 2×105 份与 P3 逐字节相同；
  · P6：FIXED、PERIODIC_SCAN 与 P3 相同，CAPTURE_PO 与 P5 相同；PHASE_FEEDBACK 改为端口相位＋重学，
    另以 phase_tracker=gain_v1 的配置副本运行，必须与 P3 的 PHASE_FEEDBACK 逐字节相同（原定律仍可复现）。
只读 --base 与 --orig；只写 --work 与 --out。任何一项不符即以非零码退出。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PLATFORM = 'integrated/CTO_virtual_drive_platform_v2_1'
UNIFIED = PLATFORM + '/current/unified'
CANDIDATE = 'candidates/synthetic_q13p8_3mA/config.json'
PATCHES = ('platform_v2_1.p4_power_drop_capture_and_phase_newton_v2.patch',
           'platform_v2_1.p5_capture_po_fourth_strategy.patch',
           'platform_v2_1.p6_formal_phase_port_relearn.patch')
GAIN_V1 = dict(phase_tracker='gain_v1', phase_signal='input', phase_target_policy='frozen')
ORIGINAL = ('FIXED', 'PERIODIC_SCAN', 'PHASE_FEEDBACK')

HASHER = r'''
import csv, hashlib, io, json, pathlib, sys
root, config, strategies, overrides, out = sys.argv[1:6]
sys.path.insert(0, root)
from controllers import Executor, run_policy
from engine import Engine
from models import model_v2_1 as model
cfg = json.loads((pathlib.Path(root)/config).read_text(encoding='utf-8')); cfg.update(json.loads(overrides))
model.configure(cfg)
cases = model.scenario_map()
phase = float(model.response(cfg['initial_frequency_Hz'], cases['CASE_000_BASELINE'])['phase_deg'][0])
schedules = {'HISTORICAL_12': cfg['historical_schedule']}
schedules.update({'COVER_'+c: ['CASE_000_BASELINE', c, 'CASE_000_BASELINE'] for c in cases})
def csv_bytes(rows):
    buf = io.StringIO(newline='')
    w = csv.DictWriter(buf, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return '﻿'.encode('utf-8')+buf.getvalue().encode('utf-8')
result = {}
for suite, ids in schedules.items():
    for s in strategies.split(','):
        e = Engine(cfg, ids, s, suite)
        run_policy(Executor(e), s, phase)
        result[f'{suite}_{s}'] = [hashlib.sha256(csv_bytes(e.rows)).hexdigest(),
                                  hashlib.sha256(json.dumps(e.events, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')).hexdigest()]
pathlib.Path(out).write_text(json.dumps(result), encoding='utf-8')
'''


def sh(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, p.stdout+p.stderr


def hashes(work, tree, config, strategies, name, overrides=None):
    script = work/'hasher.py'
    script.write_text(HASHER, encoding='utf-8')
    out = work/f'{name}.json'
    code, log = sh([sys.executable, '-B', str(script), str(tree/UNIFIED), config, ','.join(strategies),
                    json.dumps(overrides or {}), str(out)], tree)
    if code:
        raise SystemExit(f'{name} 运行失败：\n{log[-3000:]}')
    return json.loads(out.read_text(encoding='utf-8'))


def same(a, b, strategy):
    keys = [k for k in a if k.endswith('_'+strategy)]
    return len(keys) == 35 and all(a[k] == b.get(k) for k in keys)


def stage_checks(tree, orig):
    item = {}
    code, log = sh([sys.executable, '-B', '-X', 'utf8', 'run_unified.py', '--test-only'], tree/UNIFIED)
    ran = [line for line in log.splitlines() if line.startswith('Ran ')]
    item['unified_tests'] = dict(ok=code == 0 and bool(ran) and 'FAILED' not in log, ran=ran[-1] if ran else '')
    code, log = sh([sys.executable, '-B', '-X', 'utf8', '-m', 'current.parameter_sources'], tree/PLATFORM)
    item['registry'] = dict(ok=code == 0, summary=log.strip()[-200:])
    if orig is not None:
        code, log = sh([sys.executable, '-B', str(HERE/'baseline_3mA_parameters.py'), '--root', str(orig),
                        '--check', str(tree/UNIFIED)], HERE.parent)
        item['candidate_derivation'] = dict(ok=code == 0, summary=log.strip().splitlines()[-1] if log.strip() else '')
    return item


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', required=True, help='已打 P1–P3 的仓库根目录（含 integrated/CTO_virtual_drive_platform_v2_1）')
    ap.add_argument('--work', required=True)
    ap.add_argument('--orig', default=None, help='main 原样 current/unified（核对候选配置推导）')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    base, work = pathlib.Path(a.base).resolve(), pathlib.Path(a.work).resolve()
    orig = pathlib.Path(a.orig).resolve() if a.orig else None
    if work.exists() and any(work.iterdir()):
        raise SystemExit('--work 必须是新的空目录')
    work.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns('outputs', 'audits', 'logs', 'registrations', '__pycache__', 'test_tmp', 'ui_test_tmp')
    trees, report, ok = {}, dict(stages={}), True
    trees['p3'] = work/'p3'
    shutil.copytree(base/PLATFORM, trees['p3']/PLATFORM, ignore=ignore)
    previous = 'p3'
    for name, patch in zip(('p4', 'p5', 'p6'), PATCHES):
        trees[name] = work/name
        shutil.copytree(trees[previous], trees[name])
        code, log = sh(['git', 'apply', '--whitespace=nowarn', str(HERE/'patches'/patch)], trees[name])
        if code:
            raise SystemExit(f'{patch} 无法应用：\n{log}')
        previous = name
    for name, tree in trees.items():
        report['stages'][name] = stage_checks(tree, orig)
        ok &= all(v['ok'] for v in report['stages'][name].values())
    results = {}
    for baseline, config in (('default', 'config.json'), ('candidate', CANDIDATE)):
        h = {name: hashes(work, trees[name], config, ORIGINAL+(('CAPTURE_PO',) if name != 'p3' and name != 'p4' else ()),
                          f'{name}_{baseline}') for name in trees}
        h['p6_gain_v1'] = hashes(work, trees['p6'], config, ('PHASE_FEEDBACK',), f'p6_gain_v1_{baseline}', GAIN_V1)
        checks = {
            'p4_original_three_equal_p3': all(same(h['p3'], h['p4'], s) for s in ORIGINAL),
            'p5_original_three_equal_p3': all(same(h['p3'], h['p5'], s) for s in ORIGINAL),
            'p6_fixed_and_periodic_scan_equal_p3': all(same(h['p3'], h['p6'], s) for s in ('FIXED', 'PERIODIC_SCAN')),
            'p6_capture_po_equals_p5': same(h['p5'], h['p6'], 'CAPTURE_PO'),
            'p6_gain_v1_phase_equals_p3_phase': same(h['p3'], h['p6_gain_v1'], 'PHASE_FEEDBACK'),
            'p6_phase_feedback_changed': not same(h['p3'], h['p6'], 'PHASE_FEEDBACK'),
        }
        results[baseline] = checks
        ok &= all(checks.values())
    report['timelines'] = results
    report['ok'] = bool(ok)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if a.out:
        out = pathlib.Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out/'patch_check_p4_p6.json').write_text(text, encoding='utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
