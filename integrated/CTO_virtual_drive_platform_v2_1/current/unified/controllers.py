"""Formal three policies. None receives a case ID or an optimum table.

Phase target is frozen from BASELINE before any test. Phase slope uses two
executed neighbouring measurements, NOT current BVD or matching parameters.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from engine import Engine, Measurement, finite, measured_score, valid_measurement, wrap_deg

STRATEGIES = ('FIXED', 'PERIODIC_SCAN', 'PHASE_FEEDBACK')


def grid(center: float, half: float, step: float, low: float, high: float) -> list[float]:
    left, right = max(low, center-half), min(high, center+half)
    xs = list(np.arange(left, right, step, dtype=float)) + [right]
    return sorted(set(xs + [left, min(max(center, left), right)]))


# A scan point, and therefore a scan, stops for reasons that are not
# interchangeable: protection pre-empting the drive is a different event from
# corrupt data, from a plant that moved under the scan, and from a search that
# ran out of budget. Returning a bare None for all of them made the first three
# indistinguishable in the log and charged every one of them to a single
# counter, so a protection trip that happened to land on a scan release was
# reported as a scan-algorithm failure.
POINT_VALID = 'VALID'
POINT_PREEMPTED = 'PREEMPTED_PROTECTION'
POINT_INVALID = 'INVALID_MEASUREMENT'
POINT_TRUNCATED = 'END_OF_RUN_TRUNCATED'

SCAN_VALID = 'VALID_LOCAL_CANDIDATE'
SCAN_PREEMPTED = POINT_PREEMPTED
SCAN_INVALID = POINT_INVALID
SCAN_TRUNCATED = POINT_TRUNCATED
SCAN_NONSTATIONARY = 'NONSTATIONARY_SCAN'
SCAN_SEARCH_FAILED = 'SEARCH_FAILED'

# Which budget a failed scan is charged to. A status missing from this map is
# charged to the search budget: an unrecognised failure must never escape
# accounting, so unknown is treated as the controller's own fault.
BUDGET_OF_STATUS = {
    SCAN_PREEMPTED: 'preemption',
    SCAN_INVALID: 'measurement',
    SCAN_NONSTATIONARY: 'nonstationary',
    SCAN_SEARCH_FAILED: 'search',
}


@dataclass(frozen=True)
class PointResult:
    """One scan point: why it ended, and a measurement only when it is usable."""
    status: str
    measurement: Measurement | None = None

    @property
    def ok(self) -> bool:
        return self.status == POINT_VALID


@dataclass(frozen=True)
class ScanResult:
    ok: bool
    frequency_Hz: float | None
    reason: str          # diagnostic detail, kept for existing log readers
    band_edge: bool = False
    status: str = SCAN_SEARCH_FAILED    # accounting class; unknown means ours


class RetryBudget:
    """An episode has one initial attempt + max_retries; failure never rearms it."""
    def __init__(self, cfg: dict):
        self.delay, self.max_retries = cfg['failed_scan_retry_us'], cfg['failed_scan_max_retries']
        self.attempts = 0
        self.not_before = 0
        self.exhausted = False
        self.total_failures = 0

    def can_start(self, t: int) -> bool:
        return not self.exhausted and t >= self.not_before

    def start(self, t: int):
        if not self.can_start(t):
            raise RuntimeError('retry attempted before deadline or after exhaustion')
        self.attempts += 1

    def fail(self, t: int):
        self.total_failures += 1
        self.not_before = t+self.delay
        self.exhausted = self.attempts >= 1+self.max_retries

    def success(self):
        self.attempts, self.not_before = 0, 0
        # Cumulative failure count is deliberately retained.


class ScanBudget:
    """Four separate budgets, one shared latch.

    Splitting the counters stops a protection pre-emption from consuming the
    search-failure allowance, which is what silently spent one of three slots
    at the 8.0 s boundary. It does NOT remove the limit: every class has its
    own bounded allowance, and exhausting ANY of them latches the same
    low-amplitude hold that only an explicit run reset clears
    (config: failed_scan_exhaustion). Deleting the counter was never the fix.
    """
    CLASSES = ('search', 'preemption', 'measurement', 'nonstationary')

    def __init__(self, cfg: dict):
        self.delay = cfg['failed_scan_retry_us']
        self.limit = {
            'search': cfg['failed_scan_max_retries'],
            'preemption': cfg['scan_preemption_max_retries'],
            'measurement': cfg['scan_measurement_fault_max_retries'],
            'nonstationary': cfg['scan_nonstationary_max_retries'],
        }
        self.episode = {k: 0 for k in self.CLASSES}
        self.total = {k: 0 for k in self.CLASSES}
        self.attempts = 0
        self.not_before = 0
        self.exhausted = False
        self.exhausted_class = None

    @staticmethod
    def classify(status: str) -> str | None:
        """None means 'not a failure to charge' (the run simply ended)."""
        if status == SCAN_TRUNCATED:
            return None
        return BUDGET_OF_STATUS.get(status, 'search')

    @property
    def total_failures(self) -> int:
        return sum(self.total.values())

    def can_start(self, t: int) -> bool:
        return not self.exhausted and t >= self.not_before

    def start(self, t: int):
        if not self.can_start(t):
            raise RuntimeError('retry attempted before deadline or after exhaustion')
        self.attempts += 1

    def fail(self, cls: str, t: int):
        if cls not in self.limit:
            raise ValueError(f'unknown budget class {cls!r}')
        self.episode[cls] += 1
        self.total[cls] += 1
        self.not_before = t+self.delay
        if self.episode[cls] >= 1+self.limit[cls]:
            self.exhausted = True
            self.exhausted_class = cls

    def success(self):
        self.attempts, self.not_before = 0, 0
        for cls in self.CLASSES:
            self.episode[cls] = 0
        # Cumulative counts and the latch are deliberately retained.


class Executor:
    """Narrow adapter. Policies can execute/read, but cannot inspect plant truth."""
    def __init__(self, engine: Engine):
        self._engine = engine
        self.cfg = engine.cfg

    @property
    def time(self):
        return self._engine.t

    @property
    def finished(self):
        return self._engine.t >= self._engine.end

    def event(self, name, **kw):
        self._engine.event(name, **kw)

    def execute(self, f, a, kind, duration):
        return self._engine.execute(f, a, kind, int(duration))

    def control(self, f, a, kind='CONTROL'):
        return self.execute(f, a, kind, self._engine.control_duration()) if not self.finished else None

    def point(self, f, a, kind) -> PointResult:
        """Deferred actions consume logged time; latch/hold cannot be bypassed.

        The status separates the three ways a point can fail to produce data.
        Protection state is read from the returned sample, never from the plant.
        """
        start = self.time
        while not self.finished and self.time-start < self.cfg['point_acquire_timeout_us']:
            point_start = self.time
            m = self.execute(f, a, kind, self.cfg['scan_point_us'])
            if m is None or self.time-point_start != self.cfg['scan_point_us']:
                return PointResult(POINT_TRUNCATED)  # truncated dwell is not a measurement
            if not valid_measurement(m):
                # Invalid data aborts, not a successful zero-power boundary peak.
                # A guard that zeroed or froze the drive is a pre-emption, not a
                # data fault: it is the protection chain working, and charging it
                # to the search budget is what hid the 8.0 s boundary trip.
                if m.frozen or m.state != 'NORMAL':
                    return PointResult(POINT_PREEMPTED)
                return PointResult(POINT_INVALID)
            if not m.frozen and m.state == 'NORMAL' and abs(m.frequency_Hz-f)<1e-7:
                return PointResult(POINT_VALID, m)
        return PointResult(POINT_TRUNCATED if self.finished else POINT_PREEMPTED)


def changed_anchor(a: Measurement, b: Measurement, cfg: dict) -> bool:
    if not valid_measurement(a) or not valid_measurement(b):
        return True
    za, zb = complex(a.zin_real, a.zin_imag), complex(b.zin_real, b.zin_imag)
    pa, pb = a.p_port_W/a.amplitude**2, b.p_port_W/b.amplitude**2
    tol = cfg['scan_validation_relative_tolerance']
    return abs(zb-za)/max(abs(za), 1e-15)>tol or abs(pb-pa)/max(pa,1e-15)>tol


def _failed_point(result: PointResult, reason: str) -> ScanResult:
    """Carry a point's status up to the scan without inventing a cause."""
    return ScanResult(False, None, reason, status=result.status)


