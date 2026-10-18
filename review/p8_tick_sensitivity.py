#!/usr/bin/env python3
"""补充（不在 review/32 的预登记判据内）：物理候选上控制采样周期 20/10/5 ms 对恢复时间的影响。

    python -B review/p8_tick_sensitivity.py --unified <打过 P8 的 current/unified> --study <study_run2 目录> --out <新目录>

只改 control_tick_us（检测、参考与验收的样本数不变，时间随周期缩短），无噪声，FIXED、CAPTURE_PO、ADMITTANCE_TRACK。
「需要控制」的段沿用 --study 里 p8_study.json 的 needs_control（无噪声 FIXED 守在 0.9 MHz 达不到 95% 的段）。
只读 --unified 与 --study，只写 --out（须不存在）。
"""
from __future__ import annotations

import argparse
import json
from multiprocessing import Pool
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p8_admittance_track_study as S    # noqa: E402

TICKS_US = (20000, 10000, 5000)
STRATEGIES = ('FIXED', 'CAPTURE_PO', 'ADMITTANCE_TRACK')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--unified', required=True)
    ap.add_argument('--study', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    hard = set(json.loads((a.study/'p8_study.json').read_text(encoding='utf-8'))['needs_control']['physical'])
    unified = str(Path(a.unified).resolve())
    a.out.mkdir(parents=True, exist_ok=False)
    jobs = [(unified, 'physical', f'tick_{t//1000}ms', dict(control_tick_us=t), 0., 0, STRATEGIES) for t in TICKS_US]
    with Pool(len(jobs)) as pool:
        rows = [r for part in pool.map(S.run_job, jobs) for r in part]
    out = []
    for t in TICKS_US:
        for s in STRATEGIES[1:]:
            sel = [r for r in rows if r['variant'] == f'tick_{t//1000}ms' and r['strategy'] == s]
            sus = [r['sustained_95_ms'] for r in sel if r['suite'] in hard]
            got = [x for x in sus if x is not None]
            out.append(dict(control_tick_ms=t/1000, strategy=s,
                            target_settled=sum(r['settled'] for r in sel if r['suite'] != 'HISTORICAL_12'),
                            target_segments=sum(r['suite'] != 'HISTORICAL_12' for r in sel),
                            needs_control=len(sus), sustained_95_median_ms=statistics.median(got) if got else None,
                            sustained_95_max_ms=max(got) if got else None, sustained_95_missing=len(sus)-len(got),
                            historical_energy_pct=next(r['schedule_energy_pct'] for r in sel if r['suite'] == 'HISTORICAL_12')))
    (a.out/'tick_sensitivity.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    for r in out:
        print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
