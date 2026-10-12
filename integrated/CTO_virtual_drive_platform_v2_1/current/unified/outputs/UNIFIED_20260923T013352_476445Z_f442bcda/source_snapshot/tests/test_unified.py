import copy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np

from controllers import (Executor, PointResult, RetryBudget, ScanBudget, ScanResult, grid,
                         phase_update, run_policy, scan)
from engine import Engine, Measurement, Protection, measured_score, valid_measurement
from metrics import energy, evaluate, references
from models import model_v2_1 as model

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
BASE = 'CASE_000_BASELINE'


class UnifiedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs = references(CFG)

    def engine(self, ids=None, strategy='PERIODIC_SCAN'):
        return Engine(copy.deepcopy(CFG),ids or [BASE],strategy,'TEST')

    def test_bvd_Q_derived(self):
        for case in model.all_scenarios():
            b = case.bvd
            self.assertAlmostEqual(b.fs,1/(2*np.pi*np.sqrt(b.lm*b.cm)),places=6)
            self.assertAlmostEqual(b.qm,2*np.pi*b.fs*b.lm/b.rm,places=8)

    def test_units_power_and_phase(self):
        e = self.engine()
        m = e.execute(900000,1,'CONTROL',20000)
        q = model.response(900000,e.cases[BASE])
        self.assertAlmostEqual(m.phase_input_deg,float(q['phase_deg'][0]))
        # Frozen source calibration has a 6.4 microvolt rounding residual.
        self.assertAlmostEqual(m.vpp,100,places=4)
        self.assertAlmostEqual(m.irms,.005,places=7)
        self.assertAlmostEqual(m.p_port_W,.17,places=7)
        self.assertLess(abs(e.rows[0]['power_balance_error_W']),1e-12)

    def test_invalid_scan_measurements_never_succeed(self):
        for bad in (None,float('nan'),float('inf'),0.0):
            with self.subTest(bad=bad):
                e = self.engine()
                e.measurement_filter = lambda m,k: replace(m,p_port_W=bad)
                r = scan(Executor(e),900000)
                self.assertFalse(r.ok)
                self.assertIsNone(r.frequency_Hz)

    def test_late_invalid_point_not_just_anchor(self):
        e = self.engine()
        e.measurement_filter = lambda m,k: replace(m,p_port_W=float('nan')) if k=='SCAN_POINT' else m
        r = scan(Executor(e),900000)
        self.assertFalse(r.ok)
        self.assertTrue(any(x['kind']=='SCAN_POINT' for x in e.rows))

    def test_flat_scan_fails(self):
        e = self.engine()
        def flat(m,k):
            return replace(m,vpp=40.,irms=.002,p_port_W=.0272,zin_real=50.,zin_imag=0.,phase_input_deg=0.)
        e.measurement_filter = flat
        r = scan(Executor(e),900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason,'FLAT_OR_NO_SIGNAL')

    def test_scan_amplitude_synced_and_no_instant_return(self):
        e = self.engine()
        m = e.execute(900000,.4,'SCAN_POINT',1500)
        self.assertEqual(m.amplitude,e.protection.amplitude)
        m = e.execute(900000,1.,'CONTROL',20000)
        self.assertLess(m.amplitude,.41)
        self.assertEqual(m.state,'RAMP_UP')

    def test_hard_latch_applies_to_scan(self):
        e = self.engine()
        e.protection.hard_until = 60000
        m = e.execute(900000,.4,'SCAN_POINT',1500)
        self.assertEqual(m.amplitude,0.)
        self.assertEqual(m.state,'HARD_TRIP')

    def test_no_simultaneous_amplitude_and_frequency_step(self):
        e = self.engine()
        first = e.execute(850000,.4,'SCAN_POINT',1500)
        self.assertEqual(first.frequency_Hz,900000)
        self.assertLessEqual(first.amplitude,.4)
        second = e.execute(850000,.4,'SCAN_POINT',1500)
        self.assertEqual(second.amplitude,first.amplitude)
        self.assertEqual(second.frequency_Hz,850000)

    def test_retry_deadline_and_exhaustion(self):
        r = RetryBudget(CFG)
        for n in range(3):
            t = n*50000
            r.start(t)
            r.fail(t)
            self.assertFalse(r.can_start(t+49999))
        self.assertTrue(r.exhausted)
        self.assertFalse(r.can_start(100000000))
        self.assertEqual(r.total_failures,3)
        with self.assertRaises(RuntimeError):
            r.start(100000000)

    def test_failed_scan_target_unchanged_and_low_latch(self):
        e = self.engine([BASE]*3)
        def fail(io, trusted):
            io.execute(880000,.4,'FORCED_FAILED_SCAN_POINT',1500)
            return ScanResult(False,None,'FORCED_FAILURE')
        with patch('controllers.scan',side_effect=fail):
            run_policy(Executor(e),'PERIODIC_SCAN',0.)
        starts = [x for x in e.events if x['event']=='SCAN_ATTEMPT_START']
        failures = [x for x in e.events if x['event']=='SCAN_FAILURE']
        self.assertEqual(len(starts),3)
        self.assertEqual(len(failures),3)
        for f,s in zip(failures,starts[1:]):
            self.assertGreaterEqual(s['time_us']-f['time_us'],50000)
        self.assertTrue(all(x['trusted_frequency_unchanged_Hz']==900000 for x in failures))
        after = [r for r in e.rows if r['start_us']>=failures[0]['time_us']]
        self.assertTrue(all(r['applied_amplitude']<=.4 for r in after))
        self.assertTrue(any(r['kind']=='FAILED_SCAN_LATCHED_HOLD' for r in after))
        self.assertEqual(e.rows[-1]['frequency_Hz'],900000)

    def test_boundary_split_no_extra_controller_measurement(self):
        e = self.engine([BASE,'CASE_FS_M5'])
        e.execute(900000,1,'CONTROL',790000)
        count = e.action_id
        e.execute(900000,1,'CONTROL',20000)
        chunks = [r for r in e.rows if r['action_id']==count]
        self.assertEqual([r['duration_us'] for r in chunks],[10000,10000])
        self.assertEqual([r['case_id'] for r in chunks],[BASE,'CASE_FS_M5'])
        self.assertEqual(chunks[0]['applied_amplitude'],chunks[1]['applied_amplitude'])
        self.assertNotEqual(chunks[0]['p_rm_W'],chunks[1]['p_rm_W'])
        a, ref = energy(chunks,790000,810000,self.refs)
        self.assertAlmostEqual(a,sum(r['p_rm_W']*.01 for r in chunks))

    def test_unobserved_boundary_not_reprotected(self):
        e = self.engine([BASE,'CASE_FS_M5'])
        # Deliberately prepare a held command; hidden boundary is not a guard call.
        e.execute(900000,1,'CONTROL',810000)
        self.assertEqual(e.action_id,1)
        self.assertEqual(e.rows[0]['applied_amplitude'],e.rows[1]['applied_amplitude'])
        self.assertFalse(e.rows[0]['actual_hard_violation'])
        self.assertTrue(e.rows[1]['actual_hard_violation'])
        self.assertGreater(e.rows[1]['vport_Vpp'],160.)

    def test_invalid_plant_data_fails_off(self):
        p = Protection(CFG)
        r = p.apply(0,900000,.4,lambda f: {'vport_vpp':[float('nan')],'iport_irms_A':[.001]})
        self.assertEqual(p.amplitude,0.)
        self.assertEqual(p.state,'DATA_INVALID')
        self.assertTrue(r['frozen'])

    def test_failed_scan_at_final_endpoint_is_counted(self):
        e = self.engine(strategy='FIXED')
        run_policy(Executor(e),'FIXED',0.)
        e.event('SCAN_FAILURE',reason='FORCED_TRUNCATION')
        per,overall = evaluate(e.rows,e.events,CFG,self.refs)
        self.assertEqual(per[-1]['scan_failures'],1)
        self.assertEqual(overall['scan_failures'],1)

    def test_protection_invalidates_phase_pair(self):
        e = self.engine(strategy='PHASE_FEEDBACK')
        m = e.execute(900000,1,'CONTROL',20000)
        e.protection.hard_until=80000
        f = phase_update(Executor(e),m,m.phase_input_deg+10,900000)
        self.assertEqual(f,900000)
        self.assertEqual(e.t,21500)
        self.assertTrue(any(x['event']=='PHASE_PROBE_FAILED' for x in e.events))

    def test_nan_is_not_steady_state(self):
        e = self.engine(strategy='FIXED')
        e.measurement_filter=lambda m,k: replace(m,phase_input_deg=float('nan'))
        run_policy(Executor(e),'FIXED',0.)
        per,_ = evaluate(e.rows,e.events,CFG,self.refs)
        self.assertFalse(per[0]['settled'])
        self.assertIsNone(per[0]['steady_error_pct'])

    def test_short_probes_not_extra_control_samples(self):
        e = self.engine(strategy='PHASE_FEEDBACK')
        for _ in range(40):
            e.execute(900000,1,'PHASE_PROBE_MINUS',1500)
            e.execute(900000,1,'PHASE_PROBE_PLUS',1500)
            e.execute(900000,1,'CONTROL',17000)
        per,_ = evaluate(e.rows,e.events,CFG,self.refs)
        self.assertEqual(per[0]['recovery_confirm_ms'],200.)
        self.assertEqual(per[0]['max_consecutive_qualified_samples'],40)

    def test_missed_tick_breaks_continuous_window(self):
        e = self.engine(strategy='PERIODIC_SCAN')
        for _ in range(4):
            for _ in range(9):
                e.execute(900000,1,'CONTROL',20000)
            e.execute(900000,1,'SCAN_POINT',20000)
        per,_ = evaluate(e.rows,e.events,CFG,self.refs)
        self.assertFalse(per[0]['settled'])
        self.assertEqual(per[0]['max_consecutive_qualified_samples'],9)

    def test_no_fallback_for_short_qualified_run(self):
        e = self.engine()
        for _ in range(31):
            e.execute(900000,0,'HOLD',20000)
        e.protection.amplitude=1.; e.protection.state='NORMAL'
        for _ in range(9):
            e.execute(900000,1,'CONTROL',20000)
        per,_ = evaluate(e.rows,e.events,CFG,self.refs)
        self.assertFalse(per[0]['settled'])
        self.assertIsNone(per[0]['steady_error_pct'])
        self.assertEqual(per[0]['max_consecutive_qualified_samples'],9)
        self.assertIsNotNone(per[0]['fixed_tail_error_pct'])

    def test_enter_and_confirmation_are_separate(self):
        e = self.engine(strategy='FIXED')
        run_policy(Executor(e),'FIXED',0.)
        per,overall = evaluate(e.rows,e.events,CFG,self.refs)
        self.assertTrue(per[0]['settled'])
        self.assertEqual(per[0]['recovery_enter_ms'],20.)
        self.assertEqual(per[0]['recovery_confirm_ms'],200.)
        self.assertEqual(overall['logged_duration_s'],.8)

    def test_phase_probes_are_executed_and_timed(self):
        e = self.engine(strategy='PHASE_FEEDBACK')
        m = e.execute(900000,1,'CONTROL',20000)
        t = e.t
        phase_update(Executor(e),m,m.phase_input_deg+1,900000)
        self.assertGreaterEqual(e.t-t,3000)
        kinds = {r['kind'] for r in e.rows}
        self.assertIn('PHASE_PROBE_MINUS',kinds)
        self.assertIn('PHASE_PROBE_PLUS',kinds)

    def test_controller_measurement_has_no_ground_truth(self):
        fields = Measurement.__dataclass_fields__
        self.assertFalse({'case_id','optimum','scenario','schedule','bvd'} & set(fields))

    def test_reference_not_returned_from_executor(self):
        e = self.engine()
        m = Executor(e).control(900000,1.)
        self.assertIsInstance(m,Measurement)
        self.assertFalse(hasattr(m,'safe_power'))

    def test_grid_includes_boundaries_and_center(self):
        x = grid(854837.2,50000,5000,800000,1000000)
        self.assertEqual(x[0],804837.2)
        self.assertEqual(x[-1],904837.2)
        self.assertIn(854837.2,x)

    def test_truncated_probe_is_not_validated(self):
        e = self.engine()
        e.t = e.end-500
        e.protection.last_us=e.t
        result = Executor(e).point(900000,1.,'SCAN_VALIDATE')
        self.assertFalse(result.ok)
        self.assertIsNone(result.measurement)
        # A run that ended under the probe is not a failure of the search.
        self.assertEqual(result.status,'END_OF_RUN_TRUNCATED')
        self.assertIsNone(ScanBudget.classify(result.status))
        self.assertEqual(e.rows[-1]['duration_us'],500)

    def test_peak_includes_pre_guard_not_only_clamped_output(self):
        e = self.engine([BASE,'CASE_FS_M5'],'FIXED')
        run_policy(Executor(e),'FIXED',0.)
        per,overall=evaluate(e.rows,e.events,CFG,self.refs)
        self.assertGreater(per[1]['peak_voltage_Vpp'],160.)
        self.assertLessEqual(per[1]['peak_post_guard_and_hold_voltage_Vpp'],130.+1e-8)
        self.assertGreaterEqual(per[1]['pre_guard_hard_observations'],1)

    def test_all_strategies_identical_schedule_and_duration(self):
        timelines = []
        for s in ('FIXED','PERIODIC_SCAN','PHASE_FEEDBACK'):
            e = self.engine([BASE,'CASE_FS_M5'],s)
            phi = float(model.response(900000,e.cases[BASE])['phase_deg'][0])
            run_policy(Executor(e),s,phi)
            per,overall = evaluate(e.rows,e.events,CFG,self.refs)
            self.assertEqual(overall['logged_duration_s'],1.6)
            timelines.append([(r['case_id'],r['start_s'],r['end_s']) for r in per])
        self.assertEqual(timelines[0],timelines[1])
        self.assertEqual(timelines[0],timelines[2])


