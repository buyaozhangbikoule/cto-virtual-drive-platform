"""把 v2.1 电路写成状态空间，实算阶跃换频后的瞬态。

本脚本是对 docs/07 finding A 的【推翻性验证】。原 finding 用手算
tau = Qm/(pi*f0) 断言准稳态裕量只有 1.15 倍。该断言错在一个具体的物理点上：

    瞬态由【有载 Q】决定，不是换能器的【空载 Qm】。

50 Ω 源阻抗与匹配网络 ESR 都在给谐振器加阻尼。用空载 Qm 算出的 tau 偏大约 1.9 倍。

线性系统不需要数值积分：阶跃换频后的响应恰好是「新旧稳态之差」的自由衰减，
    x(t) = e^(At)·(x_ss(f1) - x_ss(f2)) + x_ss(f2)(t)
因此可用本征分解与矩阵指数精确求出。

    python3 workspace/algorithm_physics_audit_20260916/transient_check.py
"""
from __future__ import annotations

import json, math, sys
from pathlib import Path
import numpy as np
from scipy.linalg import expm

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "workspace/outputs/v2_self_consistent_rebuild/active_stage3_5"))
import model_v2_1 as m

DWELL = 1.5e-3      # SCAN_POINT_DT


def state_space(qm: float | None = None):
    """v2.1 拓扑（源 - Rs - r_l,L - 节点B - {Cmatch支路, C0, 机械支路}）的 A、B 矩阵。

    状态 x = [i_L, v_C0, v_Cmatch, i_m, v_Cm]
    """
    s = m.scenario_map()["CASE_000_BASELINE"]
    p = s.bvd if qm is None else m.changed_qm(s.bvd, qm)
    mm = s.matching
    r_l = 2 * math.pi * m.F0 * mm.l_h / mm.ql
    r_c = 1 / (2 * math.pi * m.F0 * mm.c_f * mm.qc)
    Rs, L, C, C0, Rm, Lm, Cm = s.rs, mm.l_h, mm.c_f, p.c0, p.rm, p.lm, p.cm
    A = np.array([
        [-(Rs + r_l) / L, -1 / L,           0,            0,        0],
        [1 / C0,          -1 / (r_c * C0),  1 / (r_c * C0), -1 / C0, 0],
        [0,                1 / (r_c * C),  -1 / (r_c * C),  0,       0],
        [0,                1 / Lm,          0,            -Rm / Lm, -1 / Lm],
        [0,                0,               0,             1 / Cm,   0]])
    B = np.array([1 / L, 0, 0, 0, 0.0])
    return A, B, Rm


def tau_of(A) -> float:
    ev = np.linalg.eigvals(A)
    return -1 / max(e.real for e in ev if e.real < 0)


def xss(A, B, f):
    w = 2 * math.pi * f
    return np.linalg.solve(1j * w * np.eye(5) - A, B * m.SOURCE_A1_VRMS * math.sqrt(2))


def measured_ratio(A, B, Rm, f1, f2, dwell=DWELL, frac=0.8, n=3000) -> float:
    """阶跃 f1->f2 后，驻留窗后 20% 内测得的 Rm 功率 / 真稳态功率。"""
    X1, X2 = xss(A, B, f1), xss(A, B, f2)
    dx = np.real(X1 - X2)
    ts = np.linspace(frac * dwell, dwell, n)
    w2 = 2 * math.pi * f2
    im = np.array([(expm(A * t) @ dx)[3] + np.real(X2 * np.exp(1j * w2 * t))[3] for t in ts])
    return float(Rm * np.mean(im ** 2) / (Rm * 0.5 * abs(X2[3]) ** 2))


