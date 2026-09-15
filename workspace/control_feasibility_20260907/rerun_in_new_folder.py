"""Reproduce controller results in a NEW sibling folder, preserving this evidence.

Requires the original project inputs alongside this experiment folder. This
reruns Python controllers and tests, not LTspice. No files are deleted.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    source = Path(__file__).resolve().parent
    workspace = source.parent
    manifest = json.loads((source / "input_manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        original = Path(entry["original"])
        if not original.is_file() or digest(original) != entry["sha256"]:
            raise RuntimeError(f"Original input missing/changed; do not overwrite frozen evidence: {original}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    target = workspace / f"control_feasibility_rerun_{stamp}"
    target.mkdir(exist_ok=False)
    for name in ("run_experiments.py", "validate_experiments.py"):
        shutil.copy2(source / name, target / name)
    for name in ("run_experiments.py", "validate_experiments.py"):
        process = subprocess.run([sys.executable, str(target / name)], capture_output=True, text=True,
                                 encoding="utf-8", timeout=120)
        (target / (name + ".stdout.txt")).write_text(process.stdout, encoding="utf-8")
        (target / (name + ".stderr.txt")).write_text(process.stderr, encoding="utf-8")
        process.check_returncode()
    checks = []
    for original in sorted((source / "results_r1").rglob("*.csv")):
        relative = original.relative_to(source)
        repeated = target / relative
        checks.append({"file": relative.as_posix(), "identical_bytes": digest(original) == digest(repeated),
                       "sha256": digest(repeated)})
    passed = bool(checks) and all(x["identical_bytes"] for x in checks)
    result = {"pass": passed, "output_directory": str(target), "checked_csv_count": len(checks),
              "checks": checks, "original_evidence_overwritten": False, "LTspice_rerun": False}
    (target / "repeatability_check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, ensure_ascii=False, indent=2))
    assert passed, "Repeated results differ; preserve both versions for investigation"


if __name__ == "__main__":
    main()
