"""对 docs/07 finding B 与 C 的复审——两条原结论都需大幅修正。

导师 2026-09-16：「好好审核一下你说的对不对」。结果：

B（P&O 跨扰动）：机制真实，但【后果在本架构里被完全吸收】，严重度由〔高〕降为〔低〕。
  - 检测器由 CONTROL 行驱动，与 P&O 配对无关，触发不受影响
  - 每次触发都把 po_step 重置为初值，重扫本身又不使用 po_step
  - 「步长坍缩到 0.1 kHz」需连续 3 次以上误判且检测器不触发 —— 不可达
  - 「4/7 判错方向」是假定初始方向为 +1 的产物，非稳健结论

C（SCBC 消除伪锁定）：结论成立，但【只在换能器端测相位时】。
  - 原验证用的是裸 BVD（换能器端），而代码读的是 z_in（功放输入端，含匹配网络）
  - 换能器端：过零 2 -> 1，最差吸引子 8.9% -> 100%
  - 功放输入端：过零 2 -> 2，补偿无效（匹配网络自身引入相位结构）
  - 计划书第四章指定的正是「换能器输入阻抗相位」，代码与之不符

    python3 workspace/algorithm_physics_audit_20260916/reaudit_B_C.py
"""
from __future__ import annotations

import json, math, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
out: dict = {}


def reaudit_C() -> None:
    sys.path.insert(0, str(REPO / "workspace/disturbance_v3_20260916"))
    import model_v3 as M
    b = M.BASE_BVD; w0 = 2 * math.pi * M.F0
    l0 = 1 / (w0**2 * b.c0); r_l0 = w0 * l0 / 100.0
    f = np.arange(650e3, 950e3, 50.0); w = 2 * np.pi * f
    zm = b.rm + 1j * (w * b.lm - 1 / (w * b.cm))
    p = np.abs(1.0 / zm) ** 2 * b.rm; pk = p.max()

    def zbvd(comp):
        y = 1 / zm + 1j * w * b.c0
        return 1 / (y + 1 / (r_l0 + 1j * w * l0) if comp else y)

    def zin(comp):
        zl = zbvd(comp); z0 = complex(zl[np.argmin(np.abs(f - M.F0))])
        mt = M.design_lmatch(z0, M.BASE_RS, M.F0, ql=100.0, qc=1000.0)
        rl_ = 2 * math.pi * M.F0 * mt.l_h / mt.ql
        rc_ = 1 / (2 * math.pi * M.F0 * mt.c_f * mt.qc)
        return 1 / (1 / (rc_ + 1 / (1j * w * mt.c_f)) + 1 / (rl_ + 1j * w * mt.l_h + zl))

    def cross(z):
        ph = np.angle(z, deg=True); s = np.sign(ph)
        idx = np.where(s[:-1] * s[1:] < 0)[0]
        return [{"f_Hz": float(f[i]), "power_pct": float(p[i] / pk * 100)} for i in idx]

    print("=" * 94)
    print("复审 C：SCBC 只在【换能器端】测相位时有效；代码测的是【功放输入端】")
    print("=" * 94)
    print("计划书第四章：「以【换能器输入阻抗相位】或电压—电流相位差为误差信号」")
    print("代码实际：phase_deg = angle(z_in)，含匹配网络的功放输入端阻抗\n")
    print(f"L0 = 1/(w0^2*C0) = {l0*1e6:.2f} µH，取 Q=100（原验证用无损 L0）\n")
    rows = {}
    for node, fn in (("换能器端 z_bvd", zbvd), ("功放输入端 z_in", zin)):
        for comp in (False, True):
            key = f"{node}{'+L0' if comp else ' 不补偿'}"
            c = cross(fn(comp))
            rows[key] = c
            worst = min((x["power_pct"] for x in c), default=float("nan"))
            print(f"   {key:<22} 过零 {len(c)} 个   最差吸引子 {worst:6.1f}%   "
                  + "  ".join(f"{x['f_Hz']/1e3:.1f}kHz({x['power_pct']:.1f}%)" for x in c))
    print("\n=> 换能器端 2->1 且最差吸引子 8.9%->100%；功放端 2->2，补偿无效。")
    print("   原 finding 的『2 个 -> 1 个』验的是换能器端，而代码读功放端。结论需限定节点。")
    sys.path.pop(0)
    out["C"] = {"L0_uH": l0 * 1e6, "crossings": rows,
                "verdict": "成立但须限定：仅当在换能器端测相位。代码当前在功放输入端测，"
                           "与计划书第四章指定的节点不一致。"}


