#!/usr/bin/env python3
"""合成候选基线（Q=13.81、3 mA）：由原冻结文件推导，写成正式平台的一套**候选配置**。

    python review/baseline_3mA_parameters.py --root <原 current/unified> --write <补丁副本 current/unified>
    python review/baseline_3mA_parameters.py --root <原 current/unified> --check <补丁副本 current/unified>

〔已改正 2026-10-16，见 review/26〕55fbe6e 版把结果写进 stage2_matching/、替换默认基线，并称之为
「物理基线」。审查指出：它是保留原工作点构造出来的合成参数，不是任何确定器件的拟合结果；按面积缩放
的物理解释也不成立。现在只写到 candidates/synthetic_q13p8_3mA/，默认配置不变。

推导（数值与 review/design_current_study.py 第十五节逐位相同，可交叉复核）
  1. 保留原基线的 C0、Rm、fs，即 fs 处 M = X_C0/Rm = 3.506832；指定 k_eff = 0.45，
     按 BVD 关系反算 Qm = M·(1−k²)/k² = 13.81。Lm、Cm、k_eff 随之改变——这是另一组等效电路，
     不能理解为「同一只器件放进血液、只增加阻尼」。
  2. 把 BVD 阻抗按 k = 5/3 均匀缩放（C0/k、Cm/k、Lm·k、Rm·k），使 0.9 MHz、a=1、100 Vpp 时
     换能器端电流为 3 mA。这是一次合成重设计，**不是几何缩小的推论**：同材料同长度、端面积缩为 0.6 倍时，
     用本仓库的 Mason 模型重算，Q、fs 都会变，|Z| 也不按 5/3 变（review/review_claims_check_20261016.py）。
  3. 匹配网络按 stage2 原规则重新设计：理想 L 型作初值，有损模型（QL=100、QC=1000、ESR 取 0.9 MHz 值）
     上 Nelder–Mead 最大化 0.9 MHz 处 P_Rm，容差同原脚本。
  4. 源幅度标定到 0.9 MHz、a=1 时换能器端 100 Vpp 并冻结。
  5. 候选配置：电流软/硬限 4.5/5.0 mA，作用于换能器端口——这只是用户「5 mA 上限」的一种测点解释；
     按功放输出端解释，本候选在设计点的功放电流为 45.14 mA rms，不满足。相位反馈恢复门控打开。
     〔补充 2026-10-16，review/27〕P4 起配置里有 nominal_peak_width_Hz（设计点有载半功率宽度），
     候选取本候选自己的值（同式推导，86872 Hz）；其余新增项随默认配置继承。

只读 --root；--write 只写 <副本>/candidates/synthetic_q13p8_3mA/ 下三个文件（README.md 手写，不由本脚本生成），
拒绝写原目录、workspace/、outputs/。--check 重新推导并与副本里的文件逐值比较。
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
TARGET_VPP = 100.0
CANDIDATE_DIR = 'candidates/synthetic_q13p8_3mA'
CANDIDATE_ID = 'SYNTHETIC_CANDIDATE_Q13P8_3MA'
DESIGN_FILE = 'stage2_匹配设计参数.json'
CAL_FILE = 'stage2_控制源幅度校准.json'


def derive(root: pathlib.Path) -> tuple[dict, dict, dict]:
    """返回 (设计文件, 标定文件, 摘要)；只读 root。"""
    _, _, _, model, cfg = PB.build(root)
    old_design = json.loads((root / 'stage2_matching' / DESIGN_FILE).read_text(encoding='utf-8'))
    old_cal = json.loads((root / 'stage2_matching' / CAL_FILE).read_text(encoding='utf-8'))
    base, match, rs = model.BASE_BVD, model.BASE_MATCH, model.BASE_RS
    if base.qm != 800.0 or model.SOURCE_A1_VRMS != old_cal['source_Vrms_for_a1']:
        raise SystemExit('--root 的默认基线不是原冻结基线（Qm 800、原源标定）；拒绝推导')
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
        vpp_unit = float(model.response(f0, probe, 1.0)['vport_vpp'][0])
        a1 = TARGET_VPP / vpp_unit                          # 同 DC：a1 = 100 / vpp_unit
        model.SOURCE_A1_VRMS = a1
        q = model.response(f0, probe, 1.0)
    finally:
        model.SOURCE_A1_VRMS = saved
    s = lambda key: float(q[key][0])                       # noqa: E731
    i_amp = float(abs(q['i_source'][0]))
    r_l = 2 * math.pi * model.F0 * m_new.l_h / m_new.ql
    r_c = 1 / (2 * math.pi * model.F0 * m_new.c_f * m_new.qc)
    vpp_per_vrms = 2 * math.sqrt(2)

    design = {k_: v for k_, v in old_design.items() if k_ != 'baseline_role'}
    design['model_id'] = CANDIDATE_ID
    design['bvd'] = dict(C0_F=bvd.c0, Rm_ohm=bvd.rm, Lm_H=bvd.lm, Cm_F=bvd.cm, fs_Hz=bvd.fs, Qm=bvd.qm)
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
    design['baseline_derivation'] = dict(
        status=('合成候选基线（宽峰算法对照用）：不是任何确定尺寸、材料、血液负载器件的拟合结果，未实测；'
                '不设为默认，也不宣称为目标器件参数'),
        rule=('保留原基线 C0、Rm、fs（fs 处 M = X_C0/Rm 不变），指定 k_eff = 0.45，按 BVD 关系反算 '
              'Qm = M(1-k^2)/k^2；Lm、Cm、k_eff 随之改变，不能理解为同一器件只增加阻尼。再把 BVD 阻抗按 '
              'k = 5/3 均匀缩放，使 0.9 MHz、a=1、100 Vpp 时换能器端电流为 3 mA，并按 stage2 规则重新设计'
              '匹配网络、重新标定源幅度：这是一组重新设计的合成电路，不是几何缩小的推论'),
        k_eff=KEFF, M_xc0_over_rm_at_fs=m_fixed, impedance_scale=k,
        design_point_transducer_current_Arms=DESIGN_CURRENT_A,
        design_point_amplifier_output_current_Arms=i_amp,
        current_measurement_point=('限值作用于换能器端口，这只是用户「5 mA 上限」的一种测点解释；'
                                   '按功放输出端解释，本候选在设计点不满足'),
        geometric_scaling_caveat=('同材料、同长度、端面积缩为 0.6 倍时，按本仓库 Mason 模型（血液、空气背衬）重算，'
                                  'Q、fs 都会变，|Z| 比约 1.9 而非 5/3；均匀缩放不能保证「电流减小而振速不变」'),
        previous_baseline=dict(C0_F=base.c0, Rm_ohm=base.rm, Lm_H=base.lm, Cm_F=base.cm, fs_Hz=base.fs,
                               Qm=base.qm, l_active_H=match.l_h, c_active_F=match.c_f,
                               source_Vrms_for_a1=old_cal['source_Vrms_for_a1'],
                               design_point='100 Vpp / 5.000 mA RMS / 170 mW at 0.9 MHz, a=1',
                               registered_batch='UNIFIED_20260923T013352_476445Z_f442bcda'),
        evidence=['review/24 第八、十五节（数值）', 'review/26（审查意见与改正）',
                  'review/design_current_study.py', 'review/review_claims_check_20261016.py'],
        generator='review/baseline_3mA_parameters.py')
    cal = dict(old_cal)
    cal.update(source_Vrms_for_a1=a1, source_Vpp_for_a1=a1 * vpp_per_vrms,
               transducer_Vpp=s('vport_vpp'), transducer_Irms_A=s('iport_irms_A'),
               amplifier_output_Irms_A=i_amp,
               P_Rm_W=s('p_rm_W'), P_port_W=s('p_port_W'), Q_port_var=s('q_port_var'),
               S_port_VA=s('s_port_VA'), P_source_W=s('p_source_W'), P_Rs_W=s('p_rs_W'),
               P_L_ESR_W=s('p_l_esr_W'), P_C_ESR_W=s('p_c_esr_W'),
               eta_elec=s('p_rm_W') / s('p_source_W'))
    cal['baseline'] = f'{CANDIDATE_ID}（合成候选，非默认）；推导见同目录设计文件的 baseline_derivation'
    summary = dict(Qm=bvd.qm, k_eff=KEFF, C0_pF=bvd.c0 * 1e12, Rm_ohm=bvd.rm, Lm_mH=bvd.lm * 1e3,
                   Cm_pF=bvd.cm * 1e12, L_match_uH=dm['l_active_H'] * 1e6, C_match_pF=dm['c_active_F'] * 1e12,
                   network_q=dm['network_q'], iterations=dm['iterations'], a1_Vrms=a1,
                   V_Vpp=s('vport_vpp'), I_mA=s('iport_irms_A') * 1e3, P_mW=s('p_rm_W') * 1e3,
                   amplifier_mA=i_amp * 1e3,
                   loaded_width_Hz=loaded_width(model, probe, a1))
    return design, cal, summary


def loaded_width(model, scenario, a1) -> float:
    """设计点的有载半功率宽度：a=1 时 P_Rm(f) 的半功率点间距（1 Hz 网格、交点线性插值）。

    〔补充 2026-10-16，review/27〕P4 起配置项 nominal_peak_width_Hz 取此值（四舍五入到 1 Hz）：
    控制器在第一次捕获测得峰宽之前，按它定点驻留、探针偏移与步长。默认配置同式得 2142 Hz。
    """
    import numpy as np
    saved = model.SOURCE_A1_VRMS
    try:
        model.SOURCE_A1_VRMS = a1
        f = np.arange(600000.0, 1200000.0, 1.0)
        p = model.response(f, scenario, 1.0)['p_rm_W']
    finally:
        model.SOURCE_A1_VRMS = saved
    j = int(np.argmax(p))
    half = p[j] / 2
    lo, hi = j, j
    while p[lo] > half:
        lo -= 1
    while p[hi] > half:
        hi += 1
    left = f[lo] + (half - p[lo]) / (p[lo + 1] - p[lo])
    right = f[hi] - (half - p[hi]) / (p[hi - 1] - p[hi])
    return float(right - left)


def candidate_config(default_cfg: dict, width_Hz: float | None = None) -> dict:
    cfg = dict(default_cfg)
    cfg.update({
        'version': 'plan-three-strategy-v1-candidate-synthetic-q13p8-3mA',
        'parameter_origin': 'synthetic_candidate_constructed_not_a_device_fit_non_measured',
        'user_boundaries': ('0.8-1.0 MHz, start 0.9 MHz, nominal port 100 Vpp, hard 160 Vpp; user: 5 mA RMS is an '
                            'upper limit, recommended lower, measurement point unspecified (transducer port or '
                            'amplifier output)'),
        'baseline_design_file': f'{CANDIDATE_DIR}/{DESIGN_FILE}',
        'baseline_calibration_file': f'{CANDIDATE_DIR}/{CAL_FILE}',
        'current_limit_measurement_point': ('transducer_port, i.e. one interpretation of the user 5 mA upper limit; '
                                            'under the amplifier-output interpretation this candidate draws about '
                                            '45 mA RMS at its design point and does not comply'),
        'current_soft_Arms': 0.0045,
        'current_hard_Arms': 0.005,
        'phase_centre_recovery_gate': True,
    })
    if 'nominal_peak_width_Hz' in cfg:          # P4 及以后的配置才有此项
        cfg['nominal_peak_width_Hz'] = round(width_Hz)
    return cfg


def dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


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
    cfg = candidate_config(json.loads((dest / 'config.json').read_text(encoding='utf-8')),
                           summary['loaded_width_Hz'])
    for key, value in summary.items():
        print(f'{key:>12} = {value!r}')
    out = dest / CANDIDATE_DIR
    targets = {out / DESIGN_FILE: design, out / CAL_FILE: cal, out / 'config.json': cfg}
    if args.write:
        out.mkdir(parents=True, exist_ok=True)
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
