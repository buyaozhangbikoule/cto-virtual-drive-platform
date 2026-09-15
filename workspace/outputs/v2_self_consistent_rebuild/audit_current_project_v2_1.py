"""Evidence-based compliance audit for the active MODEL_V2_1 project.

The audit deliberately ignores legacy numerical results when deciding whether
the active model has completed stages 2-5.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STAGE1 = HERE / "ltspice_stage1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def result(item: str, status: str, evidence: str, gap: str, blocking: bool) -> dict[str, object]:
    return {
        "item": item,
        "status": status,
        "evidence": evidence,
        "gap_or_action": gap,
        "blocks_final_acceptance": blocking,
    }


def main() -> None:
    rows: list[dict[str, object]] = []

    task_spec = HERE / "03_Codex任务说明_修订版_v2_1.md"
    required_tokens = (
        "MODEL_V2_1_HYPOTHETICAL",
        "HYPOTHETICAL_BASELINE",
        "phase_zero_exists=false",
        "P_AND_O",
        "实际越限必须为零",
    )
    spec_ok = task_spec.exists() and all(
        token in task_spec.read_text(encoding="utf-8") for token in required_tokens
    )
    rows.append(
        result(
            "修订版任务说明与边界",
            "PASS" if spec_ok else "FAIL",
            task_spec.name if task_spec.exists() else "missing",
            "无" if spec_ok else "补齐模型ID、来源身份、谐振判据、P&O和硬限规则",
            not spec_ok,
        )
    )

    param_json = HERE / "v2_1_活动参数清单.json"
    param_ok = False
    if param_json.exists():
        params = json.loads(param_json.read_text(encoding="utf-8"))
        baseline = params.get("baseline", {})
        param_ok = (
            "source_class" in baseline
            and "假设基线" in str(baseline.get("source_class"))
            and baseline.get("status") == "v2.1 active hypothetical baseline"
        )
    rows.append(
        result(
            "活动参数来源身份",
            "PASS" if param_ok else "FAIL",
            param_json.name if param_json.exists() else "missing",
            "无" if param_ok else "活动参数必须明确标为假设基线、非实测",
            not param_ok,
        )
    )

    stage1_required = [
        STAGE1 / "V2_1_BARE_BVD_Q800.cir",
        STAGE1 / "V2_1_BARE_BVD_Q800.raw",
        STAGE1 / "V2_1_BARE_BVD_Q800.log",
        STAGE1 / "analyze_v2_1_stage1.py",
        STAGE1 / "V2_1_STAGE1_audit.json",
        STAGE1 / "V2_1_STAGE1_LTspice_解析交叉验证.csv",
        STAGE1 / "V2_1_STAGE1_LTspice_RAW交叉验证.png",
        STAGE1 / "V2_1_STAGE1_谐振区放大_RAW证据.png",
    ]
    files_ok = all(path.exists() and path.stat().st_size > 0 for path in stage1_required)
    stage1_audit_path = STAGE1 / "V2_1_STAGE1_audit.json"
    numerical_ok = False
    hash_ok = False
    audit_data: dict[str, object] = {}
    if stage1_audit_path.exists():
        audit_data = json.loads(stage1_audit_path.read_text(encoding="utf-8"))
        numerical_ok = (
            audit_data.get("status") == "PASS"
            and float(audit_data.get("series_resonance_error_pct", 999)) < 1.0
            and float(audit_data.get("max_Z_relative_error", 999)) < 0.05
        )
        raw = STAGE1 / "V2_1_BARE_BVD_Q800.raw"
        log = STAGE1 / "V2_1_BARE_BVD_Q800.log"
        if raw.exists() and log.exists():
            hash_ok = (
                sha256(raw) == audit_data.get("raw_sha256")
                and sha256(log) == audit_data.get("log_sha256")
            )
    stage1_ok = files_ok and numerical_ok and hash_ok
    rows.append(
        result(
            "阶段一：活动裸BVD",
            "PASS" if stage1_ok else "FAIL",
            (
                f"{len(stage1_required)}/8 files; fs error="
                f"{audit_data.get('series_resonance_error_pct', 'NA')}%; "
                f"max relative error={audit_data.get('max_Z_relative_error', 'NA')}; hashes={hash_ok}"
            ),
            "无" if stage1_ok else "补齐RAW/LOG/图/误差或修复哈希不一致",
            not stage1_ok,
        )
    )

    log_path = STAGE1 / "V2_1_BARE_BVD_Q800.log"
    log_ok = log_path.exists() and "LTspice 26.0.2 for Windows" in log_path.read_text(
        encoding="utf-8", errors="replace"
    )
    rows.append(
        result(
            "LTspice真实执行证据",
            "PASS" if log_ok and hash_ok else "FAIL",
            "LTspice version line + RAW/LOG SHA-256" if log_ok else "version evidence missing",
            "无" if log_ok and hash_ok else "重新批处理并保存版本、日志与哈希",
            not (log_ok and hash_ok),
        )
    )

    stage2 = HERE / "stage2_matching"
    stage2_required = [
        stage2 / "design_stage2.py",
        stage2 / "analyze_stage2_ltspice.py",
        stage2 / "stage2_匹配设计参数.json",
        stage2 / "stage2_控制源幅度校准.json",
        stage2 / "stage2_LTspice_解析交叉验证.csv",
        stage2 / "stage2_匹配前后特征汇总.csv",
        stage2 / "stage2_匹配网络正式报告.md",
        stage2 / "stage2_01_匹配前后输入阻抗_RAW.png",
        stage2 / "stage2_02_匹配前后功率与反射_RAW.png",
        stage2 / "stage2_03_活动匹配_LTspice_Python交叉验证.png",
        stage2 / "stage2_04_校准功率分配_RAW.png",
    ]
    for stem in ("V2_1_MATCH_BEFORE", "V2_1_MATCH_IDEAL", "V2_1_MATCH_ACTIVE_LOSSY"):
        stage2_required.extend(stage2 / f"{stem}.{suffix}" for suffix in ("cir", "raw", "log"))
    stage2_files_ok = all(path.exists() and path.stat().st_size > 0 for path in stage2_required)
    stage2_audit_path = stage2 / "stage2_audit.json"
    stage2_numeric_ok = False
    same_source_ok = False
    if stage2_audit_path.exists():
        stage2_data = json.loads(stage2_audit_path.read_text(encoding="utf-8"))
        stage2_numeric_ok = stage2_data.get("status") == "PASS" and all(
            row.get("status") == "PASS" for row in stage2_data.get("cross_validation", [])
        )
        same_source = str(stage2_data.get("same_source_condition", ""))
        same_source_ok = "1 Vrms" in same_source and "50 ohm" in same_source
    stage2_hash_ok = False
    hash_csv = stage2 / "stage2_LTspice_RAW文件哈希.csv"
    if hash_csv.exists():
        with hash_csv.open(newline="", encoding="utf-8-sig") as handle:
            hash_rows = list(csv.DictReader(handle))
        stage2_hash_ok = len(hash_rows) == 9 and all(
            (stage2 / row["file"]).exists() and sha256(stage2 / row["file"]) == row["sha256"]
            for row in hash_rows
        )
    stage2_ok = stage2_files_ok and stage2_numeric_ok and same_source_ok and stage2_hash_ok
    rows.append(
        result(
            "阶段二：活动匹配网络",
            "PASS" if stage2_ok else "INCOMPLETE",
            f"{sum(path.exists() for path in stage2_required)}/{len(stage2_required)} files; numeric={stage2_numeric_ok}; same_source={same_source_ok}; hashes={stage2_hash_ok}",
            "无" if stage2_ok else "补齐三组LTspice RAW、同源条件、交叉验证、图表或哈希",
            not stage2_ok,
        )
    )

    active_stage_checks = [
        ("阶段三A：活动扰动扫描", HERE / "stage3_disturbance"),
        ("阶段三B：活动选频准则", HERE / "stage3_selection"),
        ("阶段四：活动三策略与保护", HERE / "stage4_control"),
        ("阶段五：活动综合比较", HERE / "stage5_summary"),
    ]
    for label, directory in active_stage_checks:
        present = directory.exists() and any(path.is_file() for path in directory.rglob("*"))
        rows.append(
            result(
                label,
                "INCOMPLETE" if present else "NOT_STARTED",
                str(directory.relative_to(HERE)) if present else "no active v2.1 deliverable directory",
                "必须基于MODEL_V2_1重新运行；根目录旧成果仅作LEGACY",
                True,
            )
        )

    legacy_dirs = [
        ROOT / "outputs" / "single_factor_disturbance_results",
        ROOT / "outputs" / "third_step_sweep_selection",
        ROOT / "outputs" / "fourth_fifth_rebuild",
        ROOT / "outputs" / "fifth_step_week4_synthesis",
    ]
    legacy_count = sum(path.exists() for path in legacy_dirs)
    rows.append(
        result(
            "旧成果隔离",
            "WARN",
            f"{legacy_count}/{len(legacy_dirs)} legacy directories retained outside active v2.1 directory",
            "保留作工作痕迹，但必须通过README_CURRENT和报告水印避免被误作活动结论",
            False,
        )
    )

    manifest = HERE / "run_manifest.json"
    rows.append(
        result(
            "活动模型统一入口与manifest",
            "INCOMPLETE" if not manifest.exists() else "PASS",
            manifest.name if manifest.exists() else "missing active run_manifest.json",
            "无" if manifest.exists() else "在阶段二启动前建立统一配置、运行入口、软件版本和文件哈希清单",
            not manifest.exists(),
        )
    )

    gui_shots = list(HERE.rglob("*LTspice*GUI*.png"))
    rows.append(
        result(
            "LTspice GUI补充截图",
            "USER_ACTION" if not gui_shots else "PASS",
            f"{len(gui_shots)} GUI screenshot(s)",
            "最终报告前由用户手工补截版本窗口、网表、波形和Error Log；RAW证据不受此项影响",
            False,
        )
    )

    blocking = [row for row in rows if row["blocks_final_acceptance"] and row["status"] != "PASS"]
    summary = {
        "model_id": "MODEL_V2_1_HYPOTHETICAL",
        "audit_status": "INCOMPLETE" if blocking else "PASS",
        "pass_count": sum(row["status"] == "PASS" for row in rows),
        "blocking_count": len(blocking),
        "total_items": len(rows),
        "blocking_items": [row["item"] for row in blocking],
        "rows": rows,
    }
    (HERE / "04_当前项目自动审核.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (HERE / "04_当前项目自动审核.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
