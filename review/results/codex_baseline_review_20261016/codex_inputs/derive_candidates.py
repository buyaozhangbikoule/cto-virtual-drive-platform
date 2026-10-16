"""Unmeasured physical candidates. Python + NumPy only. Run this file to regenerate.

Constitutive 1D rod: T=cD*S-h*D, E=beta*D-h*S, u''+k**2*u=0.
RMS phasors, exp(+jwt). End electrodes, uniform electric displacement D.
At z=0 stress is zero; at z=L, A*T=-Zrad*j*w*u(L).
Positive elastic and parallel dielectric loss. No fitted target power/current.
"""
from pathlib import Path
import hashlib
import json
import math
import numpy as np

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / 'assumptions_20261016.json').read_text(encoding='utf-8'))
EPS0 = 8.8541878128e-12
SQ8 = 2 * math.sqrt(2)
GX, GW = np.polynomial.legendre.leggauss(96)


def bisect(fun, lo, hi):
    flo = fun(lo)
    if flo * fun(hi) > 0:
        raise ValueError('No bracket')
    for _ in range(70):
        mid = (lo + hi) / 2
        fm = fun(mid)
        if fm * flo > 0:
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def piston_z(f, d, rho=1050., sound_speed=1570.):
    """Mechanical force/velocity impedance of a uniform baffled circular piston.

    J1(2ka) via convergent power series (our 2ka<2.5); H1 via quadrature.
    """
    f = np.atleast_1d(f)
    x = 2 * (2 * np.pi * f / sound_speed) * (d / 2)
    if np.max(np.abs(x)) > 8:
        raise ValueError('Outside declared special-function evaluation range')
    term = x / 2
    j1 = term.copy()
    for m in range(1, 40):
        term = term * (-(x*x/4) / (m*(m+1)))
        j1 += term
    theta = (GX + 1) * np.pi / 4
    integral = np.sin(x[:, None] * np.sin(theta)) @ (GW*np.pi/4*np.cos(theta)**2)
    h1 = 2*x/np.pi * integral
    return rho * sound_speed * np.pi * d*d/4 * (1 - 2*j1/x + 1j*2*h1/x)


def element(d, length=None, material_q=None):
    mat = CFG['material']
    length = CFG['geometry']['length_m'] if length is None else length
    k2 = mat['k33']**2
    area = np.pi*d*d/4
    eps_d = EPS0 * mat['eps33T_relative'] * (1-k2)
    c_d = mat['Y33E_Pa'] / (1-k2)
    velocity = math.sqrt(c_d/mat['rho_kg_m3'])
    xs = bisect(lambda x: math.tan(x)/x-1/k2, 1e-7, np.pi/2-1e-7)
    el = dict(d=d, length=length, area=area, eps_d=eps_d, c_d=c_d,
              h=math.sqrt(k2*c_d/eps_d), beta=1/eps_d, velocity=velocity,
              c_clamped=eps_d*area/length, rho=mat['rho_kg_m3'],
              tan_delta=mat['tan_delta_vendor_low_frequency'],
              free_lossless_fs=velocity*xs/(np.pi*length),
              free_lossless_fp=velocity/(2*length), k2=k2)
    target = mat['Qm_vendor_typical'] if material_q is None else material_q
    el['assumed_free_Q'] = target
    el['elastic_eta'] = (1-k2)/target
    for _ in range(8):
        b = local_bvd(el, 0.)
        el['elastic_eta'] *= b['q']/target
    el['free_local_Q_check'] = local_bvd(el, 0.)['q']
    return el


def rod(f, el, load_scale=1., dielectric=True, elastic=True):
    f = np.atleast_1d(np.asarray(f, dtype=float))
    w = 2*np.pi*f
    cd = el['c_d']*(1 + 1j*(el['elastic_eta'] if elastic else 0.))
    v = np.sqrt(cd/el['rho'])
    k = w/v
    theta = k*el['length']
    zr = load_scale*piston_z(f, el['d'])
    # Unit D=1 C/m^2. u(z)=a*cos(kz)+b*sin(kz).
    b = el['h']/(cd*k)
    a = (el['h'] - (cd*k*np.cos(theta)+1j*w*zr/el['area']*np.sin(theta))*b) / (
        -cd*k*np.sin(theta)+1j*w*zr/el['area']*np.cos(theta))
    front = a*np.cos(theta) + b*np.sin(theta)
    voltage = el['beta']*el['length'] - el['h']*(front-a)
    y_electromech = 1j*w*el['area']/voltage
    gd = w*el['c_clamped']*el['tan_delta'] if dielectric else np.zeros_like(f)
    return dict(y=y_electromech+gd, y_electromech=y_electromech, gd=gd,
                a=a, b=b, front=front, voltage=voltage, k=k, cd=cd, zr=zr)


