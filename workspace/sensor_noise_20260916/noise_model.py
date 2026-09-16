"""传感器噪声：按真实测量链建模，而不是直接给功率加噪声。

重做缘由
--------
docs/08 第二节原先把高斯噪声直接加在 `p_rm_W` 上。这违反了项目自己的口径登记：

    docs/03「P_source、P_port、P_Rm 测点不同」
    docs/03「主控制与离线图常用 P_Rm，真实反馈页使用 RAW 端口 P_port」

真实系统测不到功率——它测【电压】和【电流】，再算功率。因此噪声必须加在
V、I、相位三者上，再传播到 P_port：

    P_port = |V|·|I|·cos(phi)          phi = arg(v_port / i_port) = arg(z_bvd)
    dP/P   = n_V + n_I - tan(phi)·n_phi

最后一项是直接给功率加噪声时【完全看不到】的：相位误差被 tan(phi) 放大，
在谐振点无关紧要，偏离谐振时发散。

注意端口相位与功放输入端相位不是一回事（docs/03 第 3 条已登记该口径）：
v3 基线在 f0 处端口相位为 -14.80°、功放输入端为 -0.64°。

    python3 workspace/sensor_noise_20260916/noise_model.py
"""
from __future__ import annotations

import json, math, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "workspace/disturbance_v3_20260916"))
import model_v3 as M

RNG = np.random.default_rng(20260916)
out: dict = {}


def port_quantities(f, scenario, amp=1.0):
    """真实反馈通道能测到的三个量：|V|、|I|、端口相位。"""
    q = M.response(f, scenario, amp)
    v, i = q["v_port"], q["i_port"]
    return np.abs(v), np.abs(i), np.angle(v / i, deg=True)


def measure_power(f, scenario, sigma_amp, sigma_phase_deg, amp=1.0):
    """按测量链加噪声后算出的 P_port。"""
    mv, mi, ph = port_quantities(f, scenario, amp)
    mv = mv * (1 + RNG.normal(0, sigma_amp, np.shape(mv)))
    mi = mi * (1 + RNG.normal(0, sigma_amp, np.shape(mi)))
    ph = ph + RNG.normal(0, sigma_phase_deg, np.shape(ph))
    return mv * mi * np.cos(np.radians(ph))


def measure_power_naive(f, scenario, sigma, amp=1.0):
    """原 docs/08 的做法：直接给功率加噪声（口径错误，保留作对照）。"""
    q = M.response(f, scenario, amp)
    return q["p_port_W"] * (1 + RNG.normal(0, sigma, np.shape(q["p_port_W"])))


def po_run(scenario, meas, step=500.0, n=400, runs=40):
    """带噪声测量的 P&O，返回（平均功率捕获, 频率 std）。"""
    fine = np.arange(M.F_MIN, M.F_MAX, 25.0)
    p_true = M.response(fine, scenario, 1.0)["p_rm_W"]
    p_best = p_true.max()
    caps, freqs = [], []
    for _ in range(runs):
        f, d = M.F0, 1.0
        for _ in range(n):
            fc = float(np.clip(f + d * step, M.F_MIN, M.F_MAX))
            if float(meas(np.array([fc]), scenario)[0]) > float(meas(np.array([f]), scenario)[0]):
                f = fc
            else:
                d *= -1
        caps.append(float(M.response(f, scenario, 1.0)["p_rm_W"][0]) / p_best)
        freqs.append(f)
    return float(np.mean(caps)), float(np.std(freqs))


LADDER = [(80e3, 20e3), (20e3, 5e3)]      # v3 推荐阶梯


def scan_run(scenario, sigma_amp, sigma_phase_deg, runs=200):
    """三级扫描在正确噪声口径下的捕获率。

    粗扫的点大多远离谐振，正是 tan(phi) 放大最厉害之处，因此必须单独验。
    """
    fine = np.arange(M.F_MIN, M.F_MAX, 25.0)
    p_best = M.response(fine, scenario, 1.0)["p_rm_W"].max()
    caps = []
    for _ in range(runs):
        c = M.F0
        for hw, st in LADDER:
            g = np.arange(max(M.F_MIN, c - hw), min(M.F_MAX, c + hw) + st / 2, st)
            c = float(g[int(np.argmax(measure_power(g, scenario, sigma_amp, sigma_phase_deg)))])
        caps.append(float(M.response(np.array([c]), scenario, 1.0)["p_rm_W"][0]) / p_best)
    return float(np.mean(caps)), float(np.percentile(caps, 5)), float(min(caps))


