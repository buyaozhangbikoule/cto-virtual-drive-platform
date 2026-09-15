"""Build a SHA-256 manifest for the active v2.1 stage-3-to-5 package."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import numpy


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "final_run_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    records = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path == OUT or "__pycache__" in path.parts:
            continue
        stat = path.stat()
        records.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": stat.st_size,
            "mtime_local": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            "sha256": sha256(path),
        })
    payload = {
        "model_id": "MODEL_V2_1_HYPOTHETICAL",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "matplotlib": matplotlib.__version__,
        "ltspice_executable": "D:/LTspice.exe",
        "ltspice_version": "26.0.2.1",
        "electrical_status": "PASS",
        "structural_acoustic_status": "NOT_RUN_NO_SOLVER_OR_FROZEN_MODEL",
        "files": records,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "files": len(records), "manifest": str(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