class ScanFaultTaxonomyTests(unittest.TestCase):
    """Coverage for the failure classes that normal operation never reaches.

    Every branch added by the taxonomy patch is forced here on purpose. A
    failure path that only exists on paper is the defect the previous round
    already caught once (an uninitialised counter that ran clean because its
    branch was unreachable), so none of these are left to chance.
    """

    @classmethod
    def setUpClass(cls):
        cls.refs = references(CFG)

    def engine(self, ids=None, strategy='PERIODIC_SCAN', cfg=None):
        return Engine(cfg or copy.deepcopy(CFG), ids or [BASE], strategy, 'TEST')

    # ---- point-level status ----------------------------------------------

    def test_protection_preemption_is_not_a_search_failure(self):
        e = self.engine()
        e.protection.hard_until = 60000          # tripped before the scan starts
        r = scan(Executor(e), 900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 'PREEMPTED_PROTECTION')
        self.assertEqual(ScanBudget.classify(r.status), 'preemption')
        # The scan aborted on the anchor: no grid point was ever executed.
        self.assertFalse(any(x['kind'] == 'SCAN_POINT' for x in e.rows))

    def test_invalid_data_under_normal_protection_is_a_measurement_fault(self):
        e = self.engine()
        e.measurement_filter = lambda m, k: replace(m, p_port_W=float('nan'))
        r = scan(Executor(e), 900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 'INVALID_MEASUREMENT')
        self.assertEqual(ScanBudget.classify(r.status), 'measurement')

    def test_truncation_is_charged_to_nothing(self):
        e = self.engine()
        e.t = e.end - 500
        e.protection.last_us = e.t
        r = scan(Executor(e), 900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 'END_OF_RUN_TRUNCATED')
        self.assertIsNone(ScanBudget.classify(r.status))

    def test_unknown_status_falls_back_to_the_search_budget(self):
        self.assertEqual(ScanBudget.classify('SOMETHING_NEW'), 'search')
        self.assertEqual(ScanResult(False, None, 'FORCED').status, 'SEARCH_FAILED')

    # ---- non-stationary detection ----------------------------------------

    def test_anchor_recheck_between_levels_detects_a_moved_plant(self):
        e = self.engine()

        def moved(m, kind):
            if kind in ('SCAN_ANCHOR_LEVEL', 'SCAN_ANCHOR_END'):
                return replace(m, zin_real=m.zin_real*3., p_port_W=m.p_port_W*3.)
            return m
        e.measurement_filter = moved
        r = scan(Executor(e), 900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 'NONSTATIONARY_SCAN')
        self.assertEqual(ScanBudget.classify(r.status), 'nonstationary')
        detected = [x for x in e.events if x['event'] == 'SCAN_NONSTATIONARY_DETECTED']
        self.assertEqual(len(detected), 1)
        # Caught at the FIRST level, not after the whole three-level budget.
        self.assertEqual(detected[0]['level_index'], 0)

    def test_real_segment_change_under_a_scan_is_caught_before_the_last_level(self):
        cfg = copy.deepcopy(CFG)
        cfg['segment_us'] = 40000            # boundary lands inside level 0
        e = self.engine([BASE, 'CASE_CM_P20'], cfg=cfg)
        r = scan(Executor(e), 900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 'NONSTATIONARY_SCAN')
        self.assertTrue(any(x['case_id'] == BASE for x in e.rows))
        self.assertTrue(any(x['case_id'] == 'CASE_CM_P20' for x in e.rows))

    def test_a_stationary_plant_never_reports_nonstationary(self):
        e = self.engine()
        r = scan(Executor(e), 900000)
        self.assertTrue(r.ok)
        self.assertEqual(r.status, 'VALID_LOCAL_CANDIDATE')
        self.assertFalse(any(x['event'] == 'SCAN_NONSTATIONARY_DETECTED' for x in e.events))

    # ---- bounded coarse fallback -----------------------------------------

    def test_edge_walk_with_an_unchanged_anchor_falls_back_and_stays_bounded(self):
        """Edge-walking alone must not be reported as a moved plant.

        The forced shape is a curve that turns monotone once the coarse levels
        are done, while the anchor keeps reading the truth. That is deliberately
        artificial -- it is the discrimination under test: the fine level walks,
        the anchor says nothing moved, so the answer is a BOUNDED fallback to a
        coarser step, not NONSTATIONARY and not an unbounded re-search.
        """
        cfg = copy.deepcopy(CFG)
        cfg['scan_max_coarse_fallbacks'] = 1
        e = self.engine(cfg=cfg)
        seen = []

        def ramp_after_coarse_levels(m, kind):
            if kind != 'SCAN_POINT':
                return m                      # anchors always read the truth
            seen.append(kind)
            if len(seen) <= 40:               # levels 0 and 1 see the real curve
                return m
            scale = 1e-4*(m.frequency_Hz-cfg['frequency_min_Hz'])+1.
            return replace(m, p_port_W=scale, vpp=40., irms=.002,
                           zin_real=50., zin_imag=0.)
        e.measurement_filter = ramp_after_coarse_levels
        r = scan(Executor(e), 900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.status, 'SEARCH_FAILED')
        self.assertEqual(r.reason, 'RECENTRE_EXHAUSTED')
        fallbacks = [x for x in e.events if x['event'] == 'SCAN_COARSE_FALLBACK']
        self.assertEqual(len(fallbacks), cfg['scan_max_coarse_fallbacks'])
        self.assertEqual(fallbacks[0]['restart_frequency_Hz'], 900000)
        self.assertFalse(any(x['event'] == 'SCAN_NONSTATIONARY_DETECTED' for x in e.events))

    def test_cost_cap_bounds_one_attempt(self):
        cfg = copy.deepcopy(CFG)
        cfg['scan_max_points'] = 12
        e = self.engine(cfg=cfg)
        r = scan(Executor(e), 900000)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, 'SCAN_COST_CAP_REACHED')
        self.assertEqual(r.status, 'SEARCH_FAILED')
        self.assertLessEqual(sum(1 for x in e.rows if x['kind'] == 'SCAN_POINT'),
                             cfg['scan_max_points'])

    # ---- budget bookkeeping ----------------------------------------------

    def test_each_class_is_bounded_and_latches_independently(self):
        for cls, limit_key in (('search', 'failed_scan_max_retries'),
                               ('preemption', 'scan_preemption_max_retries'),
                               ('measurement', 'scan_measurement_fault_max_retries'),
                               ('nonstationary', 'scan_nonstationary_max_retries')):
            with self.subTest(cls=cls):
                b = ScanBudget(CFG)
                for n in range(CFG[limit_key]+1):
                    self.assertFalse(b.exhausted)
                    b.start(n*CFG['failed_scan_retry_us'])
                    b.fail(cls, n*CFG['failed_scan_retry_us'])
                self.assertTrue(b.exhausted)
                self.assertEqual(b.exhausted_class, cls)
                self.assertFalse(b.can_start(10**9))

    def test_preemption_does_not_spend_the_search_allowance(self):
        b = ScanBudget(CFG)
        for n in range(CFG['scan_preemption_max_retries']):
            b.start(n*CFG['failed_scan_retry_us'])
            b.fail('preemption', n*CFG['failed_scan_retry_us'])
        self.assertFalse(b.exhausted)
        self.assertEqual(b.episode['search'], 0)
        # ...and the search allowance is still whole.
        for n in range(CFG['failed_scan_max_retries']+1):
            self.assertFalse(b.exhausted)
            t = 10**6+n*CFG['failed_scan_retry_us']
            b.start(t)
            b.fail('search', t)
        self.assertTrue(b.exhausted)
        self.assertEqual(b.exhausted_class, 'search')

    def test_success_clears_the_episode_but_never_the_latch(self):
        b = ScanBudget(CFG)
        b.start(0); b.fail('search', 0)
        b.success()
        self.assertEqual(b.episode['search'], 0)
        self.assertEqual(b.total['search'], 1)
        self.assertEqual(b.total_failures, 1)
        b.exhausted, b.exhausted_class = True, 'search'
        b.success()
        self.assertTrue(b.exhausted, 'an explicit run reset is the only way out')

    def test_policy_reports_the_class_and_keeps_the_low_amplitude_hold(self):
        e = Engine(copy.deepcopy(CFG), [BASE]*3, 'PERIODIC_SCAN', 'TEST')

        def preempted(io, trusted):
            io.execute(880000, .4, 'FORCED_PREEMPTED_POINT', 1500)
            return ScanResult(False, None, 'FORCED', status='PREEMPTED_PROTECTION')
        with patch('controllers.scan', side_effect=preempted):
            run_policy(Executor(e), 'PERIODIC_SCAN', 0.)
        failures = [x for x in e.events if x['event'] == 'SCAN_FAILURE']
        self.assertTrue(failures)
        self.assertTrue(all(x['budget_class'] == 'preemption' for x in failures))
        self.assertTrue(all(x['total_search'] == 0 for x in failures))
        self.assertTrue(all(x['trusted_frequency_unchanged_Hz'] == 900000 for x in failures))
        after = [r for r in e.rows if r['start_us'] >= failures[0]['time_us']]
        self.assertTrue(all(r['applied_amplitude'] <= .4 for r in after))
        # Bounded: the pre-emption allowance latches too, it is not unlimited.
        self.assertEqual(len(failures), CFG['scan_preemption_max_retries']+1)
        self.assertTrue(any(r['kind'] == 'FAILED_SCAN_LATCHED_HOLD' for r in e.rows))

    def test_metrics_split_the_failure_column_without_losing_the_total(self):
        e = Engine(copy.deepcopy(CFG), [BASE]*2, 'PERIODIC_SCAN', 'TEST')
        run_policy(Executor(e), 'PERIODIC_SCAN', 0.)
        e.event('SCAN_FAILURE', reason='X', status='PREEMPTED_PROTECTION',
                budget_class='preemption')
        e.event('SCAN_FAILURE', reason='Y', status='SEARCH_FAILED', budget_class='search')
        per, overall = evaluate(e.rows, e.events, CFG, self.refs)
        self.assertEqual(overall['scan_failures_preemption'], 1)
        self.assertEqual(overall['scan_failures_search'], 1)
        self.assertEqual(overall['scan_failures'], 2)
        self.assertEqual(sum(overall[f'scan_failures_{k}'] for k in
                             ('search', 'preemption', 'measurement', 'nonstationary')),
                         overall['scan_failures'])



if __name__ == '__main__':
    unittest.main(verbosity=2)
