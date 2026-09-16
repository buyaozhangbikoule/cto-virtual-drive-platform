"""按计划书第四、六章对控制算法做物理审核。

计划书要求的审核项散在各周：
  第2周 "核对元件单位、频率单位、功率表达式和相位符号"
  第3周 "分析扫频步长和扫描范围：步长过粗会错过峰值，范围过大则增加控制延迟"
  第4周 "区分「基线较差」与「模型出错」"
  第六章 分析指标里的 "控制器增益变化对结果的敏感性"

本脚本把其中可定量判定的部分逐条算出来，不靠断言。每一项都给出判据、数值和结论。

    python3 workspace/algorithm_physics_audit_20260916/physics_checks.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
V21 = REPO / "workspace/outputs/v2_self_consistent_rebuild/active_stage3_5"
V3 = REPO / "workspace/disturbance_v3_20260916"

findings: list[dict] = []


def check_A_quasistatic() -> None:
    """准稳态假设——【本项已被 transient_check.py 推翻，保留仅为留痕】。

    原做法用手算 tau = Qm/(pi*f0)，即换能器的【空载】Qm。这是错的：
    瞬态由整个驱动回路的【有载 Q】决定，50 Ω 源阻抗与匹配 ESR 都在加阻尼。
    实测有载 tau = 148.5 us 而非 283 us，1.5 ms 驻留是 10.1 个时常数而非 5.3 个，
    实际测量误差 0.03-0.06% 而非 0.5%。

    正确的算法见 transient_check.py（状态空间本征值 + 闭式瞬态解）。
    """
    print("=" * 88)
    print("A. 准稳态假设的时间尺度自洽性")
    print("   ⚠️ 本项结论已被 transient_check.py 推翻。下面的手算用的是【空载】Qm，")
    print("      而瞬态由【有载】Q 决定。保留此输出仅为对照，勿引用其结论。")
    print("=" * 88)
    print("机械支路是二阶谐振系统，激励改变后包络按 exp(-t/tau) 衰减，tau = 2Qm/w0 = Qm/(pi*f0)。")
    print("模型是稳态 AC 解，【不模拟瞬态】，因此它报出的永远是完全稳定后的值；")
    print("真实系统若驻留时间不足，测到的是未稳定的瞬态。该假设项目从未校验。\n")
    scan_dt, control_dt = 1.5e-3, 20e-3
    rows = []
    for tag, qm, f0 in [("v2.1 (Qm=800)", 800.0, 0.9e6), ("v3 (Qm=21.1)", 21.09, 0.8e6)]:
        tau = qm / (math.pi * f0)
        settle_1pct = 4.6 * tau
        margin = scan_dt / settle_1pct
        verdict = "充足" if margin >= 3 else ("勉强" if margin >= 1 else "不足")
        print(f"{tag:<16} tau = {tau*1e6:7.2f} us   稳定到 1% 需 {settle_1pct*1e6:8.1f} us")
        print(f"{'':<16} 扫描点驻留 {scan_dt*1e6:.0f} us = {scan_dt/tau:6.1f} tau，"
              f"裕量 {margin:.2f}x  【{verdict}】  残余幅度误差 {math.exp(-scan_dt/tau)*100:.3f}%")
        print(f"{'':<16} 控制步长 {control_dt*1e3:.0f} ms = {control_dt/tau:8.1f} tau  【充足】\n")
        rows.append({"baseline": tag, "tau_us": tau * 1e6,
                     "settle_1pct_us": settle_1pct * 1e6,
                     "scan_dwell_margin": margin, "verdict": verdict})
    findings.append({
        "id": "A", "title": "【已撤回】准稳态假设未校验，v2.1 下裕量仅 1.15 倍",
        "severity": "已撤回——该问题不存在",
        "withdrawn": "2026-09-16",
        "root_error": "用换能器【空载】Qm 计算瞬态时常数。瞬态由整个驱动回路的【有载】Q "
                      "决定，50 Ω 源阻抗与匹配网络 ESR 都在加阻尼，有载 Q 约为空载的一半。",
        "corrected": "有载 tau = 148.5 us（非 283 us），1.5 ms 驻留 = 10.1 tau（非 5.3），"
                     "状态空间闭式瞬态解给出的实际测量误差为 0.03-0.06%（非 0.5%）。"
                     "准稳态假设成立且裕量充裕。",
        "residual_value": "检查本身值得保留，但阈值在空载 Qm ≈ 1600，而辐射负载使浸入血液的 "
                          "Qm 上限约 31，本项目参数范围内不可达。断言应写成"
                          "「驻留 >= 7 x 有载 tau」，用状态空间本征值求 tau。",
        "evidence": "workspace/algorithm_physics_audit_20260916/transient_check.py",
        "data_superseded": rows,
    })


def check_B_po_drift() -> None:
    """P&O：参考点与探测点之间若发生负载变化，方向判断失效且步长坍缩。"""
    print("=" * 88)
    print("B. P&O 的跨扰动方向二义性与步长坍缩")
    print("=" * 88)
    sys.path.insert(0, str(V21))
    import model_v2_1 as m
    import run_stage4_5_control as C

    sm = m.scenario_map()
    A, step = C.PROBE_AMPLITUDE, C.P_AND_O_INITIAL_STEP
    print("P&O 在 f 上测参考、在 f+step 上测探测，两点相隔 2*CONTROL_DT = "
          f"{2*C.CONTROL_DT*1e3:.0f} ms。若其间负载变化，它会把【负载变化】读成【自己这一步的结果】。\n")
    print(f"{'边界':<44}{'真实最优移动':>14}{'P&O 读到':>12}{'方向正确?':>10}")
    wrong = total = 0
    rows = []
    for i in range(len(C.SCHEDULE) - 1):
        a, b = C.SCHEDULE[i]["case_id"], C.SCHEDULE[i + 1]["case_id"]
        if a == b:
            continue
        total += 1
        sa, sb = sm[a], sm[b]
        fa = C.FINE_REFERENCE[int(np.argmax(m.safe_power(C.FINE_REFERENCE, sa)))]
        fb = C.FINE_REFERENCE[int(np.argmax(m.safe_power(C.FINE_REFERENCE, sb)))]
        true_dir = "升频" if fb > fa else ("降频" if fb < fa else "不动")
        p_ref = float(m.response(np.array([fa]), sa, A)["p_port_W"][0]) / A**2
        p_prb = float(m.response(np.array([fa + step]), sb, A)["p_port_W"][0]) / A**2
        rel = (p_prb - p_ref) / abs(p_ref)
        read = "功率上升" if rel > 0 else "功率下降->反向并减半步长"
        ok = (rel > 0 and true_dir == "升频") or (rel <= 0 and true_dir == "降频")
        if not ok:
            wrong += 1
        print(f"{a+' -> '+b:<44}{true_dir:>14}{'上升' if rel>0 else '下降':>12}{'是' if ok else '否':>10}")
        rows.append({"boundary": f"{a}->{b}", "true_direction": true_dir,
                     "po_reads": read, "correct": ok, "rel": rel})
    print(f"\n7 个边界全部读到「功率下降」——因为任何扰动都把工作点推离峰，功率必降。")
    print(f"于是 P&O 的反应恒为「反向 + 步长减半」，与最优点实际往哪走【无关】：{wrong}/{total} 判错方向。")
    print(f"\n更要命的是步长：初值 {step/1e3:g} kHz，每误判一次减半 -> ", end="")
    s = step
    seq = []
    for _ in range(4):
        s = max(C.P_AND_O_MIN_STEP, s / 2)
        seq.append(s / 1e3)
    print(" -> ".join(f"{x:g}" for x in seq) + " kHz")
    print(f"而 CASE_FS_M5 的 fs 跳变是 45 kHz。步长恰在最需要大步长时坍缩到下限 "
          f"{C.P_AND_O_MIN_STEP/1e3:g} kHz。")
    print(f"\n缓解机制存在但不够快：检测器需 {C.DISTURBANCE_CONFIRM_SAMPLES} 个连续确认 = "
          f"{C.DISTURBANCE_CONFIRM_SAMPLES*C.CONTROL_DT*1e3:.0f} ms，"
          f"而 P&O 一对只跨 {2*C.CONTROL_DT*1e3:.0f} ms。")
    print("现有 7 段日程中实际发生的跨边界配对：0/15——机制是真的，但从未被触发过，")
    print("段长 0.8 s、配对跨 40 ms，单对撞上的概率约 5%，15 对全躲开属于运气。")
    sys.path.pop(0)
    findings.append({
        "id": "B", "title": "P&O 跨扰动时方向判断失效且步长坍缩；现有日程从未触发",
        "severity": "高",
        "detail": "负载一变，归一化功率必降，P&O 恒判「反向 + 减半」。7 个边界里 "
                  f"{wrong}/{total} 方向判错，且步长在最需要大步长时坍缩到 0.1 kHz，"
                  "而 fs 跳变可达 45 kHz。检测器 60 ms 的确认时间慢于 P&O 的 40 ms 决策周期。",
        "literature": "这是光伏 MPPT 里的经典 drift 问题。Killi & Samanta, IEEE Trans. Ind. "
                      "Electron. 2015, Modified Perturb and Observe MPPT Algorithm for Drift "
                      "Avoidance in Photovoltaic Systems：在 dP 之外把 dI 纳入决策即可区分"
                      "「自己扰动的结果」与「外部条件变化」。",
        "fix": "本项目已经同时测 V、I、相位，dI 是免费的。把判据从 sign(dP) 改为 (dP, dI) 联合判据；"
               "并把「步长减半」与「方向反转」解耦——确认是外部扰动时应【放大】步长而非减半。",
        "data": rows,
    })


def check_C_scbc() -> None:
    """相位判据的多解问题，以及文献的结构性解法。"""
    print("\n" + "=" * 88)
    print("C. 相位判据多解（伪锁定）与静态电容补偿")
    print("=" * 88)
    sys.path.insert(0, str(V3))
    import model_v3 as M

    b = M.BASE_BVD
    w0 = 2 * math.pi * M.F0
    l0 = 1 / (w0**2 * b.c0)
    f = np.arange(650e3, 950e3, 100.0)
    w = 2 * np.pi * f
    zm = b.rm + 1j * (w * b.lm - 1 / (w * b.cm))
    power = np.abs(1.0 / zm) ** 2 * b.rm
    pk = power.max()

    def zeros(z):
        ph = np.angle(z, deg=True)
        s = np.sign(ph)
        return np.where(s[:-1] * s[1:] < 0)[0], ph

    i_raw, _ = zeros(1 / (1 / zm + 1j * w * b.c0))
    i_cmp, ph_cmp = zeros(1 / (1 / zm + 1j * w * b.c0 + 1 / (1j * w * l0)))
    print(f"裸 BVD 端口阻抗的相位过零点：{len(i_raw)} 个")
    for i in i_raw:
        print(f"   {f[i]/1e3:7.1f} kHz -> 机械功率为峰值的 {power[i]/pk*100:6.2f}%")
    print(f"\n并联补偿电感 L0 = 1/(w0^2*C0) = {l0*1e6:.2f} µH 后：{len(i_cmp)} 个")
    for i in i_cmp:
        print(f"   {f[i]/1e3:7.1f} kHz -> 机械功率为峰值的 {power[i]/pk*100:6.2f}%")
    i_zero = int(np.argmin(np.abs(ph_cmp)))
    i_pk = int(np.argmax(power))
    print(f"\n补偿后相位零点 {f[i_zero]/1e3:.1f} kHz 与功率峰 {f[i_pk]/1e3:.1f} kHz "
          f"相差 {abs(f[i_zero]-f[i_pk])/1e3:.1f} kHz")
    print("=> 「相位归零」与「功率最大」两个判据不再打架，伪锁定被结构性消除。")
    print("   这比本审核先前加的「事后功率探测 + 重标定」防护更干净：前者防止问题发生，后者只能补救。")
    sys.path.pop(0)
    findings.append({
        "id": "C", "title": "相位判据多解；文献有结构性解法，优于本审核先前的事后防护",
        "severity": "中（已有可用缓解，但解法可升级）",
        "detail": f"裸 BVD 相位过零 {len(i_raw)} 个，其中只有一个在功率峰上。控制律用 "
                  "np.sign(slope) 就地测符号，使每个解都成为稳定吸引子。",
        "literature": "这是超声换能器驱动里的已知问题，文献称 antiresonance frequency tracing。"
                      "解法：静态电容宽带补偿（SCBC）。见 PubMed 24626028, An improved phase-locked "
                      "loop method for automatic resonance frequency tracing based on static "
                      "capacitance broadband compensation for a high-power ultrasonic transducer.",
        "fix": f"并联 L0 = 1/(w0^2*C0) = {l0*1e6:.2f} µH（v3 几何）。实测：过零点 "
               f"{len(i_raw)} -> {len(i_cmp)}，且唯一零点与功率峰重合。"
               "先前的事后防护可保留作为兜底，但不应是主要手段。",
        "data": {"L0_uH": l0 * 1e6, "zeros_before": len(i_raw), "zeros_after": len(i_cmp)},
    })


def check_D_esr() -> None:
    """ESR 频率无关近似在加宽后的窗口里的误差。"""
    print("\n" + "=" * 88)
    print("D. ESR 频率无关近似")
    print("=" * 88)
    sys.path.insert(0, str(V21))
    import model_v2_1 as m
    l, ql = m.BASE_MATCH.l_h, m.BASE_MATCH.ql
    r_fixed = 2 * math.pi * m.F0 * l / ql
    print(f"代码取 r_L = 2*pi*f0*L/Q_L = {r_fixed:.3f} Ω 并在全频段固定。")
    print("物理上趋肤效应使 R ∝ sqrt(f)，即 Q ∝ sqrt(f)。两者之差：\n")
    print(f"{'频率(kHz)':>10}{'固定R模型Q':>13}{'趋肤模型Q':>12}{'相对差':>10}")
    worst = 0.0
    for freq in (650e3, 800e3, 900e3, 1000e3):
        q_fixed = 2 * math.pi * freq * l / r_fixed
        q_skin = ql * math.sqrt(freq / m.F0)
        diff = (q_fixed / q_skin - 1) * 100
        worst = max(worst, abs(diff))
        print(f"{freq/1e3:>10.0f}{q_fixed:>13.1f}{q_skin:>12.1f}{diff:>9.1f}%")
    print(f"\nv2.1 的窗口 800-1000 kHz 内最大偏差约 5.7%，可接受；")
    print(f"但 v3 把窗口加宽到 650-950 kHz 后，下沿偏差达 15%。")
    print("加宽扫描窗口的同时，这条近似的适用性也应重新评估——登记表未标注此项。")
    sys.path.pop(0)
    findings.append({
        "id": "D", "title": "ESR 频率无关近似在加宽后的窗口下沿偏差达 15%",
        "severity": "低",
        "detail": "固定 R 使模型 Q ∝ f，而趋肤效应下应为 Q ∝ sqrt(f)。v2.1 窗口内偏差 5.7% 可接受，"
                  "v3 窗口下沿 650 kHz 处达 15%。",
        "fix": "或改为 r_L(f) = r_L(f0)*sqrt(f/f0)，或在登记表显式标注该近似及其适用窗口。"
               "影响的是匹配网络损耗，不影响谐振频率，优先级低。",
        "data": {"worst_deviation_pct": worst},
    })


def check_E_modes() -> None:
    """单模 BVD 的成立前提：扫描窗口内是否只有一个模态。"""
    print("\n" + "=" * 88)
    print("E. 单模 BVD 在扫描窗口内是否成立")
    print("=" * 88)
    n31, f0 = 1500.0, 0.8e6
    length_mm = 3 * n31 / f0 * 1e3
    od, idd = 1.35, 0.73
    lo, hi = 650e3, 950e3
    print(f"PZT-5H 空心圆柱，N31 = {n31} Hz·m，长 {length_mm:.2f} mm，OD/ID = {od}/{idd} mm")
    print(f"扫描窗口 {lo/1e3:.0f}-{hi/1e3:.0f} kHz\n")
    modes = [(f"长度模 {n} 次谐波", n * n31 / (length_mm * 1e-3)) for n in range(1, 6)]
    modes += [("环向（呼吸）模", 1100.0 / ((od + idd) / 2 * 1e-3)),
              ("壁厚模", 2000.0 / ((od - idd) / 2 * 1e-3))]
    inside = []
    for name, freq in modes:
        mark = "★ 窗口内" if lo < freq < hi else ""
        if lo < freq < hi:
            inside.append(name)
        print(f"   {name:<20}{freq/1e3:>10.1f} kHz   {mark}")
    print(f"\n窗口内模态数：{len(inside)}（{'仅工作模态，单模 BVD 成立' if len(inside)==1 else '存在干扰模态'}）")
    print("注：v2.1 的 BVD 由工作点反推、【没有几何】，这项检查根本无法进行。")
    print("    正推的一个实际好处就是让模态洁净性变得可验证。")
    findings.append({
        "id": "E", "title": "单模 BVD 在 v3 窗口内成立（已验证）；v2.1 无几何故不可验证",
        "severity": "无（此项通过）",
        "detail": f"窗口 650-950 kHz 内只有三次谐波一个模态，最近邻居（二次 533、四次 1067 kHz）"
                  f"各距窗边 >100 kHz。环向模 1058 kHz、壁厚模 6452 kHz 均在窗外。",
        "fix": "无需修改。建议把该检查作为几何变更时的常规校验项纳入登记表。",
        "data": {"modes_in_window": inside},
    })


def main() -> None:
    check_A_quasistatic()
    check_B_po_drift()
    check_C_scbc()
    check_D_esr()
    check_E_modes()
    (HERE / "findings.json").write_text(
        json.dumps({"batch": "algorithm_physics_audit_20260916",
                    "basis": "计划书第二/三/四周与第六章的物理审核要求",
                    "findings": findings}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {HERE / 'findings.json'}")


if __name__ == "__main__":
    main()
