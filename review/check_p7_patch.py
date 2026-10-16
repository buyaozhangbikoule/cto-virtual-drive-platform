#!/usr/bin/env python3
"""P7 补丁的独立核对（review/28）：用户 5 mA 上限的测点在换能器端，P7 只记录、逐行核对和报告。

    python review/check_p7_patch.py --base <已打 P1–P3 的仓库根目录> --work <新的空临时目录>
                                    [--orig <main 原样 current/unified>] [--out <结果目录>]

在 --base 的副本上依次 git apply P4、P5、P6，再分两条路径打 P7：P6 之上（p7），以及跳过 P6、直接在 P5 之上（p5_p7）。
每个副本（p5、p6、p7、p5_p7）：
  · unified 行为测试全部通过（run_unified.py --test-only）；参数来源登记核对 ok；
  · 给了 --orig 时，候选配置可由 review/baseline_3mA_parameters.py 从原冻结文件逐值复核
    （P7 之前的副本仍写两种测点解释，P7 之后写换能器端，两种都须一致）。
判据：
  · 两种基线（默认、合成候选）× 35 个日程 × 四种策略：p7 的执行记录 CSV 与事件 JSON 与 p6 逐字节相同，
    p5_p7 与 p5 逐字节相同（各 2×140 条）——P7 不改变任何控制或保护行为；
  · P7 的两套配置都有 user_current_limit_Arms = 0.005，测点说明以 transducer_port 开头、不再写「未定」；
    默认配置的电流硬限高于该上限，候选不高于（与批次报告的结论一致）。
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
STRATEGIES = C.ORIGINAL + ('CAPTURE_PO',)
STALE = ('no stated', 'unspecified', 'one interpretation')


def apply(tree, patch):
    code, log = C.sh(['git', 'apply', '--whitespace=nowarn', str(HERE/'patches'/patch)], tree)
    if code:
        raise SystemExit(f'{patch} 无法应用到 {tree.name}：\n{log}')


def config_checks(tree):
    unified = tree/C.UNIFIED
    default = json.loads((unified/'config.json').read_text(encoding='utf-8'))
    candidate = json.loads((unified/C.CANDIDATE).read_text(encoding='utf-8'))
    item = {}
    for name, cfg in (('default', default), ('candidate', candidate)):
        point = cfg.get('current_limit_measurement_point', '')
        item[f'{name}_records_port_limit'] = (cfg.get('user_current_limit_Arms') == 0.005
                                              and point.startswith('transducer_port')
                                              and not any(s in point for s in STALE))
    item['default_hard_limit_above_user_limit'] = default['current_hard_Arms'] > default['user_current_limit_Arms']
    item['candidate_hard_limit_within_user_limit'] = candidate['current_hard_Arms'] <= candidate['user_current_limit_Arms']
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
    trees = {'p3': work/'p3'}
    shutil.copytree(base/C.PLATFORM, trees['p3']/C.PLATFORM, ignore=ignore)
    previous = 'p3'
    for name, patch in zip(('p4', 'p5', 'p6'), C.PATCHES):
        trees[name] = work/name
        shutil.copytree(trees[previous], trees[name])
        apply(trees[name], patch)
        previous = name
    for name, parent in (('p7', 'p6'), ('p5_p7', 'p5')):
        trees[name] = work/name
        shutil.copytree(trees[parent], trees[name])
        apply(trees[name], P7)
    report, ok = dict(stages={}), True
    for name in ('p5', 'p6', 'p7', 'p5_p7'):
        report['stages'][name] = C.stage_checks(trees[name], orig)
        ok &= all(v['ok'] for v in report['stages'][name].values())
    for name in ('p7', 'p5_p7'):
        report['stages'][name]['configuration'] = checks = config_checks(trees[name])
        ok &= all(checks.values())
    results = {}
    for baseline, config in (('default', 'config.json'), ('candidate', C.CANDIDATE)):
        h = {name: C.hashes(work, trees[name], config, STRATEGIES, f'{name}_{baseline}')
             for name in ('p5', 'p6', 'p7', 'p5_p7')}
        checks = {}
        for s in STRATEGIES:
            checks[f'p7_{s.lower()}_equals_p6'] = C.same(h['p6'], h['p7'], s)
            checks[f'p5_p7_{s.lower()}_equals_p5'] = C.same(h['p5'], h['p5_p7'], s)
        results[baseline] = checks
        ok &= all(checks.values())
    report['timelines'] = results
    report['ok'] = bool(ok)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if a.out:
        out = pathlib.Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out/'patch_check_p7.json').write_text(text, encoding='utf-8')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
