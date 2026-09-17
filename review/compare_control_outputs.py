"""Compare two stage 4/5 control output trees numerically rather than by hash.

Byte comparison is the wrong tool here.  The committed results were produced with
numpy 2.2.4 and reproducing them on another numpy gives last-digit differences in
accumulated sums, so a hash mismatch says nothing about whether the science moved.
This compares cell by cell and reports the worst relative difference, which does.

Verdicts:

    IDENTICAL              every cell matches byte for byte
    NUMERICALLY_IDENTICAL  worst relative difference within tolerance, default 1e-12
    CHANGED                something moved beyond tolerance, or the shape differs

Usage:

    python3 review/compare_control_outputs.py OLD_DIR NEW_DIR [--tol 1e-12]

Both arguments are directories containing the stage4_5_control CSV files.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

TEXT_SUFFIXES = {".csv"}


def load_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def compare_file(old: Path, new: Path, tol: float) -> dict:
    result = {"file": old.name, "verdict": "IDENTICAL", "notes": [],
              "cells_differing": 0, "worst_rel": 0.0, "worst_cell": None}

    if old.read_bytes() == new.read_bytes():
        return result

    old_cols, old_rows = load_csv(old)
    new_cols, new_rows = load_csv(new)

    if old_cols != new_cols:
        result["verdict"] = "CHANGED"
        added = [c for c in new_cols if c not in old_cols]
        removed = [c for c in old_cols if c not in new_cols]
        if added:
            result["notes"].append(f"columns added: {added}")
        if removed:
            result["notes"].append(f"columns removed: {removed}")
        return result
    if len(old_rows) != len(new_rows):
        result["verdict"] = "CHANGED"
        result["notes"].append(f"row count {len(old_rows)} -> {len(new_rows)}")
        return result

    for index, (row_old, row_new) in enumerate(zip(old_rows, new_rows)):
        for column in old_cols:
            a, b = row_old[column], row_new[column]
            if a == b:
                continue
            try:
                x, y = float(a), float(b)
            except ValueError:
                result["verdict"] = "CHANGED"
                result["notes"].append(f"row {index} column {column}: {a!r} -> {b!r}")
                continue
            result["cells_differing"] += 1
            rel = abs(x - y) / max(abs(x), abs(y), 1e-30)
            if rel > result["worst_rel"]:
                result["worst_rel"] = rel
                result["worst_cell"] = (index, column, a, b)

    if result["verdict"] != "CHANGED":
        result["verdict"] = "NUMERICALLY_IDENTICAL" if result["worst_rel"] <= tol else "CHANGED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("--tol", type=float, default=1e-12,
                        help="relative tolerance below which a difference is float noise")
    args = parser.parse_args()

    names = sorted({p.name for p in args.old.glob("*.csv")} | {p.name for p in args.new.glob("*.csv")})
    if not names:
        print(f"no CSV files found under {args.old} or {args.new}")
        return 2

    width = max(len(n) for n in names)
    overall = "IDENTICAL"
    rank = {"IDENTICAL": 0, "NUMERICALLY_IDENTICAL": 1, "CHANGED": 2}

    print(f"  {'file':<{width}}  {'verdict':<22}{'cells':>7}{'worst rel':>12}")
    for name in names:
        old, new = args.old / name, args.new / name
        if not old.is_file():
            print(f"  {name:<{width}}  {'ONLY IN NEW':<22}")
            overall = "CHANGED"
            continue
        if not new.is_file():
            print(f"  {name:<{width}}  {'ONLY IN OLD':<22}")
            overall = "CHANGED"
            continue
        r = compare_file(old, new, args.tol)
        if rank[r["verdict"]] > rank[overall]:
            overall = r["verdict"]
        print(f"  {name:<{width}}  {r['verdict']:<22}{r['cells_differing']:>7}"
              f"{r['worst_rel']:>12.3e}")
        for note in r["notes"][:5]:
            print(f"  {'':<{width}}    {note}")
        if r["worst_cell"] and r["verdict"] == "CHANGED":
            index, column, a, b = r["worst_cell"]
            print(f"  {'':<{width}}    worst: row {index} column {column}: {a} -> {b}")

    print()
    print(f"  overall: {overall}   (tolerance {args.tol:g})")
    if overall == "NUMERICALLY_IDENTICAL":
        print("  Differences are at the last representable digit, so nothing scientific moved.")
    return 0 if overall != "CHANGED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
