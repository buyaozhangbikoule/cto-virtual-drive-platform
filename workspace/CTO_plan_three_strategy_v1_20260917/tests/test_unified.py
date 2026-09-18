import copy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np

from controllers import Executor, RetryBudget, ScanResult, grid, phase_update, run_policy, scan
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
        self.assertIsNone(result)
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
