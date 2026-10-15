"""Independent regression for the 2026-09-22 review fixes.

Run: python -X utf8 -B review/test_radiation_load_audit_regression.py
Optional: --output-dir review/results/radiation_load_audit_20260922
Tests require SciPy; the reference calculation still only requires NumPy.
Does not modify the historical workspace, controller, matching, or limits.
"""
from __future__ import annotations
import argparse, builtins, contextlib, hashlib, importlib.util, io, json, math
from pathlib import Path
import platform, subprocess, sys, unittest
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import patch
import numpy as np

HERE = Path(__file__).resolve().parent
REFERENCE = HERE/'radiation_load_layer1_reference.py'
MODEL = HERE.parent/'workspace/outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py'

def load_module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module

ref=load_module('radiation_audit_reference',REFERENCE)
model=load_module('radiation_audit_model',MODEL)
base=model.scenario_map()['CASE_000_BASELINE']
CAPTURE={}

def numpy_only_smoke():
    original=builtins.__import__
    def block(name,*args,**kwargs):
        if name=='scipy' or name.startswith('scipy.'):
            raise ImportError('SciPy deliberately blocked in runtime smoke test')
        return original(name,*args,**kwargs)
    builtins.__import__=block
    layer=ref.Layer1(base.bvd)
    ref.report(base.bvd)
    ref.report_electrical(model,base,layer)
    ref.report_registry(layer,model.scenario_map())
    print('Runtime smoke passed with SciPy imports blocked.')

if '--numpy-only-smoke' in sys.argv:
    numpy_only_smoke()
    raise SystemExit(0)

import scipy
from scipy.optimize import brentq
from scipy.special import j1, struve

def direct_impedance(layer, medium, contact, frequency):
    """Force/velocity impedance in kg/s; independent of reference rr normalisation."""
    omega=2*np.pi*frequency
    area=np.pi*layer.radius**2
    def medium_z(name):
        rho,sound=ref.MEDIA[name]
        x=2*omega*layer.radius/sound
        return rho*sound*area*((1-2*j1(x)/x)+1j*2*struve(1,x)/x)
    return contact*medium_z(medium)+(1-contact)*medium_z('air')

def direct_equivalent(layer, medium, contact, frequency, qi=None):
    z=direct_impedance(layer,medium,contact,frequency)
    transform_squared=layer.effective_mass_kg()/layer.lm
    qi=layer.qm if qi is None else qi
    internal=2*np.pi*layer.fs*layer.lm/qi
    radiation=z.real/transform_squared
    loaded_lm=layer.lm+z.imag/(2*np.pi*frequency)/transform_squared
    loaded_fs=1/(2*np.pi*np.sqrt(loaded_lm*layer.cm))
    return dict(rm=internal+radiation,rm_internal=internal,rm_radiation=radiation,
                lm=loaded_lm,fs=loaded_fs,qm=2*np.pi*loaded_fs*loaded_lm/(internal+radiation))

def close(test, actual, expected, rel=1e-10, absolute=1e-12):
    test.assertTrue(math.isclose(float(actual),float(expected),rel_tol=rel,abs_tol=absolute),
                    f'{actual} != {expected}')

