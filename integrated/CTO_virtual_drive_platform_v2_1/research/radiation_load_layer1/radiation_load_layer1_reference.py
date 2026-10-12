#!/usr/bin/env python3
"""第一层负载参数化的参考实现与全部数字的复算。

只读：导入冻结的活动模型读取基线 BVD 与电学响应，不写入 `workspace/`，不落盘。

    python3 review/radiation_load_layer1_reference.py
    python3 review/radiation_load_layer1_reference.py --radius-mm 1.5
    python3 review/radiation_load_layer1_reference.py --self-check-only

本文件是 `review/14_第一层负载参数化_给Codex的实施指导_2026-09-18.md` 的参考实现。
文档第 3、4、5、6、7、8、9、10 节出现的每一个数字都由本脚本算出。

运行期只依赖 numpy。SciPy 与 scipy.integrate 仅在 `--cross-check` 的独立核对里使用，
是测试用的第三方对照，不是运行依赖；不带该开关时本脚本不 import scipy。

2026-09-19 第二轮外部审查（Codex）后的重写，处置见
`review/15_对第一层负载参数化审查的处置_2026-09-19.md`。最重要的一条：
原版用朴素交替级数求 Struve H1，在 x≳30 起严重失准、x≈49 处给出 −3934（真值 0.638），
而当时的自检只验 x≤8 的精度与若干点的正号，因此打印「全部断言通过」却输出了错误结果。
现改为全域稳定的积分求值 + 全域精度断言 + 定义域守卫。

2026-09-22：修正自洽模式辐射电阻的求值频率归一化；Q 分量从定义直接计算。
冻结模式不变。自洽 Q 是局部常参数 RLC 等效量，不是完整频变模型的带宽 Q。
独立物理折算回归见 test_radiation_load_audit_regression.py。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = REPO / 'workspace/outputs/v2_self_consistent_rebuild/active_stage3_5'

# --------------------------------------------------------------------------
# 声明常数。全部是声明值，不是实测值。
# --------------------------------------------------------------------------
RHO_PZT = 7500.0          # kg/m^3，硬 PZT 体密度的典型值
C_D = 4340.0              # m/s，厚度模式声速。半波厚度 L = C_D/(2 fs)
PISTON_RADIUS_M = 0.5e-3  # m，端面半径。**必须做敏感性扫描**，见 report() 第 6 节

MEDIA = {                 # name -> (rho0 [kg/m^3], c0 [m/s])
    'air':    (1.2, 343.0),
    'blood':  (1060.0, 1570.0),
    'calcif': (1900.0, 3600.0),
}

# 特殊函数的已验证定义域。超出即拒绝求值，不外推。
MAX_VALIDATED_2KA = 400.0
# 本脚本自检要求的特殊函数绝对精度（对照 scipy 与独立自适应积分）。
SPECIAL_FUNCTION_ABS_TOL = 1e-10

# A&S 表 12.1 / DLMF 11.5 的 H1 参考值，用于独立于 scipy 的定点校验
STRUVE_H1_REFERENCE = {1.0: 0.198457, 3.0: 1.020110, 5.0: 0.807812,
                       33.0: 0.541423, 49.459476178964670: 0.638358}


# ==========================================================================
# 1. 特殊函数：numpy-only，全域数值稳定
# ==========================================================================
_LEGENDRE_CACHE: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def _legendre(n: int) -> tuple[np.ndarray, np.ndarray]:
    if n not in _LEGENDRE_CACHE:
        _LEGENDRE_CACHE[n] = np.polynomial.legendre.leggauss(n)
    return _LEGENDRE_CACHE[n]


def _node_count(x: float) -> int:
    """被积函数在区间上振荡约 x/π 次，节点数随 x 线性增长即可。

    经验证：n = 2·ceil(x) + 64 在 0 < x ≤ 400 上给出
    |ΔH1| ≤ 2.4e-12、|ΔJ1| ≤ 5.3e-15（对照 scipy）。
    """
    return int(min(4096, max(64, 2*math.ceil(x) + 64)))


def _check_domain(x: float) -> float:
    if not math.isfinite(x):
        raise ValueError(f'2ka 必须是有限值，得到 {x!r}')
    if x < 0.0:
        raise ValueError(f'2ka 必须非负，得到 {x!r}')
    if x > MAX_VALIDATED_2KA:
        raise ValueError(
            f'2ka={x:.6g} 超出已验证定义域 (0, {MAX_VALIDATED_2KA}]；'
            '不做外推。要扩大范围请先扩展 verify_special_functions() 的验证网格。')
    return x


def struve_h1(x: float) -> float:
    """一阶 Struve 函数，用 DLMF 11.5.1 的积分表示求值。

        H1(z) = (2z/π) ∫_0^{π/2} cos²θ · sin(z·sinθ) dθ

    被积函数有界光滑、不含相消，因此在全域数值稳定。
    这取代了原来的朴素交替级数——那个级数数学上正确、双精度下不可用：
    见 struve_h1_naive_series 的说明与 verify_special_functions 的反例断言。
    """
    x = _check_domain(x)
    if x == 0.0:
        return 0.0
    t, w = _legendre(_node_count(x))
    theta = (t + 1.0) * (math.pi / 4.0)                 # 映射到 [0, π/2]
    return float((2.0*x/math.pi) * (math.pi/4.0) *
                 np.sum(w * np.cos(theta)**2 * np.sin(x*np.sin(theta))))


def bessel_j1(x: float) -> float:
    """一阶第一类 Bessel 函数，用 Bessel 积分表示求值。

        J1(z) = (1/π) ∫_0^{π} cos(θ − z·sinθ) dθ
    """
    x = _check_domain(x)
    if x == 0.0:
        return 0.0
    t, w = _legendre(_node_count(x))
    theta = (t + 1.0) * (math.pi / 2.0)                 # 映射到 [0, π]
    return float((1.0/math.pi) * (math.pi/2.0) *
                 np.sum(w * np.cos(theta - x*np.sin(theta))))


def struve_h1_naive_series(x: float, terms: int = 200) -> float:
    """**反例，不要用于计算。** 保留它是为了让失效可被测试固定下来。

        H1(z) = Σ_k (−1)^k (z/2)^(2k+2) / (Γ(k+3/2)·Γ(k+5/2))

    级数本身与 DLMF 11.2.1 一致，但双精度直接求和在 x 增大时被交替大项的
    相消摧毁：x=33 相对误差已达 2.3e-3，x=40 达 0.89，x≈49.46 给出 −3934
    （真值 0.638），且相邻浮点数给出 +2555。**数学上收敛不等于浮点下可用。**
    """
    total = 0.0
    for k in range(terms):
        try:
            term = ((-1.0)**k) * (x/2.0)**(2*k+2) / (math.gamma(k+1.5)*math.gamma(k+2.5))
        except OverflowError:
            break
        total += term
        if k > 5 and abs(term) < 1e-18:
            break
    return total


def piston_R1(x: float) -> float:
    """活塞辐射阻函数 R1(x) = 1 − 2·J1(x)/x。

    小 x 时 2J1(x)/x → 1，直接相减会损失有效位（x=1e-6 时直接式相对误差 8e-5），
    因此小 x 走等价级数 R1(x) = Σ_{m≥1} (−1)^{m+1}/(m!(m+1)!)·(x/2)^{2m}。
    """
    x = _check_domain(x)
    if x == 0.0:
        return 0.0
    if x < 1.0:
        total, term = 0.0, None
        for m in range(1, 60):
            term = ((-1.0)**(m+1)) / (math.factorial(m)*math.factorial(m+1)) * (x/2.0)**(2*m)
            total += term
            if abs(term) < 1e-18*max(abs(total), 1e-300):
                break
        return total
    return 1.0 - 2.0*bessel_j1(x)/x


def piston_X1(x: float) -> float:
    """活塞辐射抗函数 X1(x) = 2·H1(x)/x。在 x>0 上恒正。"""
    x = _check_domain(x)
    return 0.0 if x == 0.0 else 2.0*struve_h1(x)/x


# ==========================================================================
# 2. 输入校验
# ==========================================================================
def _positive_finite(name: str, value: float, upper: float | None = None) -> float:
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f'{name} 必须是有限值，得到 {value!r}')
    if v <= 0.0:
        raise ValueError(f'{name} 必须为正，得到 {v!r}')
    if upper is not None and v > upper:
        raise ValueError(f'{name}={v!r} 超出支持范围 (0, {upper}]')
    return v


# ==========================================================================
# 3. 加载后的 BVD
# ==========================================================================
@dataclass(frozen=True)
class LoadPoint:
    """一个负载状态。字段名刻意区分「机械支路量」与「系统量」。"""
    medium: str
    contact: float
    two_ka: float
    radiation_evaluation_frequency_Hz: float   # Z_rad 实际求值所用频率
    radiation_frequency_mode: str              # 'frozen_at_unloaded_fs' | 'self_consistent'
    rm: float                                  # Rm' = Rm_internal + Rm_radiation
    rm_internal: float
    rm_radiation: float
    lm: float
    cm: float
    fs: float
    qm: float
    q_rad: float
    q_int_loaded: float
    # 常压端电压下、孤立机械支路的半功率全宽。**不是**系统功率 FWHM，
    # 后者受源、匹配、保护降幅共同影响，必须另行从 P(f) 提取。
    motional_constant_voltage_fwhm_Hz: float
    rm_ratio: float
    fs_shift_pct: float

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class Layer1:
    """把声负载折算到机械支路，再折算回 BVD。

    一维集总等效（Mason 简化）：机械支路的质量 m、刚度 k、阻尼 c 通过机电变比 φ
    映射到电学量：Lm = m/φ²，Cm = φ²/k，Rm = c/φ²。

    串联一个辐射阻抗 Z_rad = R_rad + jω·m_rad（力/速度，单位 kg/s）后：
        c → c + R_rad      m → m + m_rad      k 不变
    因此：
        Rm' = Rm·(1 + R_rad/c)      Lm' = Lm·(1 + m_rad/m)      Cm' = Cm
        fs' = 1/(2π√(Lm'·Cm))       Qm' = 2π·fs'·Lm'/Rm'

    **φ 在两个比值里约掉了**，所以第一层不需要压电材料常数。
    但 R_rad/c 与 m_rad/m 仍然需要绝对的质量 m 与端面面积 A：
        m = ρ_PZT·A·L/2   （半波厚度模式的集总有效质量，1/2 来自正弦模态）
        R_rad = ρ0·c0·A·R1(2ka)      m_rad = ρ0·c0·A·X1(2ka)/ω
    代进去之后 A 在比值里约掉，只剩下**通过 2ka 的依赖**：
        R_rad/(ω·m) = 2·ρ0·c0·R1(2ka)/(ω·ρ_PZT·L)
        m_rad/m     = 2·ρ0·c0·X1(2ka)/(ω·ρ_PZT·L)
    所以第一层真正需要的绝对量是 **L 与 ρ_PZT**；半径 a 只通过 2ka 进入，
    但那个依赖在 2ka≈1~4 时非常陡，不能当成可以随手固定的常数。

    **关于「现有 BVD 是未加载支路」这个前提：** 本项目没有实测阻抗，现有
    Rm、Lm 是否已经包含某种负载损耗并未经辨识确定。本类**假设**它们代表未加载
    的内部机械支路，再叠加假设的辐射负载。该假设不可反过来用来论证现有参数
    「就是」某只真实器件的空气状态；若原参数已含负载，这里会重复计入。
    """

    def __init__(self, bvd, rho_pzt=RHO_PZT, c_d=C_D, radius_m=PISTON_RADIUS_M):
        self.fs = _positive_finite('bvd.fs', bvd.fs)
        self.qm = _positive_finite('bvd.qm', bvd.qm)
        self.rm = _positive_finite('bvd.rm', bvd.rm)
        self.lm = _positive_finite('bvd.lm', bvd.lm)
        self.cm = _positive_finite('bvd.cm', bvd.cm)
        self.rho_pzt = _positive_finite('rho_pzt', rho_pzt, upper=3.0e4)
        self.c_d = _positive_finite('c_d', c_d, upper=2.0e4)
        self.radius = _positive_finite('radius_m', radius_m, upper=5.0e-2)
        self.omega = 2*math.pi*self.fs
        self.thickness = self.c_d/(2*self.fs)
        # 自洽性：模型自己的 Qm 必须等于 ω·Lm/Rm
        if abs(self.omega*self.lm/self.rm - self.qm) > 1e-6*self.qm:
            raise ValueError('输入 BVD 不自洽：ω·Lm/Rm ≠ Qm')
        fs_from_lc = 1.0/(2*math.pi*math.sqrt(self.lm*self.cm))
        if not math.isclose(fs_from_lc, self.fs, rel_tol=1e-9, abs_tol=0.0):
            raise ValueError('输入 BVD 不自洽：fs ≠ 1/(2π√(Lm·Cm))')
        # 定义域守卫：最刺耳的介质（声速最低）决定最大 2ka
        slowest = min(c0 for _, c0 in MEDIA.values())
        _check_domain(2.0*(self.omega/slowest)*self.radius)

    def effective_mass_kg(self) -> float:
        return self.rho_pzt*math.pi*self.radius**2*self.thickness/2

    def internal_damping_kg_per_s(self) -> float:
        return self.omega*self.effective_mass_kg()/self.qm

    def ratios(self, medium: str, frequency_Hz: float | None = None) -> tuple[float, float, float]:
        """返回 (R_rad/(ω·m), m_rad/m, 2ka)。两者都与端面面积 A 无关。

        frequency_Hz 是**辐射阻抗的求值频率**。默认冻结在未加载 fs 上，
        这是一个参考频率附近的常参数近似，不是整个频带内精确的频变辐射模型。
        """
        if medium not in MEDIA:
            raise ValueError(f'未登记的介质 {medium!r}，可用：{sorted(MEDIA)}')
        f = self.fs if frequency_Hz is None else _positive_finite('frequency_Hz', frequency_Hz)
        omega = 2*math.pi*f
        rho0, c0 = MEDIA[medium]
        x = _check_domain(2.0*(omega/c0)*self.radius)
        common = 2.0*rho0*c0/(omega*self.rho_pzt*self.thickness)
        return common*piston_R1(x), common*piston_X1(x), x

    def _mix(self, medium: str, contact: float, frequency_Hz: float | None):
        """部分覆盖：线性叠加介质与空气的辐射阻抗。**这是声明的一阶近似。**

        严格的活塞辐射函数假定整个端面均匀加载，部分覆盖不满足这一前提。
        """
        rr_m, mr_m, x = self.ratios(medium, frequency_Hz)
        rr_a, mr_a, _ = self.ratios('air', frequency_Hz)
        return (contact*rr_m + (1.0-contact)*rr_a,
                contact*mr_m + (1.0-contact)*mr_a, x)

    def load(self, medium: str, contact: float, qm_intrinsic: float | None = None,
             self_consistent: bool = False, max_iterations: int = 64,
             tolerance_Hz: float = 1e-6) -> LoadPoint:
        """接触比例 contact∈[0,1] 覆盖 medium，其余面积仍看空气。

        self_consistent=False（默认）：把 Z_rad 冻结在未加载 fs 上求值。
        self_consistent=True：迭代到 Z_rad 的求值频率与加载后的 fs' 一致。
        两者的差值由 report() 定量给出，不靠推测。
        """
        c = float(contact)
        if not math.isfinite(c) or not 0.0 <= c <= 1.0:
            raise ValueError(f'contact 必须落在 [0,1] 且有限，得到 {contact!r}')
        qi = self.qm if qm_intrinsic is None else _positive_finite('qm_intrinsic', qm_intrinsic)

        f_eval = self.fs
        mode = 'self_consistent' if self_consistent else 'frozen_at_unloaded_fs'
        for _ in range(max_iterations if self_consistent else 1):
            rr, mr, x = self._mix(medium, c, f_eval)
            fs_new = 1.0/(2*math.pi*math.sqrt(self.lm*(1.0+mr)*self.cm))
            if not self_consistent or abs(fs_new - f_eval) <= tolerance_Hz:
                f_eval = fs_new if self_consistent else f_eval
                break
            f_eval = fs_new
        else:
            raise RuntimeError('自洽辐射频率迭代未收敛')
        if self_consistent:
            rr, mr, x = self._mix(medium, c, f_eval)

        lm2 = self.lm*(1.0+mr)
        rm_internal = self.omega*self.lm/qi          # c/φ²，与负载无关
        # rr = R_rad(f_eval)/(omega_eval*m), not R_rad/(omega_unloaded*m).
        # Keeping omega_unloaded here overestimates R_rad by fs_unloaded/f_eval
        # in self-consistent mode; reciprocal-Q checks alone cannot detect it.
        omega_eval = 2*math.pi*f_eval
        rm_radiation = omega_eval*self.lm*rr          # R_rad/φ²，与 qi 无关
        rm2 = rm_internal + rm_radiation
        fs2 = 1.0/(2*math.pi*math.sqrt(lm2*self.cm))
        qm2 = 2*math.pi*fs2*lm2/rm2

        omega_loaded = 2*math.pi*fs2
        q_int_loaded = omega_loaded*lm2/rm_internal  # ω'm'/c，直接由定义计算
        q_rad = (omega_loaded*lm2/rm_radiation
                 if rm_radiation > 0 else float('inf'))  # ω'm'/R_rad
        reciprocal = 1.0/(1.0/q_int_loaded + 1.0/q_rad)
        if abs(reciprocal-qm2) > 1e-9*qm2:           # 倒数分解必须与直接计算相符
            raise AssertionError(f'倒数分解不闭合：{reciprocal} vs {qm2}')
        return LoadPoint(
            medium=medium, contact=c, two_ka=x,
            radiation_evaluation_frequency_Hz=f_eval, radiation_frequency_mode=mode,
            rm=rm2, rm_internal=rm_internal, rm_radiation=rm_radiation,
            lm=lm2, cm=self.cm, fs=fs2, qm=qm2,
            q_rad=q_rad, q_int_loaded=q_int_loaded,
            motional_constant_voltage_fwhm_Hz=fs2/qm2,
            rm_ratio=rm2/self.rm, fs_shift_pct=100*(fs2/self.fs-1.0))


# ==========================================================================
# 4. 特殊函数的全域验证
# ==========================================================================
def verify_special_functions(cross_check: bool = False) -> None:
    """定点校验 + 全域自洽；cross_check 时再对照 scipy 与独立自适应积分。"""
    print('== 1. 特殊函数自检')
    for z, ref in sorted(STRUVE_H1_REFERENCE.items()):
        got = struve_h1(z)
        assert abs(got-ref) < 1e-5, (z, got, ref)
        print(f'  H1({z:<20.14g}) = {got:>14.9f}   参考 {ref:.6f}   ✓')

    grid = np.concatenate([np.linspace(1e-8, 1.0, 60),
                           np.linspace(1.0, MAX_VALIDATED_2KA, 1200)])
    for x in grid:
        assert piston_X1(float(x)) > 0.0, f'X1({x}) 必须为正'
    print(f'  X1 在 (0, {MAX_VALIDATED_2KA}] 的 {len(grid)} 点网格上恒正 ⇒ 附加质量恒正')
    assert abs(piston_R1(1e-6) - 1e-12/8) < 1e-20, '小 x 极限 R1 ≈ x²/8'
    assert abs(piston_R1(400.0) - 1.0) < 2e-2, '大 x 极限 R1 → 1'
    print(f'  R1(1e-6)={piston_R1(1e-6):.6e}（≈x²/8）  R1(400)={piston_R1(400.0):.6f}（→1）')

    for bad, why in ((-1.0, '负值'), (float('nan'), 'NaN'),
                     (MAX_VALIDATED_2KA*1.001, '超域')):
        try:
            struve_h1(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'{why} 输入应当被拒绝')
    print('  定义域守卫：负值 / NaN / 超域 一律拒绝求值，不外推')

    naive_bad = struve_h1_naive_series(49.45947617896467)
    assert abs(naive_bad) > 100, '朴素级数的失效必须被测试固定下来'
    print(f'  反例固定：朴素级数 H1(49.4594761789647) = {naive_bad:.4f}，'
          f'稳定求值 = {struve_h1(49.45947617896467):.9f}')

    if not cross_check:
        print('  （加 --cross-check 可再对照 scipy 与独立自适应积分）')
        return
    from scipy.integrate import quad          # 测试用第三方对照，非运行依赖
    from scipy.special import j1 as sj1, struve as sstruve
    worst_h = worst_j = 0.0
    for x in grid:
        x = float(x)
        worst_h = max(worst_h, abs(struve_h1(x) - float(sstruve(1, x))))
        worst_j = max(worst_j, abs(bessel_j1(x) - float(sj1(x))))
    print(f'  对照 scipy（{len(grid)} 点）：max|ΔH1|={worst_h:.3e}  max|ΔJ1|={worst_j:.3e}')
    assert worst_h < SPECIAL_FUNCTION_ABS_TOL and worst_j < SPECIAL_FUNCTION_ABS_TOL
    for x in (33.0, 49.45947617896467, 400.0):
        val, _ = quad(lambda t: math.sqrt(1-t*t)*math.sin(x*t), 0, 1,
                      epsabs=1e-13, epsrel=1e-13, limit=400)
        independent = 2*x/math.pi*val
        assert abs(struve_h1(x)-independent) < 1e-9, (x, independent)
        print(f'  独立自适应积分 H1({x:<18.14g}) = {independent:.12f} ✓')


# ==========================================================================
# 5. 报告
# ==========================================================================
GRID = (('空气 全接触', 'air', 1.0), ('血液 25% 接触', 'blood', 0.25),
        ('血液 50% 接触', 'blood', 0.50), ('血液 全接触', 'blood', 1.0),
        ('钙化 50% 接触', 'calcif', 0.50), ('钙化 全接触', 'calcif', 1.0))


def _fwhm(freq: np.ndarray, power: np.ndarray) -> float | None:
    """从实际 P(f) 提取半功率全宽；区间内找不到交点就返回 None，不外推。"""
    peak = int(np.argmax(power))
    half = power[peak]/2
    left_idx = np.flatnonzero(power[:peak] <= half)
    right_idx = np.flatnonzero(power[peak+1:] <= half)
    if not len(left_idx) or not len(right_idx):
        return None
    i = int(left_idx[-1])
    j = peak + 1 + int(right_idx[0])
    left = freq[i] + (half-power[i])/(power[i+1]-power[i])*(freq[i+1]-freq[i])
    right = freq[j-1] + (half-power[j-1])/(power[j]-power[j-1])*(freq[j]-freq[j-1])
    return float(right-left)


def _format_fwhm(value: float | None) -> str:
    """Missing crossings are an explicit diagnostic, not a formatting error."""
    return 'N/A(区间内缺交点)' if value is None else f'{value:.1f}'


def report(bvd, radius_m=PISTON_RADIUS_M) -> dict:
    layer = Layer1(bvd, radius_m=radius_m)
    print(f'\n== 2. 基线与导出几何  (a={radius_m*1e3:.2f} mm)')
    print(f'  fs={layer.fs:.1f} Hz  Qm={layer.qm:.1f}  Rm={layer.rm:.3f} Ω  Lm={layer.lm:.6f} H')
    print(f'  L = c_D/(2fs) = {layer.thickness*1e3:.4f} mm    m = ρAL/2 = '
          f'{layer.effective_mass_kg()*1e6:.3f} mg')
    print(f'  c = ω·m/Qm = {layer.internal_damping_kg_per_s():.4e} kg/s')
    rho0, c0 = MEDIA['air']
    x_air = 2*(layer.omega/c0)*radius_m
    print(f'  空气 R_rad = ρ0c0·A·R1 = '
          f'{rho0*c0*math.pi*radius_m**2*piston_R1(x_air):.3e} kg/s')
    print(f'  辐射阻抗求值频率（冻结近似）= {layer.fs:.1f} Hz')

    print('\n== 3. 负载格点（相对未加载基线），含内部/辐射电阻拆分')
    print(f"{'工况':<16}{'2ka':>7}{'Rm(Ω)':>11}{'Rm_int':>9}{'Rm_rad':>11}{'Rm×':>7}"
          f"{'fs(Hz)':>11}{'fs偏移':>9}{'Qm':>8}{'支路FWHM':>10}")
    rows = {}
    for label, medium, contact in GRID:
        r = layer.load(medium, contact)
        rows[label] = r
        print(f'{label:<16}{r.two_ka:>7.3f}{r.rm:>11.1f}{r.rm_internal:>9.1f}'
              f'{r.rm_radiation:>11.1f}{r.rm_ratio:>7.1f}{r.fs:>11.1f}'
              f'{r.fs_shift_pct:>+8.2f}%{r.qm:>8.2f}'
              f'{r.motional_constant_voltage_fwhm_Hz:>10.0f}')

    nom = rows['血液 全接触']
    print('\n== 4. 以「血液 全接触」为假设比较原点（不更改历史主基准）')
    print(f"{'工况':<16}{'ΔRm':>10}{'Δfs':>10}{'Qm':>10}")
    for label, r in rows.items():
        print(f'{label:<16}{100*(r.rm/nom.rm-1):>+9.1f}%'
              f'{100*(r.fs/nom.fs-1):>+9.2f}%{r.qm:>10.2f}')

    print('\n== 5. 空气中：固有 Qm 决定一切（辐射可忽略）')
    print(f"{'固有Qm':>8}{'Q_total':>10}{'支路FWHM':>10}{'Q_rad':>12}{'Q_total≤Q_int':>14}")
    for q in (500, 800, 1000, 2000):
        r = layer.load('air', 1.0, qm_intrinsic=q)
        print(f'{q:>8}{r.qm:>10.2f}{r.motional_constant_voltage_fwhm_Hz:>10.1f}'
              f'{r.q_rad:>12.0f}{str(r.qm <= q):>14}')
    print('  注：Q_total ≤ Q_intrinsic 是本格点上的回归事实，不是无条件成立的物理定律。')
    print('      由 Q′/Q_i = √(1+m_r)/(1+Q_i·r_r) 可见，当 Q_i·r_r < √(1+m_r)−1 时 Q′ > Q_i。')

    print('\n== 6. 半径敏感性：2ka 落在 R1 的陡段，a 不是可随手固定的常数')
    for medium in ('blood', 'calcif'):
        rho0, c0 = MEDIA[medium]
        print(f'  --- {medium}  ρ0c0={rho0*c0/1e6:.3f} MRayl')
        for a_mm in (0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5):
            r = Layer1(bvd, radius_m=a_mm*1e-3).load(medium, 1.0)
            print(f'    a={a_mm:4.2f} mm  2ka={r.two_ka:6.3f}  R1={piston_R1(r.two_ka):.4f}'
                  f'  Qm={r.qm:8.2f}  支路FWHM={r.motional_constant_voltage_fwhm_Hz:8.0f} Hz'
                  f'  Δfs={r.fs_shift_pct:+6.2f}%')

    print('\n== 7. 厚度模式声速敏感性（a=0.5 mm，血液全接触）')
    for cd in (3800.0, 4100.0, 4340.0, 4600.0, 5000.0):
        lay = Layer1(bvd, c_d=cd, radius_m=0.5e-3)
        r = lay.load('blood', 1.0)
        print(f'  c_D={cd:6.0f} m/s  L={lay.thickness*1e3:.4f} mm  Qm={r.qm:7.2f}'
              f'  支路FWHM={r.motional_constant_voltage_fwhm_Hz:8.0f} Hz')

    print('\n== 8. 冻结辐射频率 vs 自洽辐射频率（局部常参数等效差异）')
    print(f"{'工况':<16}{'冻结fs(Hz)':>12}{'自洽fs(Hz)':>12}{'Δfs(Hz)':>10}"
          f"{'冻结Qm':>9}{'自洽Qm':>9}{'ΔQm%':>8}")
    for label, medium, contact in GRID:
        a = layer.load(medium, contact)
        b = layer.load(medium, contact, self_consistent=True)
        print(f'{label:<16}{a.fs:>12.1f}{b.fs:>12.1f}{b.fs-a.fs:>10.1f}'
              f'{a.qm:>9.2f}{b.qm:>9.2f}{100*(b.qm/a.qm-1):>+7.2f}%')
    print('  Q 为局部常参数 RLC 等效值，不等于完整频变辐射模型的系统带宽 Q。')
    print('  是否可接受需预先定义误差容限；本表不证明闭环验收改善。')
    return rows


def report_electrical(model, base_scenario, layer: Layer1) -> None:
    """第八节的电学表，在本脚本内计算，使文档的可追溯性陈述成立。"""
    from dataclasses import replace
    print('\n== 9. 电学后果：可交付功率与端口电压解析上界')
    print('  解析上界：机械支路两端为 V_port 时 P = V²R/(R²+X²) ≤ V_rms²/R = V_pp²/(8R)，')
    print('  此上界与匹配元件如何选择无关，但达到端口功率上界不等于输入匹配良好。')
    f = np.arange(800000., 1000000.+100., 100.)
    fw = np.arange(500000., 1500000.+10., 10.)   # 仅用于找半高交点，未改控制器搜索边界
    print(f"\n{'工况':<14}{'峰频Hz':>9}{'安全峰W':>11}{'幅度':>7}{'Vpp':>8}{'mArms':>8}"
          f"{'限幅':>8}{'130Vpp上界W':>13}{'达上界%':>9}{'170mW所需Vpp':>13}"
          f"{'|Gamma|代理':>14}{'Pport/Psource%':>16}")
    grid = [('未加载基线', None, None)] + [(lbl, m, c) for lbl, m, c in GRID
                                       if (m, c) in (('air', 1.0), ('blood', 0.25),
                                                     ('blood', 1.0), ('calcif', 1.0))]
    rows = []
    for label, medium, contact in grid:
        if medium is None:
            bvd, lp = base_scenario.bvd, None
        else:
            lp = layer.load(medium, contact)
            bvd = replace(base_scenario.bvd, rm=lp.rm, lm=lp.lm, cm=lp.cm,
                          fs=lp.fs, qm=lp.qm)
        sc = replace(base_scenario, bvd=bvd)
        unit = model.response(f, sc)
        amp = model.allowed_amplitude(f, sc, use_soft_limits=True)
        power = unit['p_rm_W']*amp*amp
        i = int(np.argmax(power))
        bound = 130.0**2/(8*bvd.rm)
        v_at_peak, i_at_peak = unit['vport_vpp'][i]*amp[i], unit['iport_irms_A'][i]*amp[i]
        if amp[i] >= 1.0 - 1e-12:
            limiter = '源幅度1'
        elif 130.0/unit['vport_vpp'][i] <= 0.0055/unit['iport_irms_A'][i]:
            limiter = '电压'
        else:
            limiter = '电流'
        print(f'{label:<14}{f[i]:>9.0f}{power[i]:>11.5f}{amp[i]:>7.3f}{v_at_peak:>8.2f}'
              f'{i_at_peak*1000:>8.3f}{limiter:>8}{bound:>13.5f}'
              f'{100*power[i]/bound:>8.2f}%{math.sqrt(8*0.170*bvd.rm):>13.2f}'
              f'{unit["gamma"][i]:>14.4f}'
              f'{100*unit["p_port_W"][i]/unit["p_source_W"][i]:>16.2f}')
        assert power[i] <= bound*(1+1e-9), '实得功率不得超过解析上界'
        rows.append((label, sc, bvd, lp, power[i]))
    print('  电学效率含戴维南源电阻损耗；Gamma 仅为输入反射代理，均非声学效率或实测量。')

    print('\n== 10. 支路带宽 vs 系统带宽（F4：两者定义不同，不可互换）')
    print(f"{'工况':<14}{'fs/Qm':>10}{'未保护系统FWHM':>16}{'软限安全功率FWHM':>18}")
    for label, sc, bvd, lp, _ in rows:
        print(f'{label:<14}{bvd.fs/bvd.qm:>10.1f}'
              f'{_format_fwhm(_fwhm(fw, model.response(fw, sc)["p_rm_W"])):>16}'
              f'{_format_fwhm(_fwhm(fw, model.safe_power(fw, sc))):>18}')

    print('\n== 11. 功率含义拆分（F7：Rm′ 合并了内部阻尼与辐射阻）')
    print(f"{'工况':<14}{'总支路W':>11}{'内部耗散W':>12}{'辐射分量W':>12}{'辐射占比':>9}")
    for label, sc, bvd, lp, peak in rows:
        if lp is None:
            print(f'{label:<14}{peak:>11.6f}{peak:>12.6f}{0.0:>12.6f}{0.0:>8.1f}%')
            continue
        internal = peak*lp.rm_internal/lp.rm
        radiated = peak*lp.rm_radiation/lp.rm
        print(f'{label:<14}{peak:>11.6f}{internal:>12.6f}{radiated:>12.6f}'
              f'{100*radiated/peak:>8.1f}%')
    print('  「辐射分量」只是该理想负载模型内的功率划分，')
    print('  **不是经声场或水听器验证的声功率，更不是靶区有效治疗功率**。')


def report_registry(layer: Layer1, scenario_map) -> None:
    print('\n== 12. 标签数 / 登记数 / 唯一状态数（F6）')
    labels = [(m, eta) for m in MEDIA for eta in (0.0, 0.25, 0.5, 0.75, 1.0)]
    groups: list[dict] = []
    for medium, eta in labels:
        r = layer.load(medium, eta)
        key = (r.rm, r.lm, r.cm)
        for g in groups:
            if all(abs(a-b) <= 1e-13*max(abs(a), abs(b), 1e-300)
                   for a, b in zip(key, g['key'])):
                g['labels'].append((medium, eta))
                break
        else:
            groups.append({'key': key, 'labels': [(medium, eta)]})
    print(f'  标签 {len(labels)} 个 → 去掉三介质共有的 η=0 重复后登记 '
          f'{len(labels)-2} 项 → **唯一 BVD 状态 {len(groups)} 个**')
    for g in groups:
        if len(g['labels']) > 1:
            print(f"    别名组（Rm={g['key'][0]:.1f}）：{g['labels']}")
    print('  介质为空气时任何 η 都是同一负载。不得把重复状态当成独立覆盖证据，')
    print('  也不得在不说明权重的情况下把它们重复计入平均指标。')

    base = scenario_map['CASE_000_BASELINE'].bvd
    print('\n== 13. 现有登记表覆盖了什么（历史 34 场景，身份与结论不追溯改名）')
    for k, v in scenario_map.items():
        if k.startswith('CASE_QM_'):
            print(f'  {k:<16} Qm={v.bvd.qm:>6.1f}  支路FWHM={v.bvd.fs/v.bvd.qm:>8.1f} Hz')
    rm = [(k, v.bvd.rm/base.rm) for k, v in scenario_map.items() if k.startswith('CASE_RM_')]
    print('  Rm 族：' + '，'.join(f'{k.split("_")[-1]} ×{r:.2f}' for k, r in rm) + '（只增不减）')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default=str(DEFAULT_MODEL_DIR),
                    help='含 model_v2_1.py 的目录（默认用本仓库冻结的活动模型）')
    ap.add_argument('--radius-mm', type=float, default=PISTON_RADIUS_M*1e3)
    ap.add_argument('--cross-check', action='store_true',
                    help='额外用 scipy 与独立自适应积分对照特殊函数（测试用）')
    ap.add_argument('--self-check-only', action='store_true',
                    help='只跑特殊函数自检，不导入模型')
    args = ap.parse_args()

    verify_special_functions(cross_check=args.cross_check)
    if args.self_check_only:
        print('\n自检通过。本脚本未写入任何目录。')
        return 0

    model_dir = Path(args.model).resolve()
    if not (model_dir / 'model_v2_1.py').is_file():
        print(f'找不到 {model_dir}/model_v2_1.py', file=sys.stderr)
        return 2
    sys.path.insert(0, str(model_dir))
    import model_v2_1 as model            # noqa: E402
    scenarios = model.scenario_map()
    base = scenarios['CASE_000_BASELINE']

    report(base.bvd, radius_m=args.radius_mm*1e-3)
    layer = Layer1(base.bvd, radius_m=args.radius_mm*1e-3)
    report_electrical(model, base, layer)
    report_registry(layer, scenarios)
    print('\n全部断言通过。本脚本未写入任何目录。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