def scan(io: Executor, trusted_frequency: float) -> ScanResult:
    """Three-level local search with a re-measured anchor between levels.

    Two things changed relative to the single end-of-scan anchor check.

    A level whose argmax keeps landing on the window edge no longer aborts the
    whole scan on the spot. Edge-walking on its own does not prove the plant
    moved: a true peak outside the window, a second peak, or noise produce the
    same symptom. So the anchor is RE-MEASURED at the trusted frequency, and
    only a measured change in it is called non-stationary. If the anchor is
    unchanged, the search falls back one level coarser -- bounded by
    scan_max_coarse_fallbacks -- because a 100 Hz step with three re-centres can
    move the centre by at most 400 Hz and cannot bridge a large shift.

    The anchor is also re-measured after every completed level, not only after
    the last one, so a plant that moves under the scan is caught in one level
    instead of after the whole budget has been spent. Every re-measurement is a
    real executed point and is charged to the timeline like any other.
    """
    cfg = io.cfg
    amp = cfg['scan_amplitude']
    start_us = io.time
    points = 0
    anchor_point = io.point(trusted_frequency, amp, 'SCAN_ANCHOR_START')
    if not anchor_point.ok:
        return _failed_point(anchor_point, 'INVALID_START_ANCHOR_OR_PROTECTION')
    anchor = anchor_point.measurement
    center = trusted_frequency
    edge = False
    best_score = None
    fallbacks = 0
    level = 0
    levels = cfg['scan_levels_Hz']
    while level < len(levels):
        half, step = levels[level]
        walked = False
        for recenter in range(cfg['scan_max_recentres']+1):
            fs = grid(center, half, step, cfg['frequency_min_Hz'], cfg['frequency_max_Hz'])
            values = []
            for f in fs:
                if points >= cfg['scan_max_points'] or \
                        io.time-start_us >= cfg['scan_max_duration_us']:
                    return ScanResult(False, None, 'SCAN_COST_CAP_REACHED',
                                      status=SCAN_SEARCH_FAILED)
                p = io.point(f, amp, 'SCAN_POINT')
                points += 1
                if not p.ok:
                    return _failed_point(p, 'INVALID_POINT_OR_PROTECTION_OR_END')
                score = measured_score(p.measurement, cfg)
                if score is None or not math.isfinite(score):
                    return ScanResult(False, None, 'INVALID_POINT_OR_PROTECTION_OR_END',
                                      status=SCAN_INVALID)
                values.append(score)
            if max(values) <= 1e-15 or max(values)-min(values) <= max(values)*1e-12:
                return ScanResult(False, None, 'FLAT_OR_NO_SIGNAL', status=SCAN_SEARCH_FAILED)
            best = int(np.argmax(values))
            center, best_score = fs[best], values[best]
            edge = center in (cfg['frequency_min_Hz'], cfg['frequency_max_Hz'])
            inner_edge = best in (0, len(fs)-1) and not edge
            if not inner_edge:
                break
            io.event('SCAN_RECENTRE', frequency_Hz=center, level_step_Hz=step)
            if recenter == cfg['scan_max_recentres']:
                walked = True
        kind = 'SCAN_ANCHOR_END' if level == len(levels)-1 and not walked else 'SCAN_ANCHOR_LEVEL'
        recheck = io.point(trusted_frequency, amp, kind)
        points += 1
        if not recheck.ok:
            return _failed_point(recheck, 'ANCHOR_RECHECK_UNAVAILABLE')
        if changed_anchor(anchor, recheck.measurement, cfg):
            # Measured, not inferred: the load moved while we were scanning, so
            # every candidate collected in this attempt mixes two plants.
            io.event('SCAN_NONSTATIONARY_DETECTED', stage='LEVEL', level_index=level,
                     level_step_Hz=step, walked_to_edge=walked)
            return ScanResult(False, None, 'ANCHOR_CHANGED_OR_INVALID',
                              status=SCAN_NONSTATIONARY)
        if not walked:
            level += 1
            continue
        if level > 0 and fallbacks < cfg['scan_max_coarse_fallbacks']:
            fallbacks += 1
            io.event('SCAN_COARSE_FALLBACK', from_level_index=level,
                     to_level_index=level-1, fallback_count=fallbacks,
                     restart_frequency_Hz=trusted_frequency)
            center = trusted_frequency
            level -= 1
            continue
        return ScanResult(False, None, 'RECENTRE_EXHAUSTED', status=SCAN_SEARCH_FAILED)
    final = io.point(center, amp, 'SCAN_VALIDATE')
    if not final.ok:
        return _failed_point(final, 'FINAL_VALIDATION_UNAVAILABLE')
    score = measured_score(final.measurement, cfg)
    if score is None or abs(score-best_score)/max(best_score,1e-15)>cfg['scan_validation_relative_tolerance']:
        # A candidate that fails to reproduce may mean the search picked wrong,
        # or may mean the plant moved between the last level and this check.
        # Re-measure the anchor rather than charging a cause we did not observe.
        verdict = io.point(trusted_frequency, amp, 'SCAN_ANCHOR_VALIDATE')
        if not verdict.ok:
            return _failed_point(verdict, 'ANCHOR_RECHECK_UNAVAILABLE')
        if changed_anchor(anchor, verdict.measurement, cfg):
            io.event('SCAN_NONSTATIONARY_DETECTED', stage='FINAL_VALIDATION',
                     level_index=len(levels)-1, level_step_Hz=levels[-1][1],
                     walked_to_edge=False)
            return ScanResult(False, None, 'ANCHOR_CHANGED_OR_INVALID',
                              status=SCAN_NONSTATIONARY)
        return ScanResult(False, None, 'FINAL_VALIDATION_FAILED', status=SCAN_SEARCH_FAILED)
    # Local measured candidate, NOT proof of the global maximum or steady lock.
    return ScanResult(True, center, 'LOCAL_CANDIDATE_VALIDATED', edge, status=SCAN_VALID)


