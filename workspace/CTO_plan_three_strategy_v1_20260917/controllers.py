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


@dataclass(frozen=True)
class ScanResult:
    ok: bool
    frequency_Hz: float | None
    reason: str
    band_edge: bool = False


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

    def point(self, f, a, kind) -> Measurement | None:
        """Deferred actions consume logged time; latch/hold cannot be bypassed."""
        start = self.time
        while not self.finished and self.time-start < self.cfg['point_acquire_timeout_us']:
            point_start = self.time
            m = self.execute(f, a, kind, self.cfg['scan_point_us'])
            if self.time-point_start != self.cfg['scan_point_us']:
                return None  # truncated dwell is not a completed measurement
            if not valid_measurement(m):
                # Invalid data aborts, not a successful zero-power boundary peak.
                return None
            if not m.frozen and m.state == 'NORMAL' and abs(m.frequency_Hz-f)<1e-7:
                return m
        return None


def changed_anchor(a: Measurement, b: Measurement, cfg: dict) -> bool:
    if not valid_measurement(a) or not valid_measurement(b):
        return True
    za, zb = complex(a.zin_real, a.zin_imag), complex(b.zin_real, b.zin_imag)
    pa, pb = a.p_port_W/a.amplitude**2, b.p_port_W/b.amplitude**2
    tol = cfg['scan_validation_relative_tolerance']
    return abs(zb-za)/max(abs(za), 1e-15)>tol or abs(pb-pa)/max(pa,1e-15)>tol


def scan(io: Executor, trusted_frequency: float) -> ScanResult:
    cfg = io.cfg
    amp = cfg['scan_amplitude']
    anchor = io.point(trusted_frequency, amp, 'SCAN_ANCHOR_START')
    if not valid_measurement(anchor):
        return ScanResult(False, None, 'INVALID_START_ANCHOR_OR_PROTECTION')
    center = trusted_frequency
    edge = False
    best_score = None
    for half, step in cfg['scan_levels_Hz']:
        for recenter in range(cfg['scan_max_recentres']+1):
            fs = grid(center, half, step, cfg['frequency_min_Hz'], cfg['frequency_max_Hz'])
            values = []
            for f in fs:
                m = io.point(f, amp, 'SCAN_POINT')
                score = measured_score(m, cfg)
                if score is None or not math.isfinite(score):
                    return ScanResult(False, None, 'INVALID_POINT_OR_PROTECTION_OR_END')
                values.append(score)
            if max(values) <= 1e-15 or max(values)-min(values) <= max(values)*1e-12:
                return ScanResult(False, None, 'FLAT_OR_NO_SIGNAL')
            best = int(np.argmax(values))
            center, best_score = fs[best], values[best]
            edge = center in (cfg['frequency_min_Hz'], cfg['frequency_max_Hz'])
            inner_edge = best in (0, len(fs)-1) and not edge
            if not inner_edge:
                break
            io.event('SCAN_RECENTRE', frequency_Hz=center, level_step_Hz=step)
            if recenter == cfg['scan_max_recentres']:
                return ScanResult(False, None, 'RECENTRE_EXHAUSTED')
    end_anchor = io.point(trusted_frequency, amp, 'SCAN_ANCHOR_END')
    if changed_anchor(anchor, end_anchor, cfg):
        return ScanResult(False, None, 'ANCHOR_CHANGED_OR_INVALID')
    final = io.point(center, amp, 'SCAN_VALIDATE')
    score = measured_score(final, cfg)
    if score is None or abs(score-best_score)/max(best_score,1e-15)>cfg['scan_validation_relative_tolerance']:
        return ScanResult(False, None, 'FINAL_VALIDATION_FAILED')
    # Local measured candidate, NOT proof of the global maximum or steady lock.
    return ScanResult(True, center, 'LOCAL_CANDIDATE_VALIDATED', edge)


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
    retry = RetryBudget(cfg)
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
                retry.fail(io.time)
                failed_episode = True
                io.event('SCAN_FAILURE', reason=result.reason,
                         trusted_frequency_unchanged_Hz=target,
                         total_failures=retry.total_failures, retry_not_before_us=retry.not_before)
                if retry.exhausted:
                    io.event('SCAN_RETRIES_EXHAUSTED')
                # Never adopt the last failed scan point as a new control target.
                if not io.finished:
                    last = io.control(target, cfg['scan_amplitude'], 'FAILED_SCAN_ROLLBACK')
                continue
        if strategy == 'PHASE_FEEDBACK' and last is not None:
            target = phase_update(io, last, target_phase, target)
        if not io.finished:
            last = io.control(target, cfg['scan_amplitude'] if failed_episode else 1.)