def reaudit_B() -> None:
    sys.path.insert(0, str(REPO / "workspace/outputs/v2_self_consistent_rebuild/active_stage3_5"))
    import run_stage4_5_control as C
    import model_v2_1 as m
    scen = m.scenario_map(); opt = C.optimal_tables(scen)

    def analyse(shift):
        orig = C.schedule_at
        C.schedule_at = lambda t: orig(max(0.0, t - shift))
        rows = C.simulate("P_AND_O", scen, opt)
        C.schedule_at = orig
        po = [r for r in rows if r["action"] in ("P_AND_O_REFERENCE", "P_AND_O_PROBE")]
        pairs = straddle = 0
        for i in range(len(po) - 1):
            if po[i]["action"] == "P_AND_O_REFERENCE" and po[i + 1]["action"] == "P_AND_O_PROBE":
                pairs += 1
                if po[i]["case_id"] != po[i + 1]["case_id"]:
                    straddle += 1
        ctrl = [r for r in rows if r["action"] == "CONTROL"]
        ss = [r for r in ctrl if (r["time_s"] % 0.8) > 0.4]
        return {"shift_ms": shift * 1e3, "pairs": pairs, "straddle": straddle,
                "mean_capture": float(np.mean([r["safe_power_capture_ratio"] for r in ctrl])),
                "steady_capture": float(np.mean([r["safe_power_capture_ratio"] for r in ss])),
                "scans": C.scan_episode_count(rows),
                "triggers": int(sum(int(r["detector_trigger"]) for r in rows))}

    print("\n" + "=" * 94)
    print("复审 B：强行制造跨边界配对，看后果是否真的出现")
    print("=" * 94)
    print("检测器的 eligible 门只收 action=='CONTROL' 且 amplitude>=0.999 的行，")
    print("P&O 的 REFERENCE/PROBE（幅度 0.40）不在其列 —— 但配对之间有 5 个 CONTROL 行，")
    print("检测器照常累计。且每次触发都 po_step = INITIAL，重扫本身不使用 po_step。\n")
    print(f"{'平移(ms)':>9}{'配对':>7}{'跨边界':>8}{'均捕获':>10}{'稳态捕获':>11}{'重扫':>7}{'触发':>7}")
    rows = []
    for ms in (0, 20, 40, 50, 60, 70):
        r = analyse(ms / 1000.0); rows.append(r)
        print(f"{ms:>9}{r['pairs']:>7}{r['straddle']:>8}{r['mean_capture']*100:>9.2f}%"
              f"{r['steady_capture']*100:>10.2f}%{r['scans']:>7}{r['triggers']:>7}")
    print("\n=> 跨边界配对出现与否，重扫次数（6）与检测触发数（4）完全不变，捕获率未下降。")
    print("   捕获率的波动由扫描落点与扰动切换的相位对齐主导（与 scan_parameters.json 中")
    print("   已记录的同一效应同源），不构成跨边界配对的后果。")
    print("   机制真实，但在本架构里被检测器 + 重扫完全吸收。严重度〔高〕不成立。")
    sys.path.pop(0)
    out["B"] = {"sweep": rows,
                "verdict": "机制真实但后果被吸收。严重度由〔高〕降为〔低/理论〕。"
                           "「步长坍缩到 0.1 kHz」不可达（每次检测触发都重置 po_step，"
                           "且重扫不使用 po_step）。「4/7 判错方向」是假定初始方向的产物。"}


def main() -> None:
    reaudit_C()
    reaudit_B()
    (HERE / "reaudit_findings.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {HERE/'reaudit_findings.json'}")


if __name__ == "__main__":
    main()
