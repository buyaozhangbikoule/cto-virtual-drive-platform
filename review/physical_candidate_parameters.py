#!/usr/bin/env python3
"""物理候选 B（APC 880、D 0.5 mm、L 1.7467 mm，直接驱动）的平台参数文件（review/32，补丁 P8）。

    python -I review/physical_candidate_parameters.py --synthetic <合成候选 config.json> --out <候选目录>
    python -I review/physical_candidate_parameters.py --synthetic <合成候选 config.json> --check <候选目录>

--out 写 config.json 与两个 stage2 文件（目录须不存在）；--check 逐值复核已有文件，不符即非零退出。

输入
  · BVD：Codex 的 derive_candidates.py（sha256 183f7641…，原样存档于
    results/codex_baseline_review_20261016/codex_inputs/）用本仓库重建的假设文件、只把长度改为 1.7467 mm 的运行结果
    （results/p8_admittance_track_20261017/codex_L1747/candidate_parameters.json）中的 APC880_D0.5。
  · 合成候选的运行配置（已打 P8）：控制参数照抄，只改本候选不同的项（见 CHANGED）。
推导（不调用平台代码；平台测试再用平台模型复核）
  · 直接驱动：50 Ω 戴维南源直接接换能器，无匹配网络、无线缆（l_active_H = c_active_F = 0）。
  · 源标定：0.9 MHz、a = 1 时换能器端 100 Vpp。
  · 标称峰宽：a = 1 时 P_Rm(f) 两个半功率点的间距（1 Hz 网格、交点线性插值），取整到 1 Hz，与默认配置同式。
  · 捕获扫描幅度：无源负载上端口电压不超过源开路电压，a = min(1, 软限 ÷ 源开路 Vpp) = 1。
  · 电流限值：5 mA 的测点未定（用户 2026-10-17），两处都限，软/硬 4.5/5.0 mA（review/31）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUN = HERE/'results'/'p8_admittance_track_20261017'/'codex_L1747'/'candidate_parameters.json'
CANDIDATE_ID = 'APC880_D0.5_L1.8_front_BMF'     # Codex 的标识沿用默认长度 1.8 mm；本次运行长度为 1.7467 mm
FOLDER = 'candidates/physical_apc880_d05_L1747'
F0, RS, SQ8 = 0.9e6, 50.0, 2*math.sqrt(2)
DESIGN_NAME, CAL_NAME = 'stage2_匹配设计参数.json', 'stage2_控制源幅度校准.json'
POINT = ('both: transducer_port and amplifier_output. The user has not decided where the 5 mA RMS upper limit is '
         'measured (2026-10-17, review/31), so both are limited; without a cable (this candidate) the two currents '
         'are equal, so the choice changes nothing here')


def bvd():
    run = json.loads(RUN.read_text(encoding='utf-8'))
    cand = next(c for c in run['candidates'] if c['id'] == CANDIDATE_ID)
    assert abs(cand['element']['length']-0.0017467) < 1e-12 and abs(cand['element']['d']-0.0005) < 1e-12
    return run, cand


def response(f, b, vs):
    """Direct drive: Thevenin source vs (RMS) with RS straight into the BVD."""
    w = 2*np.pi*np.asarray(f, dtype=float)
    zm = b['rm'] + 1j*(w*b['lm'] - 1/(w*b['cm']))
    z = 1/(1/zm + 1j*w*b['c0'])
    i = vs/(RS+z)
    v = i*z
    return dict(z=z, zm=zm, i=i, v=v, p_rm=np.abs(v/zm)**2*b['rm'])


def half_power_width(b, vs):
    f = np.arange(F0-300000., F0+300000., 1.)
    p = response(f, b, vs)['p_rm']
    j = int(np.argmax(p))
    half = p[j]/2
    lo, hi = j, j
    while p[lo] > half:
        lo -= 1
    while p[hi] > half:
        hi += 1
    return float((f[hi]-(half-p[hi])/(p[hi-1]-p[hi]))-(f[lo]+(half-p[lo])/(p[lo+1]-p[lo])))


def build(synthetic: dict):
    run, cand = bvd()
    b = cand['bvd']
    z0 = complex(response(F0, b, 1.)['z'])
    vs = 100/SQ8*abs(RS+z0)/abs(z0)
    q = {k: complex(v) if np.iscomplexobj(v) else float(v) for k, v in response(F0, b, vs).items()}
    s_port = q['v']*q['i'].conjugate()
    p_source = (vs*q['i'].conjugate()).real
    p_rs = abs(q['i'])**2*RS
    width = round(half_power_width(b, vs))
    v_open_vpp = vs*SQ8
    capture_amplitude = min(1., synthetic['voltage_soft_Vpp']/v_open_vpp)
    design = dict(
        model_id='PHYSICAL_CANDIDATE_APC880_D05_L1747_DIRECT',
        topology='direct drive: Rs -> transducer port; no matching network, no cable (l_active_H = c_active_F = 0)',
        comparison_source='Thevenin source with fixed 50 ohm Rs straight into the BVD',
        bvd=dict(C0_F=b['c0'], Rm_ohm=b['rm'], Lm_H=b['lm'], Cm_F=b['cm'], fs_Hz=b['fs'], Qm=b['q']),
        matching_loss_assumptions=dict(
            source_class='NOT_USED_DIRECT_DRIVE', inductor_Q_at_f0=100.0, capacitor_Q_at_f0=1000.0,
            esr_model='no matching elements: with l_active_H = c_active_F = 0 both ESRs are zero; the two Q values only satisfy the file format and enter no result'),
        design=dict(l_ideal_H=0.0, c_ideal_F=0.0, l_active_H=0.0, c_active_F=0.0,
                    r_l_active_ohm_at_f0=0.0, r_c_active_ohm_at_f0=0.0, network='none (direct drive)'),
        calibration=dict(
            source_class='DERIVED_VALUE for direct drive; not a hardware rating',
            calibration_frequency_Hz=F0, target_transducer_Vpp=100.0, unit_source_Vrms=1.0,
            vport_per_unit_source_Vrms=abs(z0)/abs(RS+z0), a1_source_Vrms=vs, a1_source_Vpp=v_open_vpp,
            expected_p_rm_W=q['p_rm'], expected_total_iport_Arms=abs(q['i']),
            rule='freeze this Thevenin source amplitude for all future scenarios; protection may only reduce it'),
        baseline_derivation=dict(
            status='物理候选（未设为默认）：一维压电杆模型＋无限障板辐射推导、最小二乘拟合的 BVD；未实测，不宣称为目标器件参数',
            element='APC 880 端面电极杆，D 0.5 mm，L 1.7467 mm（有载 fs 0.9 MHz）；前端类血液液体、无限障板，后端空气背衬',
            bvd_source=('Codex derive_candidates.py（sha256 183f76411b15945031248c50daa3cbedd85f5a1f7732421d40c3f0ed36951a23，原样）'
                        '用本仓库重建的假设文件、长度改为 1.7467 mm 运行；候选 ' + CANDIDATE_ID +
                        '（标识沿用 Codex 的默认长度 1.8 mm）；0.8–1.0 MHz 最小二乘拟合，|Z| 最大相对误差 '
                        f"{100*b['fit']['max_relative_Z_error']:.2f}%"),
            bvd_run_file='review/results/p8_admittance_track_20261017/codex_L1747/candidate_parameters.json',
            bvd_run_file_sha256=hashlib.sha256(RUN.read_bytes()).hexdigest(),
            assumptions_sha256=run['assumptions_sha256'],
            repository_model_comparison='本仓库一维模型同一长度：Q 53.5、Rm 9206 Ω、100 Vpp 时 3.85 mA、136 mW（review/29 第 3.1 节），与本 BVD 相差 1% 以内',
            design_point_transducer_current_Arms=abs(q['i']),
            design_point_amplifier_output_current_Arms=abs(q['i']),
            current_measurement_point='5 mA 的测点未定（用户 2026-10-17），换能器端与功放输出端都限，软/硬 4.5/5.0 mA（review/31）；直接驱动、无线缆时两处电流相同',
            registered_scenarios_note='无匹配网络：CASE_LMATCH_*、CASE_CMATCH_*、CASE_QL_* 九个场景与基准相同，组合场景中只有 C0、Rm、fs、Rs 起作用',
            capture_scan_amplitude=('a = min(1, voltage_soft_Vpp ÷ 源开路 Vpp) = '
                                    f'min(1, {synthetic["voltage_soft_Vpp"]:g} ÷ {v_open_vpp:.2f}) = {capture_amplitude:g}：'
                                    '无源负载上端口电压不超过源开路电压；L 型匹配的 0.65 规则（软限 ÷ 两倍名义电压）在这里不需要'),
            evidence=['review/29 第 3.1、7.3 节', 'review/30 第五、六节', 'review/31', 'review/32'],
            generator='review/physical_candidate_parameters.py'))
    cal = dict(
        source_class='DERIVED_VALUE; direct drive and AC RMS-equivalent convention',
        source_Vrms_for_a1=vs, source_Vpp_for_a1=v_open_vpp,
        transducer_Vpp=abs(q['v'])*SQ8, transducer_Irms_A=abs(q['i']),
        P_Rm_W=q['p_rm'], P_port_W=s_port.real, Q_port_var=s_port.imag, S_port_VA=abs(s_port),
        P_source_W=p_source, P_Rs_W=p_rs, P_L_ESR_W=0.0, P_C_ESR_W=0.0, eta_elec=q['p_rm']/p_source,
        rule='freeze this source amplitude for stage3-5; protection may reduce but strategies may not increase it',
        amplifier_output_Irms_A=abs(q['i']),
        baseline='PHYSICAL_CANDIDATE_APC880_D05_L1747_DIRECT（物理候选，非默认）；推导见同目录设计文件的 baseline_derivation')
    config = changed_config(synthetic, width, capture_amplitude)
    return config, design, cal


CHANGED = ('version', 'parameter_origin', 'user_boundaries', 'baseline_design_file', 'baseline_calibration_file',
           'current_limit_measurement_point', 'user_current_limit_rule', 'current_limit_points',
           'nominal_peak_width_Hz', 'capture_scan_amplitude', 'capture_scan_rule')


def changed_config(synthetic: dict, width: int, capture_amplitude: float) -> dict:
    cfg = dict(synthetic)
    cfg.update(
        version='plan-three-strategy-v1-candidate-physical-apc880-d05-L1747-direct',
        parameter_origin='physical_candidate_1d_rod_model_least_squares_bvd_direct_drive_non_measured',
        user_boundaries=('0.8-1.0 MHz, start 0.9 MHz, nominal port 100 Vpp, hard 160 Vpp, 50 ohm source; user: 5 mA RMS is an '
                         'upper limit, recommended lower, measuring point not decided (2026-10-17); 0.9 MHz is acceptable for now'),
        baseline_design_file=f'{FOLDER}/{DESIGN_NAME}',
        baseline_calibration_file=f'{FOLDER}/{CAL_NAME}',
        current_limit_measurement_point=POINT,
        user_current_limit_rule=('user upper limit on the RMS current, applied at both current_limit_points (measuring point not '
                                 'decided, 2026-10-17); every execution row after the guard is checked against it at both points '
                                 'and reported per strategy; it does not change the guard limits'),
        current_limit_points=['transducer_port', 'amplifier_output'],
        nominal_peak_width_Hz=width,
        capture_scan_amplitude=capture_amplitude,
        capture_scan_rule=synthetic['capture_scan_rule'] + (
            '. This candidate (direct drive): the port voltage of a passive load cannot exceed the source open-circuit '
            'voltage, so capture_scan_amplitude = min(1, voltage_soft_Vpp / source open-circuit Vpp) = 1 instead of '
            'the L-match rule voltage_soft_Vpp/(2 x 100 Vpp)'))
    assert set(k for k in cfg if cfg[k] != synthetic.get(k)) <= set(CHANGED)
    return cfg


def dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--synthetic', required=True, type=Path, help='合成候选的 config.json（已打 P8）')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--out', type=Path)
    g.add_argument('--check', type=Path)
    a = ap.parse_args()
    synthetic = json.loads(a.synthetic.read_text(encoding='utf-8'))
    for key in ('current_limit_points', 'admittance_model_tolerance', 'recovery_fraction'):
        if key not in synthetic:
            raise SystemExit(f'--synthetic 缺少 {key}：先打 P8')
    files = dict(zip(('config.json', DESIGN_NAME, CAL_NAME), map(dump, build(synthetic))))
    if a.out:
        a.out.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            (a.out/name).write_bytes(data)
        print(f'wrote {len(files)} files to {a.out}')
        return 0
    bad = [n for n, data in files.items() if (a.check/n).read_bytes() != data]
    print(json.dumps(dict(checked=len(files), mismatches=bad), ensure_ascii=False))
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
