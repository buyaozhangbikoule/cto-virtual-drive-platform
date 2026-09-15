"""Check saved repeats, evidence origins and vector text; package without deletion."""
from datetime import datetime, timezone
import json
import platform
import sys
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import matplotlib
import scipy
import run_study as r


def main():
    compared=[]
    for path in sorted(r.RESULTS.rglob("*")):
        if path.suffix not in (".csv",".json") or path.name in ("run_audit.json","audit.json"):
            continue
        other=r.HERE/"repeat_results"/path.relative_to(r.RESULTS)
        assert other.exists() and r.sha(path)==r.sha(other), str(path)
        compared.append(dict(file=path.relative_to(r.RESULTS).as_posix(),sha256=r.sha(path)))
    assert sum(x["file"].endswith(".csv") for x in compared)==325
    r.save_json(r.HERE/"reproducibility.json",dict(status="BYTE_IDENTICAL",csv_count=325,
        deterministic_json_count=len(compared)-325,files=compared,
        note="Two complete executions; timestamps/elapsed wall time excluded, not statistical replication"))

    previous_ac=r.HERE.parent/"control_factorial_20260907/ltspice"
    historical=json.loads((r.FROZEN/"prior_AC/audit.json").read_text(encoding="utf-8"))
    historical_checks=[]
    for item in historical["runs"]:
        for kind in ("cir","raw","log"):
            p=previous_ac/item[kind]
            assert r.sha(p)==item[kind+"_sha256"], str(p)
            historical_checks.append(dict(historical_file=str(p),sha256=r.sha(p),new_run=False))
    r.save_json(r.HERE/"historical_AC_hash_recheck.json",historical_checks)
    vector=[]
    for path in sorted((r.HERE/"deliverables").glob("*.svg")):
        root=ET.parse(path).getroot()
        nodes=list(root.iter("{http://www.w3.org/2000/svg}text"))
        assert len(nodes)>10,path.name
        pdf=path.with_suffix(".pdf").read_bytes()
        assert b"/FontFile2" in pdf,path.name
        vector.append(dict(figure=path.stem,editable_svg_text_nodes=len(nodes),embedded_true_type_pdf=True,
                           png=path.with_suffix(".png").name))
    r.save_json(r.HERE/"deliverables/vector_export_checks.json",vector)
    manifest=json.loads((r.HERE/"input_manifest.json").read_text(encoding="utf-8"))
    assert all(r.sha(x["original"])==x["sha256"]==r.sha(r.HERE/x["frozen"]) for x in manifest)
    r.save_json(r.HERE/"execution_environment.json",dict(audit_utc=datetime.now(timezone.utc).isoformat(),
        python=sys.version,platform=platform.platform(),numpy=np.__version__,matplotlib=matplotlib.__version__,scipy=scipy.__version__,
        matrix_executions=2,matrix_runs_per_execution=108,portable_smoke_runs=4,
        unique_isolated_recovery_runs=24,recovery_executions=2,
        new_LTspice_runs=0,prior_AC_audit_sha256=r.sha(previous_ac/"audit.json"),
        description="Current scheduler: Python quasi-steady only; prior AC audit is historical evidence"))
    files=[]
    for path in r.HERE.rglob("*"):
        if not path.is_file() or any(x in path.parts for x in ("__pycache__","repeat_results","portable_check","portable_bench")):
            continue
        if path.suffix==".zip" or path.name in ("package_manifest.json","package_receipt.json","validation_failure.json"):
            continue
        files.append(path)
    files.sort()
    r.save_json(r.HERE/"package_manifest.json",[dict(file=p.relative_to(r.HERE).as_posix(),bytes=p.stat().st_size,
              sha256=r.sha(p)) for p in files])
    files.append(r.HERE/"package_manifest.json")
    target=r.HERE/"独立调幅_P&O调度_第三轮仿真证据包.zip"
    if target.exists():
        raise FileExistsError("Package exists; preserve the delivered evidence")
    with zipfile.ZipFile(target,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files:
            z.write(p,arcname="po_scheduling_20260909/"+p.relative_to(r.HERE).as_posix())
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
    receipt=dict(file=target.name,files=len(files),bytes=target.stat().st_size,sha256=r.sha(target))
    r.save_json(r.HERE/"package_receipt.json",receipt)
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=="__main__":
    main()
