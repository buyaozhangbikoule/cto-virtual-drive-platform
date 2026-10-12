"""Unified runner and evidence collector for the organized v2.1 platform.

config.yaml intentionally contains JSON syntax. JSON is valid YAML 1.2, and
using the standard-library json parser avoids an unnecessary PyYAML dependency.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
CONFIG_PATH = HERE / "config.yaml"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def resolve(path_text: str) -> Path:
    return (HERE / path_text).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_environment(config: dict, selected: list[dict]) -> list[str]:
    problems: list[str] = []
    for package in config["runtime"]["required_python_packages"]:
        try:
            importlib.import_module(package)
        except ImportError:
            problems.append(f"缺少Python依赖：{package}")
    if any(item["action"] == "ltspice_batch" or item["id"] == "stage3_disturbance" for item in selected):
        ltspice = Path(config["runtime"]["ltspice_executable"])
        if not ltspice.is_file():
            problems.append(f"找不到LTspice命令行程序：{ltspice}")
    for item in selected:
        if item["action"] == "python" and not resolve(item["script"]).is_file():
            problems.append(f"找不到脚本：{resolve(item['script'])}")
        for netlist in item.get("netlists", []):
            if not resolve(netlist).is_file():
                problems.append(f"找不到网表：{resolve(netlist)}")
    return problems


def run_pipeline(config: dict, selected: list[dict], dry_run: bool) -> list[dict]:
    records: list[dict] = []
    ltspice = Path(config["runtime"]["ltspice_executable"])
    for item in selected:
        print(f"\n[{item['id']}] {item['title']}")
        if item["action"] == "python":
            script = resolve(item["script"])
            commands = [([sys.executable, script.name], script.parent, script)]
        elif item["action"] == "ltspice_batch":
            commands = []
            for value in item["netlists"]:
                netlist = resolve(value)
                commands.append(([str(ltspice), "-b", netlist.name], netlist.parent, netlist))
        else:
            raise ValueError(f"未知action：{item['action']}")

        stage_status = "DRY_RUN" if dry_run else "PASS"
        for command, cwd, source in commands:
            print("  ", " ".join(command), f"(cwd={cwd})")
            if dry_run:
                continue
            completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
            log_dir = HERE / "results" / "run_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"{item['id']}_{source.stem}.txt"
            log_path.write_text(
                f"COMMAND: {' '.join(command)}\nCWD: {cwd}\nRETURN_CODE: {completed.returncode}\n\n"
                f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}\n",
                encoding="utf-8",
            )
            if completed.returncode != 0:
                stage_status = "FAIL"
                records.append({"stage": item["id"], "status": stage_status, "log": str(log_path)})
                raise RuntimeError(f"{item['id']}执行失败，见{log_path}")
        records.append({"stage": item["id"], "status": stage_status})
    return records


def excluded(path: Path, patterns: list[str]) -> bool:
    return any(path.match(pattern) for pattern in patterns)


def collect_outputs(config: dict) -> list[dict]:
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for rule in config["collection_rules"]:
        source_dir = resolve(rule["source"])
        target_dir = HERE / rule["target"]
        target_dir.mkdir(parents=True, exist_ok=True)
        excludes = rule.get("exclude_patterns", [])
        if not source_dir.is_dir():
            records.append({
                "source": str(source_dir), "destination": str(target_dir), "source_type": rule["source_type"],
                "status": "MISSING_SOURCE_DIR", "bytes": 0, "sha256": ""
            })
            continue
        matches: list[Path] = []
        for pattern in rule["patterns"]:
            matches.extend(path for path in source_dir.glob(pattern) if path.is_file())
        for source in sorted(set(matches)):
            if excluded(source, excludes):
                continue
            destination = target_dir / source.name
            key = (str(source), str(destination))
            if key in seen:
                continue
            seen.add(key)
            shutil.copy2(source, destination)
            status = "COPIED"
            note = ""
            if source.suffix.lower() == ".cir":
                try:
                    text = source.read_text(encoding="ascii", errors="ignore").lower()
                    if ".end" not in text:
                        status = "WARNING"
                        note = "网表副本中未发现.end；RAW/LOG仍可作为既有运行证据，但该网表不可单独复现"
                except OSError as exc:
                    status = "WARNING"
                    note = f"网表文本检查失败：{exc}"
            records.append({
                "source": str(source), "destination": str(destination.relative_to(HERE)),
                "source_type": rule["source_type"], "status": status, "bytes": destination.stat().st_size,
                "sha256": sha256(destination), "note": note,
            })
    return records


def audit_collected(records: list[dict]) -> dict:
    copied = [row for row in records if row["status"] in {"COPIED", "WARNING"}]
    warnings = [row for row in records if row["status"] == "WARNING"]
    missing = [row for row in records if row["status"] == "MISSING_SOURCE_DIR"]
    audit_files = [HERE / row["destination"] for row in copied if row["destination"].endswith("audit.json")]
    declared_audits = []
    for path in audit_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            declared_audits.append({"file": str(path.relative_to(HERE)), "declared_status": payload.get("status", "UNDECLARED")})
        except (OSError, json.JSONDecodeError) as exc:
            declared_audits.append({"file": str(path.relative_to(HERE)), "declared_status": "UNREADABLE", "error": str(exc)})
    return {
        "status": "PASS_WITH_WARNINGS" if warnings or missing else "PASS",
        "files_collected": len(copied),
        "bytes_collected": sum(row["bytes"] for row in copied),
        "warning_count": len(warnings),
        "missing_source_directory_count": len(missing),
        "declared_source_audits": declared_audits,
        "important_interpretation": [
            "RAW/LOG是LTspice批处理证据；PNG/PDF/SVG是数据派生图，不是GUI截图。",
            "当前正式三策略为固定0.9 MHz、周期扫频、扫描辅助P&O；相位误差闭环单列为消融验证。",
            "全部电学结果基于假设BVD与线性准稳态模型，不是实测或声场结果。"
        ]
    }


def write_manifests(config: dict, pipeline_records: list[dict], evidence_records: list[dict], audit: dict, mode: str) -> None:
    manifest_dir = HERE / "results" / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    csv_path = manifest_dir / "evidence_manifest.csv"
    fields = ["source", "destination", "source_type", "status", "bytes", "sha256", "note"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(evidence_records)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "project": config["project"],
        "config_sha256": sha256(CONFIG_PATH),
        "pipeline_records": pipeline_records,
        "collection_audit": audit,
    }
    (manifest_dir / "platform_run_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def select_stages(config: dict, expression: str) -> list[dict]:
    stages = config["pipeline"]
    if expression.strip().lower() == "all":
        return stages
    requested = [value.strip() for value in expression.split(",") if value.strip()]
    by_id = {item["id"]: item for item in stages}
    unknown = [value for value in requested if value not in by_id]
    if unknown:
        raise SystemExit(f"未知步骤：{', '.join(unknown)}")
    return [by_id[value] for value in requested]


def main() -> None:
    parser = argparse.ArgumentParser(description="v2.1虚拟驱动平台统一运行与证据整理")
    parser.add_argument("--steps", default="all", help="all或逗号分隔的步骤ID")
    parser.add_argument("--collect-only", action="store_true", help="不重新仿真，只整理现有真实输出")
    parser.add_argument("--dry-run", action="store_true", help="只显示将执行的命令")
    parser.add_argument("--no-collect", action="store_true", help="执行后不复制汇总文件")
    parser.add_argument("--list", action="store_true", help="列出可运行步骤")
    args = parser.parse_args()

    config = load_config()
    selected = select_stages(config, args.steps)
    if args.list:
        for item in config["pipeline"]:
            print(f"{item['id']}: {item['title']}")
        return

    problems = [] if args.collect_only else validate_environment(config, selected)
    if problems:
        raise SystemExit("环境检查未通过：\n- " + "\n- ".join(problems))

    pipeline_records: list[dict] = []
    mode = "collect_only" if args.collect_only else ("dry_run" if args.dry_run else "rerun")
    if not args.collect_only:
        pipeline_records = run_pipeline(config, selected, args.dry_run)

    evidence_records: list[dict] = []
    audit = {"status": "NOT_COLLECTED"}
    if not args.no_collect and not args.dry_run:
        evidence_records = collect_outputs(config)
        audit = audit_collected(evidence_records)
        write_manifests(config, pipeline_records, evidence_records, audit, mode)
        print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