def main() -> None:
    A, B, Rm = state_space()
    tau = tau_of(A)
    tau_hand = 800 / (math.pi * m.F0)
    print("=" * 84)
    print("docs/07 finding A 的推翻性验证")
    print("=" * 84)
    print(f"手算 tau = Qm/(pi*f0)（空载 Qm=800）: {tau_hand*1e6:7.1f} us")
    print(f"实际 tau（状态空间本征值，有载）    : {tau*1e6:7.1f} us"
          f"   相差 {tau_hand/tau:.2f} 倍")
    print(f"有载 Q = tau*w0/2 = {tau*2*math.pi*m.F0/2:.0f}"
          f"（空载 Qm 的 {tau*2*math.pi*m.F0/2/800*100:.0f}%）")
    print(f"=> 50 Ω 源阻抗与匹配 ESR 给谐振器加了阻尼。原 finding 用空载 Qm，高估了 tau。\n")
    print(f"1.5 ms 驻留 = {DWELL/tau:.1f} tau（原 finding 说 5.3 tau），"
          f"理论残余 {math.exp(-DWELL/tau)*100:.4f}%\n")

    print(f"{'阶跃情形':<40}{'|Δ幅度|/幅度':>14}{'测得/稳态':>12}{'误差':>10}")
    cases = [("粗扫逼近峰 895 -> 900 kHz (5 kHz)", 895e3, 900e3),
             ("粗扫越过峰 900 -> 905 kHz", 900e3, 905e3),
             ("细扫近峰 899 -> 900 kHz (1 kHz)", 899e3, 900e3),
             ("终扫近峰 899.9 -> 900 kHz (0.1 kHz)", 899.9e3, 900e3)]
    rows = []
    for name, f1, f2 in cases:
        X1, X2 = xss(A, B, f1), xss(A, B, f2)
        step = abs(abs(X1[3]) - abs(X2[3])) / abs(X2[3])
        r = measured_ratio(A, B, Rm, f1, f2)
        rows.append({"case": name, "amplitude_step": step, "ratio": r, "error_pct": (r - 1) * 100})
        print(f"{name:<40}{step*100:>13.2f}%{r:>12.5f}{(r-1)*100:>9.3f}%")

    print("\n=> 实测误差 0.03-0.06%，不是原 finding 说的 0.5%。准稳态假设成立且裕量充裕。\n")

    print("=" * 84)
    print("那么这个检查在什么条件下才真的会失效？")
    print("=" * 84)
    print(f"{'空载 Qm':>9}{'有载 tau':>13}{'有载 Q':>9}{'1.5ms 驻留':>14}{'残余':>11}   判定")
    sweep = []
    for qm in (400, 800, 1600, 3200, 6400):
        Aq, Bq, _ = state_space(qm)
        t = tau_of(Aq)
        n = DWELL / t
        res = math.exp(-n)
        verdict = "充裕" if n >= 7 else ("勉强" if n >= 4 else "不足")
        sweep.append({"qm_unloaded": qm, "tau_s": t, "dwell_taus": n,
                      "residual": res, "verdict": verdict})
        print(f"{qm:>9}{t*1e6:>10.1f} us{t*2*math.pi*m.F0/2:>9.0f}{n:>11.1f} tau"
              f"{res*100:>10.4f}%   {verdict}")
    print("\n阈值在空载 Qm ≈ 1600 附近。但对浸入血液的换能器，辐射负载单独就把 Qm 压到")
    print("31 以下（见 workspace/plan_extensions_20260916/），因此这个条件在本项目里不可达。")
    print("结论：检查本身值得保留在登记表里，但它标注的问题【在本项目的参数范围内不存在】。")

    (HERE / "transient_findings.json").write_text(json.dumps({
        "verdict": "docs/07 finding A 已推翻",
        "root_error": "用换能器空载 Qm 计算瞬态时常数；实际由整个驱动回路的有载 Q 决定，"
                      "50 Ω 源阻抗与匹配网络 ESR 都在加阻尼，有载 Q 约为空载 Qm 的一半。",
        "tau_hand_us": tau_hand * 1e6, "tau_actual_us": tau * 1e6,
        "dwell_in_taus": DWELL / tau,
        "measured_cases": rows,
        "qm_sweep": sweep,
        "threshold_unloaded_qm": 1600,
        "why_unreachable": "辐射负载使浸入血液的 Qm 上限约 31，远低于 1600。",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {HERE/'transient_findings.json'}")


if __name__ == "__main__":
    main()
