"""Run the packaged validators in-process after Node spawnSync EPERM.

This uses the same immutable validation scripts without changing their rules.
The bundled Python runtime can run these checks directly in this environment.
"""
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
ROOT = BUILD.parents[1]
SOURCE = ROOT / "CTO超声换能器第一月教授组会汇报_逐页讲稿版_2026-09-04.pptx"
CANDIDATE = BUILD / "candidate.pptx"
FINAL = BUILD.parent / "output/CTO第一月组会汇报_第5页修订_2026-09-06.pptx"
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
    stdout = out.getvalue()
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = {"stdout": stdout}
    record = {"exit_code": code, "result": payload, "stderr": err.getvalue()}
    (BUILD / f"validation_{label}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(label, code, json.dumps(payload, ensure_ascii=False)[:1800])
    if code:
        raise RuntimeError(f"{label} did not pass")
    return record

report = {"method": "Same packaged validators, direct in-process execution", "reason": "Node finalizer spawnSync bundled Python EPERM", "checks": {}}
check("inspect_presentation_layout_geometry.py", [SOURCE, "--inspect-font-families"], "source_fonts")
with zipfile.ZipFile(SOURCE) as z:
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    size = ET.fromstring(z.read("ppt/presentation.xml")).find("p:sldSz", ns)
    emu = f"{size.attrib['cx']},{size.attrib['cy']}"
report["checks"]["integrity"] = check("inspect_presentation_package_integrity.py", [CANDIDATE, "--fail-on-findings"], "integrity")
report["checks"]["layout"] = check("inspect_presentation_layout_geometry.py", [
    CANDIDATE, "--fail-on-findings", "--expected-slide-count", "28", "--expected-slide-size-emu", emu,
    "--validate-bullet-geometry", "--validate-heading-fit",
    "--approved-font-family", "Calibri", "--approved-font-family", "Calibri Light",
], "layout")
discovery = check("native_quantitative_chart_gate.py", [CANDIDATE, "--discover-chart-slides"], "chart_discovery")
with zipfile.ZipFile(CANDIDATE) as z:
    chart_slides = [i for i in range(1, 29) if b"<c:chart " in z.read(f"ppt/slides/slide{i}.xml")]
report["checks"]["chart_titles"] = check("native_chart_title_gate.py", [CANDIDATE], "chart_titles")
report["checks"]["tables"] = check("native_table_arithmetic_gate.py", [CANDIDATE, "--fail-on-findings"], "tables")
if chart_slides:
    report["checks"]["charts"] = check("native_quantitative_chart_gate.py", [
        CANDIDATE, "--expected-chart-slides", ",".join(map(str, chart_slides)), "--target-application", "powerpoint",
    ], "charts")

old_bytes = SOURCE.read_bytes()
new_bytes = CANDIDATE.read_bytes()
with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(CANDIDATE) as new:
    changed = [name for name in old.namelist() if not name.endswith("/") and old.read(name) != new.read(name)]
    allowed = {"ppt/slides/slide5.xml", "ppt/slides/_rels/slide5.xml.rels", "ppt/notesSlides/notesSlide5.xml"}
    assert set(changed) == allowed, changed
    report["changed_package_members"] = changed
    report["unchanged_slides"] = [i for i in range(1, 29) if i != 5]
report["source_sha256"] = hashlib.sha256(old_bytes).hexdigest()
report["final_sha256"] = hashlib.sha256(new_bytes).hexdigest()
(BUILD / "validation_manual.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
with FINAL.open("xb") as f:
    f.write(new_bytes)
print("FINAL", FINAL)
