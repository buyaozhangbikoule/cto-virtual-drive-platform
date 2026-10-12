"""Single-factor ablation: the origin of the next periodic-scan timer.

No plant truth, scenario boundary, offline power reference or acceptance test is
available to this policy. Shared scan, guard, retry and actuator are untouched.
"""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'shared'))
from controllers import Executor, ScanBudget, scan, valid_measurement

MODES=('ABSOLUTE','SCAN_END','RECOVERY_END')

class ScanClock:
    def __init__(self, period_us, mode):
        if mode not in MODES: raise ValueError(mode)
        self.period=period_us; self.mode=mode
        self.next=period_us; self.waiting=False

    def succeeded(self, now):
        self.waiting=self.mode=='RECOVERY_END'
        self.next=(None if self.waiting else
                   ((now//self.period+1)*self.period if self.mode=='ABSOLUTE' else now+self.period))

    def observe_control(self, now, m, target):
        # The caller has just REQUESTED amplitude 1 through the same protection
        # interface. NORMAL means the allowed requested amplitude was reached;
        # it does NOT mean power capture >=98% or steady acceptance succeeded.
        if (self.waiting and valid_measurement(m) and m.state=='NORMAL' and not m.frozen
                and abs(m.frequency_Hz-target)<1e-7):
            self.next=now+self.period; self.waiting=False
            return True
        return False

    def due(self, now):
        return self.next is not None and now>=self.next

def run_handoff(io:Executor, mode):
    cfg=io.cfg; target=float(cfg['initial_frequency_Hz'])
    clock=ScanClock(cfg['scan_period_us'],mode)
    retry=ScanBudget(cfg); last=None; failed_episode=False
    while not io.finished:
        if retry.exhausted:
            io.control(target,cfg['scan_amplitude'],'FAILED_SCAN_LATCHED_HOLD')
            continue
        if failed_episode and not retry.can_start(io.time):
            last=io.control(target,cfg['scan_amplitude'],'FAILED_SCAN_RETRY_WAIT')
            continue
        scan_due=failed_episode or clock.due(io.time)
        ready=last is not None and valid_measurement(last) and last.state=='NORMAL' and not last.frozen
        if scan_due and ready and retry.can_start(io.time):
            retry.start(io.time)
            io.event('SCAN_ATTEMPT_START',attempt=retry.attempts,trusted_frequency_Hz=target)
            result=scan(io,target)
            if result.ok:
                target=float(result.frequency_Hz)
                io.event('SCAN_SUCCESS',frequency_Hz=target,band_edge=result.band_edge)
                retry.success();failed_episode=False
                clock.succeeded(io.time)
                if mode!='ABSOLUTE':
                    io.event('HANDOFF_TIMER',origin=mode,next_scan_us=clock.next,waiting_for_recovery=clock.waiting)
            else:
                budget_class=retry.classify(result.status)
                if budget_class is None:
                    io.event('SCAN_TRUNCATED_BY_RUN_END',reason=result.reason,status=result.status,
                             trusted_frequency_unchanged_Hz=target)
                    continue
                retry.fail(budget_class,io.time);failed_episode=True
                io.event('SCAN_FAILURE',reason=result.reason,status=result.status,budget_class=budget_class,
                         trusted_frequency_unchanged_Hz=target,
                         episode_failures_in_class=retry.episode[budget_class],class_limit=retry.limit[budget_class],
                         total_failures=retry.total_failures,total_search=retry.total['search'],
                         total_preemption=retry.total['preemption'],total_measurement=retry.total['measurement'],
                         total_nonstationary=retry.total['nonstationary'],retry_not_before_us=retry.not_before)
                if retry.exhausted:io.event('SCAN_RETRIES_EXHAUSTED',budget_class=retry.exhausted_class)
                if not io.finished:last=io.control(target,cfg['scan_amplitude'],'FAILED_SCAN_ROLLBACK')
                continue
        if not io.finished:
            last=io.control(target,cfg['scan_amplitude'] if failed_episode else 1.)
            if not failed_episode and clock.observe_control(io.time,last,target):
                io.event('RECOVERY_TIMER_REARM',frequency_Hz=target,applied_amplitude=last.amplitude,
                         next_scan_us=clock.next,measurement_state=last.state)
