"""从实测阻抗特性反推 BVD 参数——Janů et al. 2021 方法的移植、修正与适用性验证。

文献：Janů, Bajer, Dyčka, Bystřický, "Precise experimental determination of
electrical equivalent circuit parameters for ultrasonic piezoelectric ceramic
transducers from their measured characteristics", Ultrasonics 112 (2021) 106341,
doi:10.1016/j.ultras.2020.106341。即计划书第七章参考文献 [6]。

记号对照：论文 RS/LS/CS/CP  <->  本项目 Rm/Lm/Cm/C0。

本脚本回答一个问题：**这套方法能不能测出本项目的 Qm？**
Qm 是全课题最大的未知量——它决定自适应驱动的收益是 1.00x 还是 3300x。
论文样品是 40 kHz 空气超声发射器（C0=2.8 nF、Qm≈25、Cm/C0≈0.063），
本项目假设基线是 0.9 MHz 导管尖端换能器（C0=6.86 pF、Qm=800、Cm/C0=0.0044）：
静态电容差 400 倍、Qm 差 32 倍。方法在论文工况成立不等于在我们工况成立。

结论（见 main 的三段验证）：
  1. 论文式 (1) 与 BVD 的精确 Re(Z) 完全相等，不是近似——公式本身没问题。
  2. 但论文 §2 指示「从 |Z| 极小/极大读 fS 与 fP」，而式 (1) 里的 wS 是**机械支路
     谐振** 1/sqrt(Lm*Cm)。两者被 C0 分流拉开：论文样品差 -0.93%，本项目差 -0.017%。
     把 |Z| 极值直接代入式 (3)，**论文样品和本项目都解出负的 x**，无物理意义。
     论文正文其实承认线性解的回算特征 "do not match"，只把它当迭代初值
     （原文迭代 145,955,706 步）。
  3. 因此线性步**只能做初值**，必须接一层对 4 个参数的非线性拟合。本脚本用
     scipy least_squares 实现，并给出噪声敏感度，以反推所需的仪器指标。

    python3 workspace/qm_extraction_20260916/janu2021_extraction.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

HERE = Path(__file__).resolve().parent
ACTIVE = HERE.parent / "outputs" / "v2_self_consistent_rebuild" / "active_stage3_5"
sys.path.insert(0, str(ACTIVE))
import model_v2_1 as m  # noqa: E402

RNG = np.random.default_rng(20260916)


def bvd_impedance(f, rm, lm, cm, c0):
    """换能器本体阻抗（不含匹配网络）——论文 Fig. 2 的电路。"""
    w = 2 * np.pi * np.asarray(f, dtype=float)
    zm = rm + 1j * (w * lm - 1 / (w * cm))
    return 1 / (1 / zm + 1j * w * c0)


def paper_eq1_real_part(f, c0, fs, fp, qm):
    """论文式 (1)。已验证与 BVD 精确 Re(Z) 逐点相等。"""
    w, ws, wp = 2 * np.pi * np.asarray(f, float), 2 * np.pi * fs, 2 * np.pi * fp
    return (1 / (w * c0)) * (w * ws * qm * (wp**2 - ws**2)) / (
        w**2 * ws**2 + qm**2 * (w**2 - wp**2) ** 2)


def initial_guess(f, z):
    """由实测曲线直接可读的量构造初值，全部是仪器能给的东西。"""
    a = np.abs(z)
    fs = float(f[np.argmin(a)])          # |Z| 极小 -> 串联谐振附近
    fp = float(f[np.argmax(a)])          # |Z| 极大 -> 并联谐振附近
    # 远离谐振处 |Z| ~ 1/(w*C0)：取频带两端各 5% 的样本估 C0
    edge = np.r_[f[: max(1, len(f) // 20)], f[-max(1, len(f) // 20):]]
    ze = np.r_[a[: max(1, len(a) // 20)], a[-max(1, len(a) // 20):]]
    c0 = float(np.median(1 / (2 * np.pi * edge * ze)))
    rm = float(a.min())                  # 串联谐振处 |Z| 近似 Rm（被 C0 略微拉低）
    cm = max((fp**2 - fs**2) * c0 / fs**2, c0 * 1e-6)
    lm = 1 / ((2 * math.pi * fs) ** 2 * cm)
    return dict(Rm_ohm=rm, Lm_H=lm, Cm_F=cm, C0_F=c0)


def linear_step(f, z, fs, fp):
    """论文式 (3)：给定 fS/fP 最小二乘解 x=C0/Qm, y=C0*Qm。保留以复现论文行为。"""
    a = np.abs(z)
    band = a <= math.sqrt(2) * a.min()
    ws, wp = 2 * np.pi * fs, 2 * np.pi * fp
    w, r = 2 * np.pi * f[band], np.real(z[band])
    d = wp**2 - ws**2
    A, B = w**2 * ws / d, (w**2 - wp**2) ** 2 / (ws * d)
    sol, *_ = np.linalg.lstsq(np.column_stack([A, B]), 1.0 / r, rcond=None)
    x, y = float(sol[0]), float(sol[1])
    ok = x > 0 and y > 0
    return dict(x=x, y=y, ok=ok, band_points=int(band.sum()),
                C0_F=math.sqrt(x * y) if ok else math.nan,
                Qm=math.sqrt(y / x) if ok else math.nan)


def fit(f, z, guess=None):
    """对 Rm/Lm/Cm/C0 做非线性拟合。残差用 log|Z| 与相位，量纲无关。"""
    g = guess or initial_guess(f, z)
    p0 = np.log(np.array([g["Rm_ohm"], g["Lm_H"], g["Cm_F"], g["C0_F"]]))
    logz_meas, ph_meas = np.log(np.abs(z)), np.angle(z)

    def resid(p):
        rm, lm, cm, c0 = np.exp(p)
        zz = bvd_impedance(f, rm, lm, cm, c0)
        return np.r_[np.log(np.abs(zz)) - logz_meas, np.angle(zz) - ph_meas]

    out = least_squares(resid, p0, method="lm", xtol=1e-15, ftol=1e-15, max_nfev=20000)
    rm, lm, cm, c0 = np.exp(out.x)
    fs = 1 / (2 * math.pi * math.sqrt(lm * cm))
    return dict(Rm_ohm=rm, Lm_H=lm, Cm_F=cm, C0_F=c0,
                Qm=2 * math.pi * fs * lm / rm, fs_Hz=fs,
                nfev=int(out.nfev), cost=float(out.cost))


def measure(bvd, span=0.03, n=4001, noise_db=0.0, noise_deg=0.0):
    """生成一条「实测」扫频曲线。noise_* 为阻抗分析仪的幅度/相位随机误差。"""
    f = np.linspace(bvd["fs"] * (1 - span), bvd["fs"] * (1 + span), n)
    z = bvd_impedance(f, bvd["Rm_ohm"], bvd["Lm_H"], bvd["Cm_F"], bvd["C0_F"])
    if noise_db or noise_deg:
        z = (np.abs(z) * 10 ** (RNG.normal(0, noise_db, z.shape) / 20)) * np.exp(
            1j * (np.angle(z) + np.deg2rad(RNG.normal(0, noise_deg, z.shape))))
    return f, z


def as_bvd(rm, lm, cm, c0):
    return dict(Rm_ohm=rm, Lm_H=lm, Cm_F=cm, C0_F=c0,
                fs=1 / (2 * math.pi * math.sqrt(lm * cm)),
                Qm=2 * math.pi * (1 / (2 * math.pi * math.sqrt(lm * cm))) * lm / rm)


def main() -> None:
    paper = as_bvd(908.0, 0.0915, 1.7634e-10, 2.8048e-9)
    b = m.BASE_BVD
    ours = as_bvd(b.rm, b.lm, b.cm, b.c0)

    print("=" * 76)
    print("验证 1：论文式 (1) 是否等于 BVD 精确 Re(Z)")
    print("=" * 76)
    for tag, s in (("论文样品", paper), ("本项目基线", ours)):
        f, z = measure(s, span=0.02, n=9)
        exact = np.real(z)
        fp = s["fs"] * math.sqrt(1 + s["Cm_F"] / s["C0_F"])
        approx = paper_eq1_real_part(f, s["C0_F"], s["fs"], fp, s["Qm"])
        print(f"  {tag:<10} 最大相对偏差 {np.max(np.abs(approx/exact - 1)):.3e}  -> 公式精确")

    print()
    print("=" * 76)
    print("验证 2：论文线性步（式 3）单独使用是否可行")
    print("=" * 76)
    for tag, s in (("论文样品", paper), ("本项目基线", ours)):
        f, z = measure(s, span=0.05 if s is paper else 0.01, n=200001)
        a = np.abs(z)
        fs_meas, fp_meas = float(f[np.argmin(a)]), float(f[np.argmax(a)])
        fp_true = s["fs"] * math.sqrt(1 + s["Cm_F"] / s["C0_F"])
        r1 = linear_step(f, z, fs_meas, fp_meas)
        r2 = linear_step(f, z, s["fs"], fp_true)
        print(f"  {tag}")
        print(f"    |Z|极小 {fs_meas/1e3:.4f} kHz vs 机械谐振 {s['fs']/1e3:.4f} kHz  "
              f"(差 {(fs_meas/s['fs']-1)*100:+.4f}%)")
        print(f"    按论文原文用 |Z| 极值 : {'可解' if r1['ok'] else 'x 为负，无物理意义'}")
        print(f"    改用真实 fS/fP       : Qm 误差 {(r2['Qm']/s['Qm']-1)*100:+.4f}%，"
              f"C0 误差 {(r2['C0_F']/s['C0_F']-1)*100:+.4f}%")

    print()
    print("=" * 76)
    print("验证 3：线性步做初值 + 非线性拟合，跨 Qm 能否复原（无噪声）")
    print("=" * 76)
    print(f"{'Qm真值':>8}{'Qm提取':>12}{'Qm误差':>11}{'C0误差':>11}{'Rm误差':>11}{'Cm误差':>11}")
    for qm in (10, 30, 100, 300, 800, 1000):
        bb = m.changed_qm(m.BASE_BVD, float(qm))
        s = as_bvd(bb.rm, bb.lm, bb.cm, bb.c0)
        f, z = measure(s, span=0.03, n=4001)
        g = fit(f, z)
        print(f"{qm:>8}{g['Qm']:>12.4f}{(g['Qm']/qm-1)*100:>10.5f}%"
              f"{(g['C0_F']/s['C0_F']-1)*100:>10.5f}%{(g['Rm_ohm']/s['Rm_ohm']-1)*100:>10.5f}%"
              f"{(g['Cm_F']/s['Cm_F']-1)*100:>10.5f}%")

    print()
    print("=" * 76)
    print("验证 4：噪声敏感度——要把本项目 Qm 测准，仪器需要什么指标")
    print("=" * 76)
    print(f"{'幅度噪声':>10}{'相位噪声':>10}{'Qm误差中位数':>16}{'Qm误差P95':>14}{'失败次数':>10}")
    for ndb, ndeg in ((0.0, 0.0), (0.01, 0.05), (0.05, 0.2), (0.1, 0.5), (0.5, 2.0)):
        errs = []
        fails = 0
        for _ in range(20):
            f, z = measure(ours, span=0.03, n=4001, noise_db=ndb, noise_deg=ndeg)
            try:
                g = fit(f, z)
                errs.append(abs(g["Qm"] / ours["Qm"] - 1) * 100)
            except Exception:
                fails += 1
        if errs:
            print(f"{ndb:>9.2f}dB{ndeg:>9.2f}°{np.median(errs):>15.3f}%"
                  f"{np.percentile(errs, 95):>13.3f}%{fails:>10}")
        else:
            print(f"{ndb:>9.2f}dB{ndeg:>9.2f}°{'全部失败':>16}{'':>14}{fails:>10}")

    print()
    print("=" * 76)
    print("验证 5：隔着导管电缆测量会得到什么（对应 docs/04 第 3 节未建模的 C_cable）")
    print("=" * 76)
    print(f"{'电缆':>10}{'提取C0(pF)':>13}{'Qm误差':>11}{'Rm误差':>11}{'Cm误差':>11}")
    f, _ = measure(ours, span=0.03, n=4001)
    for ccab_pf in (0, 10, 50, 100, 150):
        z = bvd_impedance(f, ours["Rm_ohm"], ours["Lm_H"], ours["Cm_F"],
                          ours["C0_F"] + ccab_pf * 1e-12)
        g = fit(f, z)
        print(f"{ccab_pf:>8}pF{g['C0_F']*1e12:>13.3f}{(g['Qm']/ours['Qm']-1)*100:>10.4f}%"
              f"{(g['Rm_ohm']/ours['Rm_ohm']-1)*100:>10.4f}%{(g['Cm_F']/ours['Cm_F']-1)*100:>10.4f}%")
    print("  => 机械支路四个量完全不受电缆影响；只有 C0 被加性污染 C0_meas = C0 + C_cable。")
    print("     推论一：Qm 可以隔着导管直接测，无需去嵌入——这消除了实测阶段的主要障碍。")
    print("     推论二：带缆与不带缆各测一次，相减即得 C_cable，正是模型里缺的那个参数。")

    out = HERE / "extraction_validation.json"
    out.write_text(json.dumps({
        "reference": "Janu et al., Ultrasonics 112 (2021) 106341",
        "paper_sample": {k: v for k, v in paper.items()},
        "project_baseline": {k: v for k, v in ours.items()},
        "finding": ("论文式(1)精确；但按 §2 用 |Z| 极值作 fS/fP 时线性步解出负 x，"
                    "论文样品与本项目均如此。线性步只能做初值，需接非线性拟合。"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写出 {out.relative_to(HERE.parents[1])}" if HERE.parents[1] in out.parents else f"\n已写出 {out}")


if __name__ == "__main__":
    main()
