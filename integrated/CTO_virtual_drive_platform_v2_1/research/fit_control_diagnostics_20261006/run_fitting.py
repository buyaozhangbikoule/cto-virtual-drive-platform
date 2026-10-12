"""Run synthetic gate FIRST, then matched ablations on published summary data."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, platform, sys
from pathlib import Path
import numpy as np
import scipy
from fitting import *

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE/'output'/'fitting_v2')
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    result = {'schema':1,'identity':'independent feature-fitting experiment, not active model calibration',
              'numpy':np.__version__,'scipy':scipy.__version__,'python':platform.python_version(),
              'feature_order':KEYS,'parameter_order':PARAMS,'random_seed':20261006,
              'synthetic_parameter_relative_tolerance':1e-5,
              'uncertainty_weights_available':False,
              'sources':{'table':'Janů et al. 2021, Table 4; DOI 10.1016/j.ultras.2020.106341',
                         'transcription':'report_0928/output/evidence/review/validate_against_janu2021.py'},
              'source_hashes':{p.name:digest(p) for p in HERE.glob('*.py')}}
    legacy = HERE/'input_reference/validate_against_janu2021.py'
    diagnosis = HERE/'input_reference/02_当前模型参数迁移与代码核对.md'
    result['input_hashes']={str(p.relative_to(HERE)):digest(p) for p in (legacy,diagnosis)}
    model_path = ROOT/'current/unified/models/model_v2_1.py'
    spec=importlib.util.spec_from_file_location('janu_current_model',model_path)
    model=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=model
    spec.loader.exec_module(model)
    bp = model.BASE_BVD
    hypothetical = [bp.rm,bp.lm,bp.cm,bp.c0]
    cases=[('paper_iteration_synthetic',PUBLISHED['Iteration'][0],(36000.,44000.)),
           ('paper_equations_synthetic',PUBLISHED['Equations'][0],(36000.,44000.)),
           ('hypothetical_900k_synthetic',hypothetical,(800000.,1000000.))]
    synthetic=[]
    for name, truth, window in cases:
        target,info=features(truth,window,details=True)
        if info['boundary_features']:
            raise RuntimeError('invalid synthetic target')
        for scale in ('relative','feature_spacing'):
            runs=[]
            for start in starts(truth):
                run=fit(start,target,window,scale=scale)
                run['parameter_max_relative_error']=float(np.max(np.abs(np.array(run['parameters'])/truth-1)))
                run['recovery_pass']=bool(run['solver_success'] and run['valid_interior'] and run['parameter_max_relative_error']<1e-5)
                runs.append(run)
            synthetic.append(dict(name=name,scale=scale,truth=truth,window_Hz=window,target=target.tolist(),runs=runs))
            print(name,scale,sum(r['recovery_pass'] for r in runs),'/',len(runs),flush=True)
    result['synthetic']=synthetic
    result['synthetic_gate_scale']='feature_spacing'
    result['synthetic_gate_pass']=all(r['recovery_pass'] for s in synthetic
                                    if s['scale']=='feature_spacing' for r in s['runs'])
    if not result['synthetic_gate_pass']:
        (args.output/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        raise RuntimeError('Synthetic gate failed; paper fit NOT run')

    # Verify the independent impedance algebra against the frozen project's model.
    checks=[]
    for name,(p,points) in PUBLISHED.items():
        r,l,c,c0=p
        fs=1/(2*np.pi*np.sqrt(l*c))
        bvd=model.BVD(c0=c0,rm=r,lm=l,cm=c,qm=2*np.pi*fs*l/r,fs=fs)
        case=model.Scenario('CHECK','published','published','published','Janů bare BVD',bvd,model.BASE_MATCH,model.BASE_RS)
        grid=np.linspace(36000.,44000.,16001)
        project=model.response(grid,case)['z_bvd']
        agreement=float(np.max(abs(impedance(grid,p)-project)/abs(project)))
        if agreement>1e-12:
            raise RuntimeError('forward solver mismatch')
        old,new=features(p,mode='grid'),features(p)
        checks.append(dict(name=name,project_solver_max_relative_error=agreement,
                           grid_features=old.tolist(),continuous_features=new.tolist(),
                           published_computed_features=points,
                           grid_percent_errors=(100*abs((old-points)/points)).tolist(),
                           continuous_percent_errors=(100*abs((new-points)/points)).tolist()))
    result['published_forward_checks']=checks
    # Actual historical function, with only its obsolete module path rebound in
    # memory to the frozen model. No source-file edits or old main() output writes.
    sys.modules['model_v2_1']=model
    oldspec=importlib.util.spec_from_file_location('historical_janu',legacy)
    oldmod=importlib.util.module_from_spec(oldspec)
    oldspec.loader.exec_module(oldmod)
    oldpars,oldseed=oldmod.fit_to_measured_points()
    oldfeatures=oldmod.significant_points(*oldpars)
    result['historical_function_replay']={
        'model_binding':str(model_path.relative_to(ROOT)), 'model_sha256':digest(model_path),
        'parameters':list(oldpars),'seed':list(oldseed),'features':oldfeatures,
        'percent_errors':oldmod.errors_against_measurement(oldfeatures),
        'note':'original function and 1e-14 tolerances, read-only import; not the A/B standardized ablation'}
    seed=seed_from_features()
    result['seed']=seed.tolist()
    result['jacobian_at_seed']={}
    for mode in ('grid','continuous'):
        fn=lambda x: (features(np.exp(x),mode=mode)-MEASURED)/abs(MEASURED)
        x=np.log(seed)
        hs=np.sqrt(np.finfo(float).eps)*np.maximum(1.,abs(x))
        default=np.column_stack([(fn(x+np.eye(4)[k]*hs[k])-fn(x))/hs[k] for k in range(4)])
        result['jacobian_at_seed'][mode]={'forward_default_step':default.tolist(),
            'frequency_row_norms':np.linalg.norm(default[[1,3,5]],axis=1).tolist(),
            'central_steps':{str(h):jacobian(fn,x,h).tolist() for h in (1e-3,1e-4,1e-5,1e-6)}}
    variants=[('A_grid_relative_default','grid','relative',False),
              ('B_continuous_relative_default','continuous','relative',False),
              ('C_continuous_relative_central','continuous','relative',True),
              ('D_continuous_spacing_central','continuous','feature_spacing',True)]
    comparisons=[]
    for name,mode,scale,central in variants:
        runs=[fit(s,MEASURED,mode=mode,scale=scale,central=central) for s in starts(seed)]
        best=min(range(len(runs)),key=lambda k:runs[k]['cost'])
        comparisons.append(dict(name=name,mode=mode,scale=scale,central=central,runs=runs,best_index=best))
        print(name,'best errors %',runs[best]['percent_errors'],flush=True)
    result['measured_summary_fit']=comparisons
    result['input_unchanged']=all(digest(HERE/p)==h for p,h in result['input_hashes'].items())
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(args.output/'results.json')

if __name__=='__main__':
    main()
