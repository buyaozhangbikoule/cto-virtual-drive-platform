"""One quasi-steady plant, clock and actuator path for every executed action.

Not a transient or hardware safety proof. The command-time guard has ideal
current-model knowledge. Hidden load changes between commands are NOT clamped.
Their held-command violations and energy remain in the physical execution log.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable
import numpy as np
from models import model_v2_1 as model


def wrap_deg(x: float) -> float:
    return (x + 180.0) % 360.0 - 180.0


def finite(*xs) -> bool:
    try:
        return all(x is not None and math.isfinite(float(x)) for x in xs)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Measurement:
    """Controller-visible data: no scenario ID, schedule or offline optimum."""
    time_us: int
    frequency_Hz: float
    amplitude: float
    vpp: float
    irms: float
    p_port_W: float
    phase_input_deg: float | None
    zin_real: float | None
    zin_imag: float | None
    valid: bool
    state: str
    frozen: bool


def valid_measurement(m: Measurement | None) -> bool:
    return bool(m is not None and m.valid and
                finite(m.frequency_Hz, m.amplitude, m.vpp, m.irms, m.p_port_W,
                       m.phase_input_deg, m.zin_real, m.zin_imag) and
                m.amplitude > 1e-9 and m.vpp > 0 and m.irms > 0 and
                m.p_port_W > 1e-15)


def measured_score(m: Measurement, cfg: dict) -> float | None:
    """Linear scaling of ACTUALLY measured power/V/I; no load/oracle query.

    Ideal C0 is lossless in this model, so P_port == P_Rm. Scaling assumes an
    unchanged linear load. The reference optimizer is not available here.
    """
    if not valid_measurement(m):
        return None
    cap = min(1.0, cfg['voltage_soft_Vpp'] * m.amplitude / m.vpp,
              cfg['current_soft_Arms'] * m.amplitude / m.irms)
    return m.p_port_W * (cap / m.amplitude) ** 2


class Protection:
    """Only this object applies amplitude/frequency, including scan/probe points."""
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.frequency = float(cfg['initial_frequency_Hz'])
        self.amplitude = 1.0
        self.state = 'NORMAL'
        self.hard_until = -1
        self.recovery_until = -1
        self.soft_until = -1
        self.last_us = 0
        self.prev_candidate_limited = False

    def limits(self, unit: dict) -> tuple[float, float]:
        v, i = float(unit['vport_vpp'][0]), float(unit['iport_irms_A'][0])
        if not finite(v, i) or v <= 0 or i <= 0:
            raise ValueError('invalid unit response')
        return (min(1., self.cfg['voltage_soft_Vpp']/v, self.cfg['current_soft_Arms']/i),
                min(1., self.cfg['voltage_hard_Vpp']/v, self.cfg['current_hard_Arms']/i))

    def apply(self, t: int, frequency: float, amplitude: float,
              unit_response: Callable[[float], dict]) -> dict:
        cfg = self.cfg
        events = []
        old_f, old_a = self.frequency, self.amplitude
        if not finite(frequency, amplitude):
            frequency, amplitude = old_f, 0.
            events.append('INVALID_COMMAND')
        f = float(np.clip(frequency, cfg['frequency_min_Hz'], cfg['frequency_max_Hz']))
        requested_a = float(np.clip(amplitude, 0., 1.))
        saturated = f != frequency
        if saturated:
            events.append('FREQUENCY_SATURATION')
        try:
            soft_old, hard_old = self.limits(unit_response(old_f))
            soft_new, hard_new = self.limits(unit_response(f))
        except (ValueError, TypeError, KeyError, IndexError, FloatingPointError):
            self.amplitude, self.state, self.last_us = 0., 'DATA_INVALID', t
            return dict(events=events+['INVALID_PLANT_DATA'], frozen=True,
                        candidate_soft_limited=False, candidate_hard_rejected=False,
                        observed_hold_hard=False, frequency_saturated=saturated)

        observed_hard = old_a > hard_old + 1e-12
        candidate_hard = requested_a > hard_new + 1e-12
        candidate_soft = requested_a > soft_new + 1e-12
        if observed_hard and t >= self.hard_until:
            self.hard_until = t + cfg['hard_hold_us']
            self.recovery_until = self.hard_until + cfg['recovery_hold_us']
            events.append('OBSERVED_HARD_TRIP')
        if candidate_soft and not self.prev_candidate_limited:
            events.append('CANDIDATE_LIMIT_ENTER')
        self.prev_candidate_limited = candidate_soft
        frozen = False
        if t < self.hard_until:
            self.amplitude, self.state, frozen = 0., 'HARD_TRIP', True
        elif t < self.recovery_until:
            self.amplitude = min(cfg['recovery_amplitude'], soft_old, requested_a)
            self.state, frozen = 'HOLD', True
        elif t < self.soft_until:
            self.amplitude = min(old_a, requested_a, soft_old)
            self.state, frozen = 'FOLDBACK', True
        else:
            wanted = min(requested_a, soft_new)
            if f != old_f and wanted < old_a - 1e-12:
                # Reduce amplitude at OLD frequency first; do not combine changes.
                self.amplitude = min(wanted, soft_old)
                self.state, frozen = 'PREPARE', True
                if soft_new < min(old_a, requested_a) - 1e-12:
                    self.soft_until = t + cfg['soft_hold_us']
                    self.state = 'FOLDBACK'
                    events.append('SOFT_FOLDBACK_ENTER')
            elif f != old_f and self.state == 'RAMP_UP':
                # Finish the frozen-frequency recovery before moving again.
                wanted = min(requested_a, soft_old)
                self.amplitude = min(wanted, old_a + cfg['ramp_amplitude_per_s'] * (t-self.last_us)/1e6)
                self.state = 'NORMAL' if self.amplitude >= wanted-1e-12 else 'RAMP_UP'
                frozen = True
            elif f != old_f:
                self.frequency = f
                self.amplitude = min(old_a, wanted)  # never raise amplitude here
                self.state = 'NORMAL'
            elif wanted < old_a - 1e-12:
                self.amplitude = wanted
                if soft_new < min(old_a, requested_a)-1e-12:
                    self.soft_until = t + cfg['soft_hold_us']
                    self.state, frozen = 'FOLDBACK', True
                    events.append('SOFT_FOLDBACK_ENTER')
                else:
                    self.state = 'NORMAL'
            else:
                dt = max(0, t-self.last_us)/1e6
                self.amplitude = min(wanted, old_a + cfg['ramp_amplitude_per_s'] * dt)
                self.state = 'NORMAL' if self.amplitude >= wanted-1e-12 else 'RAMP_UP'
                frozen = self.state != 'NORMAL'
        self.last_us = t
        assert not (self.frequency != old_f and abs(self.amplitude-old_a) > 1e-12)
        return dict(events=events, frozen=frozen,
                    candidate_soft_limited=candidate_soft,
                    candidate_hard_rejected=candidate_hard,
                    observed_hold_hard=observed_hard,
                    frequency_saturated=saturated)


class Engine:
    def __init__(self, cfg: dict, case_ids: list[str], strategy: str, suite: str):
        self.cfg, self.case_ids, self.strategy, self.suite = cfg, case_ids, strategy, suite
        self.cases = model.scenario_map()
        self.t = 0
        self.end = len(case_ids)*cfg['segment_us']
        self.protection = Protection(cfg)
        self.rows, self.events = [], []
        self.action_id = 0
        self.measurement_filter = None  # fault injection only, recorded by tests

    def event(self, name: str, **data):
        self.events.append(dict(time_us=self.t, strategy=self.strategy,
                                suite=self.suite, event=name, **data))

    def execute(self, frequency: float, amplitude: float, kind: str,
                duration_us: int) -> Measurement | None:
        if self.t >= self.end:
            return None
        assert isinstance(duration_us, int) and duration_us > 0
        t0 = self.t
        end = min(self.end, t0+duration_us)
        case = self.cases[self.case_ids[t0//self.cfg['segment_us']]]
        previous_state = self.protection.state
        previous_frequency = self.protection.frequency
        previous_amplitude = self.protection.amplitude
        pre_guard = model.response(previous_frequency,case,previous_amplitude)
        guard = self.protection.apply(t0, frequency, amplitude,
                                     lambda f: model.response(f, case))
        for name in guard['events']:
            self.event(name, action_id=self.action_id, kind=kind)
        f, a = self.protection.frequency, self.protection.amplitude
        if self.protection.state != previous_state:
            self.event('PROTECTION_STATE_TRANSITION', action_id=self.action_id, kind=kind,
                       from_state=previous_state,to_state=self.protection.state,
                       frequency_Hz=f,applied_amplitude=a)
        pieces = []
        # Segment boundaries only affect the simulated PLANT and integration.
        # The controller and protection do not receive an extra boundary update.
        while self.t < end:
            seg = self.t//self.cfg['segment_us']
            stop = min(end, (seg+1)*self.cfg['segment_us'])
            scenario = self.cases[self.case_ids[seg]]
            q = model.response(f, scenario, a)
            scalar = lambda key: float(q[key][0])
            vin, isrc = complex(q['v_input'][0]), complex(q['i_source'][0])
            zin = vin/isrc if abs(isrc) > 1e-15 else None
            phase = math.degrees(math.atan2(zin.imag, zin.real)) if zin is not None else None
            p, v, i = scalar('p_port_W'), scalar('vport_vpp'), scalar('iport_irms_A')
            row = dict(suite=self.suite, strategy=self.strategy, action_id=self.action_id,
                       kind=kind, start_us=self.t, end_us=stop, duration_us=stop-self.t,
                       action_start_us=t0, action_end_us=end,
                       segment_index=seg, case_id=scenario.case_id,
                       requested_frequency_Hz=frequency, frequency_Hz=f,
                       requested_amplitude=amplitude, applied_amplitude=a,
                       pre_guard_vport_Vpp=float(pre_guard['vport_vpp'][0]),
                       pre_guard_iport_Arms=float(pre_guard['iport_irms_A'][0]),
                       pre_guard_p_rm_W=float(pre_guard['p_rm_W'][0]),
                       pre_guard_case_id=case.case_id,
                       pre_guard_sample_here=self.t==t0,
                       protection_amplitude=a, protection_state=self.protection.state,
                       frequency_frozen=guard['frozen'], vport_Vpp=v, iport_Arms=i,
                       phase_input_deg=phase, phase_port_deg=None if a == 0 else
                       math.degrees(np.angle(complex(q['z_bvd'][0]))),
                       p_port_W=p, p_rm_W=scalar('p_rm_W'),
                       p_source_W=scalar('p_source_W'), gamma_proxy=scalar('gamma'),
                       power_balance_error_W=scalar('power_balance_error_W'),
                       zin_real_ohm=None if zin is None else zin.real,
                       zin_imag_ohm=None if zin is None else zin.imag,
                       v_input_real_Vrms=vin.real,v_input_imag_Vrms=vin.imag,
                       i_source_real_Arms=isrc.real,i_source_imag_Arms=isrc.imag,
                       electrical_valid=finite(p, v, i),
                       measurement_valid=finite(p,v,i,phase,
                           None if zin is None else zin.real,None if zin is None else zin.imag)
                           and a>1e-9 and p>1e-15 and v>0 and i>0,
                       actual_hard_violation=v>self.cfg['voltage_hard_Vpp']+1e-8 or
                       i>self.cfg['current_hard_Arms']+1e-12,
                       actual_soft_excess=v>self.cfg['voltage_soft_Vpp']+1e-8 or
                       i>self.cfg['current_soft_Arms']+1e-12,
                       candidate_soft_limited=guard['candidate_soft_limited'],
                       candidate_hard_rejected=guard['candidate_hard_rejected'],
                       observed_hold_hard=guard['observed_hold_hard'],
                       frequency_saturated=guard['frequency_saturated'])
            pieces.append(row)
            self.rows.append(row)
            self.t = stop
        r = pieces[-1]
        m = Measurement(self.t, f, a, r['vport_Vpp'], r['iport_Arms'], r['p_port_W'],
                        r['phase_input_deg'], r['zin_real_ohm'], r['zin_imag_ohm'],
                        r['measurement_valid'], r['protection_state'], r['frequency_frozen'])
        if self.measurement_filter is not None:
            m = self.measurement_filter(m, kind)
            for row in pieces:
                row['measurement_valid'] = valid_measurement(m)
        self.action_id += 1
        return m

    def control_duration(self) -> int:
        tick = self.cfg['control_tick_us']
        return min(tick-self.t % tick, self.end-self.t)
