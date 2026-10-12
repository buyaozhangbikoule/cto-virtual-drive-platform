"""Why the phase-feedback strategy is slow, and why making it faster is worse.

Read-only. Writes nothing, never touches the frozen outputs/ tree. Point --root
at a unified source directory, e.g.

    python review/phase_criterion_study.py --root \
        integrated/CTO_virtual_drive_platform_v2_1/current/unified

Five sections, each recomputing one claim of review/18 from scratch:

  S1  the loop's iteration cost and the frequency travel each segment needs
  S2  what the proportional gain is standing in for, measured per segment
  S3  whether the frozen phase target is satisfiable at the power optimum
  S4  the same question for the de-embedded arg(Z_bvd) criterion
  S5  four update laws scored by the platform's own evaluate()

S5 variant A must reproduce the registered batch (6/12 settled, 57.34% energy);
if it does not, the harness is not comparable and nothing below it is evidence.

No section passes a scenario ID, a segment boundary, the offline optimum table
or the acceptance counter to a controller. S4/S5-D read only the NOMINAL
matching components, which are the controller's own design values, never the
perturbed truth -- that is the point of the experiment, and it is why those
variants are expected to degrade when the matching network itself is the thing
that moved.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

import numpy as np

SECTIONS = ('S1', 'S2', 'S3', 'S4', 'S5')


# --------------------------------------------------------------------------
# shared setup
# --------------------------------------------------------------------------
def build(root: pathlib.Path):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'models'))
    import engine as E
    import controllers as C
    import metrics as M
    import models.model_v2_1 as model
    cfg = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    return E, C, M, model, cfg


def arg_zin(model, f: float, s) -> float:
    q = model.response(f, s)
    z = complex(q['v_input'][0]) / complex(q['i_source'][0])
    return float(np.degrees(np.arctan2(z.imag, z.real)))


def arg_zbvd(model, f: float, s) -> float:
    return float(np.degrees(np.angle(complex(model.response(f, s)['z_bvd'][0]))))


class Deembed:
    """Z_in -> Z_bvd through the NOMINAL L-match. Frozen at construction.

    Exactly inverts the forward topology in model_v2_1.response:
        Z_in  = r_l + jwL + (Z_bvd || Z_cmatch)
        Z_bvd = 1 / (1/(Z_in - r_l - jwL) - 1/Z_cmatch)
    using only values a controller knows about its own matching network.
    """

    def __init__(self, model):
        nom = model.scenario_map()['CASE_000_BASELINE'].matching
        self.l = float(nom.l_h)
        self.c = float(nom.c_f)
        self.rl = 2 * math.pi * model.F0 * self.l / float(nom.ql)
        self.rc = 1 / (2 * math.pi * model.F0 * self.c * float(nom.qc))
        self.origin = ('nominal_design_values_frozen_from_CASE_000_BASELINE_'
                       'matching_no_current_truth')

    def __call__(self, zin: complex, f: float):
        w = 2 * math.pi * f
        zpar = zin - self.rl - 1j * w * self.l
        zcm = self.rc + 1 / (1j * w * self.c)
        if abs(zpar) < 1e-15 or abs(zcm) < 1e-15:
            return None
        d = 1 / zpar - 1 / zcm
        if abs(d) < 1e-15:
            return None
        z = 1 / d
        if not (math.isfinite(z.real) and math.isfinite(z.imag)):
            return None
        return z


def roots(fn, s, target: float, lo: float, hi: float, coarse: float = 25.0,
          tol: float = 1e-9) -> list[float]:
    """Every root of fn(f,s)-target on [lo,hi]: exact grid zeros and bisected
    sign changes. The exact-zero branch matters: the calibration frequency is
    itself a root by construction and a strict sign test silently drops it."""
    g = np.arange(lo, hi + 1, coarse)
    e = [fn(f, s) - target for f in g]
    out = [float(g[i]) for i, v in enumerate(e) if v == 0.0]
    for i in range(len(g) - 1):
        if e[i] * e[i + 1] < 0:
            a, c, fa = float(g[i]), float(g[i + 1]), e[i]
            for _ in range(80):
                m = 0.5 * (a + c)
                fm = fn(m, s) - target
                if fm == 0.0:
                    a = c = m
                    break
                if fa * fm < 0:
                    c = m
                else:
                    a, fa = m, fm
                if c - a < tol:
                    break
            out.append(0.5 * (a + c))
    return sorted({round(x, 4) for x in out})


def optima(model, cfg, step: float = 25.0):
    g = np.arange(cfg['frequency_min_Hz'], cfg['frequency_max_Hz'] + 1, step)
    out = {}
    for c, s in model.scenario_map().items():
        p = np.array([float(model.response(f, s)['p_rm_W'][0]) for f in g])
        out[c] = (float(g[int(np.argmax(p))]), float(p.max()))
    return out


def unique_cases(ids):
    seen = []
    for c in ids:
        if c not in seen:
            seen.append(c)
    return seen


# --------------------------------------------------------------------------
# the four update laws
# --------------------------------------------------------------------------
def phase_of(m, deembed):
    if deembed is None:
        return m.phase_input_deg
    if m.zin_real is None or m.zin_imag is None:
        return None
    z = deembed(complex(m.zin_real, m.zin_imag), m.frequency_Hz)
    return None if z is None else math.degrees(math.atan2(z.imag, z.real))


def update(E, C, io, m, target_phase, trusted, law, clip, deembed):
    """One update. Probe cost, validity gates and ordering follow the formal
    phase_update verbatim; only the step formula and the clip differ."""
    cfg = io.cfg
    if not C.valid_measurement(m) or m.state != 'NORMAL' or m.frozen:
        return trusted
    ph = phase_of(m, deembed)
    if ph is None or not math.isfinite(ph):
        io.event('PHASE_DEEMBED_FAILED')
        return trusted
    error = E.wrap_deg(target_phase - ph)
    if abs(error) <= cfg['phase_deadband_deg']:
        return trusted
    delta = cfg['phase_probe_offset_Hz']
    lo = max(cfg['frequency_min_Hz'], trusted - delta)
    hi = min(cfg['frequency_max_Hz'], trusted + delta)
    t0 = io.time
    left = io.execute(lo, m.amplitude, 'PHASE_PROBE_MINUS', cfg['scan_point_us'])
    left_ok = (io.time - t0 == cfg['scan_point_us'] and C.valid_measurement(left)
               and left.state == 'NORMAL' and not left.frozen
               and abs(left.frequency_Hz - lo) < 1e-7)
    t0 = io.time
    right = (io.execute(hi, m.amplitude, 'PHASE_PROBE_PLUS', cfg['scan_point_us'])
             if left_ok else None)
    right_ok = (io.time - t0 == cfg['scan_point_us'] and C.valid_measurement(right)
                and right.state == 'NORMAL' and not right.frozen
                and abs(right.frequency_Hz - hi) < 1e-7)
    if not left_ok or not right_ok or hi <= lo:
        io.event('PHASE_PROBE_FAILED')
        return trusted
    pl, pr = phase_of(left, deembed), phase_of(right, deembed)
    if pl is None or pr is None:
        io.event('PHASE_DEEMBED_FAILED')
        return trusted
    slope = E.wrap_deg(pr - pl) / (hi - lo)
    if not E.finite(slope) or abs(slope) < cfg['phase_slope_min_deg_per_Hz']:
        io.event('PHASE_SLOPE_UNRESOLVED')
        return trusted
    if law == 'PROPORTIONAL':
        raw = cfg['phase_gain_Hz_per_deg'] * error * math.copysign(1, slope)
    elif law == 'SECANT':
        # Newton/secant on phi(f)-target: df = error / (dphi/df). Uses the
        # magnitude of the slope the loop has already paid two probes for,
        # instead of discarding it in favour of a hard-wired constant gain.
        raw = error / slope
    else:
        raise ValueError(law)
    df = float(np.clip(raw, -clip, clip))
    prop = trusted + df
    cand = float(np.clip(prop, cfg['frequency_min_Hz'], cfg['frequency_max_Hz']))
    if cand != prop:
        io.event('FREQUENCY_SATURATION', raw_frequency_Hz=prop)
    io.event('PHASE_UPDATE', measured_error_deg=error,
             measured_slope_deg_per_Hz=slope, proposed_frequency_Hz=cand,
             law=law, uncapped_step_Hz=raw)
    return cand


def run_variant(E, C, model, cfg, ids, law, clip, deembed_on, suite='CANDIDATE'):
    eng = E.Engine(cfg, ids, 'PHASE_FEEDBACK', suite)
    io = C.Executor(eng)
    de = Deembed(model) if deembed_on else None
    base = model.scenario_map()['CASE_000_BASELINE']
    f0 = cfg['initial_frequency_Hz']
    if de is None:
        tp = float(model.response(f0, base)['phase_deg'][0])
    else:
        # Same freeze procedure, same calibration case, de-embedded quantity.
        q = model.response(f0, base)
        z = de(complex(q['v_input'][0]) / complex(q['i_source'][0]), f0)
        tp = math.degrees(math.atan2(z.imag, z.real))
    target, last = float(f0), None
    while not io.finished:
        if last is not None:
            target = update(E, C, io, last, tp, target, law, clip, de)
        if not io.finished:
            last = io.control(target, 1.)
    return eng, tp


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
def s1(E, C, model, cfg, ids, opt):
    it_us = cfg['control_tick_us'] + 2 * cfg['scan_point_us']
    print('S1 迭代成本与每段需要的频率行程')
    print('  一次更新 = 1 个控制周期 %.0f ms + 2 个探针 %.1f ms = %.1f ms'
          % (cfg['control_tick_us'] / 1000, cfg['scan_point_us'] / 1000,
             it_us / 1000))
    print('  一段 %.0f ms 最多 %d 次更新；比例律封顶 %.0f Hz/次 -> 段内最多移动 %.0f Hz'
          % (cfg['segment_us'] / 1000, cfg['segment_us'] // it_us,
             cfg['phase_max_step_Hz'],
             (cfg['segment_us'] // it_us) * cfg['phase_max_step_Hz']))
    eng, tp = run_variant(E, C, model, cfg, ids, 'PROPORTIONAL',
                          cfg['phase_max_step_Hz'], False, 'S1')
    first = {}
    for r in eng.rows:
        first.setdefault(r['segment_index'], r['frequency_Hz'])
    print()
    print('  %3s %-20s %11s %11s %11s' % ('段', '场景', '段起频率Hz',
                                          '功率最优Hz', '真实需移动Hz'))
    need = []
    for seg, case in enumerate(ids):
        d = opt[case][0] - first[seg]
        need.append(abs(d))
        print('  %3d %-20s %11.0f %11.0f %+11.0f'
              % (seg, case, first[seg], opt[case][0], d))
    print('  单段最大真实需移动 %.0f Hz，是段内可移动上限的 %.1f 倍'
          % (max(need), max(need) / ((cfg['segment_us'] // it_us)
                                     * cfg['phase_max_step_Hz'])))
    return eng, tp


def s2(cfg, eng):
    gain, clip = cfg['phase_gain_Hz_per_deg'], cfg['phase_max_step_Hz']
    it = (cfg['control_tick_us'] + 2 * cfg['scan_point_us']) / 1e6
    print()
    print('S2 比例增益在替代什么')
    print('  比例律 df = clip(%.1f Hz/deg x error x sign(slope), +-%.0f Hz)'
          % (gain, clip))
    print('  割线步   df = error / slope            量纲 deg / (deg/Hz) = Hz')
    print('  两者相等仅当 |dphi/df| = 1/gain = %.4f deg/Hz。'
          '代码测了 slope 却只用了它的符号，幅值被丢弃。' % (1 / gain))
    ups = collections.defaultdict(list)
    for e in eng.events:
        if e['event'] == 'PHASE_UPDATE':
            ups[e['time_us'] // cfg['segment_us']].append(e)
    print()
    print('  %3s %6s %10s %12s %11s %10s'
          % ('段', '更新数', '均|df|Hz', '均|slope|', '隐含1/|s|', '欠步倍数'))
    allp, alln = [], []
    for seg in sorted(ups):
        es = ups[seg]
        dfs = [abs(float(np.clip(gain * e['measured_error_deg']
                                 * math.copysign(1, e['measured_slope_deg_per_Hz']),
                                 -clip, clip))) for e in es]
        sl = [abs(e['measured_slope_deg_per_Hz']) for e in es]
        nw = [abs(e['measured_error_deg'] / e['measured_slope_deg_per_Hz'])
              for e in es if e['measured_slope_deg_per_Hz'] != 0]
        md, ms = sum(dfs) / len(dfs), sum(sl) / len(sl)
        mn = sum(nw) / len(nw) if nw else float('nan')
        allp.extend(dfs)
        alln.extend(nw)
        print('  %3d %6d %10.1f %12.5f %11.1f %10.1f'
              % (seg, len(es), md, ms, 1 / ms if ms else float('inf'),
                 mn / md if md else float('nan')))
    mp, mnn = sum(allp) / len(allp), sum(alln) / len(alln)
    print('  全程: 比例步均值 %.1f Hz，割线步均值 %.0f Hz，欠步 %.1f 倍'
          % (mp, mnn, mnn / mp))
    print('  实测爬升率 %.1f Hz / %.0f ms = %.2f kHz/s（封顶爬升率 %.1f kHz/s）'
          % (mp, it * 1000, mp / it / 1000, clip / it / 1000))


def s3s4(model, cfg, ids, opt, tp):
    base = model.scenario_map()['CASE_000_BASELINE']
    de = Deembed(model)
    f0 = cfg['initial_frequency_Hz']
    q = model.response(f0, base)
    z = de(complex(q['v_input'][0]) / complex(q['i_source'][0]), f0)
    tb = math.degrees(math.atan2(z.imag, z.real))
    lo, hi = cfg['frequency_min_Hz'], cfg['frequency_max_Hz']
    gate = cfg['capture_threshold']
    print()
    print('S3/S4 冻结相位目标在功率最优处是否可解')
    print('  arg(Z_in)  目标 %+.6f deg（正式策略所闭的量）' % tp)
    print('  arg(Z_bvd) 目标 %+.6f deg（用标称 L 型网络去嵌后，来源 %s）'
          % (tb, de.origin))
    print('  判据: 解处功率 / 该场景参考最优功率 >= %.0f%% 才可能达标' % (100 * gate))
    print()
    rows = []
    for c in unique_cases(ids):
        s = model.scenario_map()[c]
        fopt, popt = opt[c]
        cells, bests = [], []
        for fn, t in ((arg_zin, tp), (arg_zbvd, tb)):
            rs = roots(lambda f, sc: fn(model, f, sc), s, t, lo, hi)
            fr = [100 * float(model.response(f, s)['p_rm_W'][0]) / popt for f in rs]
            bests.append(max(fr) if fr else 0.)
            cells.append(', '.join('%.0f:%.1f%%' % (f, r)
                                   for f, r in zip(rs, fr)) or '带内无解')
        rows.append((c, fopt, cells, bests))
        print('  %-20s 最优 %8.0f Hz' % (c, fopt))
        print('      arg(Z_in) 的解: %s' % cells[0])
        print('      arg(Z_bvd)的解: %s' % cells[1])
    print()
    for i, nm in enumerate(('arg(Z_in) ', 'arg(Z_bvd)')):
        b = [r[3][i] for r in rows]
        ok = sum(1 for v in b if v >= 100 * gate)
        print('  %s 存在达标解 %d/%d 场景；各场景最好解的功率占比 最小 %.1f%% '
              '中位 %.1f%% 均值 %.1f%%'
              % (nm, ok, len(rows), min(b), float(np.median(b)), sum(b) / len(b)))
    print('  两种判据的达标场景数相同；差别在其余场景是"灾难"还是"差一点"。')
    # Does the error even change sign near the optimum?
    print()
    print('  在功率最优点 +-3 kHz、1 Hz 细网格上 arg(Z_in)-目标 的取值范围:')
    for c, fopt, _, bests in rows:
        if bests[0] >= 100 * gate:
            continue
        s = model.scenario_map()[c]
        w = np.arange(fopt - 3000, fopt + 3000.5, 1.0)
        e = np.array([arg_zin(model, f, s) - tp for f in w])
        print('      %-20s [%+9.4f, %+9.4f] deg，变号 %d 次'
              % (c, e.min(), e.max(), int(np.sum(e[:-1] * e[1:] < 0))))
    print('      -> 这些场景的最优点附近根本没有解，调快环路只会更快到错的地方。')


def s5(E, C, M, model, cfg, ids):
    ref = M.references(cfg)
    variants = (('A_原样_比例律', 'PROPORTIONAL', cfg['phase_max_step_Hz'], False),
                ('B_割线步_原限幅', 'SECANT', cfg['phase_max_step_Hz'], False),
                ('C_割线步_限幅5kHz', 'SECANT', 5000.0, False),
                ('D_割线步_标称去嵌', 'SECANT', 5000.0, True))
    print()
    print('S5 四种更新律，用平台自己的 evaluate() 评分')
    print('  A 必须复现已登记批次（6/12 达标、57.34% 能量），否则以下数字不作证据。')
    print()
    tables = {}
    for name, law, clip, de in variants:
        eng, tp = run_variant(E, C, model, cfg, ids, law, clip, de, 'S5')
        per, summ = M.evaluate(eng.rows, eng.events, cfg, ref)
        cnt = collections.Counter(e['event'] for e in eng.events)
        pv = max(r['pre_guard_vport_Vpp'] for r in eng.rows)
        hv = sum(r['duration_us'] for r in eng.rows
                 if r.get('actual_hard_violation')) / 1000
        print('  %-18s 达标 %2d/12  能量 %6.2f%%  更新 %3d  探针失败 %2d  '
              '斜率失败 %2d  去嵌失败 %2d  保护前峰值 %7.3f Vpp  硬越限 %.3f ms'
              % (name, summ['settled_segments'], summ['energy_capture_pct'],
                 cnt['PHASE_UPDATE'], cnt['PHASE_PROBE_FAILED'],
                 cnt['PHASE_SLOPE_UNRESOLVED'], cnt['PHASE_DEEMBED_FAILED'],
                 pv, hv))
        tables[name] = per
    for title, key, fmt in (('每段首个合格样本时刻 (ms)', 'first_qualified_sample_ms', '%7.0f'),
                            ('每段能量捕获 (%)', 'energy_capture_pct', '%7.1f')):
        print()
        print('  ' + title)
        print('  %-18s' % '' + ''.join('%7d' % i for i in range(len(ids))))
        for name in tables:
            cells = []
            for r in tables[name]:
                v = r[key]
                cells.append('      —' if v is None else fmt % v)
            print('  %-18s' % name + ''.join(cells))
        print('  %-18s' % '场景' + ''.join('%7s' % c.replace('CASE_', '')[:6]
                                           for c in ids))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--sections', default=','.join(SECTIONS))
    a = ap.parse_args()
    want = [s.strip().upper() for s in a.sections.split(',')]
    root = pathlib.Path(a.root).resolve()
    E, C, M, model, cfg = build(root)
    ids = cfg['historical_schedule']
    opt = optima(model, cfg)
    print('源目录 %s' % root)
    print('参考最优取自 %.0f Hz 网格上的 p_rm_W 峰值；门槛 %.0f%%；'
          '达标还要求 %d 个连续 %d ms 格点样本。\n'
          % (25.0, 100 * cfg['capture_threshold'], cfg['continuous_samples'],
             cfg['control_tick_us'] / 1000))
    eng = tp = None
    if 'S1' in want or 'S2' in want:
        eng, tp = s1(E, C, model, cfg, ids, opt)
    if 'S2' in want:
        s2(cfg, eng)
    if 'S3' in want or 'S4' in want:
        if tp is None:
            tp = float(model.response(cfg['initial_frequency_Hz'],
                                      model.scenario_map()['CASE_000_BASELINE']
                                      )['phase_deg'][0])
        s3s4(model, cfg, ids, opt, tp)
    if 'S5' in want:
        s5(E, C, M, model, cfg, ids)


if __name__ == '__main__':
    main()
