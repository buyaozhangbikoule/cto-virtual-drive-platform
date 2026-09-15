"""Direct execution of immutable packaged validators after Node EPERM."""
from pathlib import Path
import contextlib
import hashlib
import io
import json
import runpy
import sys
import zipfile
import xml.etree.ElementTree as ET

BUILD = Path(__file__).resolve().parent
CFG = json.loads((BUILD / "output_config.json").read_text(encoding="utf-8"))
SOURCE, CANDIDATE, FINAL = [Path(CFG[k]) for k in ["SOURCE", "candidate", "FINAL"]]
CHANGED = CFG["CHANGED"]
SCRIPTS = Path("C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations/container_tools")

def check(script, argv, label):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = [str(SCRIPTS / script), *map(str, argv)]
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(str(SCRIPTS / script), run_name="__main__")
            except SystemExit as exc:
                code = exc.code or 0
    finally:
        sys.argv = old
    try:
        payload = json.loads(out.getvalue())
    except json.JSONDecodeError:
        payload = {"stdout": out.getvalue()}
    record = {"exit_code": code, "result": payload, "stderr": err.getvalue()}
    (BUILD / f"validation_{label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(label, code, json.dumps(payload, ensure_ascii=False)[:1500])
    if code:
        raise RuntimeError(f"{label} failed")
    return record

report = {"method": "Same packaged validators called in-process", "reason": "Node spawnSync bundled Python EPERM", "checks": {}}
check("inspect_presentation_layout_geometry.py", [SOURCE, "--inspect-font-families"], "source_fonts")
report["checks"]["integrity"] = check("inspect_presentation_package_integrity.py", [CANDIDATE, "--fail-on-findings"], "integrity")
report["checks"]["layout"] = check("inspect_presentation_layout_geometry.py", [
    CANDIDATE, "--fail-on-findings", "--expected-slide-count", "28", "--expected-slide-size-emu", "12192000,6858000",
    "--validate-bullet-geometry", "--validate-heading-fit", "--approved-font-family", "Calibri", "--require-native-table-slide", "15",
], "layout")
check("native_quantitative_chart_gate.py", [CANDIDATE, "--discover-chart-slides"], "chart_discovery")
report["checks"]["chart_titles"] = check("native_chart_title_gate.py", [CANDIDATE], "chart_titles")
report["checks"]["tables"] = check("native_table_arithmetic_gate.py", [CANDIDATE, "--fail-on-findings"], "tables")
report["checks"]["charts"] = check("native_quantitative_chart_gate.py", [
    CANDIDATE, "--expected-chart-slides", "6,15,24", "--target-application", "powerpoint",
], "charts")

with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(CANDIDATE) as new:
    changed = [name for name in old.namelist() if not name.endswith("/") and old.read(name) != new.read(name)]
    expected = {f"ppt/slides/slide{i}.xml" for i in CHANGED} | {f"ppt/notesSlides/notesSlide{i}.xml" for i in CHANGED}
    expected |= {f"ppt/slides/_rels/slide{i}.xml.rels" for i in [12, 14]}
    assert set(changed) == expected, changed
    a = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    s14 = " ".join(ET.fromstring(new.read("ppt/slides/slide14.xml")).itertext())
    assert "6 / 10" in s14 and "9 / 10" in s14
    for part in ["ppt/slides/slide14.xml", "ppt/notesSlides/notesSlide14.xml"]:
        text = new.read(part).decode("utf-8")
        assert "96.5" not in text and "2.4965" not in text and "2.4985" not in text, part
    assert old.read("ppt/slides/slide5.xml") == new.read("ppt/slides/slide5.xml")
report["changed_package_members"] = changed
report["unchanged_slides"] = [i for i in range(1, 29) if i not in CHANGED]
report["source_sha256"] = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
candidate_bytes = CANDIDATE.read_bytes()
report["final_sha256"] = hashlib.sha256(candidate_bytes).hexdigest()
audit = json.loads((BUILD / "control_revision_audit.json").read_text(encoding="utf-8"))
report["control_bundle_id"] = audit["control_bundle_id"]
report["numeric_fields_recomputed_and_compared"] = audit["postprocessing_fields_verified"]
(BUILD / "validation_manual.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
if FINAL.exists():
    assert FINAL.read_bytes() == candidate_bytes, "Existing output differs; use a new filename"
else:
    with FINAL.open("xb") as f:
        f.write(candidate_bytes)
print("FINAL", FINAL)
