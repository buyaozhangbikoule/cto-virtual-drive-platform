"""Exercise portable runner with historical location intentionally unavailable."""
import json
from pathlib import Path

import run_study as r
import reproduce
from validate_and_recover import recovery


def main():
    r.PREVIOUS=r.HERE/"__historical_location_not_available__"
    assert not r.PREVIOUS.exists()
    r.freeze=reproduce.verify_bundle
    r.CONFIGURATIONS=[r.Configuration(True,.1,.4,"R0"),r.Configuration(True,.5,.9,"R2")]
    out=r.HERE/"portable_check"
    r.main(out)
    checked=[]
    for p in out.glob("*/*.csv"):
        reference=r.RESULTS/p.relative_to(out)
        assert r.sha(p)==r.sha(reference), str(p)
        checked.append(p.relative_to(out).as_posix())
    previous,base,model,legacy=r.load()
    benchout=r.HERE/"portable_bench"
    recovery(previous,base,model,legacy,r.make_class(previous,base),out=benchout)
    bench=[]
    for p in benchout.rglob("*.csv"):
        assert r.sha(p)==r.sha(r.HERE/"recovery"/p.relative_to(benchout)), str(p)
        bench.append(p.relative_to(benchout).as_posix())
    r.save_json(r.HERE/"portable_runner_check.json",dict(status="PASS",history_path_unavailable=True,
        scheduler_smoke_runs=4,compared_matrix_csv=checked,recovery_repeated_runs=24,compared_recovery_csv=bench))
    print("Portable PASS: 4 matrix smoke runs and 24 recovery runs match saved CSV")


if __name__=="__main__":
    main()
