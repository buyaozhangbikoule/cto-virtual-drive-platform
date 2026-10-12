"""Generate integration receipts from recorded files; never edits experiment data."""
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
PLATFORM=ROOT/'CTO_virtual_drive_platform_v2_1'
sys.path.insert(0,str(PLATFORM))
from current.catalog import LABELS, load_active, read_json, read_rows, sha


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--platform-tests',required=True,type=Path)
    p.add_argument('--behavior-tests',required=True,type=Path)
    args=p.parse_args()
    ev=load_active()
    if ev['source_drift']:raise RuntimeError('Simulation source changed since run')
    logs={name:read for name,read in [('platform',args.platform_tests.read_text(encoding='utf-8')),
                                   ('behavior',args.behavior_tests.read_text(encoding='utf-8'))]}
    counts={}
    for name,log in logs.items():
        if re.search(r'\bFAILED\b',log) or not re.search(r'^OK\s*$',log,re.M):
            raise RuntimeError('Test suite not passed: '+name)
        counts[name]=int(re.search(r'Ran (\d+) tests',log).group(1))
    old=read_json(ROOT/'project_integration_20260922/protected_history.json')
    changed=[name for name,h in old.items() if not (ROOT/name).is_file() or sha(ROOT/name)!=h]
    if changed:raise RuntimeError('Historical files changed: '+repr(changed))
    backup=ROOT/'project_integration_20260922/original_platform_entrypoints'
    assert sha(backup/'run_all.py')==sha(PLATFORM/'run_all.py')
    original=read_json(ROOT/'github_update_three_strategy_20260917/checkout/workspace/CTO_plan_three_strategy_v1_20260917/config.json')
    adopted=read_json(ev['folder']/'configuration.json')
    altered=[k for k in original if original[k]!=adopted.get(k)]
    if altered:raise RuntimeError('Existing config values changed: '+repr(altered))
    added={k:v for k,v in adopted.items() if k not in original}
    upstream=read_rows(ROOT/'github_radiation_fix_20260922/checkout/review/results/scan_fault_taxonomy/historical_12_three_strategy_table.csv')
    baseline={r['strategy']:r for r in upstream}
    errors={}
    for row in ev['historical']:
        errors[row['strategy']]={key:abs(float(row[key])-float(baseline[row['strategy']][key]))
                                for key in ['energy_J','energy_capture_pct','settled_segments','scan_failures']}
    if max(v for entry in errors.values() for v in entry.values())>1e-8:
        raise RuntimeError('Unexpected numeric regression against adopted patch report')
    audit=ev['audit']
    receipt=dict(created_utc=datetime.now(timezone.utc).isoformat(),batch_id=ev['metadata']['batch_id'],
        control_behavior_tests=counts['behavior'],platform_tests=counts['platform'],
        test_logs={str(args.platform_tests.resolve()):sha(args.platform_tests),str(args.behavior_tests.resolve()):sha(args.behavior_tests)},
        test_environment_note='Some sandboxed Windows Store Python runs emitted TemporaryDirectory cleanup PermissionError after OK; UI assertions and process exit code passed. This does not certify cleanup of denied temp directories.',
        preserved_historical_files=len(old),historical_changes=changed,old_run_all_unchanged=True,
        existing_config_values_changed=altered,new_declared_patch_budget_fields=added,
        adopted_patch_numeric_regression_absolute_differences=errors,
        audit_pass=audit['audit_pass'],timelines=audit['timelines'],executed_rows=audit['executed_rows'],
        manifest_files=audit['manifest_files_verified'],PPT_modified=False,old_speaker_notes_modified=False,
        github_pushed=False,new_ltspice_run=False,new_comsol_run=False,
        scientific_scope='hypothetical BVD quasi-steady electrical comparison only')
    out=PLATFORM/'current/integration_check_20260923.json'
    out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    target=ev['targets']
    text=['# 当前成果整合验收记录（2026-09-23）','',
          '本次已补齐正式入口、采用补丁、网页统一结果、成果分区和当前说明。未修改PPT、旧讲稿或历史实验。',
          '',f"当前登记批次：`{ev['metadata']['batch_id']}`（UTC命名，运行于本地9月22日）。",'',
          '## 已核实的交付','',
          f"- {counts['behavior']}项控制行为测试＋{counts['platform']}项平台／网页测试通过；缺失证据、篡改、旧P&O混入、失败分类、无稳态回退等均有测试。",
          f"- 完整批次{audit['timelines']}条时序、{audit['executed_rows']}行；{audit['manifest_files_verified']}个文件哈希及逐日志复算通过。",
          f"- 原{len(old)}个登记历史文件哈希不变；旧run_all.py未改动、未调用。",
           '- 当前统一表和各日程时序已接入网页，默认显示当前结果；原交互探索与独立LTspice页面保留。浏览器已核验总览、局部曲线、版本分区和CSV下载事件。',
          '- 负载参考8个文件原样快照到research；14条成果／依赖索引均在本机找到。未把原型接入正式引擎。',
          '- 上游扫描分类补丁的12段结果与本次结果数值回归在1e-8以内；原有配置键值不变，新增预算在JSON单列。','',
          '## 当前12段日程结果（不是全部通过声明）','',
          '|策略|连续稳态通过/12|全过程电能 J|相对策略可行参考电能 %|独立目标段通过/34|',
          '|---|---:|---:|---:|---:|']
    for row in ev['historical']:
        s=row['strategy'];n=sum(r['strategy']==s and r['settled']=='True' for r in target)
        text.append(f"|{LABELS[s]}|{row['settled_segments']}/12|{float(row['energy_J']):.6f}|{float(row['energy_capture_pct']):.2f}|{n}/34|")
    text+=['','12段为0–9.6 s，每段0.8 s；34条目中只统计各独立试验中间目标段，含物理等价别名。',
           '电能含所有执行阶段，为准稳态保持积分，不是声学效率。本次只整合与回归，不以增加算法或调阈值换通过。','',
           '## 必须继续披露的限制','',
           f"保护前预测峰值{audit['max_pre_guard_voltage_Vpp']:.4f} Vpp，保护后／保持记录峰值{audit['max_post_guard_hold_voltage_Vpp']:.4f} Vpp。前者是旧指令在新负载下的准稳态预测，不是LTspice瞬态尖峰；后者不能用于声称真实硬限已证明。",
           '未通过连续验收的稳态误差与恢复时间保留NA，不用尾窗样本回退；周期扫频失败分类保留，不能只引用到达峰位。',
           '反射代理仅监测；绝对功率上限、结构／模式／脉冲参数、真实硬件瞬态与声场验证不因整合而完成。',
           '平台测试曾遇到Windows临时目录清理权限警告；最终断言和退出码通过。该环境警告与仿真算法验收分开记录。','',
           '## 从哪里进入','',
           '- 网页：在平台目录运行 `python run_project.py ui`，打开 http://127.0.0.1:8501 。只监听本机；不提交到云服务。',
           '- 正式重跑：`python run_project.py validate`；复核：`python run_project.py verify`。',
           '- 三策略表、逐段验收、事件和完整报告可在网页下载；唯一批次路径见current/active_batch.json。',
           '- 当前说明：docs/当前入口与成果分区_20260922.md；补丁来源：current/integration_sources.json；详细整合复核：current/integration_check_20260923.json。',
           '- 旧PPT、旧讲稿、GitHub与D盘旧ZIP未更新，不能称它们已自动同步到这次本地整合版。','']
    report=PLATFORM/'docs/当前成果整合验收记录_20260923.md'
    report.write_text('\n'.join(text),encoding='utf-8')
    paths=[PLATFORM/p for p in ['run_project.py','current_app.py','README.md','requirements-ui.txt',
           'streamlit_app.py','current/__init__.py','current/catalog.py','current/dashboard.py',
           'current/active_batch.json','current/integration_sources.json','current/artifact_registry.json',
           'current/.gitignore','current/browser_qa_20260923.json',
           'current/integration_check_20260923.json','current/patches/plan_three_strategy.scan_fault_taxonomy.patch',
           'current/tests/test_catalog.py','current/tests/test_ui.py','pages/02_参数探索与历史结果.py',
           'pages/04_统一三策略结果.py','pages/05_版本与证据分区.py',
           'docs/当前入口与成果分区_20260922.md','docs/当前成果整合验收记录_20260923.md']]
    paths+=[p for p in (PLATFORM/'research/radiation_load_layer1').rglob('*') if p.is_file()]
    paths+=[ev['folder']/'manifest.json',ev['audit_file'],args.platform_tests,args.behavior_tests]
    paths+=[PLATFORM/'current/unified'/p for p in ev['metadata']['source_hashes']]
    document=dict(scope='new integration files; simulation artifacts recursively identified by frozen batch manifest',
                  files={p.resolve().relative_to(PLATFORM).as_posix():sha(p) for p in paths})
    (PLATFORM/'current/delivery_manifest.json').write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(report=str(report),receipt=str(out),delivery_files=len(document['files']),history_preserved=len(old)),ensure_ascii=False))


if __name__=='__main__':main()