def phase_update(io: Executor, m: Measurement, target_phase: float,
                 trusted_frequency: float) -> float:
    cfg = io.cfg
    if not valid_measurement(m) or m.state != 'NORMAL' or m.frozen:
        return trusted_frequency
    error = wrap_deg(target_phase-m.phase_input_deg)
    if abs(error) <= cfg['phase_deadband_deg']:
        return trusted_frequency
    delta = cfg['phase_probe_offset_Hz']
    lo = max(cfg['frequency_min_Hz'], trusted_frequency-delta)
    hi = min(cfg['frequency_max_Hz'], trusted_frequency+delta)
    # Same actual amplitude for both probes. Guard may reduce it; no free slope.
    # A protection interruption invalidates THIS slope pair. Do not wait for
    # recovery and combine a stale central phase with much later neighbours.
    probe_start = io.time
    left = io.execute(lo, m.amplitude, 'PHASE_PROBE_MINUS', cfg['scan_point_us'])
    left_ok = (io.time-probe_start==cfg['scan_point_us'] and valid_measurement(left)
               and left.state=='NORMAL' and not left.frozen and abs(left.frequency_Hz-lo)<1e-7)
    probe_start = io.time
    right = io.execute(hi, m.amplitude, 'PHASE_PROBE_PLUS', cfg['scan_point_us']) if left_ok else None
    right_ok = (io.time-probe_start==cfg['scan_point_us'] and valid_measurement(right)
                and right.state=='NORMAL' and not right.frozen and abs(right.frequency_Hz-hi)<1e-7)
    if not left_ok or not right_ok or hi <= lo:
        io.event('PHASE_PROBE_FAILED')
        return trusted_frequency
    slope = wrap_deg(right.phase_input_deg-left.phase_input_deg)/(hi-lo)
    if not finite(slope) or abs(slope)<cfg['phase_slope_min_deg_per_Hz']:
        io.event('PHASE_SLOPE_UNRESOLVED')
        return trusted_frequency
    df = float(np.clip(cfg['phase_gain_Hz_per_deg']*error*np.sign(slope),
                       -cfg['phase_max_step_Hz'], cfg['phase_max_step_Hz']))
    raw = trusted_frequency+df
    candidate = float(np.clip(raw, cfg['frequency_min_Hz'], cfg['frequency_max_Hz']))
    if candidate != raw:
        io.event('FREQUENCY_SATURATION', raw_frequency_Hz=raw)
    io.event('PHASE_UPDATE', measured_error_deg=error,
             measured_slope_deg_per_Hz=slope, proposed_frequency_Hz=candidate)
    return candidate


