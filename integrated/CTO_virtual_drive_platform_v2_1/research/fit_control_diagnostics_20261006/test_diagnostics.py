from __future__ import annotations
import copy, json, unittest
from pathlib import Path
import numpy as np
from scipy.optimize import minimize_scalar
import fitting as f
import control_accounting as c

class FeatureTests(unittest.TestCase):
    def test_continuous_extrema_against_scalar_minimization(self):
        for p,_ in f.PUBLISHED.values():
            got=f.features(p)
            functions=[lambda x:abs(f.impedance(x,p)),lambda x:-abs(f.impedance(x,p)),
                       lambda x:-np.angle(f.impedance(x,p),deg=True)]
            for k,fn in zip((1,3,5),functions):
                opt=minimize_scalar(fn,bounds=(got[k]-100,got[k]+100),method='bounded',options={'xatol':1e-7})
                self.assertLess(abs(opt.x-got[k]),.003)

    def test_complex_derivative(self):
        p=f.PUBLISHED['Iteration'][0]
        for freq in (38500,40000,41000):
            numeric=(f.impedance(freq+.01,p)-f.impedance(freq-.01,p))/.02/f.impedance(freq,p)
            self.assertLess(abs(numeric-f.logz_derivative(freq,p)),1e-10)

    def test_no_frequency_quantization(self):
        p=np.array(f.PUBLISHED['Iteration'][0]); x=np.log(p)
        j=f.jacobian(lambda v:f.features(np.exp(v)),x)
        self.assertTrue(np.all(np.linalg.norm(j[[1,3,5]],axis=1)>1000))

    def test_old_seed_zero_frequency_jacobian(self):
        x=np.log(f.seed_from_features()); h=np.sqrt(np.finfo(float).eps)*np.maximum(1,abs(x))
        fn=lambda x:f.features(np.exp(x),mode='grid')
        j=np.column_stack([(fn(x+np.eye(4)[k]*h[k])-fn(x))/h[k] for k in range(4)])
        np.testing.assert_array_equal(j[[1,3,5]],np.zeros((3,4)))

    def test_jacobian_step_stability(self):
        x=np.log(f.seed_from_features())
        fn=lambda x:f.features(np.exp(x))/abs(f.MEASURED)
        np.testing.assert_allclose(f.jacobian(fn,x,1e-5),f.jacobian(fn,x,1e-6),rtol=1e-5,atol=1e-7)

    def test_scale_is_spacing_not_claimed_uncertainty(self):
        self.assertEqual(f.scales(f.MEASURED,'feature_spacing')[1],1226.)
        np.testing.assert_equal(f.scales(f.MEASURED)[[1,3,5]],f.MEASURED[[1,3,5]])

    def test_phase_is_maximum(self):
        p=f.PUBLISHED['Iteration'][0]; a=f.features(p)
        self.assertGreater(a[4],np.angle(f.impedance(36000,p),deg=True))

    def test_invalid_params(self):
        with self.assertRaises(ValueError): f.features([0,1,1,1])

    def test_boundary_flag(self):
        _,info=f.features(f.PUBLISHED['Iteration'][0],(1000,1100),details=True)
        self.assertTrue(info['boundary_features'])

    def test_saved_synthetic_gate_and_failed_ablation_retained(self):
        data=json.loads((Path(__file__).parent/'output/fitting_v2/results.json').read_text(encoding='utf-8'))
        chosen=[r for s in data['synthetic'] if s['scale']=='feature_spacing' for r in s['runs']]
        self.assertEqual(len(chosen),36)
        self.assertTrue(all(r['recovery_pass'] and r['parameter_max_relative_error']<1e-5 for r in chosen))
        old=[r for s in data['synthetic'] if s['scale']=='relative' for r in s['runs']]
        self.assertEqual(len(old),36)  # retain failures, never silently drop them

class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.cfg={'control_tick_us':20000,'continuous_samples':10,'capture_threshold':.98}
        self.rows=[dict(kind='CONTROL',protection_state='NORMAL',frequency_frozen=False,measurement_valid=True,
                       start_us=i*20000,end_us=(i+1)*20000,action_end_us=(i+1)*20000,duration_us=20000,
                       p_rm_W=1.,actual_hard_violation=False) for i in range(10)]

    def test_exact_confirmation(self):
        window,n,first=c.confirmation(self.rows,self.cfg,1.)
        self.assertEqual((len(window),n,first),(10,10,20000))
        self.assertEqual(window[-1]['end_us']-window[0]['end_us'],180000)

    def test_nine_not_pass(self):
        self.assertFalse(c.confirmation(self.rows[:9],self.cfg,1.)[0])

    def test_missed_tick_breaks_run(self):
        rows=[r for i,r in enumerate(self.rows) if i!=4]
        self.assertFalse(c.confirmation(rows,self.cfg,1.)[0])

    def test_noncontrol_not_extra_qualified_sample(self):
        self.rows[4]['kind']='PHASE_PROBE_PLUS'
        self.assertFalse(c.confirmation(self.rows,self.cfg,1.)[0])

    def test_rejected_sample_breaks_run(self):
        self.rows[4]['frequency_frozen']=True
        self.assertFalse(c.confirmation(self.rows,self.cfg,1.)[0])

    def test_stage_protection_over_probe(self):
        r=copy.copy(self.rows[0]);r.update(kind='SCAN_POINT',protection_state='HARD_TRIP')
        self.assertEqual(c.classify(r,self.cfg,1.,set(),None),c.STAGES[0])

    def test_signed_energy_not_clipped(self):
        r=copy.copy(self.rows[0]);r['p_rm_W']=1.1
        t=c.empty_ledger();c.accumulate(t,r,1.)
        self.assertAlmostEqual(t['signed_deficit_J'],-.002)
        self.assertAlmostEqual(t['surplus_J'],.002)

    def test_105_timelines_reconciled(self):
        data=json.loads((Path(__file__).parent/'output/control/results.json').read_text(encoding='utf-8'))
        self.assertEqual(data['reconciled_timelines'],105)
        self.assertTrue(data['source_unchanged'])
        for report in data['reports']:
            self.assertEqual(sum(v['duration_us'] for v in report['stages'].values()),report['totals']['duration_us'])
            for s in report['segments']: self.assertIsNone(s['detection_wait_ms'])

    def test_frozen_tuning_validation_separation(self):
        p=json.loads((Path(__file__).parent/'validation_protocol.json').read_text(encoding='utf-8'))
        self.assertFalse(set(p['tuning_cases'])&set(p['validation_cases']))
        self.assertTrue(p['physical_parameter_fingerprints_disjoint'])
        self.assertEqual((p['segment_us'],p['capture_threshold'],p['continuous_samples']),(800000,.98,10))
        self.assertEqual(p['status'],'FROZEN_DESIGN_NOT_EXECUTED')

if __name__=='__main__': unittest.main(verbosity=2)
