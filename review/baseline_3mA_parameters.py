#!/usr/bin/env python3
"""换主基线：由原冻结文件推导 3 mA 物理基线，写入补丁副本的两个 stage2 文件。

    python review/baseline_3mA_parameters.py --root <原 current/unified> --write <补丁副本 current/unified>
    python review/baseline_3mA_parameters.py --root <原 current/unified> --check <补丁副本 current/unified>

推导（与 review/design_current_study.py 第十五节逐位相同，结果可用它交叉复核）
  1. 工作点钉死 M = X_C0/Rm（fs 处，原基线 3.506832）；取 k_eff = 0.45，
     Qm = M·(1−k²)/k² = 13.81（review/24 第八节：同一工作点的物理基线）。
  2. 阻抗按 k = 5/3 均匀缩放（C0/k、Cm/k、Lm·k、Rm·k）：0.9 MHz、a=1、100 Vpp 时端口电流
     5 mA → 3 mA；Q、fs、k_eff 不变（同材料同长度、端面积 3/5）。
  3. 匹配网络按 stage2 原规则重设计：理想 L 型作初值，有损模型（QL=100、QC=1000、ESR 取
     0.9 MHz 值）上 Nelder–Mead 最大化 0.9 MHz 处 P_Rm，容差同原脚本。
  4. 源幅度标定到 0.9 MHz、a=1 时端口 100 Vpp，冻结。

只读原目录；--write 只写补丁副本的 stage2_matching/ 两个文件，拒绝写原目录、workspace/、outputs/。
--check 重新推导并与副本里的文件逐值比较（float 必须完全相等）。
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import physical_baseline_control_check as PB    # noqa: E402
import design_current_study as DC               # noqa: E402

KEFF = 0.45
DESIGN_CURRENT_A = 0.003
PREVIOUS_DESIGN_CURRENT_A = 0.005
TARGET_VPP = 100.0
DESIGN_FILE = 'stage2_匹配设计参数.json'
CAL_FILE = 'stage2_控制源幅度校准.json'


def derive(root: pathlib.Path) -> tuple[dict, dict, dict]:
    """返回 (设计文件, 标定文件, 摘要)；只读 root。"""
    _, _, _, model, cfg = PB.build(root)
    old_design = json.loads((root / 'stage2_matching' / DESIGN_FILE).read_text(encoding='utf-8'))
    old_cal = json.loads((root / 'stage2_matching' / CAL_FILE).read_text(encoding='utf-8'))
    base, match, rs = model.BASE_BVD, model.BASE_MATCH, model.BASE_RS
    if base.qm != 800.0 or model.SOURCE_A1_VRMS != old_cal['source_Vrms_for_a1']:
        raise SystemExit('--root 不是原冻结基线（Qm 800、原源标定）；拒绝从已改动的目录推导')
    f0 = cfg['initial_frequency_Hz']
    w0 = 2 * math.pi * base.fs
    m_fixed = (1 / (w0 * base.c0)) / base.rm
    q_new = m_fixed / (KEFF ** 2 / (1 - KEFF ** 2))          # 与 design_current_study 同式
    base_q = model.changed_qm(base, q_new)
    k = 5.0 / 3.0                    # = 5 mA / 3 mA；与 design_current_study 的 5.0 / i_d 同一浮点值
    bvd = model.bvd_from_fs_qm(c0=base_q.c0 / k, rm=base_q.rm * k, fs=base_q.fs, qm=base_q.qm)
    dm = DC.design_matching(bvd, rs, match.ql, match.qc, model.F0)
    m_new = model.Matching(l_h=dm['l_active_H'], c_f=dm['c_active_F'], ql=match.ql, qc=match.qc)
    probe = model.Scenario('PROBE', 'probe', 'probe', 'probe', '', bvd, m_new, rs)
    saved = model.SOURCE_A1_VRMS
    try:
        model.SOURCE_A1_VRMS = 1.0
        unit = model.response(f0, probe, 1.0)
        vpp_unit = float(unit['vport_vpp'][0])
        a1 = TARGET_VPP / vpp_unit                          # 同 DC：a1 = 100 / vpp_unit
        model.SOURCE_A1_VRMS = a1
        q = model.response(f0, probe, 1.0)
    finally:
        model.SOURCE_A1_VRMS = saved
    s = lambda key: float(q[key][0])                       # noqa: E731
    r_l = 2 * math.pi * model.F0 * m_new.l_h / m_new.ql
    r_c = 1 / (2 * math.pi * model.F0 * m_new.c_f * m_new.qc)
    vpp_per_vrms = 2 * math.sqrt(2)

    design = dict(old_design)
    design['model_id'] = 'MODEL_V2_1_PHYSICAL_BASELINE_3MA'
    design['bvd'] = dict(C0_F=bvd.c0, Rm_ohm=bvd.rm, Lm_H=bvd.lm, Cm_F=bvd.cm, fs_Hz=bvd.fs, Qm=bvd.qm)
    design['baseline_derivation'] = dict(
        status='假设基线（由一维 Mason 模型与需求推导，非实测器件）；2026-10-16 起替代 Qm=800 假设基线',
        rule=('同一工作点的物理基线：fs 处 M=X_C0/Rm 由工作点钉死；取 k_eff=0.45 得 Qm=M(1-k^2)/k^2；'
              '再按 k=5/3 均匀缩放阻抗（C0/k、Cm/k、Lm*k、Rm*k），使 0.9 MHz、a=1、100 Vpp 时端口电流为 3 mA；'
              '匹配网络按 stage2 原规则重设计，源幅度重标定到 100 Vpp'),
        k_eff=KEFF, M_xc0_over_rm_at_fs=m_fixed, impedance_scale=k,
        design_point_current_Arms=DESIGN_CURRENT_A,
        user_current_upper_limit_Arms=PREVIOUS_DESIGN_CURRENT_A,
        previous_baseline=dict(C0_F=base.c0, Rm_ohm=base.rm, Lm_H=base.lm, Cm_F=base.cm, fs_Hz=base.fs,
                               Qm=base.qm, l_active_H=match.l_h, c_active_F=match.c_f,
                               source_Vrms_for_a1=old_cal['source_Vrms_for_a1'],
                               design_point='100 Vpp / 5.000 mA RMS / 170 mW at 0.9 MHz, a=1',
                               registered_batch='UNIFIED_20260923T013352_476445Z_f442bcda'),
        evidence=['review/24_仿真参数的物理可实现性_对照原始需求_2026-10-15.md 第八、十五节',
                  'review/physical_realizability_study.py', 'review/design_current_study.py',
                  'review/25 （本次换基线说明）'],
        generator='review/baseline_3mA_parameters.py')
    design['design'] = dict(
        l_ideal_H=dm['l_ideal_H'], c_ideal_F=dm['c_ideal_F'],
        l_active_H=dm['l_active_H'], c_active_F=dm['c_active_F'],
        r_l_active_ohm_at_f0=r_l, r_c_active_ohm_at_f0=r_c,
        network_q=dm['network_q'], optimizer_iterations=dm['iterations'], optimizer_success=True)
    design['calibration'] = dict(
        old_design['calibration'],
        calibration_frequency_Hz=float(f0), target_transducer_Vpp=TARGET_VPP, unit_source_Vrms=1.0,
        vport_per_unit_source_Vrms=vpp_unit / vpp_per_vrms,
        a1_source_Vrms=a1, a1_source_Vpp=a1 * vpp_per_vrms,
        expected_p_rm_W=s('p_rm_W'), expected_total_iport_Arms=s('iport_irms_A'))
    cal = dict(old_cal)
    cal.update(source_Vrms_for_a1=a1, source_Vpp_for_a1=a1 * vpp_per_vrms,
               transducer_Vpp=s('vport_vpp'), transducer_Irms_A=s('iport_irms_A'),
               P_Rm_W=s('p_rm_W'), P_port_W=s('p_port_W'), Q_port_var=s('q_port_var'),
               S_port_VA=s('s_port_VA'), P_source_W=s('p_source_W'), P_Rs_W=s('p_rs_W'),
               P_L_ESR_W=s('p_l_esr_W'), P_C_ESR_W=s('p_c_esr_W'),
               eta_elec=s('p_rm_W') / s('p_source_W'))
    cal['baseline'] = 'MODEL_V2_1_PHYSICAL_BASELINE_3MA；推导见 stage2_匹配设计参数.json 的 baseline_derivation'
    summary = dict(Qm=bvd.qm, k_eff=KEFF, C0_pF=bvd.c0 * 1e12, Rm_ohm=bvd.rm, Lm_mH=bvd.lm * 1e3,
                   Cm_fF=bvd.cm * 1e15, L_match_uH=dm['l_active_H'] * 1e6, C_match_pF=dm['c_active_F'] * 1e12,
                   network_q=dm['network_q'], iterations=dm['iterations'], a1_Vrms=a1,
                   V_Vpp=s('vport_vpp'), I_mA=s('iport_irms_A') * 1e3, P_mW=s('p_rm_W') * 1e3,
                   eta_elec=s('p_rm_W') / s('p_source_W'))
    return design, cal, summary


def dump(data: dict) -> str:
    """与原文件同格式：CRLF 换行、末尾无换行。"""
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).replace('\n', '\r\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True, help='原 current/unified（只读）')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--write', help='补丁副本的 current/unified')
    g.add_argument('--check', help='补丁副本的 current/unified：重新推导并逐值比较')
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve()
    dest = pathlib.Path(args.write or args.check).resolve()
    if dest == root:
        raise SystemExit('原目录与补丁副本不能相同')
    if {'workspace', 'outputs'} & set(dest.parts):
        raise SystemExit(f'拒绝写入 workspace/ 或 outputs/：{dest}')
    design, cal, summary = derive(root)
    for key, value in summary.items():
        print(f'{key:>12} = {value!r}')
    targets = {dest / 'stage2_matching' / DESIGN_FILE: design, dest / 'stage2_matching' / CAL_FILE: cal}
    if args.write:
        for path, data in targets.items():
            path.write_text(dump(data), encoding='utf-8')
            print('写入', path)
        return 0
    bad = [str(p) for p, data in targets.items()
           if json.loads(p.read_text(encoding='utf-8')) != json.loads(dump(data))]
    print('复核：' + ('一致' if not bad else '不一致 ' + ', '.join(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
