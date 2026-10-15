"""Independent check of the 2026-10-14 Codex feedback-recovery v2 candidate.

Read-only. Writes nothing. Takes the unified source directory and the directory
holding the candidate's `candidate.py`, runs its two policies on the frozen
baseline, scores them with the platform's own evaluate(), and checks every
number the candidate's README claims plus three it does not report.

    python review/check_codex_recovery_v2.py \
        --root <unified source dir> --candidate <dir containing candidate.py>

Sections:
  S1  reproduce the README's five-row table and its per-item claims
  S2  isolation: what candidate.py is allowed to see
  S3  the recovery gate's own behaviour (begin/complete/truncate, wait times)
  S4  why 8/12 vs 7/12 is one 20 ms tick, not an algorithmic difference
  S5  amplitude-starvation accounting, v2 against our own L2
  S6  the 34-scenario COVER schedules, which the README does not cover

S1 must reproduce 6/12 and 57.337359% for the formal phase policy; if it does
not, the harness is not comparable and nothing below it is evidence.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

FORBIDDEN = re.compile(
    r'\b(model|scenario|case_id|reference|optimum|settled|segment_index'
    r'|metrics|schedule)\b')


def build(root: pathlib.Path, cand: pathlib.Path):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    sys.path.insert(0, str(cand))
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import engine as E
    import controllers as C
    import metrics as M
    import models.model_v2_1 as model
    import candidate as CAND
    import amplitude_recovery_study as ARS
    cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    return E, C, M, model, CAND, ARS, cfg


def summarise(M, cfg, ref, name, eng, claim=None):
    per, s = M.evaluate(eng.rows, eng.events, cfg, ref)
    c = collections.Counter(e['event'] for e in eng.events)
    pv = max(r['pre_guard_vport_Vpp'] for r in eng.rows)
    pi = max(r['pre_guard_iport_Arms'] for r in eng.rows)
    hv = sum(r['duration_us'] for r in eng.rows
             if r.get('actual_hard_violation')) / 1000
    low = sum(r['duration_us'] for r in eng.rows
              if r['applied_amplitude'] < 0.999) / 1000
    probe = sum(r['duration_us'] for r in eng.rows
                if r['kind'].startswith('PHASE_PROBE')) / 1000
    mark = ''
    if claim:
        ok = (s['settled_segments'] == claim[0]
              and abs(s['energy_capture_pct'] - claim[1]) < 5e-6
              and abs(pv - claim[2]) < 5e-6)
        mark = '  [README: %s]' % ('逐位一致' if ok else '**不一致**')
    print('  %-16s 达标 %2d/12  能量 %11.6f%%  保护前 %11.6f Vpp / %.6f mA  '
          '硬越限 %.3f ms%s'
          % (name, s['settled_segments'], s['energy_capture_pct'], pv,
             1000 * pi, hv, mark))
    print('  %16s 更新 %3d  探针失败 %2d  探针 %6.1f ms  非满幅 %6.1f ms'
          % ('', c['PHASE_UPDATE'], c['PHASE_PROBE_FAILED'], probe, low))
    return per, s, c


def starvation(model, cfg, ref, eng):
    """Energy lost purely to amplitude below the soft-feasible limit.

    An identity-style split along the variant's OWN realised frequency path,
    not a second independent measurement of the gain.
    """
    scen = model.scenario_map()
    act = cap = refe = 0.0
    for r in eng.rows:
        q = model.response(r['frequency_Hz'], scen[r['case_id']])
        a = min(1.0, cfg['voltage_soft_Vpp'] / float(q['vport_vpp'][0]),
                cfg['current_soft_Arms'] / float(q['iport_irms_A'][0]))
        dt = r['duration_us'] / 1e6
        act += r['p_rm_W'] * dt
        cap += float(q['p_rm_W'][0]) * a * a * dt
        refe += ref[r['case_id']]['policy']['power_W'] * dt
    return act, cap, 100 * (cap - act) / refe


def qualifies(r, cfg, refw):
    return (r['protection_state'] == 'NORMAL' and not r['frequency_frozen']
            and r['measurement_valid']
            and r['end_us'] % cfg['control_tick_us'] == 0
            and r['action_end_us'] == r['end_us']
            and r['p_rm_W'] / refw >= cfg['capture_threshold']
            and not r['actual_hard_violation'])


def longest_run(rows, cfg, refw):
    best = run = 0
    for r in rows:
        if qualifies(r, cfg, refw):
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--candidate', required=True)
    ap.add_argument('--skip-cover', action='store_true',
                    help='skip S6, which runs 33 three-segment schedules')
    a = ap.parse_args()
    root = pathlib.Path(a.root).resolve()
    cand = pathlib.Path(a.candidate).resolve()
    E, C, M, model, CAND, ARS, cfg = build(root, cand)
    ids = cfg['historical_schedule']
    ref = M.references(cfg)
    base = model.scenario_map()['CASE_000_BASELINE']
    tp = float(model.response(cfg['initial_frequency_Hz'], base)['phase_deg'][0])
    ARS.TARGET[0] = tp

    def run_formal(strategy):
        eng = E.Engine(cfg, ids, strategy, 'CHECK')
        C.run_policy(C.Executor(eng), strategy, tp)
        return eng

    def run_cand(fn, *args):
        eng = E.Engine(cfg, ids, 'PHASE_FEEDBACK' if fn is CAND.run_phase_recovery
                       else 'PERIODIC_SCAN', 'CHECK')
        fn(C.Executor(eng), *args)
        return eng

    print('S1  复现 README 第 3 节')
    eng0 = run_formal('PHASE_FEEDBACK')
    per0, _, _ = summarise(M, cfg, ref, '原相位策略', eng0, (6, 57.337359, 188.220389))
    engv = run_cand(CAND.run_phase_recovery, tp)
    perv, sv, cv = summarise(M, cfg, ref, '相位恢复v2', engv,
                             (7, 70.104969, 188.227662))
    engp = run_formal('PERIODIC_SCAN')
    summarise(M, cfg, ref, '原周期扫频', engp, (1, 41.958642, 188.224711))
    engs = run_cand(CAND.run_scan_end)
    summarise(M, cfg, ref, '扫频SCAN_END', engs, (7, 43.493320, 176.225386))
    engl = ARS.run_phase(E, C, cfg, ids, 0.1, True, 'L2')
    perl, _, _ = summarise(M, cfg, ref, '（我方 L2）', engl,
                           (8, 69.271055, 188.227662))
    print('  README 另称: 更新 154->101, 探针失败 10->8, 探针 489->327 ms, '
          '非满幅 5260->3518.5 ms')
    print()
    print('  逐段确认时间 (ms):')
    for i in (4, 5, 7, 9, 11):
        f = lambda v: '未通过' if v is None else '%.0f' % v
        print('    段%-3d %-20s 原 %-8s v2 %-8s   能量 %7.3f%% -> %7.3f%%'
              % (i, ids[i], f(per0[i]['recovery_confirm_ms']),
                 f(perv[i]['recovery_confirm_ms']),
                 per0[i]['energy_capture_pct'], perv[i]['energy_capture_pct']))

    print()
    print('S2  隔离性')
    src = (cand / 'candidate.py').read_text(encoding='utf-8')
    body = '\n'.join(l for l in src.split('\n') if not l.lstrip().startswith('#'))
    imports = [l.strip() for l in body.split('\n')
               if l.startswith(('import ', 'from '))]
    for l in imports:
        print('    %s' % l)
    hits = []
    for i, line in enumerate(body.split('\n'), 1):
        if FORBIDDEN.search(line) and not line.lstrip().startswith('"""'):
            hits.append((i, line.strip()[:70]))
    print('    禁止词命中（场景/模型/最优表/验收计数）: %d'
          % len([h for h in hits if '"""' not in h[1]]))
    for i, l in hits[:5]:
        print('      行%d: %s' % (i, l))

    print()
    print('S3  恢复门控自身的行为（README 未报）')
    for k in ('CENTRE_RECOVERY_BEGIN', 'CENTRE_RECOVERY_COMPLETE',
              'CENTRE_RECOVERY_TRUNCATED', 'PHASE_NO_NEW_CENTRE_RETURN',
              'PHASE_RECOVERY_INVALID_MEASUREMENT_WAIT'):
        print('    %-42s %d' % (k, cv[k]))
    w = [e['wait_us'] / 1000 for e in engv.events
         if e['event'] == 'CENTRE_RECOVERY_COMPLETE']
    if w:
        print('    恢复等待 ms: 最小 %.1f 中位 %.1f 最大 %.1f 合计 %.1f'
              % (min(w), sorted(w)[len(w) // 2], max(w), sum(w)))
        # The probe pair ends 2*scan_point into a tick, and the gate then needs
        # two further lattice samples, so the floor is 2*tick - 2*scan_point.
        print('    理论下界 = 2*tick - 2*scan_point = %.1f ms'
              % ((2 * cfg['control_tick_us'] - 2 * cfg['scan_point_us']) / 1000))

    print()
    print('S4  8/12 与 7/12 之差')
    refw = ref['CASE_000_BASELINE']['policy']['power_W']
    for nm, eg in (('相位恢复v2', engv), ('我方 L2', engl)):
        rows = [r for r in eg.rows
                if r['segment_index'] == 7 and r['kind'] == 'CONTROL']
        print('    %-10s 第7段最长连续合格样本 = %d  (门槛 %d)'
              % (nm, longest_run(rows, cfg, refw), cfg['continuous_samples']))
    print('    -> 差一个 %.0f ms 格点，落在验收规则的阶跃点上，不构成算法优劣'
          % (cfg['control_tick_us'] / 1000))

    print()
    print('S5  幅度饥饿核算（恒等式拆分，非独立复测）')
    print('    %-12s %12s %14s %16s' % ('', '实际电能J', '同轨迹满幅J', '饥饿损失占参考%'))
    for nm, eg in (('原相位', eng0), ('相位恢复v2', engv), ('我方 L2', engl)):
        act, cap, loss = starvation(model, cfg, ref, eg)
        print('    %-12s %12.6f %14.6f %16.3f' % (nm, act, cap, loss))

    if a.skip_cover:
        return
    print()
    print('S6  34 场景 COVER 日程（README 只报 20 个；此处为独立检验）')
    cases = [c for c in model.scenario_map() if c != 'CASE_000_BASELINE']
    agg = {'base': [0, 0, 0.0], 'v2': [0, 0, 0.0]}
    trunc = pv_up = pi_up = 0
    worse = []
    for c in cases:
        sch = ['CASE_000_BASELINE', c, 'CASE_000_BASELINE']
        got = {}
        for nm in ('base', 'v2'):
            eg = E.Engine(cfg, sch, 'PHASE_FEEDBACK', 'COVER')
            io = C.Executor(eg)
            if nm == 'base':
                C.run_policy(io, 'PHASE_FEEDBACK', tp)
            else:
                CAND.run_phase_recovery(io, tp)
            per, s = M.evaluate(eg.rows, eg.events, cfg, ref)
            got[nm] = (per, s, collections.Counter(e['event'] for e in eg.events),
                       max(r['pre_guard_vport_Vpp'] for r in eg.rows),
                       max(r['pre_guard_iport_Arms'] for r in eg.rows))
            agg[nm][0] += 1 if per[1]['settled'] else 0
            agg[nm][1] += 1 if per[2]['settled'] else 0
            agg[nm][2] += s['energy_capture_pct']
        trunc += got['v2'][2]['CENTRE_RECOVERY_TRUNCATED']
        d = got['v2'][1]['energy_capture_pct'] - got['base'][1]['energy_capture_pct']
        if d < -1e-9:
            worse.append((c, d))
        pv_up += got['v2'][3] > got['base'][3] + 1e-9
        pi_up += got['v2'][4] > got['base'][4] + 1e-9
    n = len(cases)
    print('    %-12s %12s %12s %14s' % ('', '扰动段通过', '返回段通过', '能量均值%'))
    for nm, lab in (('base', '原相位'), ('v2', '相位恢复v2')):
        print('    %-12s %9d/%d %10d/%d %14.4f'
              % (lab, agg[nm][0], n, agg[nm][1], n, agg[nm][2] / n))
    print('    门控悬挂 CENTRE_RECOVERY_TRUNCATED 合计 = %d' % trunc)
    print('    v2 能量低于原相位的场景 = %d' % len(worse))
    for c, d in sorted(worse, key=lambda x: x[1])[:4]:
        print('      %-22s %+.6f pp' % (c, d))
    print('    保护前预测电压峰值升高 %d/%d；电流峰值升高 %d/%d'
          % (pv_up, n, pi_up, n))


if __name__ == '__main__':
    main()