def local_bvd(el, scale):
    def zm(f):
        y = rod([f], el, scale, dielectric=False)['y'][0]
        return 1/(y-1j*2*np.pi*f*el['c_clamped'])
    f0 = el['free_lossless_fs']
    fs = bisect(lambda f: zm(f).imag, f0*.7, f0*1.1)
    rm = zm(fs).real
    df = max(1., fs*1e-6)
    lm = (zm(fs+df).imag-zm(fs-df).imag)/(2*df)/(4*np.pi)
    cm = 1/((2*np.pi*fs)**2*lm)
    return dict(c0=el['c_clamped'], rm=rm, lm=lm, cm=cm,
                fs=fs, q=2*np.pi*fs*lm/rm)


def unpack(x):
    c0, rm, fs, q = np.exp(x)
    w = 2*np.pi*fs
    lm = q*rm/w
    cm = 1/(w*q*rm)
    return dict(c0=float(c0), rm=float(rm), fs=float(fs), q=float(q),
                lm=float(lm), cm=float(cm),
                fp_bvd_lossless=float(fs*math.sqrt(1+cm/c0)),
                k_eff_bvd=float(math.sqrt(cm/(cm+c0))),
                motional_bandwidth_Hz=float(fs/q),
                amplitude_ringdown_tau_s=float(q/(np.pi*fs)))


def bvd_y(f, b):
    w = 2*np.pi*np.asarray(f)
    return 1j*w*b['c0']+1/(b['rm']+1j*(w*b['lm']-1/(w*b['cm'])))


def fit_bvd(el, scale=1.):
    f = np.linspace(*CFG['fit']['band_Hz'], CFG['fit']['samples'])
    ref = rod(f, el, scale)
    y = ref['y_electromech']
    denom = np.maximum(np.abs(y), .1*np.max(np.abs(y)))
    initial = local_bvd(el, scale)
    x = np.log([initial[key] for key in ('c0', 'rm', 'fs', 'q')])
    def residual(x):
        diff = (bvd_y(f, unpack(x))-y)/denom
        return np.concatenate((diff.real, diff.imag))
    damp = 1e-3
    for it in range(150):
        r = residual(x)
        h = 1e-5
        jac = np.column_stack([(residual(x+np.eye(4)[i]*h)-residual(x-np.eye(4)[i]*h))/(2*h) for i in range(4)])
        hessian = jac.T@jac
        step = np.linalg.solve(hessian+damp*np.diag(np.maximum(np.diag(hessian), 1e-9)), -jac.T@r)
        if np.max(np.abs(step)) > .4:
            step *= .4/np.max(np.abs(step))
        r2 = residual(x+step)
        if r2@r2 < r@r:
            x += step
            damp = max(damp/3, 1e-12)
            if np.max(np.abs(step)) < 1e-10:
                break
        else:
            damp *= 10
            if damp > 1e12:
                break
    b = unpack(x)
    yfit = bvd_y(f, b)+ref['gd']
    rel_z = np.abs(1/yfit-1/ref['y'])/np.abs(1/ref['y'])
    b['fit'] = dict(iterations=it+1, band_Hz=CFG['fit']['band_Hz'],
                   max_relative_Z_error=float(np.max(rel_z)),
                   relative_Y_L2_error=float(np.linalg.norm(yfit-ref['y'])/np.linalg.norm(ref['y'])),
                   max_relative_Z_error_without_dielectric=float(np.max(np.abs(1/bvd_y(f,b)-1/ref['y'])/np.abs(1/ref['y']))),
                   passes_5percent_gate=bool(np.max(rel_z)<CFG['fit']['acceptance_max_relative_impedance_error']))
    return b


def one_point(f, el, b, vpp=100., current_limit=None, scale=1.):
    y = rod([f], el, scale)['y'][0]
    v = vpp/SQ8
    if current_limit is not None:
        v = min(v, current_limit/abs(y))
    i = v*y
    vs = v+50*i
    return dict(f_Hz=float(f), port_Vpp=float(v*SQ8), ceramic_Arms=float(abs(i)),
                amplifier_Arms=float(abs(i)), port_P_W=float(v*v*y.real),
                port_phase_deg=float(-np.angle(y,deg=True)), power_factor=float(y.real/abs(y)),
                required_Thevenin_Vpp=float(abs(vs)*SQ8),
                source_50ohm_loss_W=float(50*abs(i)**2),
                bvd_port_P_W=float(v*v*(bvd_y([f],b)[0].real+2*np.pi*f*el['c_clamped']*el['tan_delta'])))


def optimize(el, b, vpp, ilim, scale=1.):
    f = np.arange(800000.,1000000.1,25.)
    r = rod(f, el, scale)
    y = r['y']
    vmax = np.minimum(vpp/SQ8, ilim/np.abs(y))
    p = vmax*vmax*y.real
    i = int(np.argmax(p))
    out = one_point(f[i],el,b,vpp,ilim,scale)
    out['binding_constraint'] = 'current' if ilim/abs(y[i]) < vpp/SQ8 else 'voltage'
    out['front_displacement_peak_m'] = float(np.sqrt(2)*vmax[i]*abs(r['front'][i]/r['voltage'][i]))
    out['front_velocity_rms_m_s'] = float(2*np.pi*f[i]*vmax[i]*abs(r['front'][i]/r['voltage'][i]))
    out['model_front_radiation_P_W'] = float(r['zr'][i].real*out['front_velocity_rms_m_s']**2)
    return out


