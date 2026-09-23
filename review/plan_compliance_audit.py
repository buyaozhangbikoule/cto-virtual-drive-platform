#!/usr/bin/env python3
"""复算 review/16 的每一个数字：对照第一月计划书的合规性审查。

只读。导入冻结的活动模型与已产出的结果表，不写入任何目录。

    python3 review/plan_compliance_audit.py
    python3 review/plan_compliance_audit.py --root <仓库根>

审查对象是计划书《面向冠状动脉CTO的虚拟换能器阻抗建模与自适应驱动控制仿真研究》
四周任务与第六节分析指标里**可核查**的条目，不评价超出计划书范围的工作。

输出七节，依次对应 review/16 的第二节（已满足条目的自动核验）
与第三节 G1–G5（五条缺口）。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
ACTIVE = 'workspace/outputs/v2_self_consistent_rebuild/active_stage3_5'
BAND = (800000.0, 1000000.0)
FINE_STEP_HZ = 1.0


def load_model(root: Path):
    sys.path.insert(0, str(root / ACTIVE))
    import model_v2_1 as model            # noqa: E402
    return model


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


# ==========================================================================
# 第二节：已满足条目的自动核验
# ==========================================================================
def section_satisfied(root: Path, model) -> None:
    print('== 1. 已满足条目的自动核验')

    q = model.response(np.array([900000.0]), model.scenario_map()['CASE_000_BASELINE'])
    required = ('z_in', 'v_port', 'i_port', 's_port_VA', 'p_port_W', 'phase_deg')
    missing = [k for k in required if k not in q]
    print(f'  计划书四.1 要求的输出量：{len(required)} 项，缺 {missing or "无"}'
          f'（response 共 {len(q)} 个字段）')

    cases = model.scenario_map()
    fam: dict[str, int] = {}
    for c in cases.values():
        fam[c.family if c.family != 'single_factor' else c.case_id.split('_')[1]] = \
            fam.get(c.family if c.family != 'single_factor' else c.case_id.split('_')[1], 0) + 1
    classes = {
        '谐振频率偏移': ['FS'],
        'C0 变化': ['C0'],
        '机械支路电阻变化': ['RM'],
        '源/匹配网络参数偏差': ['RS', 'LMATCH', 'CMATCH', 'QL'],
    }
    print('  计划书四.2 要求的四类扰动 × 三等级：')
    for label, keys in classes.items():
        n = sum(fam.get(k, 0) for k in keys)
        print(f'    {label:<22} {n} 个场景  {"✓" if n >= 3 else "✗"}')
    print(f'    组合扰动 {fam.get("combined", 0)} 个（低/中/高）  '
          f'{"✓" if fam.get("combined", 0) >= 3 else "✗"}  场景总数 {len(cases)}')

    checks = [
        ('计划书三周「三种选频判据对照」',
         f'{ACTIVE}/stage3_selection/stage3_initial_three_criteria.csv',
         ('max_power_frequency_Hz', 'min_abs_phase_frequency_Hz', 'min_reflection_frequency_Hz')),
        ('计划书三周「扫频窗口与步长权衡」',
         f'{ACTIVE}/stage3_selection/stage3_window_step_aggregate.csv',
         ('criterion', 'window_halfwidth_kHz', 'step_kHz')),
        ('计划书三周「增益扫描：收敛/振荡/频率饱和」',
         f'{ACTIVE}/stage4_5_control/phase_ablation/phase_gain_sweep_summary.csv',
         ('gain_Hz_per_deg', 'wrong_phase_lock_segments', 'frequency_saturation_ms')),
        ('计划书六「稳态误差/恢复时间/过冲/约束触发」',
         f'{ACTIVE}/stage4_5_control/stage5_per_segment_metrics.csv',
         ('steady_error_pct', 'recovery_time_ms', 'peak_power_overshoot_pct',
          'soft_limit_triggers', 'hard_trip_triggers')),
        ('计划书四周「电声接口标准化字段」',
         f'{ACTIVE}/structural_acoustic/electro_acoustic_interface_template.csv',
         ('frequency_Hz', 'drive_Vpp', 'electrical_P_Rm_W', 'relative_acoustic_efficiency',
          'target_pressure_proxy_Pa', 'wall_pressure_proxy_Pa', 'target_to_wall_ratio')),
    ]
    for label, rel, cols in checks:
        path = root / rel
        if not path.is_file():
            print(f'  {label}：**文件缺失** {rel}')
            continue
        header = read_csv(path)[0].keys() if read_csv(path) else []
        lack = [c for c in cols if c not in header]
        print(f'  {label}：{"✓ 全部列齐备" if not lack else f"✗ 缺 {lack}"}')

    lt = root / f'{ACTIVE}/stage3_disturbance/stage3_LTspice_cross_validation.csv'
    if lt.is_file():
        rows = read_csv(lt)
        worst = max(float(r['max_zin_relative_error']) for r in rows)
        print(f'  计划书二周「跨工具一致性」：{len(rows)} 个场景，'
              f'状态 {sorted(set(r["status"] for r in rows))}，'
              f'zin 最大相对误差 {worst:.3e}')

    stage2 = root / 'workspace/outputs/v2_self_consistent_rebuild/stage2_matching'
    if stage2.is_dir():
        cir = sorted(p.name for p in stage2.glob('*.cir'))
        print(f'  计划书二周「无匹配→理想→有损耗」：{cir}')


# ==========================================================================
# G1：串联与并联谐振
# ==========================================================================
def section_g1(root: Path, model) -> None:
    print('\n== 2. G1 并联谐振从未被计算（计划书四.1 明文要求同时观察）')
    base = model.scenario_map()['CASE_000_BASELINE']
    b = base.bvd
    fs = 1/(2*math.pi*math.sqrt(b.lm*b.cm))
    fp = fs*math.sqrt(1.0 + b.cm/b.c0)
    print(f'  Cm/C0 = {b.cm/b.c0:.6f}')
    print(f'  解析 fs = {fs:.1f} Hz     解析 fp = fs·√(1+Cm/C0) = {fp:.1f} Hz'
          f'     间隔 {fp-fs:.1f} Hz')
    print(f'  两者是否都在 {BAND[0]/1e6:.1f}–{BAND[1]/1e6:.1f} MHz 带内：'
          f'{BAND[0] < fs < BAND[1] and BAND[0] < fp < BAND[1]}')

    f = np.arange(880000.0, 940000.0, FINE_STEP_HZ)
    q = model.response(f, base)
    zb, zi = np.abs(q['z_bvd']), np.abs(q['z_in'])
    print(f'  {FINE_STEP_HZ:.0f} Hz 网格实测：')
    print(f'    |z_bvd| 极小 @ {f[int(np.argmin(zb))]:.0f} Hz = {zb.min():.1f} Ω   ← 串联谐振')
    print(f'    |z_bvd| 极大 @ {f[int(np.argmax(zb))]:.0f} Hz = {zb.max():.1f} Ω   ← 并联/反谐振')
    print(f'    |z_in|  极小 @ {f[int(np.argmin(zi))]:.0f} Hz = {zi.min():.1f} Ω')
    print(f'    P_Rm 峰  @ {f[int(np.argmax(q["p_rm_W"]))]:.0f} Hz')

    reg = root / f'{ACTIVE}/stage3_disturbance/stage3_scenario_registry_and_summary.csv'
    rows = read_csv(reg)
    r = next(x for x in rows if x['case_id'] == 'CASE_000_BASELINE')
    gap = float(r['zin_abs_min_Hz']) - float(r['power_peak_Hz'])
    print(f'  登记表（{len(rows)} 行）记录的两个数：')
    print(f'    power_peak_Hz   = {r["power_peak_Hz"]}')
    print(f'    zin_abs_min_Hz  = {r["zin_abs_min_Hz"]}      **相差 {gap:.0f} Hz**')
    hits = [k for k in r if any(t in k.lower() for t in ('parallel', 'anti', 'fp_'))]
    print(f'  登记表中的并联/反谐振字段：{hits or "无"}')
    print('  → 两个数都在表里，但没有任何文档指出它们相差 7.1 kHz，')
    print('    也没有据此把「阻抗最低」排除为工作点判据。数据有了，结论没写。')


# ==========================================================================
# G2：相位误差信号在带内的零点个数
# ==========================================================================
def section_g2(root: Path, model) -> None:
    print('\n== 3. G2 arg(Z_in) 带内有多个过零点，而第三策略以它为误差信号')
    base = model.scenario_map()['CASE_000_BASELINE']
    f = np.arange(BAND[0], BAND[1], FINE_STEP_HZ)
    q = model.response(f, base)
    ph = q['phase_deg']
    sign = np.sign(ph)
    cross = np.flatnonzero(sign[:-1]*sign[1:] < 0)
    print(f'  {FINE_STEP_HZ:.0f} Hz 网格，{BAND[0]/1e6:.1f}–{BAND[1]/1e6:.1f} MHz 内过零点：'
          f'**{len(cross)} 个**')
    for i in cross:
        print(f'    {f[i]:.0f} Hz   （{ph[i]:+.3f}° → {ph[i+1]:+.3f}°）')
    print(f'  P_Rm 峰 @ {f[int(np.argmax(q["p_rm_W"]))]:.0f} Hz')

    reg = root / f'{ACTIVE}/stage3_disturbance/stage3_scenario_registry_and_summary.csv'
    r = next(x for x in read_csv(reg) if x['case_id'] == 'CASE_000_BASELINE')
    print(f'  登记表 phase_zero_or_min_Hz = {r["phase_zero_or_min_Hz"]}'
          f'   status = {r["phase_feature_status"]}')
    print('  → 登记表只记单数 ZERO_CROSSING，没有记过零点个数。')

    gain = root / f'{ACTIVE}/stage4_5_control/phase_ablation/phase_gain_sweep_summary.csv'
    if gain.is_file():
        print('  项目自己的增益扫描（同一现象的独立证据）：')
        print(f"    {'增益':>8}{'稳态功率误差':>14}{'平均相位误差':>14}{'错锁段':>8}")
        for g in read_csv(gain):
            print(f"    {float(g['gain_Hz_per_deg']):>8.0f}"
                  f"{float(g['mean_steady_power_error_pct']):>13.1f}%"
                  f"{float(g['mean_abs_phase_error_deg']):>13.1f}°"
                  f"{int(float(g['wrong_phase_lock_segments'])):>8}")


# ==========================================================================
# G3：正式三策略名单
# ==========================================================================
def section_g3(root: Path) -> None:
    print('\n== 4. G3 正式三策略对比用的是 P&O，不是相位闭环')
    table = root / f'{ACTIVE}/stage4_5_control/stage5_integrated_strategy_table.csv'
    rows = read_csv(table)
    print(f'  {table.relative_to(root)} 中的策略：')
    for r in rows:
        print(f"    {r['strategy']:<16} 稳态误差 {float(r['steady_error_pct']):>7.2f}%"
              f"   未达标段 {r['unsettled_segments']}")
    print('  计划书四周要求的是「固定频率、周期扫频和**相位闭环**」。')
    abl = root / f'{ACTIVE}/stage4_5_control/phase_ablation'
    print(f'  相位闭环存在于单独消融目录 {abl.relative_to(root)}：'
          f'{sorted(p.name for p in abl.glob("*.csv")) if abl.is_dir() else "缺失"}')


# ==========================================================================
# G4：相对功率传递效率
# ==========================================================================
def section_g4(root: Path, model) -> None:
    print('\n== 5. G4 「相对功率传递效率」未计算（计划书六、分析指标明列）')
    found = set()
    for path in (root / 'workspace/outputs').rglob('*.csv'):
        try:
            with path.open(encoding='utf-8-sig', newline='') as fh:
                header = fh.readline()
        except OSError:
            continue
        for col in header.strip().split(','):
            if 'eff' in col.lower() or '效率' in col:
                found.add(col.strip())
    print(f'  全仓库 CSV 表头里含 eff/效率 的列：{sorted(found) or "无"}')
    print('  （relative_acoustic_efficiency 是声学接口的占位列，不是电学效率）')
    print('\n  分子分母模型都已输出，补算如下：')
    print(f"  {'场景':<22}{'P_source(W)':>12}{'P_Rm(W)':>10}{'P_Rs(W)':>10}"
          f"{'L_ESR':>9}{'C_ESR':>9}{'η=P_Rm/P_src':>14}")
    for cid in ('CASE_000_BASELINE', 'CASE_RM_P50', 'CASE_FS_M5',
                'CASE_LM_P20', 'CASE_COMBINED_HIGH'):
        sc = model.scenario_map()[cid]
        q = model.response(np.array([900000.0]), sc)
        ps, pr, prs, pl, pc = (float(q[k][0]) for k in
                               ('p_source_W', 'p_rm_W', 'p_rs_W', 'p_l_esr_W', 'p_c_esr_W'))
        print(f'  {cid:<22}{ps:>12.5f}{pr:>10.5f}{prs:>10.5f}{pl:>9.5f}{pc:>9.5f}'
              f'{100*pr/ps:>13.2f}%')
    print('  → 现用的 power_capture_pct 是「离可行最优多远」，与「送进去的功率有多少')
    print('    到了机械支路」是两个量，不能互相替代。')


# ==========================================================================
# G5：参数来源分类
# ==========================================================================
def section_g5(root: Path, model) -> None:
    print('\n== 6. G5 参数来源分类只有一句总括，没有逐参数登记')
    from dataclasses import fields
    sc = model.scenario_map()['CASE_000_BASELINE']
    names = [f.name for f in fields(sc)]
    prov = [n for n in names if any(t in n for t in ('origin', 'source', 'prov'))]
    print(f'  Scenario 字段：{names}')
    print(f'  其中来源标注字段：{prov or "无"}')
    src = (root / ACTIVE / 'model_v2_1.py').read_text(encoding='utf-8').splitlines()
    for i, line in enumerate(src[:12], 1):
        if 'hypothetical' in line or 'scan variable' in line:
            print(f'  model_v2_1.py:{i}  {line.strip()}')
    print('  计划书二.3 要求「文献参考值 / 假设基线值 / 扫描变量」三分类逐参数登记。')
    print('  现状是一句免责声明。实质含义：**三类里「文献参考值」一个都没有。**')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=str(REPO), help='仓库根目录')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if not (root / ACTIVE / 'model_v2_1.py').is_file():
        print(f'找不到 {root}/{ACTIVE}/model_v2_1.py', file=sys.stderr)
        return 2
    model = load_model(root)
    print(f'仓库根 {root}')
    section_satisfied(root, model)
    section_g1(root, model)
    section_g2(root, model)
    section_g3(root)
    section_g4(root, model)
    section_g5(root, model)
    print('\n本脚本只读，未写入任何目录。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
