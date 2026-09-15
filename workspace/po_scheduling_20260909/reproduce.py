"""Portable rerun using bundled frozen sources, not their historic locations."""
import argparse
import json
from pathlib import Path

import run_study as r


def verify_bundle():
    manifest=json.loads((r.HERE/"input_manifest.json").read_text(encoding="utf-8"))
    for x in manifest:
        assert r.sha(r.HERE/x["frozen"]) == x["sha256"], x["frozen"]


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True,help="Fresh directory for the 108 matrix runs")
    p.add_argument("--bench-out",type=Path,help="Optional fresh directory for the 24 fixed-frequency recovery runs")
    a=p.parse_args()
    verify_bundle()
    r.freeze=verify_bundle
    r.main(a.out)
    if a.bench_out:
        from validate_and_recover import recovery
        previous,base,model,legacy=r.load()
        recovery(previous,base,model,legacy,r.make_class(previous,base),out=a.bench_out)


if __name__ == "__main__":
    main()