class Regression(unittest.TestCase):
    def test_01_original_special_function_cross_check(self):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            ref.verify_special_functions(cross_check=True)
        CAPTURE['special_function_log']=stream.getvalue()

    def test_02_special_function_boundaries(self):
        for x in (0,1e-12,1e-6,np.nextafter(1.,0.),1.,np.nextafter(1.,2.),33.,49.45947617896467,400.):
            with self.subTest(x=x):
                close(self,ref.struve_h1(x),struve(1,x),absolute=1e-10)
                close(self,ref.bessel_j1(x),j1(x),absolute=1e-10)
        for x in (-1.,float('nan'),float('inf'),np.nextafter(400.,np.inf)):
            with self.subTest(bad=x),self.assertRaises(ValueError): ref.struve_h1(x)

    def test_03_frozen_direct_mapping_36_cases(self):
        rows=[]
        for radius in (.3,.5,1.,1.5):
            layer=ref.Layer1(base.bvd,radius_m=radius*1e-3)
            for medium in ref.MEDIA:
                for eta in (.25,.5,1):
                    actual=layer.load(medium,eta)
                    expected=direct_equivalent(layer,medium,eta,layer.fs)
                    with self.subTest(radius_mm=radius,medium=medium,contact=eta):
                        for key in ('rm','rm_radiation','lm','fs','qm'):
                            close(self,getattr(actual,key),expected[key])
                    rows.append(dict(radius_mm=radius,medium=medium,contact=eta,
                                     rm_rel_error=abs(actual.rm/expected['rm']-1),
                                     lm_rel_error=abs(actual.lm/expected['lm']-1)))
        CAPTURE['frozen_mapping_checks']=rows

    def test_04_self_consistent_direct_mechanical_root(self):
        layer=ref.Layer1(base.bvd)
        mass=layer.effective_mass_kg()
        stiffness=mass/(layer.lm*layer.cm)
        rows=[]
        for _,medium,eta in ref.GRID:
            actual=layer.load(medium,eta,self_consistent=True)
            root=brentq(lambda f:2*np.pi*f*mass-stiffness/(2*np.pi*f)+
                        direct_impedance(layer,medium,eta,f).imag,.7e6,1e6,xtol=1e-8)
            expected=direct_equivalent(layer,medium,eta,root)
            frozen=layer.load(medium,eta)
            with self.subTest(medium=medium,contact=eta):
                close(self,actual.fs,root,absolute=2e-6)
                for key in ('rm','rm_radiation','lm','qm'): close(self,getattr(actual,key),expected[key])
            rows.append(dict(medium=medium,contact=eta,frozen=frozen.as_dict(),
                             self_consistent=actual.as_dict(),independent=expected,
                             independent_mechanical_root_Hz=root,
                             delta_Q_pct=100*(actual.qm/frozen.qm-1)))
        CAPTURE['self_consistent_checks']=rows

    def test_05_q_decomposition_and_intrinsic_q_variants(self):
        layer=ref.Layer1(base.bvd)
        for qi in (500,800,1000):
            for consistent in (False,True):
                lp=layer.load('calcif',1.,qm_intrinsic=qi,self_consistent=consistent)
                direct=direct_equivalent(layer,'calcif',1.,lp.radiation_evaluation_frequency_Hz,qi=qi)
                close(self,lp.rm_radiation,direct['rm_radiation'])
                close(self,lp.qm,1/(1/lp.q_rad+1/lp.q_int_loaded))

    def test_06_corrected_q_regression(self):
        layer=ref.Layer1(base.bvd)
        close(self,layer.load('blood',1.,self_consistent=True).qm,31.76560059734565,absolute=1e-8)
        close(self,layer.load('calcif',1.,self_consistent=True).qm,28.74751449113429,absolute=1e-8)

    def test_07_registry_aliases(self):
        layer=ref.Layer1(base.bvd)
        groups=[]
        for medium in ref.MEDIA:
            for eta in (0,.25,.5,.75,1):
                lp=layer.load(medium,eta)
                key=[lp.rm,lp.lm,lp.cm]
                for group in groups:
                    if np.allclose(key,group['bvd'],rtol=1e-13,atol=0):
                        group['labels'].append([medium,eta]); break
                else: groups.append({'bvd':key,'labels':[[medium,eta]]})
        self.assertEqual(len(groups),9)
        self.assertEqual(max(len(g['labels']) for g in groups),7)
        CAPTURE['alias_groups']=groups

    def test_08_power_bound_does_not_imply_input_match(self):
        lp=ref.Layer1(base.bvd).load('blood',1.)
        sc=replace(base,bvd=replace(base.bvd,**{k:getattr(lp,k) for k in ('rm','lm','cm','fs','qm')}))
        f=np.arange(.8e6,1e6+100,100)
        response=model.response(f,sc)
        amplitude=model.allowed_amplitude(f,sc,use_soft_limits=True)
        power=response['p_rm_W']*amplitude**2
        i=int(np.argmax(power))
        bound=model.VPP_SOFT**2/(8*lp.rm)
        self.assertTrue(np.all(power<=bound*(1+1e-12)))
        self.assertGreater(power[i]/bound,.99999)
        self.assertGreater(response['gamma'][i],.7)
        close(self,power[i],.011192121105505935)
        close(self,response['gamma'][i],.7332242113789963)
        z=response['z_in'][i]
        CAPTURE['blood_frozen_power_and_matching']={
            'peak_Hz':float(f[i]),'peak_W':float(power[i]),'voltage_bound_W':bound,
            'fraction_of_bound':float(power[i]/bound),'z_in_ohm':[float(z.real),float(z.imag)],
            'gamma_proxy':float(response['gamma'][i]),
            'P_port_over_P_source':float(response['p_port_W'][i]/response['p_source_W'][i])}

    def test_09_all_unique_loads_balance_constraints_and_power_partition(self):
        f=np.arange(.8e6,1e6+100,100)
        residuals=[]
        for medium,eta in [('air',1)]+[(m,e) for m in ('blood','calcif') for e in (.25,.5,.75,1)]:
            for consistent in (False,True):
                lp=ref.Layer1(base.bvd).load(medium,eta,self_consistent=consistent)
                sc=replace(base,bvd=replace(base.bvd,**{k:getattr(lp,k) for k in ('rm','lm','cm','fs','qm')}))
                r=model.response(f,sc)
                a=model.allowed_amplitude(f,sc,use_soft_limits=True)
                total=r['p_rm_W']*a**2
                internal=np.abs(r['i_motional']*a)**2*lp.rm_internal
                radiation=np.abs(r['i_motional']*a)**2*lp.rm_radiation
                self.assertTrue(np.allclose(total,internal+radiation,rtol=1e-12,atol=1e-15))
                self.assertLessEqual(float(max(r['vport_vpp']*a)),model.VPP_SOFT*(1+1e-12))
                self.assertLessEqual(float(max(r['iport_irms_A']*a)),model.IRMS_SOFT*(1+1e-12))
                self.assertLessEqual(float(max(total)),model.VPP_SOFT**2/(8*lp.rm)*(1+1e-12))
                error=float(max(abs(r['power_balance_error_W'])))
                self.assertLess(error,1e-12)
                residuals.append(error)
        CAPTURE['maximum_balance_residual_W']=max(residuals)

    def test_10_invalid_inputs(self):
        for kwargs in [dict(radius_m=0),dict(radius_m=float('nan')),dict(rho_pzt=-1),dict(c_d=float('inf'))]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError): ref.Layer1(base.bvd,**kwargs)
        layer=ref.Layer1(base.bvd)
        for eta in (-1,2,float('nan')):
            with self.assertRaises(ValueError): layer.load('blood',eta)
        with self.assertRaises(ValueError): layer.load('blood',1,qm_intrinsic=0)

    def test_11_reject_inconsistent_fs_lm_cm_at_construction(self):
        with self.assertRaisesRegex(ValueError,'fs'):
            ref.Layer1(replace(base.bvd,cm=2*base.bvd.cm))

    def test_12_missing_half_height_crossing_is_explicit(self):
        self.assertIsNone(ref._fwhm(np.array([1.,2.,3.]),np.array([1.,2.,3.])))
        self.assertIn('N/A',ref._format_fwhm(None))
        stream=io.StringIO()
        with patch.object(ref,'_fwhm',return_value=None),contextlib.redirect_stdout(stream):
            ref.report_electrical(model,base,ref.Layer1(base.bvd))
        self.assertIn('N/A(区间内缺交点)',stream.getvalue())

    def test_13_baseline_and_1p5mm_reports(self):
        for radius in (.5,1.5):
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):
                ref.report(base.bvd,radius_m=radius*1e-3)
                ref.report_electrical(model,base,ref.Layer1(base.bvd,radius_m=radius*1e-3))
            CAPTURE[f'report_{radius:g}mm']=stream.getvalue()

    def test_14_numpy_only_runtime(self):
        run=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),'--numpy-only-smoke'],
                           capture_output=True,text=True,encoding='utf-8',timeout=120)
        self.assertEqual(run.returncode,0,run.stderr)
        CAPTURE['numpy_only_smoke_returncode']=run.returncode

    def test_15_historical_baseline_unchanged(self):
        self.assertEqual(len(model.scenario_map()),34)
        r=model.response(.9e6,base)
        close(self,r['p_rm_W'][0],.16999997832489855)
        close(self,r['vport_vpp'][0],99.99999362496995)
        close(self,r['iport_irms_A'][0],.004999999681248331)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    watched=[MODEL,*sorted((MODEL.parent.parent/'stage2_matching').glob('*.json'))]
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    before={str(p.relative_to(HERE.parent)):digest(p) for p in watched}
    stream=io.StringIO()
    results=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Regression))
    after={str(p.relative_to(HERE.parent)):digest(p) for p in watched}
    evidence={'scope':'REFERENCE_AND_STATIC_REGRESSION_NO_NEW_CONTROL_OR_LTSPICE_RUN',
              'assumptions':'Hypothetical BVD/geometry/media; not measured transducer or acoustic field.',
              'runtime':dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__),
              'tests_run':results.testsRun,'failures':len(results.failures),'errors':len(results.errors),
              'skipped':len(results.skipped),'passed':results.wasSuccessful() and before==after,
              'frozen_model_unchanged':before==after,'frozen_model_sha256':before,
              'code_sha256':{REFERENCE.name:digest(REFERENCE),Path(__file__).name:digest(Path(__file__))},
              'details':CAPTURE}
    print(stream.getvalue())
    if args.output_dir:
        args.output_dir.mkdir(parents=True,exist_ok=True)
        (args.output_dir/'test_results.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        (args.output_dir/'test_log.txt').write_text(stream.getvalue(),encoding='utf-8')
        (args.output_dir/'run_receipt.json').write_text(json.dumps({'ran_at_utc':datetime.now(timezone.utc).isoformat(),
              'code_sha256':evidence['code_sha256']},ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if evidence['passed'] else 1

if __name__=='__main__':
    raise SystemExit(main())
