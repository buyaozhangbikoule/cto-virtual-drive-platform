"""Same packaged validation scripts, directly callable on Windows."""
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
contract = json.loads((BUILD / "preservation_contract.json").read_text(encoding="utf-8"))
SOURCE = Path(contract["source"])
CANDIDATE = BUILD / "candidate.pptx"
FINAL = Path(contract["final"])
SCRIPTS = Path("C:/Users/24739/.codex/plugins/cache/openai-primary-runtime/presentations/26.904.11930/skills/presentations/container_tools")

def check(script, argv, label):
    out, err = io.StringIO(), io.StringIO()
    old_argv = sys.argv
    sys.argv = [str(SCRIPTS / script), *map(str, argv)]
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                runpy.run_path(str(SCRIPTS / script), run_name="__main__")
            except SystemExit as exc:
                code = exc.code or 0
    finally:
        sys.argv = old_argv
    try:
        payload = json.loads(out.getvalue())
    except json.JSONDecodeError:
        payload = {"stdout": out.getvalue()}
    record = {"exit_code": code, "result": payload, "stderr": err.getvalue()}
    (BUILD / f"validation_{label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(label, code, json.dumps(payload, ensure_ascii=False)[:850])
    if code:
        raise RuntimeError(f"{label} failed")
    return record

report = {"method": "Same immutable packaged validators, run directly in-process", "checks": {}}
if (BUILD / "finalizer_error.json").exists():
    report["finalizer_limitation"] = json.loads((BUILD / "finalizer_error.json").read_text())
check("inspect_presentation_layout_geometry.py", [SOURCE, "--inspect-font-families"], "source_fonts")
with zipfile.ZipFile(SOURCE) as z:
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    size = ET.fromstring(z.read("ppt/presentation.xml")).find("p:sldSz", ns)
    emu = f"{size.attrib['cx']},{size.attrib['cy']}"
report["checks"]["integrity"] = check("inspect_presentation_package_integrity.py", [CANDIDATE, "--fail-on-findings"], "integrity")
report["checks"]["layout"] = check("inspect_presentation_layout_geometry.py", [
    CANDIDATE, "--fail-on-findings", "--expected-slide-count", "28", "--expected-slide-size-emu", emu,
    "--validate-bullet-geometry", "--validate-heading-fit", "--require-native-table-slide", "15",
    "--approved-font-family", "Calibri", "--approved-font-family", "Calibri Light",
], "layout")
discovery = check("native_quantitative_chart_gate.py", [CANDIDATE, "--discover-chart-slides"], "chart_discovery")
report["checks"]["chart_titles"] = check("native_chart_title_gate.py", [CANDIDATE], "chart_titles")
report["checks"]["tables"] = check("native_table_arithmetic_gate.py", [CANDIDATE, "--fail-on-findings"], "tables")
owners = discovery["result"]["chart_owner_slides"]
report["checks"]["charts"] = check("native_quantitative_chart_gate.py", [
    CANDIDATE, "--expected-chart-slides", ",".join(map(str, owners)), "--target-application", "powerpoint",
], "charts")
old_bytes = SOURCE.read_bytes()
new_bytes = CANDIDATE.read_bytes()
assert hashlib.sha256(old_bytes).hexdigest() == contract["sourceSha256"]
with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(CANDIDATE) as new:
    changed = [name for name in old.namelist() if not name.endswith("/") and old.read(name) != new.read(name)]
    assert set(changed) <= set(contract["expectedChanges"]), changed
    for i in range(1, 29):
        if i not in [12, 14, 15]:
            assert old.read(f"ppt/slides/slide{i}.xml") == new.read(f"ppt/slides/slide{i}.xml")
            assert old.read(f"ppt/notesSlides/notesSlide{i}.xml") == new.read(f"ppt/notesSlides/notesSlide{i}.xml")
    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    for n in [12, 14, 15]:
        visible = " ".join(t.text or "" for t in ET.fromstring(new.read(f"ppt/slides/slide{n}.xml")).findall(".//a:t", ns))
        notes = " ".join(t.text or "" for t in ET.fromstring(new.read(f"ppt/notesSlides/notesSlide{n}.xml")).findall(".//a:t", ns))
        for stale in ["96.5", "2.4965", "2.4985", "最稳健"]:
            assert stale not in visible + notes, (n, stale)
        if n == 14:
            assert "6 / 10" in visible and "9 / 10" in visible
            assert "未通过验收" in visible
    report["changed_package_members"] = changed
    report["unchanged_slides"] = [i for i in range(1, 29) if i not in [12, 14, 15]]
report["source_sha256"] = hashlib.sha256(old_bytes).hexdigest()
report["final_sha256"] = hashlib.sha256(new_bytes).hexdigest()
(BUILD / "validation_manual.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
if FINAL.exists():
    assert FINAL.read_bytes() == new_bytes, "Existing output differs; use a new revision filename"
else:
    with FINAL.open("xb") as f:
        f.write(new_bytes)
print("FINAL", FINAL)
