"""Independent consistency checks for the rebuilt controller outputs."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(r"C:\Users\24739\Documents\Codex\2026-08-10\new-chat")
OUT = ROOT / "outputs" / "fourth_fifth_rebuild"
RAW = ROOT / "outputs" / "fourth_step_control_strategies" / "ltspice_cases"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


rows = read_csv(OUT / "第四步_控制时序明细.csv")
strategies = sorted({row["strategy"] for row in rows})
checks = []

for strategy in strategies:
    subset = [row for row in rows if row["strategy"] == strategy]
    times = [float(row["time_s"]) for row in subset]
    checks.append({
        "check": f"{strategy}: time monotonic",
        "passed": all(b >= a for a, b in zip(times, times[1:])),
        "detail": f"rows={len(subset)}, t={times[0]:.6f}..{times[-1]:.6f}s",
    })
    frequencies = [float(row["frequency_hz"]) for row in subset]
    amplitudes = [float(row["amplitude_command"]) for row in subset]
    checks.append({
        "check": f"{strategy}: command bounds",
        "passed": min(frequencies) >= 0.84e6 and max(frequencies) <= 0.96e6
        and min(amplitudes) >= 0 and max(amplitudes) <= 1,
        "detail": f"f={min(frequencies):.1f}..{max(frequencies):.1f}Hz, a={min(amplitudes):.3f}..{max(amplitudes):.3f}",
    })
    state_ids = {int(row["state_index"]) for row in subset}
    checks.append({
        "check": f"{strategy}: all disturbance states covered",
        "passed": state_ids == set(range(25)),
        "detail": f"states={len(state_ids)}",
    })

hard_rows = [index for index, row in enumerate(rows) if int(row["hard_trip_observed"])]
hard_details = []
hard_ok = True
for index in hard_rows:
    source = rows[index]
    strategy = source["strategy"]
    stop = float(source["time_s"]) + float(source["duration_s"])
    held = 0.0
    for later in rows[index + 1:]:
        if later["strategy"] != strategy:
            break
        if float(later["amplitude_command"]) == 0.0:
            held += float(later["duration_s"])
        elif held > 0:
            break
    passed = held >= 0.100 - 1e-9
    hard_ok &= passed
    hard_details.append(f"{strategy}@{stop:.3f}s hold={held*1e3:.1f}ms")
checks.append({
    "check": "hard trip enforces at least 100 ms zero amplitude",
    "passed": hard_ok and len(hard_rows) >= 1,
    "detail": "; ".join(hard_details) if hard_details else "no hard event",
})

inventory = []
for path in sorted(RAW.glob("*.raw")):
    if path.name.endswith(".op.raw"):
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    inventory.append({
        "file": path.name,
        "bytes": path.stat().st_size,
        "modified_local": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        "sha256": digest,
    })
write_csv(OUT / "LTspice_RAW文件清单与哈希.csv", inventory)
checks.append({
    "check": "LTspice RAW inventory complete",
    "passed": len(inventory) == 24 and all(row["bytes"] > 0 for row in inventory),
    "detail": f"raw_files={len(inventory)}",
})

result = {
    "all_passed": all(bool(item["passed"]) for item in checks),
    "checks": checks,
    "raw_inventory_count": len(inventory),
}
(OUT / "自动审计结果.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
