"""Fail-closed, explicit batch selection. Never select a run by timestamp."""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
STRATEGIES = {"FIXED", "PERIODIC_SCAN", "PHASE_FEEDBACK"}
LABELS = {"FIXED": "固定频率＋共同保护", "PERIODIC_SCAN": "周期扫频＋共同保护",
          "PHASE_FEEDBACK": "相位误差闭环＋共同保护"}


class EvidenceError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def inside(root, relative):
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or Path(relative).is_absolute():
        raise EvidenceError(f"越界证据路径：{relative}")
    return candidate


def validate_batch(folder, audit_file, root=PLATFORM):
    folder, audit_file, root = Path(folder).resolve(), Path(audit_file).resolve(), Path(root).resolve()
    if not folder.is_relative_to(root / "current" / "unified" / "outputs"):
        raise EvidenceError("当前结果必须位于 current/unified/outputs")
    if not audit_file.is_relative_to(root / "current" / "unified" / "audits"):
        raise EvidenceError("复核文件必须位于 current/unified/audits")
    manifest = read_json(folder / "manifest.json")
    for name, expected in manifest["files"].items():
        path = inside(folder, name)
        if not path.is_file() or sha(path) != expected:
            raise EvidenceError(f"证据缺失或哈希不符：{name}")
    required = {"run_metadata.json", "configuration.json", "reference_optima.json", "phase_calibration.json",
                "scenario_registry.json", "schedules.json", "historical_12_three_strategy_table.csv",
                "registered34_target_segment_metrics.csv", "formal_three_strategy_summary.csv",
                "per_segment_metrics.csv", "tests.txt", "integration_sources.json"}
    if not required.issubset(manifest["files"]):
        raise EvidenceError("批次清单缺少必需文件")
    meta, audit = read_json(folder / "run_metadata.json"), read_json(audit_file)
    if folder.name != meta["batch_id"] or manifest["batch_id"] != folder.name or audit["batch_id"] != folder.name:
        raise EvidenceError("批次标识不一致")
    if set(meta["strategies"]) != STRATEGIES or meta["suite_count"] != 35 or meta["tests_passed"] < 41:
        raise EvidenceError("正式策略/覆盖范围/行为测试不完整")
    if audit.get("audit_pass") is not True or audit.get("problems") or audit.get("timelines") != 105:
        raise EvidenceError("完整批次复核未通过")
    if audit["manifest_files_verified"] != len(manifest["files"]):
        raise EvidenceError("复核覆盖的文件数不一致")
    hist = read_rows(folder / "historical_12_three_strategy_table.csv")
    target = read_rows(folder / "registered34_target_segment_metrics.csv")
    overall = read_rows(folder / "formal_three_strategy_summary.csv")
    cases = {r["case_id"] for r in read_json(folder / "scenario_registry.json")}
    if len(cases) != 34 or len(hist) != 3 or {r["strategy"] for r in hist} != STRATEGIES:
        raise EvidenceError("登记场景或12段综合表不完整")
    pairs = {(r["case_id"], r["strategy"]) for r in target}
    if len(target) != 102 or pairs != {(c,s) for c in cases for s in STRATEGIES}:
        raise EvidenceError("34场景三策略覆盖不完整或重复")
    if len(overall) != 105 or len({(r['suite'],r['strategy']) for r in overall}) != 105:
        raise EvidenceError("综合表出现缺行或重复")
    for row in read_rows(folder / "per_segment_metrics.csv"):
        if row["settled"] != "True" and row["steady_error_pct"] != "":
            raise EvidenceError("未通过却填充稳态误差")
    for row in overall:
        execution = f"executions/{row['suite']}_{row['strategy']}.csv"
        event_file = f"events/{row['suite']}_{row['strategy']}.json"
        if execution not in manifest["files"] or event_file not in manifest["files"]:
            raise EvidenceError("执行记录/事件日志缺失")
        events = read_json(folder / event_file)
        failures = [e for e in events if e['event']=='SCAN_FAILURE']
        if int(row['scan_failures']) != len(failures):
            raise EvidenceError('扫描失败总数与事件不一致')
        for label in ('search','preemption','measurement','nonstationary'):
            count = sum(e.get('budget_class','search')==label for e in failures)
            if int(row['scan_failures_'+label]) != count:
                raise EvidenceError('扫描失败分类与事件不一致：'+label)
        if sum(int(row['scan_failures_'+label]) for label in ('search','preemption','measurement','nonstationary')) != len(failures):
            raise EvidenceError('存在未纳入分类的扫描失败')
    return dict(folder=folder, audit_file=audit_file, metadata=meta, audit=audit,
                manifest=manifest, historical=hist, targets=target, overall=overall)


def register_batch(folder, audit_file, root=PLATFORM):
    root = Path(root).resolve()
    result = validate_batch(folder, audit_file, root)
    pointer = dict(schema_version=1, batch_id=result["metadata"]["batch_id"],
                   batch_path=result["folder"].relative_to(root).as_posix(),
                   audit_path=result["audit_file"].relative_to(root).as_posix(),
                   manifest_sha256=sha(result["folder"] / "manifest.json"),
                   audit_sha256=sha(result["audit_file"]),
                   interpretation="current unified quasi-steady results; not a certificate of controller safety")
    dest = root / "current" / "active_batch.json"
    if dest.exists():
        archive = root / "current" / "registrations"
        archive.mkdir(exist_ok=True)
        old = dest.read_bytes()
        (archive / (hashlib.sha256(old).hexdigest() + ".json")).write_bytes(old)
    temp = dest.with_suffix(".tmp")
    temp.write_text(json.dumps(pointer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(dest)
    return pointer


def load_active(root=PLATFORM):
    root = Path(root).resolve()
    path = root / "current" / "active_batch.json"
    if not path.is_file():
        raise EvidenceError("尚未登记当前完整批次；不会自动回退到历史结果。请运行 python run_project.py validate")
    pointer = read_json(path)
    folder, audit = inside(root, pointer["batch_path"]), inside(root, pointer["audit_path"])
    if sha(folder / "manifest.json") != pointer["manifest_sha256"] or sha(audit) != pointer["audit_sha256"]:
        raise EvidenceError("登记后的证据清单/复核文件已改变")
    result = validate_batch(folder, audit, root)
    if pointer['batch_id'] != result['metadata']['batch_id']:
        raise EvidenceError("登记与批次不匹配")
    drift = []
    for rel, expected in result['metadata']['source_hashes'].items():
        source = inside(root / 'current' / 'unified', rel)
        if not source.is_file() or sha(source) != expected:
            drift.append(rel)
    result['source_drift'] = drift
    return result
