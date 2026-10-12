"""Independent bare-BVD feature fitting experiment; never writes active model.

Parameters: Rm [ohm], Lm [H], Cm [F], C0 [F]. phim means MAXIMUM
impedance angle, not the most negative angle. fS/fP are impedance extrema,
not the theoretical motional series/parallel resonance definitions.
"""
from __future__ import annotations
import numpy as np
from numpy.polynomial import Polynomial as Poly
from scipy.optimize import brentq, least_squares

KEYS = ['ZS', 'fS', 'ZP', 'fP', 'phim', 'fphim']
PARAMS = ['Rm_ohm', 'Lm_H', 'Cm_F', 'C0_F']
# Transcribed from the preserved Janů Table 4 audit, DOI 10.1016/j.ultras.2020.106341.
MEASURED = np.array([1100., 39624., 3277., 40850., -25.6, 40292.])
PUBLISHED = {
    'E5061B': ([1323., .1359, 1.1726e-10, 2.7005e-9], [872.,39434.,2402.,41147.,-32.1,40290.]),
    'Equations': ([908., .0915, 1.7634e-10, 2.8048e-9], [697.,39252.,2771.,41203.,-14.3,40227.]),
    'Iteration': ([1330., .2300, 6.9000e-11, 2.2700e-9], [947.,39709.,3156.,40790.,-23.6,40250.]),
}

def impedance(f, p):
    r, l, c, c0 = p
    w = 2*np.pi*np.asarray(f)
    zm = r + 1j*(w*l - 1/(w*c))
    return 1/(1/zm + 1j*w*c0)

def logz_derivative(f, p):
    r, l, c, c0 = p
    zm = r + 1j*(2*np.pi*f*l - 1/(2*np.pi*f*c))
    dzm = 1j*(2*np.pi*l + 1/(2*np.pi*c*f*f))
    return -(-dzm/zm**2 + 1j*2*np.pi*c0)/(1/zm + 1j*2*np.pi*f*c0)

def features(p, window=(36000.,44000.), mode='continuous', details=False):
    p = np.asarray(p, float)
    if np.any(~np.isfinite(p)) or np.any(p <= 0):
        raise ValueError('finite positive circuit parameters required')
    lo, hi = window
    if mode == 'grid':
        f = np.arange(lo, hi, .5)
        z = impedance(f, p)
        ii = [np.argmin(abs(z)), np.argmax(abs(z)), np.argmax(np.angle(z))]
        ff = f[ii]
    else:
        r, l, c, c0 = p
        fs = 1/(2*np.pi*np.sqrt(l*c))
        q, ratio = 2*np.pi*fs*l/r, c0/c
        # With x=(f/fs)^2, |Z/R|^2 = Q^2*N(x)/D(x).
        # N=x^2+(1/Q^2-2)x+1; D=x*((1+r-r*x)^2+r^2*x/Q^2).
        n = Poly([1., 1/q**2-2, 1.])
        d = Poly([0.,1.])* (Poly([1+ratio,-ratio])**2 + Poly([0.,ratio**2/q**2]))
        roots = (n.deriv()*d-n*d.deriv()).roots()
        candidates = sorted(fs*np.sqrt(z.real) for z in roots
                            if abs(z.imag)<1e-7 and z.real>0)
        # Polynomial roots only bracket extrema. Refine using the direct complex
        # derivative, avoiding subtractive cancellation in the quartic near Q=800.
        stationary = []
        for i, guess in enumerate(candidates):
            if not lo < guess < hi:
                continue
            left = max(lo, (candidates[i-1]+guess)/2 if i else lo)
            right = min(hi, (guess+candidates[i+1])/2 if i+1<len(candidates) else hi)
            fn = lambda f: float(logz_derivative(f,p).real)
            if fn(left)*fn(right) < 0:
                stationary.append(brentq(fn,left,right,xtol=1e-8,rtol=1e-14))
        fc = np.array([lo, *stationary, hi])
        zc = impedance(fc,p)
        # phase = atan(Q*((1+2r)t-(1+r)/t-r*t^3) - r*t/Q).
        # d phase/dt = 0 gives 3r*x^2-(1+2r-r/Q^2)*x-(1+r)=0.
        b = 1+2*ratio-ratio/q**2
        disc = np.hypot(b,np.sqrt(12*ratio*(1+ratio)))
        xp = ((b+disc)/(6*ratio) if b>=0 else 2*(1+ratio)/(disc-b))
        phi_freqs = np.array([lo, np.clip(fs*np.sqrt(xp),lo,hi), hi])
        ff = np.array([fc[np.argmin(abs(zc))], fc[np.argmax(abs(zc))],
                       phi_freqs[np.argmax(np.angle(impedance(phi_freqs,p)))]] )
    zz = impedance(ff,p)
    result = np.array([abs(zz[0]), ff[0], abs(zz[1]), ff[1], np.angle(zz[2],deg=True), ff[2]])
    info = {'boundary_features': [KEYS[k] for k in (1,3,5)
                                  if result[k]<=lo+1e-6 or result[k]>=hi-(.5 if mode=='grid' else 1e-6)]}
    return (result, info) if details else result

def seed_from_features(target=MEASURED, c0=2.5e-9):
    cm = c0*((target[3]/target[1])**2-1)
    return np.array([target[0], 1/((2*np.pi*target[1])**2*cm), cm, c0])

def scales(target, choice='relative'):
    out = np.abs(target).copy()
    if choice == 'feature_spacing':
        out[[1,3,5]] = target[3]-target[1]
    if np.any(out<=0):
        raise ValueError('nonzero residual scales required')
    return out

def jacobian(fun, x, h=1e-5):
    eye = np.eye(len(x))*h
    return np.column_stack([(fun(x+e)-fun(x-e))/(2*h) for e in eye])

def fit(start, target, window=(36000.,44000.), mode='continuous', scale='relative', central=True):
    scale_values = scales(target,scale)
    fun = lambda x: (features(np.exp(x),window,mode)-target)/scale_values
    answer = least_squares(fun,np.log(start),jac=(lambda x: jacobian(fun,x)) if central else '2-point',
                           max_nfev=400, xtol=1e-12,ftol=1e-12,gtol=1e-12, x_scale=1.)
    p = np.exp(answer.x)
    f, info = features(p,window,mode,details=True)
    j = jacobian(fun,answer.x)
    sv = np.linalg.svd(j,compute_uv=False)
    return dict(start=list(start),parameters=p.tolist(), features=f.tolist(),
                percent_errors=(100*np.abs((f-target)/target)).tolist(),
                signed_residuals=((f-target)/scale_values).tolist(), scales=scale_values.tolist(),
                cost=float(answer.cost), solver_success=bool(answer.success), message=answer.message,
                nfev=answer.nfev, valid_interior=not info['boundary_features'], **info,
                jacobian=j.tolist(),singular_values=sv.tolist(),rank=int(np.linalg.matrix_rank(j)),
                condition=float(sv[0]/sv[-1]))

def starts(seed, count=12, random_seed=20261006):
    # Perturb R,L,C0 independently but constrain initial fs to +/-1.5%, so all
    # starts actually probe the same measured band. This is not a global search.
    rng = np.random.default_rng(random_seed)
    out = [np.asarray(seed,float)]
    for _ in range(count-1):
        a,b,d = np.exp(rng.uniform(-.5,.5,3))
        freq_factor = np.exp(rng.uniform(-.015,.015))
        out.append(np.asarray(seed)*[a,b,1/(b*freq_factor**2),d])
    return out
