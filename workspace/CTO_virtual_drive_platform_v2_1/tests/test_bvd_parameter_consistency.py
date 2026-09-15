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
