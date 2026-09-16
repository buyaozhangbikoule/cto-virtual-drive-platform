"""BVD 参数三份副本的一致性回归测试。

Lm/Cm 在三处各存一份:
  1. bvd_parameters.json 的 Qm 推导而来(模型实际使用的)
  2. stage2_匹配设计参数.json 的 Lm_H/Cm_F 字段(历史设计产物)
  3. stage2 LTspice 网表里的字面值(交叉验证证据的来源)

三者此前一致仅因同源生成,没有任何机制保证。本文件把这个不变量固化下来:
改了 Qm 而没有重新生成网表,测试立即失败,而不是等到有人发现
Python/LTspice 的 1.4e-7 结论已经悄悄失效。

只读测试:不写入任何结果目录,不调用会覆盖历史批次的 main()。

    pytest workspace/CTO_virtual_drive_platform_v2_1/tests/test_bvd_parameter_consistency.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
REBUILD = REPO / "workspace" / "outputs" / "v2_self_consistent_rebuild"
ACTIVE = REBUILD / "active_stage3_5"
STAGE2 = REBUILD / "stage2_matching"
DESIGN_JSON = STAGE2 / "stage2_匹配设计参数.json"
NETLIST = STAGE2 / "V2_1_MATCH_ACTIVE_LOSSY.cir"
RAW = STAGE2 / "V2_1_MATCH_ACTIVE_LOSSY.raw"

# 网表元件 -> 该值在模型里的来源。覆盖全部 9 个元件,没有遗漏。
NETLIST_TO_MODEL = {
    "C0": lambda m: m.BASE_BVD.c0,
    "Rm": lambda m: m.BASE_BVD.rm,
    "Lm": lambda m: m.BASE_BVD.lm,
    "Cm": lambda m: m.BASE_BVD.cm,
    "Lmatch": lambda m: m.BASE_MATCH.l_h,
    "Cmatch": lambda m: m.BASE_MATCH.c_f,
    "Rsource": lambda m: m.BASE_RS,
    "Rlesr": lambda m: 2 * math.pi * m.F0 * m.BASE_MATCH.l_h / m.BASE_MATCH.ql,
    "Rcesr": lambda m: 1 / (2 * math.pi * m.F0 * m.BASE_MATCH.c_f * m.BASE_MATCH.qc),
}
NETLIST_TOL = 1e-12


def _load(name: str, path: Path):
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"无法加载 {path}"
    module = importlib.util.module_from_spec(spec)
    # 必须先登记再执行:模块里的 dataclass 在解析延迟注解时会回查 sys.modules。
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def model():
    import sys

    sys.path.insert(0, str(ACTIVE))
    return _load("active_model_v2_1", ACTIVE / "model_v2_1.py")


@pytest.fixture(scope="module")
def design() -> dict:
    return json.loads(DESIGN_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads((ACTIVE / "bvd_parameters.json").read_text(encoding="utf-8"))


def _netlist_values() -> dict[str, float]:
    """解析 '<名称> <节点> <节点> <值> [Rser=...]' 形式的元件行。"""
    values: dict[str, float] = {}
    for line in NETLIST.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] in NETLIST_TO_MODEL:
            if re.fullmatch(r"[-+0-9.eE]+", parts[3]):
                values[parts[0]] = float(parts[3])
    return values


def test_registry_declares_qm(registry):
    """Qm 必须在登记表里且已标注类别,不能回到代码硬编码。

    刻意不断言 Qm 等于某个具体值:Qm 是第一扫描变量,把它钉死会挡住合法的
    Qm 扫描。真正要守的不变量是三份副本一致,由下面几个用例覆盖。
    """
    qm = registry["bvd_parameters"]["Qm"]
    assert isinstance(qm["value"], (int, float))
    assert math.isfinite(qm["value"]) and qm["value"] > 0
    assert qm["class"] == "ASSUMED_BASELINE"
    assert qm["origin"] == "REGISTRY"


def test_model_reads_qm_from_registry(model, registry):
    assert model.BASE_QM == registry["bvd_parameters"]["Qm"]["value"]
    assert model.BASE_BVD.qm == model.BASE_QM


def test_derived_lm_cm_match_design_json(model, design, registry):
    """副本 1 vs 副本 2:Qm 推导值必须等于设计 JSON 存储值。"""
    tol = float(registry["consistency_check"]["tolerance_rel"])
    for name, derived in (("Lm_H", model.BASE_BVD.lm), ("Cm_F", model.BASE_BVD.cm)):
        stored = float(design["bvd"][name])
        assert abs(derived - stored) / abs(stored) <= tol, (
            f"{name}: 由 Qm={model.BASE_QM} 推导得 {derived!r},设计 JSON 存储 {stored!r}"
        )


def test_design_json_sha256_pinned(registry):
    """设计 JSON 受 FILE_MANIFEST 覆盖,登记表钉住它的 sha256,不得被静默修改。"""
    actual = hashlib.sha256(DESIGN_JSON.read_bytes()).hexdigest()
    assert actual == registry["stage2_design_reference"]["sha256"]


def test_netlist_matches_active_model(model):
    """副本 1/2 vs 副本 3:LTspice 网表的每个元件值必须等于模型值。

    这是 Qm 改动后最容易悄悄失效的一环 —— 网表不会自动重新生成。
    """
    values = _netlist_values()
    missing = set(NETLIST_TO_MODEL) - set(values)
    assert not missing, f"网表里找不到这些元件:{sorted(missing)}"
    for name, getter in NETLIST_TO_MODEL.items():
        expected = getter(model)
        assert abs(values[name] - expected) / abs(expected) <= NETLIST_TOL, (
            f"{name}: 网表为 {values[name]!r},模型为 {expected!r}。"
            f"很可能是改了 Qm 但没有用 design_stage2.py 重新生成网表。"
        )


def test_stage2_audit_record_still_claims_pass():
    """历史交叉验证记录本身没有被改写以掩盖回归。"""
    audit = json.loads(
        (REPO / "workspace" / "CTO_virtual_drive_platform_v2_1" / "evidence"
         / "ltspice" / "stage2" / "stage2_audit.json").read_text(encoding="utf-8")
    )
    assert audit["status"] == "PASS"
    for entry in audit["cross_validation"]:
        assert entry["status"] == "PASS"
        # 计划书判据 <0.1%
        assert entry["max_zin_relative_error"] < 1e-3
        assert entry["max_prm_full_scale_error"] < 1e-3


@pytest.mark.skipif(not RAW.exists(), reason="LTspice .raw 仅随 Release 分发,不在 Git 树中")
def test_active_model_matches_ltspice_raw(model):
    """完整交接包在场时,直接比对活动模型与 LTspice RAW 的输入阻抗。

    Git 树里 .raw 被 GIT_OMISSIONS 排除,因此本用例在纯 Git 检出下跳过;
    解压两个 Release 包后即自动生效。
    """
    read_raw = _load(
        "stage1_raw_parser",
        REPO / "workspace" / "CTO_virtual_drive_platform_v2_1" / "scripts"
        / "archived_sources" / "stage1" / "analyze_v2_stage1.py",
    ).read_ltspice_raw
    raw = read_raw(RAW)
    freq = np.real(raw["frequency"])
    # 网表源是 1 Vrms;模型的 amplitude=1 对应 SOURCE_A1_VRMS。
    z_in_raw = raw["v(n_in)"] / (-raw["i(vdrive)"])
    z_in_model = model.response(freq, model.scenario_map()["CASE_000_BASELINE"], 1.0)["z_in"]
    rel = np.max(np.abs(z_in_raw - z_in_model) / np.abs(z_in_model))
    assert rel < 1e-3, f"活动模型与 LTspice RAW 的 z_in 最大相对误差 {rel:.3e}"


# --------------------------------------------------------------------------
# 驱动限值登记表与驱动口径
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def limits() -> dict:
    return json.loads((ACTIVE / "drive_limits.json").read_text(encoding="utf-8"))


def test_model_reads_drive_limits_from_registry(model, limits):
    """V/I 限值与功放能力上限必须来自登记表,不能回到代码硬编码。"""
    t = limits["transducer_limits"]
    assert model.VPP_SOFT == t["VPP_SOFT"]["value"]
    assert model.VPP_HARD == t["VPP_HARD"]["value"]
    assert model.IRMS_SOFT == t["IRMS_SOFT"]["value"]
    assert model.IRMS_HARD == t["IRMS_HARD"]["value"]
    assert model.SOURCE_MAX_AMPLITUDE == limits["source_capability"]["max_amplitude"]["value"]


def test_default_drive_mode_is_frozen_a1(model):
    """默认口径必须是 FROZEN_A1，否则历史批次不可复现。"""
    assert model.SOURCE_MAX_AMPLITUDE == 1.0


def test_frozen_a1_is_source_bound_everywhere(model):
    """记录现状：默认口径下 V/I 保护从不触发，34/34 由源幅度绑定。

    这不是「应该如此」，而是把审核发现第 1 节的事实钉住：一旦有人改了
    max_amplitude 却没有同步更新报告口径，这个用例会失败并提醒他。
    """
    f = np.linspace(model.F_MIN, model.F_MAX, 20001)
    source_bound = 0
    for s in model.all_scenarios():
        a = model.allowed_amplitude(f, s, use_soft_limits=True)
        if float(a[int(np.argmax(model.safe_power(f, s)))]) >= model.SOURCE_MAX_AMPLITUDE - 1e-12:
            source_bound += 1
    assert source_bound == len(model.all_scenarios()), (
        "默认口径下应当全部由源幅度绑定；若此处变化，说明驱动口径已改，"
        "docs/04_代码审核_2026-09-15.md 第 1 节的结论需要同步更新。"
    )


def test_push_to_limit_engages_vi_protection(model):
    """PUSH_TO_LIMIT 口径下，V/I 约束必须真正成为绑定约束。"""
    f = np.linspace(model.F_MIN, model.F_MAX, 20001)
    cap = 2.5
    vi_bound = 0
    for s in model.all_scenarios():
        a = model.allowed_amplitude(f, s, use_soft_limits=True, source_max=cap)
        if float(a[int(np.argmax(model.safe_power(f, s, source_max=cap)))]) < cap - 1e-12:
            vi_bound += 1
    assert vi_bound == len(model.all_scenarios())


def test_push_to_limit_never_exceeds_compliance(model):
    """推到上限后仍不得越界：这正是「零越界」指标真正被检验的地方。"""
    f = np.linspace(model.F_MIN, model.F_MAX, 20001)
    for s in model.all_scenarios():
        a = model.allowed_amplitude(f, s, use_soft_limits=False, source_max=2.5)
        r = model.response(f, s, 1.0)
        assert np.max(r["vport_vpp"] * a) <= model.VPP_HARD * (1 + 1e-12)
        assert np.max(r["iport_irms_A"] * a) <= model.IRMS_HARD * (1 + 1e-12)


def test_source_max_must_be_positive(model):
    s = model.scenario_map()["CASE_000_BASELINE"]
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            model.allowed_amplitude(0.9e6, s, use_soft_limits=True, source_max=bad)


# --------------------------------------------------------------------------
# 选频研究的约束口径（计划书第 3 周）
# --------------------------------------------------------------------------

def test_selection_study_applies_vi_constraints():
    """选频脚本必须标注选出的工作点是否越过 V/I 上限。

    计划书第 3 周：「设定电压、电流和功率的相对上限，作为控制器不得越过的
    模型内部约束。」不加这几列时，最小相位准则会在 30/34 场景选出越过
    160 Vpp 硬上限的点，且功率往往不足峰值的 1%，表面上看不出异常。
    """
    src = (REBUILD / "active_stage3_5" / "run_stage3_selection.py").read_text(encoding="utf-8")
    for field in ("exceeds_V_hard", "exceeds_V_soft", "exceeds_I_hard",
                  "exceeds_I_soft", "admissible_at_a1"):
        assert field in src, f"run_stage3_selection.py 缺少约束列 {field}"


def test_closed_loop_selects_by_power_not_phase(model):
    """闭环控制器按端口有功功率选点，不按相位或反射代理。

    这是「最小相位准则会选出越界点」在运行期不构成安全问题的原因，
    也是必须守住的性质：若有人把 local_scan 改成按相位选点，
    就会把 docs/05 第 3 节量化的越界风险引入闭环。
    """
    src = (REBUILD / "active_stage3_5" / "run_stage4_5_control.py").read_text(encoding="utf-8")
    assert src.count('measured.append((row["normalized_port_power_W"]') == 3, (
        "local_scan 的三级扫描应全部按端口有功功率选点"
    )
    assert "min_abs_phase" not in src and "argmin(np.abs(q[\"phase_deg\"]))" not in src


def test_max_power_criterion_is_the_constrained_optimum(model):
    """最大功率准则本身就是约束下的最优解（34/34 场景）。

    这条是 docs/05 第 6 节可直接写进报告的结论，固化以防回归。
    """
    f = np.arange(0.84e6, 0.96e6 + 1, 0.5e3)
    for s in model.all_scenarios():
        q = model.response(f, s, 1.0)
        a = model.allowed_amplitude(f, s, use_soft_limits=True)
        deliverable = q["p_rm_W"] * a**2
        ok = (q["vport_vpp"] <= model.VPP_HARD) & (q["iport_irms_A"] <= model.IRMS_HARD)
        assert ok.any(), f"{s.case_id}: 无任何合规频点"
        best_constrained = float(f[int(np.argmax(np.where(ok, deliverable, -np.inf)))])
        best_power = float(f[int(np.argmax(q["p_rm_W"]))])
        assert abs(best_constrained - best_power) <= 1.0, (
            f"{s.case_id}: 约束内最优 {best_constrained} != 最大功率点 {best_power}"
        )


def test_selection_report_scenario_count_is_not_hardcoded():
    """报告里的场景数必须由数据算出。

    活动登记表从 28 个场景扩到 34 个后，write_report() 里硬编码的 "28" 没有
    跟着更新，导致报告与同一脚本写出的 audit JSON（scenario_count）互相矛盾。
    这类「数字写死在字符串里」的错误不会被任何数值检查发现。

    注意：`report_evidence_final/` 与 `archived_sources/` 下的 28 是 28 场景
    时期的正确记录，不在本用例范围内，也不应被改。
    """
    src = (REBUILD / "active_stage3_5" / "run_stage3_selection.py").read_text(encoding="utf-8")
    assert "以全部28个活动场景" not in src
    assert "len(initial)}个活动场景" in src


def test_live_selection_reports_agree_with_scenario_count(model):
    """活动批次的报告与实际场景数一致（历史证据批次除外）。"""
    n = len(model.all_scenarios())
    live = [
        REBUILD / "active_stage3_5" / "stage3_selection" / "stage3_selection_report.md",
        REPO / "workspace" / "CTO_virtual_drive_platform_v2_1" / "results" / "tables"
        / "stage3_selection" / "stage3_selection_report.md",
    ]
    for path in live:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert f"以全部{n}个活动场景" in text, f"{path.name} 的场景数与登记表({n})不一致"


# --------------------------------------------------------------------------
# 相位消融：伪锁定检测必须保留
# --------------------------------------------------------------------------

def test_phase_ablation_target_is_power_calibrated():
    """相位设定点必须由功率最优点标定，不得退回朴素的相位归零。

    项目本来就是这么做的（target = phase at baseline constrained max-P_Rm，
    约 -1.078 度）。固化它，免得有人「简化」成 target=0 —— 那样会让伪锁定
    更容易发生，而表面上看不出区别。
    """
    src = (REBUILD / "active_stage3_5" / "run_phase_ablation.py").read_text(encoding="utf-8")
    assert "target_phase = phase_at(baseline_opt" in src, "目标相位必须由功率最优点标定"


def test_phase_ablation_keeps_wrong_lock_detector():
    """必须保留「相位收敛但功率低」的伪锁定判据。

    这是本项目自己发明的检测器，也是 docs/04 第 4 节所述失效模式的唯一
    内建观测手段。删掉它，伪锁定就会以「|相位误差| 合格」的面貌通过验收。
    """
    src = (REBUILD / "active_stage3_5" / "run_phase_ablation.py").read_text(encoding="utf-8")
    assert "wrong_phase_lock_flag" in src
    assert "phase_error <= 0.5 and capture < 0.95" in src
    assert "wrong_phase_lock_seen_in_gain_sweep" in src


def test_phase_target_has_multiple_stable_solutions(model):
    """记录机理：目标相位在带内有多个解，全部在 sign(slope) 下稳定。

    这是伪锁定的根因。若模型改动使解的个数变化，本用例会失败并提示
    重新评估 docs/04 第 4 节与 docs/05 第 6 节的结论。
    """
    s = model.scenario_map()["CASE_000_BASELINE"]
    fine = np.arange(model.F_MIN, model.F_MAX + 0.1, 100.0)
    f_opt = float(fine[int(np.argmax(model.safe_power(fine, s)))])
    target = float(model.response(np.array([f_opt]), s, 1.0)["phase_deg"][0])
    dense = np.linspace(model.F_MIN, model.F_MAX, 400001)
    phase = model.response(dense, s, 1.0)["phase_deg"]
    crossings = dense[np.where(np.diff(np.sign(phase - target)))[0]]
    # 去掉数值上重合的解
    distinct = [crossings[0]]
    for c in crossings[1:]:
        if c - distinct[-1] > 100.0:
            distinct.append(c)
    assert len(distinct) >= 3, (
        f"目标相位 {target:.3f} 度只有 {len(distinct)} 个解；"
        "docs/04 第 4 节的三吸引子结论需要重新评估"
    )
    powers = [float(model.safe_power(np.array([c]), s)[0]) for c in distinct]
    assert min(powers) / max(powers) < 0.1, "至少一个解应为低功率伪锁点"


# --------------------------------------------------------------------------
# 三级扫描阶梯与捕获级覆盖范围
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scan_registry() -> dict:
    return json.loads((ACTIVE / "scan_parameters.json").read_text(encoding="utf-8"))


def test_scan_ladder_read_from_registry():
    """三级阶梯的 6 个常量必须来自登记表，不得写死回代码。"""
    src = (ACTIVE / "run_stage4_5_control.py").read_text(encoding="utf-8")
    for name in ("COARSE_HALFWIDTH_HZ", "COARSE_STEP_HZ", "FINE_HALFWIDTH_HZ",
                 "FINE_STEP_HZ", "ULTRA_HALFWIDTH_HZ", "ULTRA_STEP_HZ"):
        assert name in src, f"缺少具名常量 {name}"
    assert "current_f - 50e3" not in src, "捕获级窗口不得写死"
    assert "coarse_best - 5e3" not in src and "fine_best - 1e3" not in src


def test_registry_records_required_coarse_halfwidth(model, scan_registry):
    """登记表记录的「所需捕获级半宽」必须等于全部场景的最大 fs 偏移。"""
    required = max(abs(s.bvd.fs - model.F0) for s in model.all_scenarios())
    declared = float(scan_registry["known_coverage_gap"]["required_halfwidth_Hz"])
    assert abs(declared - required) <= 1.0, (
        f"登记表声明 {declared} Hz，实际需要 {required:.1f} Hz"
    )


def test_declared_coverage_gap_matches_reality(model, scan_registry):
    """登记表声明的「够不到的场景」必须与当前捕获级窗口下的实测一致。

    这是本条改动的核心可审计性保证：
      - 现在（±50 kHz）声明 LM_P20/CM_P20 够不到，测试据此通过；
      - 若有人把窗口放宽到 ±100 kHz 却忘了清空该列表，测试失败；
      - 若有人把窗口收窄，新增的够不到场景也会让测试失败。
    缺口被写进登记表本身，而不是只存在于审核文档里。
    """
    half = float(scan_registry["ladder"]["coarse"]["halfwidth_Hz"])
    actual = sorted(s.case_id for s in model.all_scenarios()
                    if abs(s.bvd.fs - model.F0) > half)
    declared = sorted(scan_registry["known_coverage_gap"]["uncovered_scenarios_at_current_coarse"])
    assert actual == declared, (
        f"捕获级 ±{half/1e3:.0f} kHz 下实际够不到 {actual}，登记表声明 {declared}。"
        "改了窗口就要同步更新 known_coverage_gap。"
    )


def test_fine_step_stays_below_power_fwhm(model, scan_registry):
    """细化级步长必须小于基线功率峰 FWHM。

    这是粗扫失手后仍能被捞回来的原因，也是 32/34 场景达到 100% 捕获的机理。
    步长一旦大于峰宽，三级扫描就会整个跨过峰值。
    """
    s = model.scenario_map()["CASE_000_BASELINE"]
    f = np.linspace(model.F_MIN, model.F_MAX, 400001)
    width, status, _, _ = model.half_power_width(f, model.safe_power(f, s))
    assert status == "OK"
    step = float(scan_registry["ladder"]["fine"]["step_Hz"])
    assert step < width, f"细化级步长 {step} Hz 不小于功率峰 FWHM {width:.0f} Hz"


# --------------------------------------------------------------------------
# 模型数值行为的回归保护
# --------------------------------------------------------------------------

NUMERIC_BASELINE = Path(__file__).resolve().parent / "model_numeric_baseline.json"
# 相对容差：允许不同 numpy/BLAS 版本的末位差异，但拦住任何有物理意义的改动
NUMERIC_RTOL = 1e-9


@pytest.fixture(scope="module")
def numeric_baseline() -> dict:
    return json.loads(NUMERIC_BASELINE.read_text(encoding="utf-8"))


def _numeric_snapshot(model, scenario) -> dict:
    """与生成基线时完全相同的口径：0.8-1.0 MHz、2001 点、amplitude=1。"""
    f = np.linspace(model.F_MIN, model.F_MAX, 2001)
    r = model.response(f, scenario, 1.0)
    keys = ["p_rm_W", "p_port_W", "q_port_var", "s_port_VA", "p_source_W",
            "p_rs_W", "p_l_esr_W", "p_c_esr_W", "gamma", "vport_vpp",
            "iport_irms_A", "phase_deg"]
    row = {k: float(np.sum(r[k])) for k in keys}
    row["zin_abs_sum"] = float(np.sum(np.abs(r["z_in"])))
    row["zbvd_abs_sum"] = float(np.sum(np.abs(r["z_bvd"])))
    row["a_soft_sum"] = float(np.sum(model.allowed_amplitude(f, scenario, use_soft_limits=True)))
    row["a_hard_sum"] = float(np.sum(model.allowed_amplitude(f, scenario, use_soft_limits=False)))
    row["safe_power_sum"] = float(np.sum(model.safe_power(f, scenario)))
    w, status, _, _ = model.half_power_width(f, model.safe_power(f, scenario))
    row["fwhm_Hz"] = float(w) if status == "OK" else status
    return row


def test_numeric_baseline_covers_every_scenario(model, numeric_baseline):
    assert sorted(numeric_baseline) == sorted(s.case_id for s in model.all_scenarios()), (
        "基线与场景登记表不一致：新增或删除场景后需重新生成 model_numeric_baseline.json"
    )


def test_model_numeric_behaviour_unchanged(model, numeric_baseline):
    """锁住模型的数值行为本身，而不只是参数与结构。

    前面的用例保证参数来自登记表、三份副本一致、阶梯覆盖已声明；
    但它们都拦不住「公式改了、参数没改」这类回归——例如误改 ESR 的频率依赖、
    把 p_port 与 p_rm 的定义搞混、或在限幅里少一个 clip。本用例覆盖 response()
    的全部输出量、软硬两套限幅、safe_power 与半功率宽度，共 34 场景 x 18 个量。

    基线由 active_stage3_5 当前模型生成（0.8-1.0 MHz、2001 点、amplitude=1）。
    若确实有意改变模型，重新生成基线并在提交信息里说明改了什么、为什么。
    """
    bad = []
    for s in model.all_scenarios():
        got = _numeric_snapshot(model, s)
        exp = numeric_baseline[s.case_id]
        for k, want in exp.items():
            have = got[k]
            if isinstance(want, str) or isinstance(have, str):
                if want != have:
                    bad.append(f"{s.case_id}.{k}: {want!r} -> {have!r}")
                continue
            if want == 0:
                if abs(have) > 1e-30:
                    bad.append(f"{s.case_id}.{k}: 0 -> {have!r}")
            elif abs(have - want) / abs(want) > NUMERIC_RTOL:
                bad.append(f"{s.case_id}.{k}: {want!r} -> {have!r} "
                           f"(相对差 {abs(have-want)/abs(want):.3e})")
    assert not bad, "模型数值行为发生变化：\n  " + "\n  ".join(bad[:12])


def test_power_balance_closes_everywhere(model):
    """能量守恒是模型的硬性质，与基线无关，任何改动都不得破坏。"""
    f = np.linspace(model.F_MIN, model.F_MAX, 2001)
    for s in model.all_scenarios():
        err = np.max(np.abs(model.response(f, s, 1.0)["power_balance_error_W"]))
        assert err < 1e-12, f"{s.case_id}: 功率守恒残差 {err:.3e} W"


def test_p_port_equals_p_rm(model):
    """C0 无损，故端口有功功率恒等于机械支路功率。定义搞混会被此用例拦住。"""
    f = np.linspace(model.F_MIN, model.F_MAX, 2001)
    for s in model.all_scenarios():
        r = model.response(f, s, 1.0)
        rel = np.max(np.abs(r["p_port_W"] - r["p_rm_W"]) / np.maximum(r["p_rm_W"], 1e-30))
        assert rel < 1e-9, f"{s.case_id}: p_port 与 p_rm 相对偏差 {rel:.3e}"


def test_amplitude_never_exceeds_declared_source_cap(model):
    """限幅不得越过登记的功放能力上限，也不得为负。"""
    f = np.linspace(model.F_MIN, model.F_MAX, 2001)
    for s in model.all_scenarios():
        for soft in (True, False):
            a = model.allowed_amplitude(f, s, use_soft_limits=soft)
            assert np.all(a >= 0.0)
            assert np.all(a <= model.SOURCE_MAX_AMPLITUDE + 1e-12)


# --------------------------------------------------------------------------
# 相位闭环作为正式策略
# --------------------------------------------------------------------------

def test_phase_lock_is_a_formal_strategy():
    """计划书第 4 周点名要求对比「固定频率、周期扫频和相位闭环」。

    此前正式表里第三种是 P&O，相位闭环只作为消融实验存在。
    """
    src = (ACTIVE / "run_stage4_5_control.py").read_text(encoding="utf-8")
    assert '"PHASE_LOCK"' in src
    assert "STRATEGIES = [" in src
    line = next(l for l in src.splitlines() if l.startswith("STRATEGIES = ["))
    for name in ("FIXED_0P9", "PERIODIC_SCAN", "PHASE_LOCK"):
        assert name in line, f"正式策略表缺少 {name}"


def test_phase_controller_params_from_registry(scan_registry):
    """相位控制器与防护的参数必须来自登记表，不得写死。"""
    ph = scan_registry["phase_controller"]
    for k in ("gain_Hz_per_deg", "probe_Hz", "deadband_deg", "max_update_Hz"):
        assert isinstance(ph[k]["value"], (int, float))
    g = ph["false_lock_guard"]
    for k in ("probe_Hz", "ratio_threshold", "cooldown_s", "min_dwell_s"):
        assert isinstance(g[k]["value"], (int, float))
    src = (ACTIVE / "run_stage4_5_control.py").read_text(encoding="utf-8")
    for name in ("PHASE_GAIN_HZ_PER_DEG", "GUARD_PROBE_HZ", "GUARD_RATIO"):
        assert name in src


def test_false_lock_guard_recalibrates_setpoint():
    """防护必须两步齐全：探测判伪锁 + 重扫后重新标定相位设定点。

    只重扫不重标定是无效的——功率峰处相位并非 0（标称点 −0.99°），
    控制器会立刻被拉回伪锁点。这一点在 gap-closure 批次里实测验证过。
    """
    src = (ACTIVE / "run_stage4_5_control.py").read_text(encoding="utf-8")
    assert "PHASE_FALSE_LOCK_GUARD" in src, "缺少伪锁定判定分支"
    assert "phase_target_deg = float(" in src, "重捕获后必须重新标定相位设定点"
    assert "GUARD_RATIO" in src and "p_port_W" in src, "防护必须基于可观测的端口有功功率"


def test_disturbance_table_records_parallel_resonance():
    """扰动汇总表必须成对记录串联与并联谐振（计划书第四章、第六章）。"""
    src = (ACTIVE / "run_stage3_disturbance.py").read_text(encoding="utf-8")
    for col in ("fp_Hz", "zin_abs_max_ohm", "fp_minus_fs_Hz", "zbvd_abs_max_ohm"):
        assert f'"{col}"' in src, f"扰动汇总表缺少 {col} 列"


def test_manifest_mismatches_are_all_recorded():
    """被 FILE_MANIFEST 收录的文件若被改动，必须在 POST_HANDOFF_CHANGES.json 中有记录。

    FILE_MANIFEST.json 是交接当日的交付回执，不是演进中仓库的实时完整性检查。
    交接后的开发必然使其失配——失配本身不是错误，**没有记录的失配才是**。
    本用例保证两者始终对得上：改了受清单覆盖的文件却忘了登记，立刻失败。
    """
    import hashlib

    manifest = {e["path"]: e for e in
                json.loads((REPO / "FILE_MANIFEST.json").read_text(encoding="utf-8"))}
    recorded = {c["file"] for c in
                json.loads((REPO / "POST_HANDOFF_CHANGES.json").read_text(encoding="utf-8"))["changes"]}
    unrecorded = []
    for path, entry in manifest.items():
        f = REPO / path
        if not f.is_file():
            continue  # 未纳入 Git 树的 Release 文件，README 已说明
        if f.stat().st_size != entry["bytes"] or \
                hashlib.sha256(f.read_bytes()).hexdigest() != entry["sha256"]:
            if path not in recorded:
                unrecorded.append(path)
    assert not unrecorded, (
        "以下文件与 FILE_MANIFEST 失配但未登记到 POST_HANDOFF_CHANGES.json：\n  "
        + "\n  ".join(unrecorded))
