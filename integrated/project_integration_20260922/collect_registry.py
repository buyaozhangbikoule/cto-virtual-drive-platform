"""Mechanical archival copy and explicit provenance index, no prototype integration."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
PLATFORM=ROOT/'CTO_virtual_drive_platform_v2_1'
SOURCE=ROOT/'github_radiation_fix_20260922/checkout/review'
DEST=PLATFORM/'research/radiation_load_layer1'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    files=['radiation_load_layer1_reference.py','test_radiation_load_audit_regression.py',
        '14_第一层负载参数化_给Codex的实施指导_2026-09-18.md',
        '15_对第一层负载参数化审查的处置_2026-09-19.md',
        '16_负载层第二轮审核修正与回归_2026-09-22.md',
        'results/radiation_load_audit_20260922/test_results.json',
        'results/radiation_load_audit_20260922/test_log.txt',
        'results/radiation_load_audit_20260922/run_receipt.json']
    manifest={}
    for rel in files:
        src,dst=SOURCE/rel,DEST/rel
        dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists() and sha(dst)!=sha(src):raise RuntimeError('Refuse overwrite: '+str(dst))
        if not dst.exists():shutil.copy2(src,dst)
        assert sha(dst)==sha(src)
        manifest[rel]=sha(dst)
    (DEST/'source_manifest.json').write_text(json.dumps(dict(
        source_commit='6d363a97862e587d49c020e511d667b06350a5ac',
        repository='https://github.com/buyaozhangbikoule/cto-virtual-drive-platform',
        branch='claude/project-review-algorithm-analysis-jslypz',
        role='unintegrated research prototype; copied verbatim; historical tests not rerun here',
        source_directory=str(SOURCE),files=manifest),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    records=[
      ('当前','run_project.py','正式命令入口'),
      ('当前','current_app.py','正式网页入口'),
      ('当前','current/active_batch.json','唯一已核验批次定位'),
      ('已采用','current/patches/plan_three_strategy.scan_fault_taxonomy.patch','仅扫描失败分类补丁'),
      ('历史','run_all.py','旧流水线；本次未运行，不要用来更新当前批次'),
      ('历史','results/tables/stage4_5','旧P&O三策略和单独相位补充，非当前统一结果'),
      ('历史','figures','存档绘图，不更名成当前批次'),
      ('历史','evidence/ltspice','原AC证据；与新控制时序分开'),
      ('独立实验','results/ltspice_closed_loop/CL_20260914_124949_410d5f9d/reversal_acceptance.json','五轮真实RAW反馈接口；非动态三策略验收'),
      ('历史外部依赖','../outputs/v2_self_consistent_rebuild/active_stage3_5','旧交互页面所需冻结解析模型'),
      ('历史外部资料','../ltspice_transient_replay_20260911_continue/运行与核查报告.md','开环指令重放，不是完整闭环'),
      ('扩展研究外部资料','../control_factorial_20260907/deliverables/第二轮控制消融验证报告.md','相位/PI/约束及8组合等历史试验；未合并正式引擎'),
      ('未接入','research/radiation_load_layer1/radiation_load_layer1_reference.py','第一层负载参考快照，不改变正式34条目'),
      ('接口模板','interfaces/electro_acoustic_v1','不等于结构／声场结果'),
    ]
    rows=[dict(身份=c,路径=p,说明=d,本机存在=(PLATFORM/p).exists()) for c,p,d in records]
    (PLATFORM/'current/artifact_registry.json').write_text(json.dumps(dict(
        schema_version=1,relative_paths_base='platform root; ../ entries intentionally external',artifacts=rows),
        ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(copied_research_files=len(files),registered_artifacts=len(rows),
          missing=[r for r in rows if not r['本机存在']]),ensure_ascii=False))


if __name__=='__main__':main()
