"""Independent entrypoint; NEVER writes to historical project directories."""
from __future__ import annotations
import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import sys
import unittest
import numpy as np

from controllers import Executor, STRATEGIES, run_policy
from engine import Engine
from metrics import evaluate, references
from models import model_v2_1 as model

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_write(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def csv_write(path, rows):
    if not rows:
        return
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def tests():
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    return result, stream.getvalue()


def verify(folder):
    doc = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    bad = [name for name,h in doc['files'].items() if not (folder/name).is_file() or sha(folder/name)!=h]
    print(json.dumps({'verified_files':len(doc['files']),'mismatches':bad},ensure_ascii=False))
    return not bad


def make_report(folder, batch, config, overall, segments, test_result):
    hist = [r for r in overall if r['suite']=='HISTORICAL_12']
    fs = [r for r in segments if r['suite']=='HISTORICAL_12' and r['segment_index']==3]
    coverage = [r for r in segments if r['suite'].startswith('COVER_') and r['segment_index']==1]
    lines = [f'# 计划书三策略统一准稳态验证 — {batch}', '',
      '这是独立新实现的一次同批次比较，不覆盖历史结果，也不是旧三策略结果的重新拼表。', '',
      '## 本批次真实完成', '',
      f'- 行为测试：{test_result.testsRun} 项全部通过；包括无效/零功率扫描、扫描幅度同步、硬停锁存、失败重试耗尽和无回退统计。',
      '- 正式策略：FIXED / PERIODIC_SCAN / PHASE_FEEDBACK；P&O 不纳入此批次正式比较。',
      '- 共用同一模型、配置、执行保护器、整数微秒时钟、虚拟测量和指标计算函数。',
      '- 原 12 段日程保留，每段 0.8 s；另做登记场景的基准→场景→基准覆盖试验（若以 --suite all 运行）。',
      '- 相位目标仅在基准 0.9 MHz 标定一次；邻频斜率由真实执行的两次准稳态试探估计，时间/幅度/保护全部入账。', '',
      '## 历史 12 段日程的新批次结果', '',
      '|策略|通过段数/12|全程电能 J|相对策略可行参考电能 %|峰值 Vpp（含保护前）|峰值 mA RMS（含保护前）|扫描失败次数|',
      '|---|---:|---:|---:|---:|---:|---:|']
    for r in hist:
        lines.append(f"|{r['strategy']}|{r['settled_segments']}/12|{r['energy_J']:.6f}|{r['energy_capture_pct']:.2f}|{r['peak_voltage_Vpp']:.3f}|{r['peak_current_mArms']:.6f}|{r['scan_failures']}|")
    lines += ['', '保护前旧指令在新负载下的准稳态预测也属于必须披露的记录。保护后峰值单独保存，不能代替上表包含保护前预测的最大值。约188 Vpp不是LTspice瞬态峰值或实测尖峰；保护前观测不赋予人为持续时间，不虚构瞬态积分。', '',
              '本轮仅完成统一比较和实现修正，尚未完成优化调参；不能据此宣布某策略对真实器件普遍更好。']
    if coverage:
        lines += ['', '### 34 个登记场景的目标扰动段覆盖', '',
                  '每个独立试验为基准0.8 s→目标场景0.8 s→基准0.8 s；下表仅统计中间段，不用基准段增加通过率。', '',
                  '|策略|目标场景通过数/34|', '|---|---:|']
        for name in STRATEGIES:
            count=sum(r['settled'] for r in coverage if r['strategy']==name)
            lines.append(f'|{name}|{count}/34|')
    lines += ['', '### fs−5% 段（2.4–3.2 s）', '',
      '|策略|连续验收|最长合格串|进入/确认 ms|稳态误差 %|固定尾窗误差 %|',
      '|---|---|---:|---|---|---:|']
    for r in fs:
        timing = 'NA' if not r['settled'] else f"{r['recovery_enter_ms']:.1f} / {r['recovery_confirm_ms']:.1f}"
        err = 'NA（未通过，不回退）' if r['steady_error_pct'] is None else f"{r['steady_error_pct']:.6f}"
        lines.append(f"|{r['strategy']}|{'通过' if r['settled'] else '未通过'}|{r['max_consecutive_qualified_samples']}|{timing}|{err}|{r['fixed_tail_error_pct']:.3f}|")
    lines += ['', '## 必须一并汇报的限制', '',
      '1. “完成统一比较”不等于“三种控制都通过验收”。未通过是本批次有效结果；没有改变 98% / 10 样本门槛或延长原扰动段。',
      '2. 捕获率参考是 130 Vpp / 5.5 mA RMS 软阈值及 a≤1 下、100 Hz 离散网格的策略可行最大 P_Rm；不是仅受 160 Vpp / 6 mA 硬限约束的最大值。两种参考都写在 reference_optima.json。',
      '   100 Hz 网格参考是近似值；连续调频可能落在网格点之间，使比值略高于100%。不将其截断成100%，也不解读为效率超过100%；audit_batch.py 提供10 Hz网格复核作为误差诊断，不更换正式分母。',
      '3. 能量是准稳态分段保持积分，含扫描、相位试探、停机、等待和渐升。不是 LTspice 瞬态电能，也不是声学效率。',
      '4. 共同保护器在指令时刻使用当前精确模型作理想可行幅度检查：这是理想安全接口，不是仅靠有延迟传感器的真实保护。候选硬越限与实际施加后的越限分别记录。',
      '5. 扰动发生在保持区间内部时不免费触发保护；只把电学响应按真实时间边界拆分入账。仍不包含连续 RLC 瞬态、测量噪声、功放动态或硬件执行延迟。',
      '6. 失败最多初次＋2 次重试，间隔至少 50 ms；耗尽后保持低幅并锁存到显式重置。这是预登记保守假设，不是最优重试设计；它可能降低后续能量捕获。',
      '7. 相位固定目标可能在扰动后不再对应高功率。不同扰动的相位曲线可非单调；邻频测斜率也不保证全局寻优。',
      '8. 反射代理只监测，无已验证的反射上限；未独立规定绝对功率上限。没有把这两项冒充为已经完成的约束。',
      '9. 本轮没有重新运行 LTspice、真实器件或 COMSOL。模型来自已存档 v2.1，不代表本轮每个控制动作已经由 LTspice 复核。',
      '10. 本轮不调参优化排名。此处为模糊推测内容：进一步整定相位增益、扫描周期或失败后可观测重置规则可能改善表现，但本批次没有验证。', '',
      '## 查阅入口', '',
      '- formal_three_strategy_summary.csv：同口径综合表；per_segment_metrics.csv：逐段验收与尾窗诊断。',
      '- executions/*.csv：所有实际阶段、候选/实际幅度、单位、测点和边界切分。',
      '- events/*.json：扫描失败、重试、保护、相位更新、饱和事件。',
      '- configuration.json / phase_calibration.json / scenario_registry.json / schedules.json：冻结输入。',
      '- tests.txt / source_snapshot/ / manifest.json：测试与可追溯来源。', '',
      '所有结论仅限于特定假设 BVD 模型与登记扰动范围内的准稳态电学表现。']
    (folder/'统一验证报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=['historical','all'],default='all')
    parser.add_argument('--test-only',action='store_true')
    parser.add_argument('--verify',type=Path)
    args = parser.parse_args()
    if args.verify:
        return 0 if verify(args.verify) else 1
    result, test_log = tests()
    print(test_log,flush=True)
    if not result.wasSuccessful():
        return 1
    if args.test_only:
        return 0
    config = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
    source_files = [p for p in ROOT.rglob('*') if p.is_file() and
                    p.suffix in ('.py','.json','.md','.txt') and
                    not ({'outputs','audits','__pycache__'} & set(p.relative_to(ROOT).parts))]
    code_hashes = {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(source_files)}
    code_id = hashlib.sha256(json.dumps(code_hashes,sort_keys=True).encode()).hexdigest()
    batch = datetime.now(timezone.utc).strftime('UNIFIED_%Y%m%dT%H%M%S_%fZ_')+code_id[:8]
    folder = ROOT/'outputs'/batch
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'executions').mkdir()
    (folder/'events').mkdir()
    for p in source_files:
        dest = folder/'source_snapshot'/p.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,dest)
    json_write(folder/'configuration.json',config)
    (folder/'tests.txt').write_text(test_log,encoding='utf-8')
    ref = references(config)
    json_write(folder/'reference_optima.json',ref)
    cases = model.scenario_map()
    json_write(folder/'scenario_registry.json',[dict(**asdict(s),origin='hypothetical_baseline_or_scan_variable_non_measured') for s in cases.values()])
    phase = float(model.response(config['initial_frequency_Hz'],cases['CASE_000_BASELINE'])['phase_deg'][0])
    json_write(folder/'phase_calibration.json',dict(target_deg=phase,calibration_case='CASE_000_BASELINE',
        frequency_Hz=config['initial_frequency_Hz'],measurement='arg(V_input / I_source), RMS phasors',
        target_frozen_before_test=True,current_load_truth_or_optimum_used_by_phase=False,
        slope='two_executed_neighbour_measurements_with_logged_cost'))
    schedules = {'HISTORICAL_12':config['historical_schedule']}
    if args.suite=='all':
        for case_id in cases:
            schedules['COVER_'+case_id] = ['CASE_000_BASELINE',case_id,'CASE_000_BASELINE']
    json_write(folder/'schedules.json',{s:[dict(index=i,start_us=i*config['segment_us'],
        end_us=(i+1)*config['segment_us'],case_id=c) for i,c in enumerate(ids)] for s,ids in schedules.items()})
    print(f'BATCH {batch}\nFrozen input phase target {phase:.9f} deg',flush=True)
    print('Phasors RMS; Vpp=2*sqrt(2)*Vrms; S=V*conj(I); P=real(S), Q=imag(S).',flush=True)
    print('phase_in=arg(Vinput/Isource), phase_port separate; frequency Hz; power W; time integer us.',flush=True)
    all_segments, all_overall = [], []
    for suite, ids in schedules.items():
        for strategy in STRATEGIES:
            engine = Engine(config,ids,strategy,suite)
            run_policy(Executor(engine),strategy,phase)
            per, summary = evaluate(engine.rows,engine.events,config,ref)
            for row in per:
                row['batch_id'] = batch
            summary['batch_id'] = batch
            all_segments.extend(per)
            all_overall.append(summary)
            csv_write(folder/'executions'/f'{suite}_{strategy}.csv',engine.rows)
            json_write(folder/'events'/f'{suite}_{strategy}.json',engine.events)
            print(f"{suite} {strategy}: {summary['settled_segments']}/{len(ids)}; energy {summary['energy_capture_pct']:.2f}%; scans failed {summary['scan_failures']}",flush=True)
    csv_write(folder/'per_segment_metrics.csv',all_segments)
    csv_write(folder/'formal_three_strategy_summary.csv',all_overall)
    csv_write(folder/'historical_12_three_strategy_table.csv',[r for r in all_overall if r['suite']=='HISTORICAL_12'])
    csv_write(folder/'registered34_target_segment_metrics.csv',[r for r in all_segments if r['suite'].startswith('COVER_') and r['segment_index']==1])
    json_write(folder/'run_metadata.json',dict(batch_id=batch,source_tree_sha256=code_id,source_hashes=code_hashes,
        python=sys.version,numpy=np.__version__,platform=platform.platform(),command=sys.argv,
        source_model_provenance='copy from claude_review_round2_20260917/testbed (second review 0b4a600038f53623870d88976ebb5ab18bad9710)',
        strategies=STRATEGIES,suite_count=len(schedules),tests_passed=result.testsRun,
        control_uses_schedule_or_offline_reference=False,ideal_guard_uses_current_model=True,
        phase_target_deg=phase,physical_scope='hypothetical linear quasi-steady electrical model; no hardware/acoustic claim'))
    make_report(folder,batch,config,all_overall,all_segments,result)
    json_write(folder/'manifest.json',dict(batch_id=batch,source_tree_sha256=code_id,
        files={p.relative_to(folder).as_posix():sha(p) for p in sorted(folder.rglob('*')) if p.is_file()}))
    assert verify(folder)
    print(f'OUTPUT {folder}',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
