#!/usr/bin/env python3
"""审核 Codex 的峰宽自适应寻优原型，并与「去嵌导纳（动生电抗）模型预测」比较（review/30）。

    python review/controller_speed_study.py [--codex <Codex 交付目录>] [--seeds N] [--out <目录>]

只读；--out 时另写一份 JSON（拒绝 workspace/ 与 outputs/）。运行期只依赖 numpy。
--codex 默认 results/controller_probe_review_20261017/codex_inputs/；其中 width_aware_probe.py
按文件路径导入（不改 sys.path），复现时在临时目录里原样运行（python -I）。

和 Codex 原型同一个口径：50 Ω 戴维南源直接驱动四元件 BVD，无线缆、无匹配；源开路电压标定为未扰动 fs 处
陶瓷端 100 Vpp；可行功率 = 端口有功功率按 100 Vpp、两处 4 mA 等比降幅后的值。控制器只读它测过的点；
密网格最优值只用于事后评分。这是测点数研究，不是时间仿真。

检查项
  0. 原样运行 Codex 的脚本，与它交付的 probe_results.json 逐项比较。
  1. 把 Codex 的启动扫描与局部重捕获放到更宽的条件下：
     - Q 从 13.8 到 800：合成候选、A/B/C、A 与 B 的无法兰端面（review/29 第 7.4 节）、默认基线 Qm=800；
     - 0.8 MHz 的 APC 880 D 0.5 mm（review/30 第六节），分别用 Codex 的 0.8–1.0 MHz 频带与以 0.8 MHz 为中心的 0.7–0.9 MHz；
     - 扰动以峰宽 w = fs/Q 为单位：fs 移 ±0.25、±1、±2 w，另加 Rm +30%、C0 +20%；
     - 测量噪声：每个测点的可行功率与导纳各加相对 σ = 0、0.5%、2% 的随机误差（与 review/27 的噪声研究同量级）。
     触发规则与 Codex 相同（功率或导纳相对参考变化 >5%），并按它 README 的写法要求连续两次确认。
  2. 同样的启动测点、同样的触发，换一种重捕获：用启动测点拟合 BVD（C0 由黄金分割、动生支路由线性最小二乘），
     之后每测一个点就用它的去嵌动生电抗更新 fs（两点时同时更新 Lm），按模型算出约束下的最优频率，直接去那里测；
     模型预测与实测功率不符或 5 点内不收敛时，退回 Codex 的局部重捕获（测点照计）。
  3. 时间账：把测点数换成时间要看每点驻留与平台的其他环节，按 review/27 记录的现行参数与物理时间常数列出。
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import math
import pathlib
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / 'results'
DEFAULT_CODEX = RESULTS / 'controller_probe_review_20261017' / 'codex_inputs'
PROFILES = RESULTS / 'codex_baseline_review_20261016' / 'codex_inputs' / 'bvd_candidate_profiles.json'
BOUNDARY = RESULTS / 'radiation_boundary_20261017' / 'radiation_boundary_check.json'
CANDIDATES_0P8 = RESULTS / 'candidates_0p8MHz_20261017' / 'candidates_0p8MHz.json'

BAND_CODEX = (800e3, 1000e3)
BAND_0P8 = (700e3, 900e3)
SHIFTS_W = (-2.0, -1.0, -0.25, 0.25, 1.0, 2.0)
NOISE = (0.0, 0.005, 0.02)
TRIGGER = 0.05
GOOD = 0.98                      # 评分门槛：达到离线最优的 98%


def load_codex(codex_dir):
    spec = importlib.util.spec_from_file_location('codex_width_aware_probe', codex_dir / 'width_aware_probe.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # dataclass 在执行模块时要从 sys.modules 查到它
    flag, sys.dont_write_bytecode = sys.dont_write_bytecode, True     # 不在存档目录里留 __pycache__
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = flag
    return mod


def reproduce(codex_dir):
    with tempfile.TemporaryDirectory() as tmp:
        t = pathlib.Path(tmp)
        (t / 'adaptive_controller_study').mkdir()
        (t / 'cto_candidate_registration' / 'provenance').mkdir(parents=True)
        shutil.copy2(codex_dir / 'width_aware_probe.py', t / 'adaptive_controller_study')
        shutil.copy2(PROFILES, t / 'cto_candidate_registration' / 'provenance' / 'bvd_candidate_profiles.json')
        run = subprocess.run([sys.executable, '-I', 'width_aware_probe.py'], cwd=t / 'adaptive_controller_study',
                             capture_output=True, text=True)
        if run.returncode:
            raise SystemExit('Codex 脚本运行失败：\n' + run.stderr[-2000:])
        got = json.loads(run.stdout)
    ref = json.loads((codex_dir / 'probe_results.json').read_text(encoding='utf-8'))
    assert len(got) == len(ref)
    worst = 0.0
    for g, r in zip(got, ref):
        assert g.keys() == r.keys()
        for k in r:
            if isinstance(r[k], float):
                worst = max(worst, abs(g[k] - r[k]) / max(abs(r[k]), 1e-300))
            else:
                assert g[k] == r[k], (k, g[k], r[k])
    return dict(rows=len(ref), max_rel_diff=worst)


# ------------------------------------------------------------------ 器件集合
def bvd_from(mod, c0, rm, fs, q):
    w = 2 * math.pi * fs
    lm = q * rm / w
    return mod.BVD(c0, rm, lm, 1.0 / (w * w * lm))


def cases(mod):
    out = []
    pb = json.loads(PROFILES.read_text(encoding='utf-8'))
    syn = bvd_from(mod, 4.1148384631190455e-12, 12254.90196078431, 900e3, 13.810857823361614)   # P3 合成候选
    out.append(('Q13.8 合成候选', syn, BAND_CODEX))
    for name, p in zip('ABC', pb):
        out.append((f'{name}（Codex）', mod.BVD(p['C0_F'], p['Rm_ohm'], p['Lm_H'], p['Cm_F']), BAND_CODEX))
    rb = json.loads(BOUNDARY.read_text(encoding='utf-8'))['radiation_boundary']
    for name, pair in (('A 无法兰', rb[0]), ('B 无法兰', rb[1])):
        s = pair['unflanged']
        out.append((name, bvd_from(mod, s['C0_clamped_pF'] * 1e-12, s['Rm_ohm'], s['fs_Hz'], s['Q']), BAND_CODEX))
    out.append(('Qm=800 默认基线', bvd_from(mod, 6.858064105198409e-12, 7352.941176470586, 900e3, 800.0), BAND_CODEX))
    c8 = json.loads(CANDIDATES_0P8.read_text(encoding='utf-8'))['baffled']
    s = next(r for r in c8 if r['material'] == 'APC880' and abs(r['D_mm'] - 0.5) < 1e-9)
    b08 = bvd_from(mod, s['C0_clamped_pF'] * 1e-12, s['Rm_ohm'], s['fs_Hz'], s['Q'])
    out.append(('0.8 MHz B，频带 0.8–1.0', b08, BAND_CODEX))
    out.append(('0.8 MHz B，频带 0.7–0.9', b08, BAND_0P8))
    return out


def disturbances(mod, bvd):
    w = bvd.fs / (2 * math.pi * bvd.fs * bvd.lm / bvd.rm)
    out = []
    for k in SHIFTS_W:
        fs = bvd.fs + k * w
        out.append((f'fs {k:+g} w', dataclasses.replace(bvd, cm=1.0 / ((2 * math.pi * fs) ** 2 * bvd.lm))))
    out.append(('Rm +30%', dataclasses.replace(bvd, rm=bvd.rm * 1.3)))
    out.append(('C0 +20%', dataclasses.replace(bvd, c0=bvd.c0 * 1.2)))
    return out


# ------------------------------------------------------------------ 测量
class Meter:
    """被测对象：返回带噪声的可行功率与陶瓷端导纳，并计数测点。"""

    def __init__(self, mod, bvd, src, sigma, rng):
        self.mod, self.bvd, self.src, self.sigma, self.rng = mod, bvd, src, sigma, rng
        self.count = 0

    def __call__(self, f):
        self.count += 1
        s = float(self.mod.feasible_score_original(f, self.bvd, self.src))
        y = self.mod.ceramic_admittance(f, self.bvd)
        if self.sigma:
            s *= 1.0 + self.sigma * self.rng.standard_normal()
            y *= 1.0 + self.sigma * (self.rng.standard_normal() + 1j * self.rng.standard_normal()) / math.sqrt(2)
        return s, y


def argmax_refined(score, lo, hi, coarse):
    """粗网格取最大，再在邻域按 1 Hz 细化（限流时可行功率在两条限值交点处有折角）。"""
    f = np.arange(lo, hi + 1, coarse)
    k = int(np.argmax(score(f)))
    f = np.arange(max(lo, f[k] - coarse), min(hi, f[k] + coarse) + 0.5, 1.0)
    p = score(f)
    k = int(np.argmax(p))
    return float(f[k]), float(p[k])


def optimum(mod, bvd, src, band):
    return argmax_refined(lambda f: mod.feasible_score_original(f, bvd, src), band[0], band[1], 50.0)


def optimum_wide(mod, bvd, src, band):
    """不受频带限制的最优（用来看频带本身是否把真峰挡在外面）。"""
    return optimum(mod, bvd, src, (min(band[0], 600e3), max(band[1], 1100e3)))


def triggered(meter_ref, meter_now, f):
    """Codex 的规则：功率或导纳相对参考变化 >5%，连续两次。"""
    s0, y0 = meter_ref(f)
    hits = 0
    for _ in range(2):
        s1, y1 = meter_now(f)
        hits += abs(s1 / s0 - 1) > TRIGGER or abs(y1 / y0 - 1) > TRIGGER
    return hits == 2


# ------------------------------------------------------------------ Codex 的方法（导入原函数）
def codex_startup(mod, meter):
    original = mod.feasible_score_original
    mod.feasible_score = lambda f, bvd, src: meter(float(f))[0]
    try:
        return mod.startup(meter.bvd, meter.src)
    finally:
        mod.feasible_score = original


def codex_reacquire(mod, meter, start_f, width):
    original = mod.feasible_score_original
    mod.feasible_score = lambda f, bvd, src: meter(float(f))[0]
    try:
        f, _, _ = mod.local_reacquire(start_f, width, meter.bvd, meter.src)
    finally:
        mod.feasible_score = original
    return f


# ------------------------------------------------------------------ 去嵌导纳模型预测
def fit_bvd(mod, f, y):
    """C0 用黄金分割，动生支路（Rm、Lm、1/Cm）在给定 C0 时是加权线性最小二乘。"""
    f, y = np.asarray(f), np.asarray(y)
    w = 2 * np.pi * f
    w0 = float(np.median(w))
    u = w / w0

    def solve(c0):
        ym = y - 1j * w * c0
        z = 1.0 / ym
        wt = np.abs(ym) ** 2
        rm = float(np.sum(wt * z.real) / np.sum(wt))
        a = np.column_stack([u, -1.0 / u]) * np.sqrt(wt)[:, None]
        (p, q), *_ = np.linalg.lstsq(a, z.imag * np.sqrt(wt), rcond=None)
        lm, dinv = p / w0, q * w0
        model = 1j * w * c0 + 1.0 / (rm + 1j * (lm * w - dinv / w))
        return float(np.sum(np.abs(model - y) ** 2)), (c0, rm, lm, dinv)

    def resid(c0):
        r, (_, rm, lm, dinv) = solve(c0)
        return r if (rm > 0 and lm > 0 and dinv > 0) else math.inf

    # 谐振附近 Im(Y)/ω 远大于 C0，单段黄金分割会落进非物理的局部极小：先粗网格取物理解中残差最小的格点，再在两邻格之间细化
    grid = np.linspace(0.0, 2.0 * float(np.max(np.abs(y.imag / w))), 401)
    res = np.array([resid(c) for c in grid])
    k = int(np.argmin(res))
    if not math.isfinite(res[k]):
        return None
    lo, hi = grid[max(k - 1, 0)], grid[min(k + 1, len(grid) - 1)]
    g = (math.sqrt(5) - 1) / 2
    x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
    r1, r2 = resid(x1), resid(x2)
    for _ in range(60):
        if r1 < r2:
            hi, x2, r2 = x2, x1, r1
            x1 = hi - g * (hi - lo)
            r1 = resid(x1)
        else:
            lo, x1, r1 = x1, x2, r2
            x2 = lo + g * (hi - lo)
            r2 = resid(x2)
    c0, rm, lm, dinv = solve(0.5 * (lo + hi))[1]
    if not (rm > 0 and lm > 0 and dinv > 0):
        return None
    return mod.BVD(c0, rm, lm, 1.0 / dinv)


def model_optimum(mod, model, src, band, center=None, span=None):
    lo, hi = band if center is None else (max(band[0], center - span), min(band[1], center + span))
    return argmax_refined(lambda f: mod.feasible_score_original(f, model, src), lo, hi, 20.0)


def admittance_startup(mod, meter, band):
    """与 Codex 同样的测点（5 kHz 粗扫、最好点 ±5 kHz 内 1 kHz 细扫），另记导纳，拟合后去模型最优处复核。"""
    samples = {}
    for f in np.arange(band[0], band[1] + 1, 5_000):
        samples[float(f)] = meter(float(f))
    coarse = max(samples, key=lambda k: samples[k][0])
    for f in np.arange(max(band[0], coarse - 5_000), min(band[1], coarse + 5_000) + 1, 1_000):
        if float(f) not in samples:
            samples[float(f)] = meter(float(f))
    best = max(samples, key=lambda k: samples[k][0])
    width = mod.estimated_width({k: v[0] for k, v in samples.items()}, best)
    fs = sorted(samples)
    model = fit_bvd(mod, fs, [samples[k][1] for k in fs])
    if model is None:
        return best, None, width
    f_star, _ = model_optimum(mod, model, meter.src, band)
    s, _ = meter(f_star)
    if s < 0.97 * samples[best][0]:
        return best, model, width
    return f_star, model, width


def admittance_reacquire(mod, meter, f0, model, band):
    """每测一点：去嵌动生电抗 X → 已知 Lm 时由 X 解出新的 Cm（fs）；两点以上时由两点同时解 Lm 与 1/Cm；
    Rm 取实测 Re(Zm)。按更新后的模型算约束下的最优频率，直接去测；预测与实测相符即停。"""
    c0, lm = model.c0, model.lm
    w_est = model.fs / (2 * math.pi * model.fs * lm / model.rm)
    pts = []
    f = f0
    for _ in range(5):
        s, y = meter(f)
        zm = 1.0 / (y - 1j * 2 * math.pi * f * c0)
        pts.append((f, zm.real, zm.imag, s))
        om = 2 * math.pi * f
        # 两点斜率的噪声与点距成反比：点距 ≥ w/4 时，2% 噪声下 Lm 误差约 10%；更近就沿用原 Lm
        if len(pts) >= 2 and abs(pts[-1][0] - pts[-2][0]) > 0.25 * w_est:
            (fa, _, xa, _), (fb, _, xb, _) = pts[-2], pts[-1]
            wa, wb = 2 * math.pi * fa, 2 * math.pi * fb
            det = wa / wb - wb / wa
            lm_new = (xa / wb - xb / wa) / det
            dinv = (xa * wb - xb * wa) / det
            if lm_new > 0 and dinv > 0:
                lm = lm_new
        dinv = om * (lm * om - zm.imag)
        if dinv <= 0:
            break
        model = mod.BVD(c0, max(zm.real, 1.0), lm, 1.0 / dinv)
        w_est = model.fs / (2 * math.pi * model.fs * lm / model.rm)
        f_star, p_pred = model_optimum(mod, model, meter.src, band, center=f, span=6 * w_est)
        if abs(f_star - f) < 0.02 * w_est:
            if s >= 0.95 * p_pred:
                return f, model
            break
        f = f_star
    best = max(pts, key=lambda t: t[3])[0]
    return codex_reacquire(mod, meter, best, w_est), model


# ------------------------------------------------------------------ 一组试验
def run_case(mod, name, bvd, band, sigma, seed):
    mod.F_MIN, mod.F_MAX = band
    src = mod.calibrated_source_vpp(bvd)
    rng = np.random.default_rng(seed)
    out = dict(case=name, sigma=sigma, seed=seed, events=[])
    # 启动：两种方法各自从头扫（测点相同，后者多一个复核点）
    m = Meter(mod, bvd, src, sigma, rng)
    f_codex, width, _ = codex_startup(mod, m)
    n_codex = m.count
    m2 = Meter(mod, bvd, src, sigma, rng)
    f_adm, model, width_adm = admittance_startup(mod, m2, band)
    n_adm = m2.count
    f_opt, p_opt = optimum(mod, bvd, src, band)
    p_wide = optimum_wide(mod, bvd, src, band)[1]
    true = lambda f, b: float(mod.feasible_score_original(f, b, src))
    q = 2 * math.pi * bvd.fs * bvd.lm / bvd.rm
    out['startup'] = dict(Q=q, true_width=bvd.fs / q, f_opt=f_opt, band_limited_over_wide=p_opt / p_wide,
                          codex=dict(f=f_codex, ratio=true(f_codex, bvd) / p_opt, probes=n_codex, width=width),
                          admittance=dict(f=f_adm, ratio=true(f_adm, bvd) / p_opt, probes=n_adm,
                                          fit_ok=model is not None))
    for dname, changed in disturbances(mod, bvd):
        fo, po = optimum(mod, changed, src, band)
        ev = dict(change=dname, f_opt=fo, band_limited_over_wide=po / optimum_wide(mod, changed, src, band)[1])
        for method, f0 in (('codex', f_codex), ('admittance', f_adm)):
            ref = Meter(mod, bvd, src, sigma, rng)
            now = Meter(mod, changed, src, sigma, rng)
            if not triggered(ref, now, f0):
                ev[method] = dict(triggered=False, probes=0, ratio=true(f0, changed) / po)
                continue
            m = Meter(mod, changed, src, sigma, rng)
            if method == 'codex':
                f1 = codex_reacquire(mod, m, f0, width)
            elif model is None:
                f1 = codex_reacquire(mod, m, f0, width_adm)
            else:
                f1, _ = admittance_reacquire(mod, m, f0, model, band)
            ev[method] = dict(triggered=True, probes=m.count, ratio=true(f1, changed) / po, f=f1)
        out['events'].append(ev)
    return out


def summarize(runs):
    rows = {}
    for r in runs:
        for ev in r['events']:
            for method in ('codex', 'admittance'):
                e = ev[method]
                key = (r['case'], r['sigma'], method)
                d = rows.setdefault(key, dict(n=0, good=0, trig=0, probes=[], ratios=[]))
                d['n'] += 1
                d['good'] += e['ratio'] >= GOOD
                d['trig'] += e['triggered']
                d['ratios'].append(e['ratio'])
                if e['triggered']:
                    d['probes'].append(e['probes'])
    out = []
    for (case, sigma, method), d in rows.items():
        pr = d['probes'] or [0]
        out.append(dict(case=case, sigma=sigma, method=method, events=d['n'], good_fraction=d['good'] / d['n'],
                        worst_ratio=min(d['ratios']), mean_ratio=float(np.mean(d['ratios'])), triggered=d['trig'],
                        probes_median=float(np.median(pr)), probes_max=int(max(pr))))
    return out


# review/27 记录的现行 CAPTURE_PO 参数：连续 3 个 20 ms 样本低于参考 90% 才捕获；捕获约 45 点（Qm=800 约 75 点）；
# 捕获时幅度 0.65，之后按 2.5/s 渐升回满幅（约 140 ms）；保护跳闸另加 60 ms 停 + 100 ms 保持。
PLATFORM = dict(sample_ms=20.0, detect_samples=3, capture_points=45, capture_points_narrow=75,
                ramp_ms=(1.0 - 0.65) / 2.5 * 1e3, trip_ms=60.0 + 100.0)
PROPOSED = dict(detect_samples=2, amplitude_settle_ms=1.0)   # 前馈直接给出可行幅度；1 ms 是假设的功放建立时间


def time_budget(case_list, summary):
    """每点驻留：物理下限 5τ + 50 个载波周期（τ = 2Q/ω）；平台现行 clip(10/(π·w), 200 μs, 1.5 ms)，
    下面的时间账一律按平台驻留算。现行与建议各列一条从扰动到回到满幅的时间（不含保护跳闸）。"""
    rows = []
    for name, bvd, _ in case_list:
        q = 2 * math.pi * bvd.fs * bvd.lm / bvd.rm
        tau = 2 * q / (2 * math.pi * bvd.fs)
        w = bvd.fs / q
        dwell = min(max(10 / (math.pi * w), 200e-6), 1.5e-3)
        med = {s['method']: s['probes_median'] for s in summary if s['case'] == name and s['sigma'] == 0.005}
        cap = PLATFORM['capture_points_narrow'] if q > 200 else PLATFORM['capture_points']
        platform = dict(detect_ms=PLATFORM['detect_samples'] * PLATFORM['sample_ms'], search_ms=cap * dwell * 1e3,
                        amplitude_ms=PLATFORM['ramp_ms'])
        platform['total_ms'] = sum(platform.values())
        proposed = {}
        for ts in (20.0, 5.0):
            p = dict(detect_ms=PROPOSED['detect_samples'] * ts, search_ms=med['admittance'] * dwell * 1e3,
                     amplitude_ms=PROPOSED['amplitude_settle_ms'])
            p['total_ms'] = sum(p.values())
            proposed[f'sample_{ts:g}ms'] = p
        rows.append(dict(case=name, Q=q, fs=bvd.fs, tau_us=tau * 1e6, dwell_floor_us=(5 * tau + 50 / bvd.fs) * 1e6,
                         dwell_platform_us=dwell * 1e6, probes_codex=med['codex'], probes_admittance=med['admittance'],
                         search_codex_ms=med['codex'] * dwell * 1e3, platform_capture_po=platform, proposed=proposed,
                         trip_extra_ms=PLATFORM['trip_ms']))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--codex', default=str(DEFAULT_CODEX))
    ap.add_argument('--seeds', type=int, default=30)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    codex_dir = pathlib.Path(a.codex).resolve()
    res = dict(trigger=TRIGGER, good=GOOD, shifts_in_width=SHIFTS_W, noise=NOISE, seeds=a.seeds)

    rep = reproduce(codex_dir)
    res['reproduction'] = rep
    print(f"== 0. 原样运行 Codex 的脚本：{rep['rows']} 行全部一致，浮点量最大相对差 {rep['max_rel_diff']:.1e}")

    mod = load_codex(codex_dir)
    mod.feasible_score_original = mod.feasible_score
    case_list = cases(mod)
    runs = []
    for name, bvd, band in case_list:
        for sigma in NOISE:
            for seed in (range(a.seeds) if sigma else (0,)):
                runs.append(run_case(mod, name, bvd, band, sigma, seed))
    summary = summarize(runs)
    res['summary'] = summary
    res['startup'] = [dict(case=r['case'], sigma=r['sigma'], seed=r['seed'], **r['startup']) for r in runs]

    res['events_noise_free'] = [dict(case=r['case'], events=r['events']) for r in runs if r['sigma'] == 0]
    print('\n== 1–2. 启动（无噪声）：选中频点功率 ÷ 频带内离线最优；Codex 估得的峰宽 ÷ 真实 fs/Q；频带内最优 ÷ 不限频带最优')
    for r in runs:
        if r['sigma'] == 0:
            st = r['startup']
            print(f"  {r['case']:<20} Q {st['Q']:6.1f}"
                  f"  Codex {100*st['codex']['ratio']:6.2f}%（{st['codex']['probes']} 点，峰宽估计 ×{st['codex']['width']/st['true_width']:.2f}）"
                  f"  导纳模型 {100*st['admittance']['ratio']:6.2f}%（{st['admittance']['probes']} 点）"
                  f"  频带内/不限 {100*st['band_limited_over_wide']:6.2f}%")
    for sigma in NOISE[1:]:
        print(f'\n  启动，σ = {100*sigma:g}%（{a.seeds} 个种子）：最差的选中频点功率')
        for name, _, _ in case_list:
            sel = [r['startup'] for r in runs if r['case'] == name and r['sigma'] == sigma]
            print(f"    {name:<20} Codex 最差 {100*min(s['codex']['ratio'] for s in sel):6.2f}%"
                  f"  导纳模型最差 {100*min(s['admittance']['ratio'] for s in sel):6.2f}%")

    print('\n== 1–2. 扰动后：达到离线最优 98% 的比例、最差比值、触发后测点数（中位 / 最大）')
    for sigma in NOISE:
        print(f'  σ = {100*sigma:g}%' + ('' if sigma == 0 else f'（{a.seeds} 个种子 × 8 种扰动）'))
        for name, _, _ in case_list:
            line = f'    {name:<20}'
            for method, cn in (('codex', 'Codex'), ('admittance', '导纳模型')):
                s = next(x for x in summary if x['case'] == name and x['sigma'] == sigma and x['method'] == method)
                line += (f"  {cn} {100*s['good_fraction']:5.1f}% 最差 {100*s['worst_ratio']:6.2f}%"
                         f" 测点 {s['probes_median']:4.1f}/{s['probes_max']:2d}")
            print(line)

    print('\n  频带本身的代价（无噪声）：扰动后频带内最优 ÷ 不限频带最优，取各扰动中最小者')
    for c in res['events_noise_free']:
        worst = min(c['events'], key=lambda e: e['band_limited_over_wide'])
        print(f"    {c['case']:<20} {100*worst['band_limited_over_wide']:6.2f}%（{worst['change']}）")

    tb = time_budget(case_list, summary)
    res['time_budget'] = tb
    res['time_budget_assumptions'] = dict(platform=PLATFORM, proposed=PROPOSED)
    print('\n== 3. 时间账：从扰动到回到满幅（不含保护跳闸；驻留按平台现行规则 clip(10/(π·w), 200 μs, 1.5 ms)；测点数取 σ = 0.5% 的中位数）')
    for t in tb:
        pl, p20, p5 = t['platform_capture_po'], t['proposed']['sample_20ms'], t['proposed']['sample_5ms']
        print(f"  {t['case']:<20} Q {t['Q']:6.1f}  τ {t['tau_us']:6.1f} μs  驻留 {t['dwell_platform_us']:5.0f} μs（物理下限 {t['dwell_floor_us']:5.0f} μs）"
              f"  搜索测点 Codex {t['probes_codex']:4.1f} / 导纳模型 {t['probes_admittance']:3.1f}")
        print(f"      现行 CAPTURE_PO：检测 {pl['detect_ms']:.0f} + 捕获 {pl['search_ms']:5.1f} + 渐升 {pl['amplitude_ms']:.0f} = {pl['total_ms']:6.1f} ms"
              f"   建议（20 ms 采样）：{p20['detect_ms']:.0f} + {p20['search_ms']:4.2f} + {p20['amplitude_ms']:.0f} = {p20['total_ms']:5.1f} ms"
              f"   建议（5 ms 采样）：{p5['total_ms']:5.1f} ms")

    if a.out:
        out = pathlib.Path(a.out).resolve()
        if {'workspace', 'outputs'} & set(out.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out}')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'controller_speed_study.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n',
                                                         encoding='utf-8')
        print(f'\n已写入 {out / "controller_speed_study.json"}')


if __name__ == '__main__':
    main()