def main() -> None:
    s = M.scenario_map()["CASE_000_BASELINE"]

    # ---- 1. 恒等式与相位放大 ----
    mv, mi, ph0 = port_quantities(np.array([M.F0]), s)
    p_id = float(mv[0] * mi[0] * math.cos(math.radians(ph0[0])))
    p_md = float(M.response(np.array([M.F0]), s, 1.0)["p_port_W"][0])
    print("=" * 90)
    print("传感器噪声重做：按 V/I/相位建模，而非直接给功率加噪声")
    print("=" * 90)
    print(f"恒等式核对：|V||I|cos(phi) = {p_id*1e3:.6f} mW，模型 P_port = {p_md*1e3:.6f} mW\n")
    print(f"端口相位 arg(z_bvd) @ f0 = {ph0[0]:+.2f}°   tan = {math.tan(math.radians(ph0[0])):.4f}")
    print(f"功放输入端 arg(z_in) @ f0 = "
          f"{float(M.response(np.array([M.F0]), s, 1.0)['phase_deg'][0]):+.2f}°   （两者不同，docs/03 第 3 条）\n")

    f = np.arange(M.F_MIN, M.F_MAX, 5e3)
    _, _, phf = port_quantities(f, s)
    print("相位误差经 tan(phi) 放大后的功率误差（每 1° 相位误差）：")
    print(f"{'频率(kHz)':>10}{'端口相位(°)':>13}{'1° -> 功率误差':>18}")
    amp_rows = []
    for k in range(0, len(f), 10):
        t = math.tan(math.radians(phf[k]))
        err = abs(t) * math.radians(1.0) * 100
        amp_rows.append({"f_Hz": float(f[k]), "phase_deg": float(phf[k]), "pct_per_deg": err})
        print(f"{f[k]/1e3:>10.0f}{phf[k]:>13.2f}{err:>17.2f}%")

    # ---- 2. 信噪比对照 ----
    fine = np.arange(M.F_MIN, M.F_MAX, 25.0)
    p = M.response(fine, s, 1.0)["p_rm_W"]
    ipk = int(np.argmax(p))
    sig = abs(float(M.response(np.array([fine[ipk] + 500.0]), s, 1.0)["p_rm_W"][0]) - p[ipk]) / p[ipk]
    t0 = abs(math.tan(math.radians(ph0[0])))
    print(f"\nP&O 在峰顶走一个步长（0.5 kHz）的信号 = {sig*100:.4f}%")
    print(f"同处 1° 相位误差造成的功率误差       = {t0*math.radians(1.0)*100:.4f}%"
          f"   —— 噪信比 {t0*math.radians(1.0)/sig:.1f}:1")
    print("=> 相位噪声在峰顶就已经压过 P&O 的信号。原做法（噪声加在功率上）看不到这一项。")

    # ---- 3. 蒙特卡洛：新口径 vs 旧口径 ----
    print("\n" + "=" * 90)
    print("P&O 蒙特卡洛：新口径（V/I/相位加噪）vs 旧口径（功率加噪）")
    print("=" * 90)
    print(f"{'幅度噪声':>9}{'相位噪声':>9}" + f"{'新口径 捕获':>14}{'新口径 频率std':>16}"
          f"{'旧口径 捕获':>14}{'旧口径 频率std':>16}")
    mc = []
    for s_amp, s_ph in [(0.001, 0.1), (0.001, 0.5), (0.001, 1.0),
                        (0.005, 0.5), (0.005, 1.0), (0.01, 1.0), (0.01, 2.0)]:
        cap_n, sd_n = po_run(s, lambda ff, sc: measure_power(ff, sc, s_amp, s_ph))
        # 旧口径取等效幅度噪声（两路幅度合成 sqrt(2)*s_amp）
        eq = math.sqrt(2) * s_amp
        cap_o, sd_o = po_run(s, lambda ff, sc: measure_power_naive(ff, sc, eq))
        mc.append({"sigma_amp": s_amp, "sigma_phase_deg": s_ph,
                   "new_capture": cap_n, "new_freq_std_Hz": sd_n,
                   "old_capture": cap_o, "old_freq_std_Hz": sd_o})
        print(f"{s_amp*100:>8.1f}%{s_ph:>8.1f}°{cap_n*100:>13.2f}%{sd_n/1e3:>15.2f}"
              f"{cap_o*100:>13.2f}%{sd_o/1e3:>15.2f}")

    # ---- 3b. 扫描是否被 tan(phi) 放大带偏 ----
    print("\n" + "=" * 90)
    print("三级扫描在正确噪声口径下的捕获率（粗扫点远离谐振 = 放大最严重处）")
    print("=" * 90)
    print(f"{'幅度噪声':>9}{'相位噪声':>9}{'平均捕获':>11}{'P5':>10}{'最差':>10}")
    scan_rows = []
    for sa, sp in [(0.001, 0.1), (0.001, 1.0), (0.005, 1.0), (0.01, 2.0), (0.01, 5.0), (0.02, 10.0)]:
        mn, p5, wo = scan_run(s, sa, sp)
        scan_rows.append({"sigma_amp": sa, "sigma_phase_deg": sp,
                          "mean": mn, "p5": p5, "worst": wo})
        print(f"{sa*100:>8.1f}%{sp:>8.1f}°{mn*100:>10.2f}%{p5*100:>9.2f}%{wo*100:>9.2f}%")
    fl = np.array([650e3, 700e3, 750e3, 800e3])
    pl = M.response(fl, s, 1.0)["p_rm_W"]
    pb = M.response(np.arange(M.F_MIN, M.F_MAX, 25.0), s, 1.0)["p_rm_W"].max()
    print("\n放大最严重处的绝对功率有多小：")
    for k in range(len(fl)):
        print(f"   {fl[k]/1e3:.0f} kHz 为峰值的 {pl[k]/pb*100:7.3f}%，"
              f"即使误差 45% 仍只有 {pl[k]/pb*1.45*100:7.3f}%")
    print("=> 放大最严重的地方绝对功率也最小，不足以把这些点抬到峰之上。扫描未被带偏。")
    out["scan"] = scan_rows

    # ---- 4. SCBC 是否也治这个 ----
    print("\n" + "=" * 90)
    print("附带检查：静态电容补偿（SCBC）是否也降低相位噪声敏感度")
    print("=" * 90)
    b = M.BASE_BVD
    w0 = 2 * math.pi * M.F0
    l0 = 1 / (w0**2 * b.c0); r_l0 = w0 * l0 / 100.0
    w = 2 * math.pi * M.F0
    zm = b.rm + 1j * (w * b.lm - 1 / (w * b.cm))
    z_raw = 1 / (1 / zm + 1j * w * b.c0)
    z_cmp = 1 / (1 / zm + 1j * w * b.c0 + 1 / (r_l0 + 1j * w * l0))
    for tag, z in (("不补偿", z_raw), (f"加 L0 = {l0*1e6:.2f} µH", z_cmp)):
        phi = math.degrees(math.atan2(z.imag, z.real))
        t = abs(math.tan(math.radians(phi)))
        print(f"   {tag:<22} 端口相位 {phi:+7.2f}°   tan = {t:6.4f}   "
              f"1° 相位误差 -> {t*math.radians(1.0)*100:6.3f}% 功率误差")
    phi_r = math.degrees(math.atan2(z_raw.imag, z_raw.real))
    phi_c = math.degrees(math.atan2(z_cmp.imag, z_cmp.real))
    ratio = abs(math.tan(math.radians(phi_r))) / max(abs(math.tan(math.radians(phi_c))), 1e-12)
    print(f"\n=> SCBC 把工作点的 tan(phi) 降低 {ratio:.0f} 倍，"
          "即功率测量对相位误差的敏感度同比下降。")
    print("   这是 SCBC 的第二项收益，与消除伪锁定相互独立，先前未识别。")

    out.update({
        "identity_check": {"v_i_cos": p_id, "model_p_port": p_md},
        "port_phase_at_f0_deg": float(ph0[0]),
        "zin_phase_at_f0_deg": float(M.response(np.array([M.F0]), s, 1.0)["phase_deg"][0]),
        "phase_amplification": amp_rows,
        "po_signal_at_peak_pct": sig * 100,
        "monte_carlo": mc,
        "scbc": {"L0_uH": l0 * 1e6, "tan_phi_raw": abs(math.tan(math.radians(phi_r))),
                 "tan_phi_compensated": abs(math.tan(math.radians(phi_c))),
                 "sensitivity_reduction": ratio},
    })
    (HERE / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {HERE/'results.json'}")


if __name__ == "__main__":
    main()
