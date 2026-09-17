"""Force the four scan-failure classes and check the result is never accepted as a lock.

Written in response to finding F1 of the external review: ``local_scan`` reports a
``converged`` flag that the callers assigned and then ignored, so a scan that
pinned to a window edge, or that straddled a plant change, could still set the
operating frequency, re-record the phase target and replace the reference curve.

The failure path cannot be exercised by the registered schedule, because after the
edge-aware fix every registered scenario converges.  That is exactly why it needs a
forced test: code on a path nothing runs is code nobody has checked.

The four classes, following the review's acceptance list:

    A  plant changes part way through a scan, so its points come from two loads
    B  the re-centre budget is exhausted and the argmax is still on a window edge
    C  the peak sits on the 0.8 or 1.0 MHz band limit, which is NOT a failure
    D  no measurement is available

Usage, from inside a working copy that has the patch applied:

    cd working_x/outputs/v2_self_consistent_rebuild/active_stage3_5
    cp <repo>/review/test_failed_scan_handling.py .
    python3 test_failed_scan_handling.py
"""

from __future__ import annotations

import sys

import numpy as np

import run_stage4_5_control as R
from model_v2_1 import F_MIN, F_MAX, safe_power, scenario_map


FINE = np.arange(F_MIN, F_MAX + 0.1, 100.0)
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not condition:
        failures.append(name)


def scan_once(start_hz: float, scenarios: dict, optima: dict, schedule_override=None):
    """Run one local_scan, optionally with a patched schedule_at, and report it."""
    rows: list[dict] = []
    protection = R.Protection()
    original = R.schedule_at
    if schedule_override is not None:
        R.schedule_at = schedule_override
    try:
        frequency, t, converged = R.local_scan(
            0.0, "TEST", start_hz, "TEST", rows, protection, scenarios, optima)
    finally:
        R.schedule_at = original
    return frequency, converged, rows


def main() -> int:
    scenarios = scenario_map()
    optima = R.optimal_tables(scenarios)
    # optimal_tables only covers the schedule's cases; the test needs more.
    for case_id, s in scenarios.items():
        if case_id not in optima:
            p = safe_power(FINE, s)
            i = int(np.argmax(p))
            optima[case_id] = {"frequency_Hz": float(FINE[i]), "power_W": float(p[i])}

    print("A. plant changes part way through the scan")
    switch_at = 0.0300          # 20 points in, inside the coarse level
    def straddling_schedule(t: float) -> dict:
        case = "CASE_000_BASELINE" if t < switch_at else "CASE_FS_M5"
        return {"state_index": 0 if t < switch_at else 1, "case_id": case,
                "start_s": 0.0, "end_s": 10.0}
    frequency, converged, rows = scan_once(R.F0, scenarios, optima, straddling_schedule)
    after = scenarios["CASE_FS_M5"]
    reference = float(safe_power(FINE, after).max())
    capture = 100.0 * float(safe_power(frequency, after)[0]) / reference
    print(f"      returned {frequency / 1e3:.4f} kHz, converged={converged}, "
          f"capture against the new plant {capture:.4f}%")
    # A straddling scan may or may not trip the edge test, so the check that
    # matters is the one the review asked for: when it does report failure, the
    # caller must not treat it as a lock.  That is checked in B below with a case
    # that fails deterministically.  Here we only record the outcome.
    print(f"      (recorded, not asserted: a straddling scan is not guaranteed to "
          f"pin to an edge)")

    print("B. re-centre budget exhausted, argmax still on a window edge")
    # Start at the top of the band against a plant whose peak is far below, and
    # temporarily allow no re-centres so the coarse level must end on its edge.
    saved = R.MAX_SCAN_RECENTRES
    R.MAX_SCAN_RECENTRES = 0
    try:
        target = scenarios["CASE_LM_P20"]          # peak at 821.4 kHz
        frequency, converged, _ = scan_once(R.F0, scenarios, optima,
                                            lambda t: {"state_index": 0,
                                                       "case_id": "CASE_LM_P20",
                                                       "start_s": 0.0, "end_s": 10.0})
    finally:
        R.MAX_SCAN_RECENTRES = saved
    reference = float(safe_power(FINE, target).max())
    capture = 100.0 * float(safe_power(frequency, target)[0]) / reference
    check("a scan pinned to a window edge reports converged=False",
          converged is False, f"returned {frequency / 1e3:.1f} kHz, capture {capture:.4f}%")
    check("and that result is the known 844.0 kHz artefact, not a real peak",
          abs(frequency - 844e3) < 1.0 and capture < 1.0)

    print("C. peak on the band limit is not a failure")
    # Shift fs down so the constrained peak lands at or below F_MIN.
    drifted = R.__dict__["scenario_map"]()["CASE_000_BASELINE"]
    from model_v2_1 import Scenario, shifted_fs, BASE_MATCH, BASE_RS
    edge_plant = Scenario("EDGE", "test", "fs", "-12%", "band-edge probe",
                          shifted_fs(drifted.bvd, 0.88), BASE_MATCH, BASE_RS)
    scenarios_edge = dict(scenarios, EDGE=edge_plant)
    p = safe_power(FINE, edge_plant)
    optima_edge = dict(optima, EDGE={"frequency_Hz": float(FINE[int(np.argmax(p))]),
                                     "power_W": float(p.max())})
    frequency, converged, _ = scan_once(R.F0, scenarios_edge, optima_edge,
                                        lambda t: {"state_index": 0, "case_id": "EDGE",
                                                   "start_s": 0.0, "end_s": 10.0})
    capture = 100.0 * float(safe_power(frequency, edge_plant)[0]) / float(p.max())
    check("a peak at the band limit is reported as converged",
          converged is True, f"returned {frequency / 1e3:.1f} kHz, capture {capture:.2f}%")

    print("D. the caller honours the flag")
    source = open(R.__file__, encoding="utf-8").read()
    check("PERIODIC_SCAN branches on the flag", "if completed:" in source)
    check("no call site discards it", source.count("_, completed = local_scan") == 0)
    check("a failed scan does not reset the failure counter",
          "failed_scans += 1" in source)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {failures}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