def verify(el):
    f = np.linspace(8e5, 1e6, 161)
    w = 2*np.pi*f
    r = rod(f, el, 0., dielectric=False, elastic=False)
    x = w*el['length']/(2*el['velocity'])
    z_free = (1-el['k2']*np.tan(x)/x)/(1j*w*el['c_clamped'])
    err_free = np.max(np.abs(1/r['y']-z_free)/np.maximum(abs(z_free),1.))
    r = rod(f, el, 1.)
    zcoord=(GX+1)*el['length']/2
    strain=r['k'][:,None]*(-r['a'][:,None]*np.sin(r['k'][:,None]*zcoord)+r['b'][:,None]*np.cos(r['k'][:,None]*zcoord))
    p_elastic=w*el['area']*r['cd'].imag*(np.abs(strain)**2 @ (GW*el['length']/2))/np.abs(r['voltage'])**2
    p_rad=r['zr'].real*np.abs(1j*w*r['front']/r['voltage'])**2
    balance=np.max(np.abs(p_elastic+p_rad+r['gd']-r['y'].real)/r['y'].real)
    # Independent Mason T-network implementation of the same continuum.
    vc=np.sqrt(r['cd']/el['rho']); zc=el['rho']*vc*el['area']; theta=w*el['length']/vc
    n2=el['k2']*el['c_d']*el['area']*el['c_clamped']/el['length']
    zs=1j*zc*np.tan(theta/2); zp=zc/(1j*np.sin(theta))
    zmechanical=zp+(zs+r['zr'])*zs/(2*zs+r['zr'])
    ymason=1j*w*el['c_clamped']+1/(-1/(1j*w*el['c_clamped'])+zmechanical/n2)+r['gd']
    err_mason=np.max(np.abs(ymason-r['y'])/np.abs(r['y']))
    assert err_free<1e-9 and balance<1e-8 and err_mason<1e-9
    assert np.all(r['y'].real > 0)
    return dict(free_analytic_relative_error=float(err_free), power_balance_relative_error=float(balance),
                independent_mason_relative_error=float(err_mason), passive=True)


def main():
    candidates=[]
    for d in CFG['geometry']['diameters_m']:
        el=element(d)
        b=fit_bvd(el)
        checks=verify(el)
        assert b['fit']['passes_5percent_gate']
        cases={f'V{v}_I{int(i*1000)}mA':optimize(el,b,v,i) for v,i in [(100, .004),(100,.005),(160,.005)]}
        item=dict(id=f'APC880_D{d*1000:.1f}_L1.8_front_BMF', status='unmeasured_model_candidate',
                  element=el,bvd=b,dielectric_conductance=dict(formula='G(f)=2*pi*f*C_clamped*tan_delta',
                  C_clamped_F=el['c_clamped'],tan_delta=el['tan_delta']),
                  points=dict(at_900k_100Vpp=one_point(900000,el,b),at_fs_100Vpp=one_point(b['fs'],el,b)),
                  constrained_optima=cases, verification=checks)
        item['load_sensitivity']=[]
        for scale in CFG['boundary']['radiation_load_multipliers_for_sensitivity']:
            bs=fit_bvd(el,scale)
            item['load_sensitivity'].append(dict(scale=scale,bvd=bs,normal=optimize(el,bs,100,.004,scale)))
        candidates.append(item)
    # Independently declared material-loss/length perturbations of primary geometry.
    sensitivity=[]
    for name, length, qmat in [('length_minus5pct',.0018*.95,1000),('length_plus5pct',.0018*1.05,1000),
                               ('free_Q_500',.0018,500),('free_Q_1500',.0018,1500)]:
        el=element(.0005,length,qmat); b=fit_bvd(el)
        sensitivity.append(dict(name=name,element=el,bvd=b,normal=optimize(el,b,100,.004)))
    out=dict(schema_version=1,date='2026-10-16',purpose=CFG['purpose'],
             assumptions_file='assumptions_20261016.json',
             assumptions_sha256=hashlib.sha256((HERE/'assumptions_20261016.json').read_bytes()).hexdigest(),
             script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             power_target_W=None,candidates=candidates,primary_sensitivity=sensitivity)
    (HERE/'candidate_parameters.json').write_text(json.dumps(out,indent=2,ensure_ascii=False),encoding='utf-8')
    for c in candidates:
        b=c['bvd']; n=c['constrained_optima']['V100_I4mA']; p=c['points']['at_fs_100Vpp']
        print(c['id'])
        print('BVD:',json.dumps(b,ensure_ascii=False))
        print('100Vpp at fs: I=%.5f mA, P=%.5f mW'%(p['ceramic_Arms']*1e3,p['port_P_W']*1e3))
        print('Normal optimum:',json.dumps(n,ensure_ascii=False))
        print('Checks:',json.dumps(c['verification']))
    return out


if __name__=='__main__':
    main()