def run_policy(io: Executor, strategy: str, target_phase: float):
    if strategy not in STRATEGIES:
        raise ValueError(strategy)
    cfg = io.cfg
    target = float(cfg['initial_frequency_Hz'])
    next_scan = cfg['scan_period_us']
    retry = ScanBudget(cfg)
    last = None
    failed_episode = False
    while not io.finished:
        if strategy == 'PERIODIC_SCAN' and retry.exhausted:
            io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_LATCHED_HOLD')
            continue
        if strategy == 'PERIODIC_SCAN' and failed_episode and not retry.can_start(io.time):
            last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_RETRY_WAIT')
            continue
        scan_due = strategy == 'PERIODIC_SCAN' and (failed_episode or io.time >= next_scan)
        # Failed attempts use low-amplitude recovery, never ramp to full in between.
        ready = last is not None and valid_measurement(last) and last.state == 'NORMAL' and not last.frozen
        if scan_due and ready and retry.can_start(io.time):
            retry.start(io.time)
            io.event('SCAN_ATTEMPT_START', attempt=retry.attempts, trusted_frequency_Hz=target)
            result = scan(io, target)
            if result.ok:
                target = float(result.frequency_Hz)
                io.event('SCAN_SUCCESS', frequency_Hz=target, band_edge=result.band_edge)
                retry.success()
                failed_episode = False
                next_scan = (io.time//cfg['scan_period_us']+1)*cfg['scan_period_us']
            else:
                budget_class = retry.classify(result.status)
                if budget_class is None:
                    # The run ended under the scan. Not a failure of anything;
                    # recording it as one would put a phantom count in the table.
                    io.event('SCAN_TRUNCATED_BY_RUN_END', reason=result.reason,
                             status=result.status, trusted_frequency_unchanged_Hz=target)
                    continue
                retry.fail(budget_class, io.time)
                failed_episode = True
                io.event('SCAN_FAILURE', reason=result.reason, status=result.status,
                         budget_class=budget_class,
                         trusted_frequency_unchanged_Hz=target,
                         episode_failures_in_class=retry.episode[budget_class],
                         class_limit=retry.limit[budget_class],
                         total_failures=retry.total_failures,
                         total_search=retry.total['search'],
                         total_preemption=retry.total['preemption'],
                         total_measurement=retry.total['measurement'],
                         total_nonstationary=retry.total['nonstationary'],
                         retry_not_before_us=retry.not_before)
                if retry.exhausted:
                    io.event('SCAN_RETRIES_EXHAUSTED', budget_class=retry.exhausted_class)
                # Never adopt the last failed scan point as a new control target.
                if not io.finished:
                    last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_ROLLBACK')
                continue
        if strategy == 'PHASE_FEEDBACK' and last is not None:
            target = phase_update(io, last, target_phase, target)
        if not io.finished:
            last = io.control(target, cfg['scan_amplitude'] if failed_episode else 1.)
