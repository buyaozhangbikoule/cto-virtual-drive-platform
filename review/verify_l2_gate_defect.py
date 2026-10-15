"""Verify the 2026-10-15 Codex re-check of review/22, then attack the
pre-guard current-peak rise. Read-only.

C1  does our L2 really gate on `new != target` too (review/22 §4.2 claim)?
C2  does our L2's failure to clear a_prev during protection actually bite?
C3  are CASE_QL_100 and CASE_QM_800 physically identical to CASE_000_BASELINE?
C4  de-duplicated COVER numbers and the weighted capture rate
C5  their synthetic gate sequences, against both gates
M   mechanism: why does the pre-guard current peak rise on 13 scenarios?
"""
import collections
import json
import pathlib
import sys
from dataclasses import asdict

R = pathlib.Path('/tmp/claude-0/-home-user-cto-virtual-drive-platform/'
                 'bc293afb-98ff-55d3-b088-2c39b9b0faae/scratchpad/main_unified')
S = pathlib.Path('/tmp/claude-0/-home-user-cto-virtual-drive-platform/'
                 'bc293afb-98ff-55d3-b088-2c39b9b0faae/scratchpad')
REPO = pathlib.Path('/home/user/cto-virtual-drive-platform')
for p in (R, R / 'models', S / 'codex_v2', REPO / 'review'):
    sys.path.insert(0, str(p))
import engine as E                                                 # noqa: E402
import controllers as C                                            # noqa: E402
import metrics as M                                                # noqa: E402
import models.model_v2_1 as model                                  # noqa: E402
import candidate as CAND                                           # noqa: E402
import amplitude_recovery_study as ARS                             # noqa: E402

cfg = json.loads((R / 'config.json').read_text())
ids = cfg['historical_schedule']
ref = M.references(cfg)
TP = float(model.response(cfg['initial_frequency_Hz'],
                          model.scenario_map()['CASE_000_BASELINE'])['phase_deg'][0])
ARS.TARGET[0] = TP
scen = model.scenario_map()


# ----------------------------------------------------------------- C2
print('=' * 86)
print('C2  我方 L2 在保护占用期间不清 a_prev —— 实际会不会误判"已稳定"')
print('=' * 86)


def run_l2_instrumented(clear_on_interrupt: bool):
    eng = E.Engine(cfg, ids, 'PHASE_FEEDBACK', 'C2')
    io = C.Executor(eng)
    target, last = float(cfg['initial_frequency_Hz']), None
    settling, a_prev = False, -1.0
    stale_release = []
    while not io.finished:
        if last is not None:
            may_probe = True
            if settling:
                if (C.valid_measurement(last) and last.state == 'NORMAL'
                        and not last.frozen):
                    if last.amplitude > a_prev + 1e-12:
                        a_prev, may_probe = last.amplitude, False
                    else:
                        if last.amplitude < a_prev - 1e-12:
                            stale_release.append(
                                dict(t=io.time, amp=last.amplitude, a_prev=a_prev))
                        settling = False
                else:
                    may_probe = False
                    if clear_on_interrupt:
                        a_prev = -1.0        # the fix Codex's reading implies
            if may_probe:
                new, probed = ARS.probe_update(E, C, io, last, TP, target,
                                               cfg['phase_deadband_deg'])
                if probed and new != target:
                    settling, a_prev = True, -1.0
                target = new
        if not io.finished:
            last = io.control(target, 1.)
    return eng, stale_release


for fix, lab in ((False, '现状（不清 a_prev）'), (True, '清 a_prev')):
    eng, stale = run_l2_instrumented(fix)
    per, s = M.evaluate(eng.rows, eng.events, cfg, ref)
    pv = max(r['pre_guard_vport_Vpp'] for r in eng.rows)
    print('  %-18s 达标 %2d/12  能量 %11.6f%%  峰值 %11.6f Vpp  '
          '"幅度下降却判稳定"的次数 = %d'
          % (lab, s['settled_segments'], s['energy_capture_pct'], pv, len(stale)))
    if stale and not fix:
        for x in stale[:4]:
            print('      t=%7.1f ms  幅度 %.6f < 记录值 %.6f'
                  % (x['t'] / 1000, x['amp'], x['a_prev']))

# ----------------------------------------------------------------- C3
print()
print('=' * 86)
print('C3  CASE_QL_100 / CASE_QM_800 是否与 CASE_000_BASELINE 物理等同')
print('=' * 86)
base = scen['CASE_000_BASELINE']
groups = collections.defaultdict(list)
for cid, s0 in scen.items():
    key = json.dumps(dict(bvd=asdict(s0.bvd), matching=asdict(s0.matching),
                          rs=s0.rs), sort_keys=True)
    groups[key].append(cid)
alias = [g for g in groups.values() if len(g) > 1]
print('  34 个登记项 -> %d 个唯一物理状态' % len(groups))
for g in alias:
    print('    别名组: %s' % ', '.join(sorted(g)))
base_key = json.dumps(dict(bvd=asdict(base.bvd), matching=asdict(base.matching),
                           rs=base.rs), sort_keys=True)
print('  与基准同组的登记项: %s' % ', '.join(sorted(groups[base_key])))

# ----------------------------------------------------------------- C5
print()
print('=' * 86)
print('C5  Codex 构造的幅度序列，两种开门判据各自怎么判')
print('=' * 86)


def gate_v2(seq):
    """abs(m-p) <= 1e-12 : near-equal plateau."""
    prev = None
    for i, a in enumerate(seq):
        if prev is not None and abs(a - prev) <= 1e-12:
            return i
        prev = a
    return None


def gate_l2(seq):
    """our L2: release when amplitude is no longer rising."""
    a_prev = -1.0
    for i, a in enumerate(seq):
        if a > a_prev + 1e-12:
            a_prev = a
        else:
            return i
    return None


for seq, note in (((0.50, 0.49, 0.48), '持续下降'),
                  ((0.50, 0.10, 0.10), '突降后平台'),
                  ((0.50, 0.60, 0.70, 0.70), '正常升幅到平台'),
                  ((0.50, 0.5000000001, 0.5000000002), '微小抖动')):
    v = gate_v2(seq)
    l = gate_l2(seq)
    f = lambda x: '不放行' if x is None else '第%d点放行' % (x + 1)
    print('  %-22s %-28s v2判据: %-12s L2判据: %s'
          % (str(seq), note, f(v), f(l)))
print('  -> Codex 的结论成立：L2 的"不再上升"把"正在下降"也当成稳定，')
print('     而 v2 的近乎相等在持续微抖下不放行。两者各有失效方向。')
