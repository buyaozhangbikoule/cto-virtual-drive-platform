"""Package final evidence without changing any source data or old project file."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    roots = [HERE / name for name in ("snapshot", "results_r1", "ltspice_ac_verification", "deliverables")]
    files = [p for root in roots for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += [p for p in HERE.iterdir() if p.suffix in (".py", ".md") or p.name in ("input_manifest.json", "requirements.txt")]
    files = sorted(set(files))
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "scope": "Final results_r1 only; earlier development runs remain outside this package",
                "files": [{"path": p.relative_to(HERE).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)} for p in files]}
    manifest_path = HERE / "evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    bundle = HERE / "控制恢复流程_第一轮真实仿真证据包.zip"
    with zipfile.ZipFile(bundle, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files + [manifest_path]:
            archive.write(path, arcname=path.relative_to(HERE).as_posix())
    with zipfile.ZipFile(bundle) as archive:
        assert archive.testzip() is None
        for record in manifest["files"]:
            assert hashlib.sha256(archive.read(record["path"])).hexdigest() == record["sha256"]
    status = {"zip": bundle.name, "file_count": len(files) + 1, "bytes": bundle.stat().st_size,
              "sha256": sha(bundle), "zip_crc_and_all_member_hashes_verified": True}
    (HERE / "package_audit.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
