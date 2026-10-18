#!/usr/bin/env python3
"""P8 补丁的独立核对（review/32）：直接驱动、电流限值测点、物理候选、ADMITTANCE_TRACK、恢复时间指标。

    python review/check_p8_patch.py --base <已打 P1–P3 的仓库根目录> --work <新的空临时目录>
                                    [--orig <main 原样 current/unified>] [--out <结果目录>]

在 --base 的副本上依次 git apply P4、P5、P6、P7（p7），再打 P8（p8）。
p7、p8 各自：
  · unified 行为测试全部通过（run_unified.py --test-only）；参数来源登记核对 ok；
  · 给了 --orig 时，合成候选可由 review/baseline_3mA_parameters.py 从原冻结文件逐值复核（P8 只给它加了与默认配置相同的新项）。
p8 另查：
  · 物理候选的三个 JSON 可由 review/physical_candidate_parameters.py 逐字节复核；
  · 正式策略集合仍是四个，ADMITTANCE_TRACK 只在 EXTRA_STRATEGIES 里；
  · ADMITTANCE_TRACK 在三套配置的历史 12 段上跑完，保护后没有越过硬限的行。
判据：
  · 默认、合成候选两套配置 × 35 个日程 × 四种正式策略：p8 的执行记录 CSV 与事件 JSON 与 p7 逐字节相同（2×140 条）。
只读 --base 与 --orig；只写 --work 与 --out。任何一项不符即以非零码退出。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_p4_p6_patches as C    # noqa: E402  同目录：复用打补丁、测试与哈希的写法

P7 = 'platform_v2_1.p7_user_current_limit_transducer_port.patch'
P8 = 'platform_v2_1.p8_direct_drive_current_points_admittance_track.patch'
FORMAL = C.ORIGINAL + ('CAPTURE_PO',)
PHYSICAL = 'candidates/physical_apc880_d05_L1747'
EXTRA = r'''
import json, pathlib, sys
root = sys.argv[1]
sys.path.insert(0, root)
import controllers
from controllers import Executor, run_policy
from engine import Engine
from models import model_v2_1 as model
out = dict(formal=list(controllers.STRATEGIES), extra=list(controllers.EXTRA_STRATEGIES), runs={})
for config in ('config.json', 'candidates/synthetic_q13p8_3mA/config.json', 'candidates/physical_apc880_d05_L1747/config.json'):
    cfg = json.loads((pathlib.Path(root)/config).read_text(encoding='utf-8'))
    model.configure(cfg)
    e = Engine(cfg, cfg['historical_schedule'], 'ADMITTANCE_TRACK', 'HISTORICAL_12')
    run_policy(Executor(e), 'ADMITTANCE_TRACK', 0.)
    out['runs'][config] = dict(duration_us=e.rows[-1]['end_us'], hard_rows=sum(r['actual_hard_violation'] for r in e.rows))
print(json.dumps(out))
'''


def apply(tree, patch):
    code, log = C.sh(['git', 'apply', '--whitespace=nowarn', str(HERE/'patches'/patch)], tree)
    if code:
        raise SystemExit(f'{patch} 无法应用到 {tree.name}：\n{log}')


def p8_checks(work, tree):
    unified = tree/C.UNIFIED
    item = {}
    code, log = C.sh([sys.executable, '-I', str(HERE/'physical_candidate_parameters.py'), '--synthetic',
                      str(unified/C.CANDIDATE), '--check', str(unified/PHYSICAL)], HERE.parent)
    item['physical_candidate_files'] = dict(ok=code == 0, summary=log.strip()[-300:])
    script = work/'extra.py'
    script.write_text(EXTRA, encoding='utf-8')
    code, log = C.sh([sys.executable, '-B', str(script), str(unified)], tree)
    if code:
        raise SystemExit(f'ADMITTANCE_TRACK 运行失败：\n{log[-3000:]}')
    r = json.loads(log.strip().splitlines()[-1])
    item['strategy_sets'] = dict(ok=r['formal'] == list(FORMAL) and r['extra'] == ['ADMITTANCE_TRACK'],
                                 formal=r['formal'], extra=r['extra'])
    item['admittance_track_runs'] = dict(ok=all(v['duration_us'] == 9600000 and v['hard_rows'] == 0
                                                for v in r['runs'].values()), runs=r['runs'])
    return item


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', required=True, help='已打 P1–P3 的仓库根目录（含 integrated/CTO_virtual_drive_platform_v2_1）')
    ap.add_argument('--work', required=True)
    ap.add_argument('--orig', default=None, help='main 原样 current/unified（核对合成候选推导）')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    base, work = pathlib.Path(a.base).resolve(), pathlib.Path(a.work).resolve()
    orig = pathlib.Path(a.orig).resolve() if a.orig else None
    if work.exists() and any(work.iterdir()):
        raise SystemExit('--work 必须是新的空目录')
    work.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns('outputs', 'audits', 'logs', 'registrations', '__pycache__', 'test_tmp', 'ui_test_tmp')
    p7, p8 = work/'p7', work/'p8'
    shutil.copytree(base/C.PLATFORM, p7/C.PLATFORM, ignore=ignore)
    for patch in C.PATCHES+(P7,):
        apply(p7, patch)
    shutil.copytree(p7, p8)
    apply(p8, P8)
    report, ok = dict(stages={}), True
    for name, tree in (('p7', p7), ('p8', p8)):
        report['stages'][name] = C.stage_checks(tree, orig)
        ok &= all(v['ok'] for v in report['stages'][name].values())
    report['stages']['p8'].update(extra := p8_checks(work, p8))
    ok &= all(v['ok'] for v in extra.values())
    results = {}
    for baseline, config in (('default', 'config.json'), ('candidate', C.CANDIDATE)):
        h7 = C.hashes(work, p7, config, FORMAL, f'p7_{baseline}')
        h8 = C.hashes(work, p8, config, FORMAL, f'p8_{baseline}')
        results[baseline] = {f'p8_{s.lower()}_equals_p7': C.same(h7, h8, s) for s in FORMAL}
        ok &= all(results[baseline].values())
    report['timelines'] = results
    report['ok'] = bool(ok)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if a.out:
        out = pathlib.Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out/'patch_check_p8.json').write_text(text, encoding='utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
