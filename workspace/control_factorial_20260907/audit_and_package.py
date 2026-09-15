"""Verify independent re-execution and raw artifacts; package final evidence."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

import run_factorial as r


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def main():
    checks = []
    def check(name, condition, **details):
        checks.append({"name": name, "pass": bool(condition), **details})
        assert condition, name

    repeated = []
    for file in sorted(r.RESULTS.rglob("*.csv")):
        other = r.HERE / "repeat_results" / file.relative_to(r.RESULTS)
        identical = r.sha(file) == r.sha(other)
        repeated.append({"file": file.relative_to(r.RESULTS).as_posix(), "identical_bytes": identical, "sha256": r.sha(file)})
    check("all_reexecuted_CSV_identical", bool(repeated) and all(x["identical_bytes"] for x in repeated), count=len(repeated))
    r.save_json(r.HERE / "deliverables/repeatability_check.json", {"pass": True, "csv_count": len(repeated), "files": repeated})

    # Observe C differences; do not assume offline-equal peaks imply identical searches.
    c_comparisons = []
    for dwell in (.8, 1.6):
        for left, right in (("E02_000", "E05_C"), ("E03_A", "E07_AC"), ("E04_B", "E08_BC"), ("E06_AB", "E09_ABC")):
            a = read(r.RESULTS / f"{left}_dwell_{dwell:.1f}s/timeline.csv")
            b = read(r.RESULTS / f"{right}_dwell_{dwell:.1f}s/timeline.csv")
            fields = ("strategy", "time_s", "duration_s", "action", "frequency_Hz", "amplitude_command", "protection_state")
            control_a = [[x[k] for k in fields] for x in a if x["action"] == "CONTROL"]
            control_b = [[x[k] for k in fields] for x in b if x["action"] == "CONTROL"]
            differences = [{"row": i, "time_s": x["time_s"], "action": x["action"],
                            "fields": {k: [x[k], y[k]] for k in fields if x[k] != y[k]}}
                           for i, (x, y) in enumerate(zip(a, b)) if any(x[k] != y[k] for k in fields)]
            c_comparisons.append({"without_C": left, "with_C": right, "dwell_s": dwell,
                                  "control_samples_identical": control_a == control_b,
                                  "rows_without_C": len(a), "rows_with_C": len(b),
                                  "differing_action_rows": len(differences), "differences": differences})
    r.save_json(r.HERE / "deliverables/C_command_comparison.json", c_comparisons)
    check("C_comparison_recorded_without_forcing_equivalence", len(c_comparisons) == 8)

    lt = json.loads((r.HERE / "ltspice/audit.json").read_text(encoding="utf-8"))
    check("12_real_AC_runs", len(lt["runs"]) == 12 and lt["LTspice_actually_executed"])
    for run in lt["runs"]:
        check(run["cir"] + ":solver_success", run["return_code"] == 0 and run["points"] == 2001 and run["pass_5pct"])
        for ext in ("cir", "raw", "log"):
            check(run[ext] + ":sha256", r.sha(r.HERE / "ltspice" / run[ext]) == run[ext + "_sha256"])

    # Audit all diagnostic samples, not only the successful subset.
    count = 0
    for file in (r.HERE / "diagnostics").rglob("timeline.csv"):
        rows = read(file)
        count += len(rows)
        assert all(float(x["vport_vpp"]) <= 160 + 1e-9 and float(x["iport_irms_A"]) <= .006 + 1e-12
                   and x["amplitude_command"] == x["internal_amplitude"] and int(x["guard_called"]) == 1 for x in rows)
    check("all_static_and_stress_recorded_points_guarded", True, rows=count, continuous_safety_proven=False)
    manifest = json.loads((r.HERE / "input_manifest.json").read_text(encoding="utf-8"))
    check("previous_round_untouched", all(r.sha(x["original"]) == x["sha256"] == r.sha(r.HERE / x["frozen"]) for x in manifest))
    tests = json.loads((r.RESULTS / "independent_tests.json").read_text(encoding="utf-8"))
    check("independent_tests_pass", tests["status"] == "PASS", tests=tests["check_count"])
    r.save_json(r.HERE / "deliverables/artifact_audit.json", {"status": "PASS", "checks": checks})

    roots = [r.HERE / name for name in ("frozen", "results", "diagnostics", "ltspice", "deliverables")]
    files = [p for root in roots for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += [p for p in r.HERE.iterdir() if p.is_file() and (p.suffix in (".py", ".md") or p.name in ("requirements.txt", "input_manifest.json"))]
    files = sorted(set(files))
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "excluded": ["development", "results_draft1", "repeat_results (CSV identity preserved in repeatability_check.json)"],
                "files": [{"path": p.relative_to(r.HERE).as_posix(), "bytes": p.stat().st_size, "sha256": r.sha(p)} for p in files]}
    manifest_path = r.HERE / "evidence_manifest.json"
    r.save_json(manifest_path, manifest)
    bundle = r.HERE / "三因素控制消融_真实仿真证据包.zip"
    with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files + [manifest_path]:
            archive.write(file, arcname=file.relative_to(r.HERE).as_posix())
    with zipfile.ZipFile(bundle) as archive:
        assert archive.testzip() is None
        assert all(hashlib.sha256(archive.read(x["path"])).hexdigest() == x["sha256"] for x in manifest["files"])
    status = {"zip": bundle.name, "sha256": r.sha(bundle), "bytes": bundle.stat().st_size,
              "file_count": len(files)+1, "CRC_and_member_hashes_verified": True,
              "repeat_CSV_count": len(repeated), "independent_test_count": tests["check_count"],
              "C_control_samples_identical_all_pairs": all(x["control_samples_identical"] for x in c_comparisons),
              "C_scan_path_differences_retained": sum(x["differing_action_rows"] for x in c_comparisons)}
    r.save_json(r.HERE / "package_audit.json", status)
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
