#!/usr/bin/env python3
"""拆分后三个补丁的独立核对（review/26）：默认结果逐字节不变、门控等于 v2、候选等于 55fbe6e 的批次。

    python review/check_split_patches.py --orig <main 原样 current/unified>
        --stage1 <打完 P1 的 current/unified> --stage2 <打完 P1+P2> --final <打完 P1+P2+P3>
        --registered <旧登记批次目录> --reviewed <55fbe6e 提交里的候选批次（精简版）目录>
        --default-batch <final 上 run_project.py validate 产出并登记的批次>
        --candidate-batch <final 上 run_unified.py --config candidates/... 产出的批次>
        --work <新的临时目录> [--candidate <v2 candidate.py 所在目录>] [--out <结果目录>]

O   原源码本机重跑（逐字节对照基准；与 Windows 登记批次的末位差按 check_baseline_switch 的口径限定）。
S1  P1 默认配置：105 条执行记录、105 份事件、四张表、场景登记（含说明文字）与 O 逐字节相同。
S2  P1+P2 默认配置（门控关）：同上。另以门控开的配置副本运行：FIXED、PERIODIC_SCAN 与 O 逐字节相同，
    相位反馈 12 段 = v2 登记值 7/12、70.104969%；给了 --candidate 时与 v2 候选 35 个日程逐字节相同；
    并做旧基线上门控开/关的消融（review/23 的逐试验保护前电流峰值口径）。
F   P1+P2+P3 默认配置：与 O 逐字节相同；正式入口 validate 产出的默认批次也与 O 逐字节相同。
C   候选配置：自己的运行与 --candidate-batch 逐字节相同；事件日志与 55fbe6e 提交里的批次逐字节相同，
    执行记录的 sha256 与该批次 manifest 相同，四张表去 batch_id 后相同；逐值等于 review/24 第十五节。
D   候选配置、门控关：FIXED、PERIODIC_SCAN 与 C 逐字节相同；相位反馈门控开/关逐条消融。
只读输入目录与批次；只写 --work 与 --out。任何一项不符即以非零码退出。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_baseline_switch as CB             # noqa: E402
import power_tracking_prototype as PT          # noqa: E402

CANDIDATE_CONFIG = 'candidates/synthetic_q13p8_3mA/config.json'


def copy_tree(src, dest):
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns('outputs', 'audits', '__pycache__'))
    return dest


def run(tree, config=None):
    cmd = [sys.executable, '-B', '-X', 'utf8', 'run_unified.py', '--suite', 'all']
    if config is not None:
        cmd += ['--config', str(config)]
    p = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, encoding='utf-8')
    if p.returncode != 0:
        raise SystemExit(f'{tree} 运行失败：\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}')
    out = [line[7:] for line in p.stdout.splitlines() if line.startswith('OUTPUT ')]
    tests = [line for line in p.stdout.splitlines() if line.startswith('Ran ')]
    if len(out) != 1:
        raise SystemExit('必须收到唯一的 OUTPUT 路径')
    return pathlib.Path(out[0]), tests[-1] if tests else ''


def variant(tree, base_config, work, name, **changes):
    cfg = json.loads((tree / base_config).read_text(encoding='utf-8'))
    cfg.update(changes)
    path = work / f'{name}.json'
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def strict(batch, ref, strategies=CB.STRATEGIES):
    """逐字节：执行记录、事件；表去 batch_id；参考、相位、日程；场景登记连说明文字也相同。"""
    r = CB.compare_registered(batch, ref, strategies)
    r['scenario_registry_bytes_identical'] = ((batch / 'scenario_registry.json').read_bytes()
                                              == (ref / 'scenario_registry.json').read_bytes())
    ok = CB.all_identical(r) and r['scenario_registry_bytes_identical']
    return ok, r


def against_reviewed(batch, reviewed):
    """候选批次 vs 55fbe6e 提交里的精简批次（无 executions/，manifest 里有它们的 sha256）。"""
    manifest = CB.read_json(reviewed / 'manifest.json')['files']
    ex = sorted(p.name for p in (batch / 'executions').iterdir())
    ex_bad = [n for n in ex if hashlib.sha256((batch / 'executions' / n).read_bytes()).hexdigest()
              != manifest.get(f'executions/{n}')]
    ev = sorted(p.name for p in (reviewed / 'events').iterdir())
    ev_bad = [n for n in ev if (batch / 'events' / n).read_bytes() != (reviewed / 'events' / n).read_bytes()]
    tables = {t: CB.read_rows(batch / t) == CB.read_rows(reviewed / t) for t in CB.TABLES}
    jsons = {j: CB.read_json(batch / j) == CB.read_json(reviewed / j)
             for j in ('reference_optima.json', 'phase_calibration.json', 'schedules.json')}
    a = {r['case_id']: r for r in CB.read_json(batch / 'scenario_registry.json')}
    b = {r['case_id']: r for r in CB.read_json(reviewed / 'scenario_registry.json')}
    physics = sorted(c for c in b if {k: v for k, v in a[c].items() if k not in ('level', 'description')}
                     != {k: v for k, v in b[c].items() if k not in ('level', 'description')})
    text = sorted(c for c in b if a[c] != b[c] and c not in physics)
    ok = (len(ex) == 105 and not ex_bad and len(ev) == 105 and not ev_bad and all(tables.values())
          and all(jsons.values()) and set(a) == set(b) and not physics)
    return ok, dict(executions_sha256_checked=len(ex), executions_mismatch=ex_bad, events_checked=len(ev),
                    events_mismatch=ev_bad, tables_identical=tables, json_identical=jsons,
                    scenario_physics_differences=physics, scenario_text_only_differences=text)


def main():
    ap = argparse.ArgumentParser()
    for name in ('orig', 'stage1', 'stage2', 'final', 'registered', 'reviewed', 'default-batch',
                 'candidate-batch', 'work'):
        ap.add_argument('--' + name, required=True)
    ap.add_argument('--candidate', default=None)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    P = lambda x: pathlib.Path(x).resolve()                 # noqa: E731
    orig, s1, s2, final = P(a.orig), P(a.stage1), P(a.stage2), P(a.final)
    registered, reviewed = P(a.registered), P(a.reviewed)
    default_batch, candidate_batch, work = P(a.default_batch), P(a.candidate_batch), P(a.work)
    out_dir = P(a.out) if a.out else None
    for d in (work, out_dir):
        if d is not None and {'workspace', 'outputs'} & set(d.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{d}')
    if work.exists():
        raise SystemExit(f'--work 必须是新目录：{work}')
    work.mkdir(parents=True)
    rep, fail = {}, []

    o_batch, o_tests = run(copy_tree(orig, work / 'O'))
    rep['O'] = dict(batch=o_batch.name, tests=o_tests, vs_registered=CB.compare_platforms(o_batch, registered))
    if not rep['O']['vs_registered']['ok']:
        fail.append('O：本机原源码与 Windows 登记批次的差别超出已登记的库实现末位差')

    for tag, tree in (('S1', s1), ('S2', s2), ('F', final)):
        t = copy_tree(tree, work / tag)
        b, tests = run(t)
        ok, r = strict(b, o_batch)
        rep[tag] = dict(batch=b.name, tests=tests, default_vs_O=r, default_identical=ok)
        if not ok:
            fail.append(f'{tag}：默认配置结果与原源码不逐字节相同')
        if tag == 'S2':
            g, tests_g = run(t, variant(t, 'config.json', work, 'S2_gate_on', phase_centre_recovery_gate=True))
            ok_fs, r_fs = strict(g, o_batch, ('FIXED', 'PERIODIC_SCAN'))
            h = CB.summaries(g)[('HISTORICAL_12', 'PHASE_FEEDBACK')]
            got = (int(h['settled_segments']), round(float(h['energy_capture_pct']), 6))
            rep['S2'].update(gate_on_batch=g.name, gate_on_fixed_scan_vs_O=r_fs, gate_on_phase_h12=got,
                             v2_registered=PT.V2_REGISTERED, ablation_old_baseline=CB.ablation(g, o_batch)[1])
            if not ok_fs:
                fail.append('S2：开门控改变了 FIXED 或 PERIODIC_SCAN')
            if got != PT.V2_REGISTERED:
                fail.append(f'S2：门控开 12 段 {got} ≠ v2 {PT.V2_REGISTERED}')
            if a.candidate:
                rp = CB.candidate_replay(orig, g, P(a.candidate))
                rep['S2']['v2_candidate_replay'] = rp
                if rp['mismatches']:
                    fail.append('S2：门控与 v2 候选不逐字节相同')
        if tag == 'F':
            ok_d, r_d = strict(default_batch, o_batch)
            rep['F'].update(validate_batch=default_batch.name, validate_batch_vs_O=r_d,
                            validate_batch_identical=ok_d)
            if not ok_d:
                fail.append('F：validate 产出的默认批次与原源码不逐字节相同')
            c, tests_c = run(t, CANDIDATE_CONFIG)
            ok_c, r_c = strict(c, candidate_batch)
            ok_r, r_r = against_reviewed(c, reviewed)
            study = CB.check_against_study(c)
            rep['C'] = dict(batch=c.name, tests=tests_c, deliverable=candidate_batch.name,
                            vs_deliverable=r_c, deliverable_identical=ok_c,
                            vs_reviewed_55fbe6e=r_r, reviewed_identical=ok_r, vs_study=study,
                            tables={s: CB.strategy_table(c, s) for s in CB.STRATEGIES},
                            default_tables={s: CB.strategy_table(default_batch, s) for s in CB.STRATEGIES},
                            configuration={k: CB.read_json(c / 'configuration.json')[k] for k in
                                           ('version', 'current_soft_Arms', 'current_hard_Arms',
                                            'phase_centre_recovery_gate', 'baseline_design_file')},
                            baseline=CB.read_json(c / 'run_metadata.json')['baseline_model_id'],
                            amplifier_output_current_peak_mArms=CB.read_json(
                                c / 'run_metadata.json')['amplifier_output_current_peak_mArms'])
            if not ok_c:
                fail.append('C：候选重跑与交付的候选批次不逐字节相同')
            if not ok_r:
                fail.append('C：候选批次与 55fbe6e 审查过的批次不一致')
            if study['mismatches']:
                fail.append('C：候选批次与 review/24 第十五节不逐值相同')
            d, tests_d = run(t, variant(t, CANDIDATE_CONFIG, work, 'C_gate_off', phase_centre_recovery_gate=False))
            fs_ok = all(not v[1] for v in (CB.same_bytes(c, d, x, ('FIXED', 'PERIODIC_SCAN'))
                                           for x in ('executions', 'events')))
            rows, summary = CB.ablation(c, d)
            rep['D'] = dict(batch=d.name, tests=tests_d, fixed_scan_identical_to_C=fs_ok,
                            phase_gate_off_table=CB.strategy_table(d, 'PHASE_FEEDBACK'), ablation_summary=summary)
            if not fs_ok:
                fail.append('D：关门控改变了候选上的 FIXED 或 PERIODIC_SCAN')
    rep['failures'] = fail

    print(f"O  原源码本机 vs Windows 登记批次：可接受 {rep['O']['vs_registered']['ok']}")
    for tag in ('S1', 'S2', 'F'):
        print(f"{tag} 默认配置 vs O 逐字节：{rep[tag]['default_identical']}（{rep[tag]['tests']}）")
    print(f"S2 门控开：12 段 {rep['S2']['gate_on_phase_h12']}，v2 {PT.V2_REGISTERED}；"
          f"候选重放 {rep['S2'].get('v2_candidate_replay', '未给 --candidate')}")
    ab = rep['S2']['ablation_old_baseline']
    print(f"   旧基线门控开/关：逐试验电流峰值上升 {len(ab['trial_peak_current_higher'])}/31，"
          f"电压 {len(ab['trial_peak_voltage_higher'])}/31")
    print(f"F  validate 默认批次 vs O 逐字节：{rep['F']['validate_batch_identical']}")
    print(f"C  候选：与交付批次逐字节 {rep['C']['deliverable_identical']}；与 55fbe6e 批次 {rep['C']['reviewed_identical']}"
          f"（场景说明文字差 {rep['C']['vs_reviewed_55fbe6e']['scenario_text_only_differences']}）；"
          f"与研究结果不符 {rep['C']['vs_study']['mismatches']}")
    for s in CB.STRATEGIES:
        t, r = rep['C']['tables'][s], rep['C']['default_tables'][s]
        print(f"   {s:15s} 候选 12段 {t['h12_settled']}/12 {t['h12_energy_pct']:.4f}% 覆盖独立 "
              f"{t['cover_unique_target_settled']}/31 | 默认 {r['h12_settled']}/12 {r['h12_energy_pct']:.4f}% "
              f"覆盖独立 {r['cover_unique_target_settled']}/31")
    sm = rep['D']['ablation_summary']
    print(f"D  候选门控开/关：目标段 {sm['target_settled_on']}/{sm['target_settled_off']}，"
          f"逐试验电流峰值上升 {len(sm['trial_peak_current_higher'])}/31；FIXED/SCAN 不变 {rep['D']['fixed_scan_identical_to_C']}")
    print('\n' + ('全部核对通过' if not fail else '核对失败：' + '；'.join(fail)))
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / 'split_patches_check.json').write_text(
            json.dumps(rep, ensure_ascii=False, indent=2, default=list), encoding='utf-8')
    return 1 if fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
