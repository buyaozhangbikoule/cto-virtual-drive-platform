#!/usr/bin/env python3
"""5 mA 的测点未定时：换能器端与功放端电流在什么条件下不同，功放端并联补偿电感的效果（review/31）。

    python review/current_limit_location.py [--out <目录>]

只读；--out 时另写一份 JSON（拒绝 workspace/ 与 outputs/）。运行期只依赖 numpy。
元件与 Mason 模型沿用 codex_baseline_check.py：APC 880 杆 D 0.5 mm、L 1.7467 mm（有载 fs 900 kHz，review/29 第 3.1 节），
前端障板活塞、类血液液体，后端自由。

- 导管线缆按集总并联电容（1–1.5 m 远小于线缆中 λ/4，集总近似可用），并在换能器与功放之间。
- 换能器端保持 100 Vpp，算换能器端电流、功放端电流，以及功放端限 5 mA 时换能器端最多能加多少电压。
- 补偿：在功放输出口并一个电感 Lc = 1/(ω0²·C线缆)，ω0 取 900 kHz；电感损耗按 Q_L = 100 折成并联电导。
  另算频率偏 ±2% 时补偿后的功放端电流（控制器跟频时补偿电感不跟着改）。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import codex_baseline_check as C   # noqa: E402

L_ROD = 1.7467e-3
F0 = 900e3
CABLE_PF = (0.0, 30.0, 100.0, 150.0)
DETUNE = (-0.02, 0.0, 0.02)
Q_L = 100.0
V_PORT_VPP = 100.0
I_LIMIT = 5e-3


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    el = C.element(0.5e-3, L_ROD)
    z = C.zfun(el)
    v = V_PORT_VPP / C.SQ8
    w0 = 2 * math.pi * F0
    rows = []
    print(f'== APC 880 杆 D 0.5 mm、L {L_ROD*1e3:.4f} mm；换能器端 {V_PORT_VPP:g} Vpp；补偿电感按 {F0/1e3:g} kHz 定、Q_L = {Q_L:g}')
    for cpf in CABLE_PF:
        c = cpf * 1e-12
        lc = 1.0 / (w0 * w0 * c) if c else None
        loss_mw = v * v * (w0 * c / Q_L) * 1e3 if c else 0.0
        print(f"  线缆 {cpf:5.0f} pF" + (f"：补偿电感 {lc*1e3:.3f} mH，电感损耗约 {loss_mw:.1f} mW" if c else ''))
        for d in DETUNE:
            f = F0 * (1 + d)
            w = 2 * math.pi * f
            yt = complex(1.0 / z(np.array([f]))[0])
            ytot = yt + 1j * w * c
            yl = (1.0 / (1j * w * lc) + 1.0 / (Q_L * w0 * lc)) if c else 0.0
            row = dict(cable_pF=cpf, f_Hz=f, detune=d, port_mA=v * abs(yt) * 1e3, amp_mA=v * abs(ytot) * 1e3,
                       amp_compensated_mA=v * abs(ytot + yl) * 1e3,
                       port_Vpp_max_if_amp_limited=min(V_PORT_VPP, I_LIMIT / abs(ytot) * C.SQ8),
                       comp_inductor_mH=lc * 1e3 if c else None, inductor_loss_mW=loss_mw)
            rows.append(row)
            print(f"    {f/1e3:6.1f} kHz：换能器端 {row['port_mA']:5.2f} mA；功放端 未补偿 {row['amp_mA']:6.2f} mA、"
                  f"补偿后 {row['amp_compensated_mA']:5.2f} mA；功放端限 5 mA 时换能器端最多 {row['port_Vpp_max_if_amp_limited']:6.1f} Vpp")
    if a.out:
        out = pathlib.Path(a.out).resolve()
        if {'workspace', 'outputs'} & set(out.parts):
            raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{out}')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'current_limit_location.json').write_text(json.dumps(dict(rod_L_m=L_ROD, f0_Hz=F0, q_l=Q_L, rows=rows),
                                                                    ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'\n已写入 {out / "current_limit_location.json"}')


if __name__ == '__main__':
    main()
