"""Build the reproducibility manifest for the currently completed v2.1 work."""

from __future__ import annotations

import hashlib
import json
import platform
import re
from datetime import datetime
from pathlib import Path

import matplotlib
import numpy


HERE = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    tracked = [
        HERE / "03_Codex任务说明_修订版_v2_1.md",
        HERE / "freeze_parameters_v2_1.py",
        HERE / "v2_1_活动参数清单.json",
        HERE / "v2_1_活动基线参数.csv",
        HERE / "v2_1_Qm敏感性参数.csv",
        HERE / "ltspice_stage1" / "V2_1_BARE_BVD_Q800.cir",
        HERE / "ltspice_stage1" / "V2_1_BARE_BVD_Q800.raw",
        HERE / "ltspice_stage1" / "V2_1_BARE_BVD_Q800.log",
        HERE / "ltspice_stage1" / "analyze_v2_1_stage1.py",
        HERE / "ltspice_stage1" / "V2_1_STAGE1_audit.json",
        HERE / "ltspice_stage1" / "V2_1_STAGE1_LTspice_解析交叉验证.csv",
        HERE / "ltspice_stage1" / "V2_1_STAGE1_LTspice_RAW交叉验证.png",
        HERE / "ltspice_stage1" / "V2_1_STAGE1_谐振区放大_RAW证据.png",
    ]
    tracked.extend(
        sorted(
            path
            for path in (HERE / "stage2_matching").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    )
    missing = [str(path.relative_to(HERE)) for path in tracked if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing tracked files: {missing}")

    log_text = (HERE / "ltspice_stage1" / "V2_1_BARE_BVD_Q800.log").read_text(
        encoding="utf-8", errors="replace"
    )
    match = re.search(r"LTspice[^\r\n]+", log_text)
    payload = {
        "model_id": "MODEL_V2_1_HYPOTHETICAL",
        "model_status": "ACTIVE_INCOMPLETE",
        "generated_at_local": datetime.now().astimezone().isoformat(),
        "scope": "small-signal linear BVD electrical simulation and quasi-steady control preparation; no measured, acoustic, COMSOL or clinical data",
        "completed_stages": ["stage1_bare_BVD", "stage2_matching"],
        "software": {
            "python": platform.python_version(),
            "numpy": numpy.__version__,
            "matplotlib": matplotlib.__version__,
            "ltspice": match.group(0) if match else "unknown",
            "platform": platform.platform(),
        },
        "commands": [
            "python freeze_parameters_v2_1.py",
            "D:\\LTspice.exe -b V2_1_BARE_BVD_Q800.cir",
            "python analyze_v2_1_stage1.py",
            "python stage2_matching/design_stage2.py",
            "D:\\LTspice.exe -b stage2_matching/V2_1_MATCH_BEFORE.cir",
            "D:\\LTspice.exe -b stage2_matching/V2_1_MATCH_IDEAL.cir",
            "D:\\LTspice.exe -b stage2_matching/V2_1_MATCH_ACTIVE_LOSSY.cir",
            "python stage2_matching/analyze_stage2_ltspice.py",
            "python audit_current_project_v2_1.py",
        ],
        "units": {
            "frequency": "Hz internally; kHz/MHz for reporting",
            "voltage": "phasor RMS in AC RAW; report Vrms and Vpp=2*sqrt(2)*Vrms",
            "current": "phasor RMS magnitude; report Arms and Apeak=sqrt(2)*Arms",
            "phase": "arg(Vport/Iport), degrees; positive inductive, negative capacitive",
            "complex_power": "S=V_rms*conj(I_rms); P=Re(S), Q=Im(S)",
        },
        "files": [
            {
                "path": str(path.relative_to(HERE)).replace("\\", "/"),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in tracked
        ],
        "pending_stages": [
            "stage3_disturbance",
            "stage3_selection",
            "stage4_control",
            "stage5_summary",
        ],
    }
    (HERE / "run_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
