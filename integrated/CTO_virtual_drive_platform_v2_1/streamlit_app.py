"""Optional research UI for interactive v2.1 analytic-model exploration."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st


plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial", "DejaVu Sans", "sans-serif"],
    "axes.unicode_minus": False,
})


HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "config.yaml").read_text(encoding="utf-8"))
MODEL_PATH = (
    HERE / "../outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py"
).resolve()
LTSPICE_BRIDGE_PATH = (HERE / "scripts/ltspice_bridge.py").resolve()
FACTOR_DISPLAY_NAMES = {
    "C0": "静态电容 C₀",
    "Rm": "机械支路电阻 Rₘ",
    "fs": "串联谐振频率 fₛ",
    "Lm": "机械支路电感 Lₘ（Lm-only）",
    "Cm": "机械支路电容 Cₘ（Cm-only）",
    "Rs": "戴维南源阻抗 Rₛ",
    "Lmatch": "匹配电感 Lmatch",
    "Cmatch": "匹配电容 C_match",
    "inductor_Q": "匹配电感品质因数 Q",
    "Qm": "机械品质因数 Qₘ",
    "baseline": "基准",
    "combined": "组合扰动",
}


@st.cache_resource
def load_model():
    sys.path.insert(0, str(MODEL_PATH.parent))
    spec = importlib.util.spec_from_file_location("active_model_v2_1", MODEL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模型：{MODEL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@st.cache_resource
def load_ltspice_bridge():
    spec = importlib.util.spec_from_file_location("platform_ltspice_bridge", LTSPICE_BRIDGE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载LTspice桥接模块：{LTSPICE_BRIDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


model = load_model()
ltspice_bridge = load_ltspice_bridge()
st.set_page_config(page_title="虚拟驱动平台 v2.1", layout="wide")
st.title("超声换能器虚拟阻抗与驱动控制平台原型 v2.1")
st.info("本页为单场景参数探索与历史结果，不是当前统一控制批次。滑块不会修改已冻结的正式结果。")
st.page_link("pages/04_统一三策略结果.py", label="当前正式结果：固定／周期扫频／相位反馈（同批次）", icon="📊")
st.page_link("pages/03_LTspice闭环验证.py", label="打开独立实验页：LTspice闭环验证", icon="🔁")
st.warning(
    "当前为假设BVD参数的小信号线性解析模型。界面结果不是实测、声压、热效应、临床安全或硬件实时控制结果。"
)
st.info(
    "前级统一建模为戴维南等效：理想正弦电压源＋串联源阻抗 Rs。"
    "这里的Rs不是完整功放的开关器件、反馈环路、效率或热模型。"
)

with st.sidebar:
    st.header("单场景扫描变量")
    c0_pct = st.slider("静态电容 C₀变化 (%)", -30.0, 30.0, 0.0, 1.0)
    rm_pct = st.slider("机械支路电阻 Rₘ变化 (%)", -50.0, 50.0, 0.0, 1.0)
    fs_pct = st.slider("串联谐振频率变化 (%)", -10.0, 10.0, 0.0, 0.1)
    lm_pct = st.slider("机械支路电感 Lₘ（Lm-only）变化 (%)", -20.0, 20.0, 0.0, 1.0)
    cm_pct = st.slider("机械支路电容 Cₘ（Cm-only）变化 (%)", -20.0, 20.0, 0.0, 1.0)
    rs_pct = st.slider("戴维南源阻抗 Rs变化 (%)", -20.0, 20.0, 0.0, 1.0)
    lmatch_pct = st.slider("匹配电感变化 (%)", -20.0, 20.0, 0.0, 1.0)
    ql = st.select_slider("匹配电感Q（扫描变量）", options=[20, 50, 100], value=100)
    amplitude = st.slider("归一化幅度命令", 0.0, 1.0, 1.0, 0.05)
    step_hz = st.select_slider("频率步长 (Hz)", options=[100, 500, 1000, 2000], value=500)

base_bvd = model.BASE_BVD
bvd = model.bvd_from_fs_qm(
    c0=base_bvd.c0 * (1 + c0_pct / 100),
    rm=base_bvd.rm * (1 + rm_pct / 100),
    fs=base_bvd.fs * (1 + fs_pct / 100),
    qm=base_bvd.qm,
)
custom_lm = bvd.lm * (1 + lm_pct / 100)
custom_cm = bvd.cm * (1 + cm_pct / 100)
custom_fs = 1 / (2 * np.pi * np.sqrt(custom_lm * custom_cm))
custom_qm = 2 * np.pi * custom_fs * custom_lm / bvd.rm
bvd = model.BVD(
    c0=bvd.c0,
    rm=bvd.rm,
    lm=custom_lm,
    cm=custom_cm,
    qm=custom_qm,
    fs=custom_fs,
)
matching = model.Matching(
    l_h=model.BASE_MATCH.l_h * (1 + lmatch_pct / 100),
    c_f=model.BASE_MATCH.c_f,
    ql=float(ql),
    qc=model.BASE_MATCH.qc,
)
scenario = model.Scenario(
    case_id="UI_CUSTOM",
    family="interactive",
    factor="multi_parameter",
    level="custom",
    description="Streamlit interactive hypothetical scenario",
    bvd=bvd,
    matching=matching,
    rs=model.BASE_RS * (1 + rs_pct / 100),
)
frequency = np.arange(model.F_MIN, model.F_MAX + 0.1, float(step_hz))
result = model.response(frequency, scenario, amplitude=amplitude)
unit_result = model.response(frequency, scenario, amplitude=1.0)
safe_power_w = model.safe_power(frequency, scenario)
peak_index = int(np.argmax(unit_result["p_rm_W"]))
zmin_index = int(np.argmin(np.abs(unit_result["z_in"])))
gamma_min_index = int(np.argmin(unit_result["gamma"]))
motional_fs_hz = 1.0 / (2.0 * np.pi * np.sqrt(bvd.lm * bvd.cm))
lossless_fp_est_hz = motional_fs_hz * np.sqrt(1.0 + bvd.cm / bvd.c0)

phase = unit_result["phase_deg"]
phase_crossings = np.where(phase[:-1] * phase[1:] <= 0)[0]
phase_zero_candidates = []
for crossing in phase_crossings:
    f0, f1 = frequency[crossing], frequency[crossing + 1]
    p0, p1 = phase[crossing], phase[crossing + 1]
    if p1 == p0:
        phase_zero_candidates.append(float((f0 + f1) / 2))
    else:
        phase_zero_candidates.append(float(f0 - p0 * (f1 - f0) / (p1 - p0)))
if phase_zero_candidates:
    phase_feature_hz = min(phase_zero_candidates, key=lambda value: abs(value - frequency[peak_index]))
    phase_feature_status = f"ZERO_CROSSING（共{len(phase_zero_candidates)}个）"
else:
    phase_min_index = int(np.argmin(np.abs(phase)))
    phase_feature_hz = float(frequency[phase_min_index])
    phase_feature_status = "无零点，使用最小绝对相位"

p_source_at_peak = float(result["p_source_W"][peak_index])
p_port_at_peak = float(result["p_port_W"][peak_index])
p_rm_at_peak = float(result["p_rm_W"][peak_index])
eta_elec_at_peak = p_port_at_peak / p_source_at_peak if p_source_at_peak > 1e-30 else np.nan

col1, col2, col3, col4 = st.columns(4)
col1.metric("有功功率峰值频率", f"{frequency[peak_index] / 1e6:.4f} MHz")
col2.metric("运动支路有功 P_Rm", f"{p_rm_at_peak * 1e3:.1f} mW")
col3.metric("戴维南源有功 P_source", f"{p_source_at_peak * 1e3:.1f} mW")
col4.metric("端口有功 P_port", f"{p_port_at_peak * 1e3:.1f} mW")

col5, col6, col7, col8 = st.columns(4)
col5.metric("电学功率分配 η_elec", "—" if not np.isfinite(eta_elec_at_peak) else f"{eta_elec_at_peak * 100:.2f}%")
col6.metric(
    "峰值点匹配网络输入相位 arg(Z_in)",
    f"{unit_result['phase_deg'][peak_index]:.3f}°",
)
col7.metric("峰值点反射代理", f"{unit_result['gamma'][peak_index]:.5f}")
col8.metric(
    "换能器端 Vpp / Irms",
    f"{result['vport_vpp'][peak_index]:.2f} V / {result['iport_irms_A'][peak_index] * 1e3:.3f} mA",
)

st.caption(
    "以上功率量均取在运动支路有功功率峰值频率；"
    "η_elec=P_port/P_source，仅表示戴维南源至换能器电端口的有功功率传输比例，不是电声转换效率。"
    "页面当前相位量为匹配网络输入端、戴维南源所见输入阻抗相位 arg(Z_in)，"
    "不是换能器端口相位 arg(V_port/I_port)。"
)

st.subheader("谐振状态：多个特征点并列报告")
resonance_table = pd.DataFrame([
    {
        "特征": "运动支路串联谐振 fs",
        "定义": "1/(2π√(L_m·C_m))，BVD元件派生",
        "频率 (MHz)": motional_fs_hz / 1e6,
        "特征值": "不含匹配网络极值判据",
    },
    {
        "特征": "裸BVD并联谐振估计 fp",
        "定义": "f_s·√(1+C_m/C_0)，无损近似",
        "频率 (MHz)": lossless_fp_est_hz / 1e6,
        "特征值": "含损耗及匹配后需数值确认",
    },
    {
        "特征": "运动支路有功功率峰值",
        "定义": "argmax P_Rm(f)",
        "频率 (MHz)": frequency[peak_index] / 1e6,
        "特征值": f"{unit_result['p_rm_W'][peak_index] * 1e3:.1f} mW（a=1）",
    },
    {
        "特征": "输入阻抗幅值极小点",
        "定义": "argmin |Z_in(f)|",
        "频率 (MHz)": frequency[zmin_index] / 1e6,
        "特征值": f"{abs(unit_result['z_in'][zmin_index]):.3f} Ω",
    },
    {
        "特征": "匹配网络输入相位零点/最小绝对相位",
        "定义": phase_feature_status,
        "频率 (MHz)": phase_feature_hz / 1e6,
        "特征值": "不能默认等于功率最大点",
    },
    {
        "特征": "最小反射代理点",
        "定义": "argmin |(Z_in-Rs)/(Z_in+Rs)|",
        "频率 (MHz)": frequency[gamma_min_index] / 1e6,
        "特征值": f"{unit_result['gamma'][gamma_min_index]:.6f}",
    },
])
st.dataframe(
    resonance_table.style.format({"频率 (MHz)": "{:.4f}"}),
    width="stretch",
    hide_index=True,
)
st.warning(
    "谐振状态是多特征描述：运动支路fs、裸BVD并联谐振估计、功率峰值、"
    "|Z_in|极值、匹配网络输入相位arg(Z_in)零点和最小反射点可能不重合；"
    "匹配网络加入后尤其不能只用该相位零点代表。"
)

fig, axes = plt.subplots(4, 1, figsize=(10, 10), sharex=True)
axes[0].plot(frequency / 1e6, result["p_rm_W"] * 1e3, color="#B64342")
axes[0].axvline(frequency[peak_index] / 1e6, color="#B64342", linestyle="--", linewidth=0.9)
axes[0].set_ylabel("P_Rm (mW)")
axes[1].plot(frequency / 1e6, np.abs(unit_result["z_in"]), color="#272727")
axes[1].axvline(frequency[zmin_index] / 1e6, color="#272727", linestyle="--", linewidth=0.9)
axes[1].set_ylabel("|Z_in| (ohm)")
axes[2].plot(frequency / 1e6, unit_result["phase_deg"], color="#3775BA")
axes[2].axhline(0, color="#777777", linewidth=0.8)
axes[2].axvline(phase_feature_hz / 1e6, color="#3775BA", linestyle="--", linewidth=0.9)
axes[2].set_ylabel("arg(Z_in) (deg)")
axes[3].plot(frequency / 1e6, unit_result["gamma"], color="#42949E")
axes[3].axvline(frequency[gamma_min_index] / 1e6, color="#42949E", linestyle="--", linewidth=0.9)
axes[3].set_ylabel("Reflection proxy")
axes[3].set_xlabel("Frequency (MHz)")
for axis in axes:
    axis.grid(alpha=0.25)
fig.tight_layout()
st.pyplot(fig)

table = pd.DataFrame({
    "frequency_Hz": frequency,
    "Zin_real_ohm": np.real(result["z_in"]),
    "Zin_imag_ohm": np.imag(result["z_in"]),
    "Zin_abs_ohm": np.abs(result["z_in"]),
    "Zin_phase_deg": result["phase_deg"],
    "P_Rm_W": result["p_rm_W"],
    "P_port_W": result["p_port_W"],
    "P_source_W": result["p_source_W"],
    "eta_elec_Pport_over_Psource": np.divide(
        result["p_port_W"], result["p_source_W"],
        out=np.full_like(result["p_rm_W"], np.nan),
        where=result["p_source_W"] > 1e-30,
    ),
    "reflection_proxy": result["gamma"],
    "Vport_Vpp": result["vport_vpp"],
    "Iport_Arms": result["iport_irms_A"],
})
st.dataframe(table.iloc[:: max(1, len(table) // 200)], width="stretch")
st.download_button(
    "导出当前场景CSV",
    data=table.to_csv(index=False).encode("utf-8-sig"),
    file_name="UI_CUSTOM_frequency_response.csv",
    mime="text/csv",
)

st.subheader("当前场景：真实LTspice AC扫频验证")
st.caption(
    "点击后，平台会把当前侧栏参数写入独立临时网表，真实调用LTspice批处理并解析RAW。"
    "实线为LTspice RAW，虚线为Python解析模型；运行目录与正式阶段一至三证据隔离。"
)
ltspice_executable = Path(CONFIG["runtime"]["ltspice_executable"])
ltspice_output_root = HERE / "results" / "interactive_ltspice"
current_lt_payload = ltspice_bridge.scenario_payload(model, scenario, frequency, amplitude)
if amplitude <= 0:
    st.warning("幅度命令为0时无法由V/I重建阻抗；请先把归一化幅度设为大于0。")
if not ltspice_executable.is_file():
    st.error(f"找不到LTspice：{ltspice_executable}。请修改config.yaml中的runtime.ltspice_executable。")

run_ltspice_clicked = st.button(
    "运行LTspice验证当前场景",
    type="primary",
    disabled=(amplitude <= 0 or not ltspice_executable.is_file()),
    help="生成新的.cir/.raw/.log，不覆盖正式验收证据。",
)
if run_ltspice_clicked:
    try:
        with st.spinner("正在调用LTspice、解析RAW并与Python模型比较……"):
            st.session_state["latest_ltspice_validation"] = ltspice_bridge.run_ltspice_current_scenario(
                model=model,
                scenario=scenario,
                frequency_hz=frequency,
                amplitude=amplitude,
                ltspice_executable=ltspice_executable,
                output_root=ltspice_output_root,
            )
    except Exception as exc:
        st.exception(exc)

lt_validation = st.session_state.get("latest_ltspice_validation")
if lt_validation is not None:
    lt_audit = lt_validation["audit"]
    if lt_validation["scenario"] != current_lt_payload:
        st.warning("侧栏参数已在上次LTspice运行后发生变化。下面仍显示上次运行结果；请重新点击按钮。")
    if lt_audit["status"] == "PASS":
        st.success("LTspice/Python交叉验证：PASS（主要复数量相对误差与功率满量程误差均小于5%）。")
    else:
        st.error("LTspice/Python交叉验证：FAIL。请先检查误差表和LTspice日志，不应直接采用该结果。")

    audit_col1, audit_col2, audit_col3, audit_col4 = st.columns(4)
    audit_col1.metric("LTspice返回码", str(lt_audit["ltspice_return_code"]))
    audit_col2.metric("RAW点数", str(lt_audit["points"]))
    audit_col3.metric("RAW大小", f"{lt_audit['raw_bytes'] / 1024:.1f} KiB")
    audit_col4.metric("审核状态", lt_audit["status"])

    lt_actual = lt_validation["actual"]
    lt_expected = lt_validation["expected"]
    lt_expected_z_port = lt_validation["expected_z_port"]
    lt_f_mhz = lt_actual["frequency_Hz"] / 1e6

    tab_vi, tab_z, tab_power, tab_audit = st.tabs([
        "端口电压/电流",
        "输入与换能器端口阻抗",
        "功率与反射代理",
        "误差与运行证据",
    ])

    with tab_vi:
        vi_fig, vi_axes = plt.subplots(2, 2, figsize=(11, 6.5), sharex=True)
        vi_axes[0, 0].plot(lt_f_mhz, np.abs(lt_actual["v_port"]), label="LTspice RAW", color="#3775BA")
        vi_axes[0, 0].plot(lt_f_mhz, np.abs(lt_expected["v_port"]), "--", label="Python", color="#B64342")
        vi_axes[0, 0].set_ylabel("|V_port| (V RMS-equivalent)")
        vi_axes[0, 1].plot(lt_f_mhz, np.angle(lt_actual["v_port"], deg=True), color="#3775BA")
        vi_axes[0, 1].plot(lt_f_mhz, np.angle(lt_expected["v_port"], deg=True), "--", color="#B64342")
        vi_axes[0, 1].set_ylabel("arg(V_port) (deg)")
        vi_axes[1, 0].plot(lt_f_mhz, np.abs(lt_actual["i_port"]) * 1e3, color="#3775BA")
        vi_axes[1, 0].plot(lt_f_mhz, np.abs(lt_expected["i_port"]) * 1e3, "--", color="#B64342")
        vi_axes[1, 0].set_ylabel("|I_port| (mA RMS-equivalent)")
        vi_axes[1, 1].plot(lt_f_mhz, np.angle(lt_actual["i_port"], deg=True), color="#3775BA")
        vi_axes[1, 1].plot(lt_f_mhz, np.angle(lt_expected["i_port"], deg=True), "--", color="#B64342")
        vi_axes[1, 1].set_ylabel("arg(I_port) (deg)")
        for vi_axis in vi_axes.flat:
            vi_axis.grid(alpha=0.25)
            vi_axis.set_xlabel("Frequency (MHz)")
        vi_axes[0, 0].legend()
        vi_fig.suptitle("Current interactive scenario: LTspice port phasors vs Python")
        vi_fig.tight_layout()
        st.pyplot(vi_fig)
        plt.close(vi_fig)

    with tab_z:
        z_fig, z_axes = plt.subplots(2, 2, figsize=(11, 6.5), sharex=True)
        z_axes[0, 0].plot(lt_f_mhz, np.abs(lt_actual["z_in"]), label="LTspice RAW", color="#272727")
        z_axes[0, 0].plot(lt_f_mhz, np.abs(lt_expected["z_in"]), "--", label="Python", color="#B64342")
        z_axes[0, 0].set_ylabel("|Z_in| (ohm)")
        z_axes[0, 1].plot(lt_f_mhz, np.angle(lt_actual["z_in"], deg=True), color="#272727")
        z_axes[0, 1].plot(lt_f_mhz, np.angle(lt_expected["z_in"], deg=True), "--", color="#B64342")
        z_axes[0, 1].axhline(0, color="#888888", linewidth=0.7)
        z_axes[0, 1].set_ylabel("arg(Z_in) (deg)")
        z_axes[1, 0].plot(lt_f_mhz, np.abs(lt_actual["z_port"]), color="#3775BA")
        z_axes[1, 0].plot(lt_f_mhz, np.abs(lt_expected_z_port), "--", color="#B64342")
        z_axes[1, 0].set_ylabel("|Z_port| (ohm)")
        z_axes[1, 1].plot(lt_f_mhz, np.angle(lt_actual["z_port"], deg=True), color="#3775BA")
        z_axes[1, 1].plot(lt_f_mhz, np.angle(lt_expected_z_port, deg=True), "--", color="#B64342")
        z_axes[1, 1].axhline(0, color="#888888", linewidth=0.7)
        z_axes[1, 1].set_ylabel("arg(V_port/I_port) (deg)")
        for z_axis in z_axes.flat:
            z_axis.grid(alpha=0.25)
            z_axis.set_xlabel("Frequency (MHz)")
        z_axes[0, 0].legend()
        z_fig.suptitle("Matching-input impedance and transducer-port impedance")
        z_fig.tight_layout()
        st.pyplot(z_fig)
        plt.close(z_fig)
        st.caption(
            "上排是匹配网络输入端量Z_in；下排是换能器端口量Z_port=V_port/I_port。"
            "两种相位位置不同，不能互换。"
        )

    with tab_power:
        power_fig, power_axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
        power_axes[0].plot(lt_f_mhz, lt_actual["p_port_W"] * 1e3, label="LTspice P_port", color="#3775BA")
        power_axes[0].plot(lt_f_mhz, lt_expected["p_port_W"] * 1e3, "--", label="Python P_port", color="#3775BA")
        power_axes[0].plot(lt_f_mhz, lt_actual["p_rm_W"] * 1e3, label="LTspice P_Rm", color="#B64342")
        power_axes[0].plot(lt_f_mhz, lt_expected["p_rm_W"] * 1e3, "--", label="Python P_Rm", color="#B64342")
        power_axes[0].set_ylabel("Active power (mW)")
        power_axes[0].legend(ncol=2)
        power_axes[1].plot(lt_f_mhz, lt_actual["gamma"], label="LTspice RAW", color="#42949E")
        power_axes[1].plot(lt_f_mhz, lt_expected["gamma"], "--", label="Python", color="#B64342")
        power_axes[1].set_ylabel("Reflection proxy")
        power_axes[1].set_xlabel("Frequency (MHz)")
        power_axes[1].legend()
        for power_axis in power_axes:
            power_axis.grid(alpha=0.25)
        power_fig.suptitle("Port/motional active power and reflection proxy")
        power_fig.tight_layout()
        st.pyplot(power_fig)
        plt.close(power_fig)

    with tab_audit:
        error_rows = []
        for error_name, error_value in lt_audit["errors"].items():
            is_absolute = "absolute" in error_name
            error_rows.append({
                "误差指标": error_name,
                "原始数值": error_value,
                "便于阅读": f"{error_value:.6g}" if is_absolute else f"{error_value * 100:.6f}%",
                "口径": "绝对误差" if is_absolute else "相对/满量程误差",
            })
        st.dataframe(pd.DataFrame(error_rows), width="stretch", hide_index=True)
        st.markdown("**可追溯运行文件**")
        st.code(
            "\n".join([
                f"运行目录: {lt_audit['run_directory']}",
                f"网表: {lt_audit['cir_path']}",
                f"RAW: {lt_audit['raw_path']}",
                f"LOG: {lt_audit['log_path']}",
                f"RAW SHA-256: {lt_audit['raw_sha256']}",
                f"LOG SHA-256: {lt_audit['log_sha256']}",
            ]),
            language="text",
        )
        st.download_button(
            "下载本次LTspice/Python逐频对照CSV",
            data=lt_validation["comparison_csv"],
            file_name="UI_LTspice_Python_frequency_comparison.csv",
            mime="text/csv",
        )
        st.download_button(
            "下载本次LTspice审核JSON",
            data=json.dumps(lt_audit, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="UI_LTspice_validation_audit.json",
            mime="application/json",
        )

    st.info(
        "这里显示的是AC扫频复相量，不是V(t)/I(t)瞬态波形。"
        "如需0.9 MHz时域正弦波，需要另建.tran网表并单独定义时间步长与稳态截取窗口。"
    )

with st.expander("参数来源与边界"):
    st.json(CONFIG["declared_parameters"])
    st.markdown(
        "界面修改项均视为**扫描变量**；未修改的BVD和匹配参数仍是v2.1假设基线或派生值。"
        "机械支路Lₘ（Lm-only）/Cₘ（Cm-only）交互项只改变指定运动支路元件，随后计算派生fₛ和Qₘ。"
        "界面不会改写权威配置、LTspice网表或正式结果。"
    )

st.divider()
st.header("已有扰动场景：有功功率峰值汇总")
summary_path = HERE / "results" / "tables" / "stage3_disturbance" / "stage3_scenario_registry_and_summary.csv"
if summary_path.is_file():
    summary = pd.read_csv(summary_path)
    factor_options = summary["factor"].drop_duplicates().tolist()
    selected_factors = st.multiselect(
        "筛选参数类型",
        options=factor_options,
        default=factor_options,
        format_func=lambda value: FACTOR_DISPLAY_NAMES.get(value, value),
        help="power_peak为同一冻结源条件下的运动支路有功功率峰值；safe_power_peak还考虑软保护限幅。",
    )
    visible = summary[summary["factor"].isin(selected_factors)].copy()
    peak_table = pd.DataFrame({
        "场景编号": visible["case_id"],
        "参数": visible["factor"].map(lambda value: FACTOR_DISPLAY_NAMES.get(value, value)),
        "等级": visible["level"],
        "功率峰值频率 (MHz)": visible["power_peak_Hz"] / 1e6,
        "有功功率峰值 (mW)": visible["power_peak_W"] * 1e3,
        "安全峰值频率 (MHz)": visible["safe_power_peak_Hz"] / 1e6,
        "安全有功峰值 (mW)": visible["safe_power_peak_W"] * 1e3,
        "功率半高宽 (kHz)": visible["power_FWHM_Hz"] / 1e3,
    })
    st.dataframe(
        peak_table.style.format({
            "功率峰值频率 (MHz)": "{:.4f}",
            "有功功率峰值 (mW)": "{:.1f}",
            "安全峰值频率 (MHz)": "{:.4f}",
            "安全有功峰值 (mW)": "{:.1f}",
            "功率半高宽 (kHz)": "{:.1f}",
        }),
        width="stretch",
        hide_index=True,
    )
    st.download_button(
        "下载全部场景峰值汇总CSV",
        data=summary_path.read_bytes(),
        file_name=summary_path.name,
        mime="text/csv",
    )
    st.caption(
        "原始字段：power_peak_Hz（峰值频率，Hz）、power_peak_W（峰值高度，W）。"
        "表中为方便阅读分别换算为MHz和mW。"
    )
else:
    st.error(f"未找到阶段三汇总表：{summary_path}")

st.divider()
st.header("阶段三正式结果图")
official_figure_dir = HERE / "figures" / "stage3_disturbance"
sensitivity_figure = official_figure_dir / "stage3_01_single_factor_sensitivity.png"
representative_figure = official_figure_dir / "stage3_02_representative_responses.png"

figure_col1, figure_col2 = st.columns(2)
with figure_col1:
    st.subheader("各等级峰位、峰高与峰宽变化")
    if sensitivity_figure.is_file():
        st.image(str(sensitivity_figure), width="stretch")
        st.caption(
            "中间红色子图是有功功率峰值高度变化；上图是有功功率峰值频率偏移；"
            "下图是功率半高宽变化。"
        )
    else:
        st.error(f"缺少图片：{sensitivity_figure}")

with figure_col2:
    st.subheader("代表场景的完整有功功率频响")
    if representative_figure.is_file():
        st.image(str(representative_figure), width="stretch")
        st.caption(
            "上半部分为运动支路有功功率 P_Rm(f)，"
            "下半部分为匹配网络输入相位 arg(Z_in)；"
            "这里只展示基准和各类代表性扰动，不包含每个等级。"
        )
    else:
        st.error(f"缺少图片：{representative_figure}")

st.subheader("独立参数—有功功率峰值折线图")
trend_dir = official_figure_dir / "parameter_peak_trends"
absolute_trend = trend_dir / "stage3_05_parameter_peak_trends_absolute.png"
relative_trend = trend_dir / "stage3_06_parameter_peak_trends_relative_zoom.png"
trend_source = HERE / "results" / "tables" / "stage3_disturbance" / "stage3_parameter_peak_trends_source.csv"

trend_tab1, trend_tab2 = st.tabs(["绝对峰值（共享纵轴，推荐汇报）", "相对变化放大（各面板独立纵轴）"])
with trend_tab1:
    if absolute_trend.is_file():
        st.image(str(absolute_trend), width="stretch")
        st.caption(
            "所有面板共用同一mW纵轴，可直接比较影响强弱；灰色虚线为基准峰值约170 mW。"
        )
    else:
        st.error(f"缺少图片：{absolute_trend}")

with trend_tab2:
    if relative_trend.is_file():
        st.image(str(relative_trend), width="stretch")
        st.warning(
            "该图为了显示C0等微小变化，对每个面板单独设置纵轴；只能比较同一参数内的方向和变化，"
            "不能用视觉斜率跨面板比较影响强弱。"
        )
    else:
        st.error(f"缺少图片：{relative_trend}")

if trend_source.is_file():
    st.download_button(
        "下载参数—峰值折线图源数据CSV",
        data=trend_source.read_bytes(),
        file_name=trend_source.name,
        mime="text/csv",
    )

st.subheader("机械支路电容 Cₘ（Cm-only）专项图")
cm_only_figure = official_figure_dir / "cm_only" / "stage3_07_cm_only_power_and_electrical_limits.png"
cm_only_summary = HERE / "results" / "tables" / "stage3_disturbance" / "stage3_cm_only_power_safety_summary.csv"
if cm_only_figure.is_file():
    st.image(str(cm_only_figure), width="stretch")
    st.caption(
        "峰值频率按0.1 kHz扫描网格显示4位MHz小数，功率保留0.1 mW；"
        "电压/电流面板用于显示未限幅扫频点是否需要保护降幅，不代表声学或临床安全。"
    )
if cm_only_summary.is_file():
    st.download_button(
        "下载Cₘ单因素峰值与电气约束汇总CSV",
        data=cm_only_summary.read_bytes(),
        file_name=cm_only_summary.name,
        mime="text/csv",
    )

st.divider()
st.header("按参数查看：基准＋三个等级的完整 P(f)")
all_registered_scenarios = model.all_scenarios()
available_factors = ["C0", "Rm", "fs", "Lm", "Cm", "Rs", "Lmatch", "Cmatch", "inductor_Q", "Qm"]
factor_for_curves = st.selectbox(
    "选择参数",
    options=available_factors,
    format_func=lambda value: FACTOR_DISPLAY_NAMES.get(value, value),
    help="曲线由活动v2.1解析模型即时重算，参数等级与正式阶段三场景登记表一致。",
)

if factor_for_curves == "Qm":
    curve_scenarios = [s for s in all_registered_scenarios if s.factor == "Qm"]
else:
    baseline_scenario = next(s for s in all_registered_scenarios if s.case_id == "CASE_000_BASELINE")
    curve_scenarios = [baseline_scenario] + [
        s for s in all_registered_scenarios
        if s.factor == factor_for_curves and s.family == "single_factor"
    ]

curve_frequency = np.arange(model.F_MIN, model.F_MAX + 0.1, 100.0)
curve_colors = ["#333333", "#9DB7D5", "#527EAF", "#174F86"]
curve_figure, (curve_power_axis, curve_voltage_axis, curve_current_axis) = plt.subplots(
    3, 1, figsize=(11.2, 8.4), sharex=True,
    gridspec_kw={"height_ratios": [2.0, 1.0, 1.0]},
)
curve_rows = []
for curve_index, curve_scenario in enumerate(curve_scenarios):
    curve_response = model.response(curve_frequency, curve_scenario)
    curve_peak_index = int(np.argmax(curve_response["p_rm_W"]))
    curve_peak_frequency = float(curve_frequency[curve_peak_index])
    curve_peak_power = float(curve_response["p_rm_W"][curve_peak_index])
    curve_label = "基准" if curve_scenario.case_id == "CASE_000_BASELINE" else curve_scenario.level
    plot_label = "基准" if curve_scenario.case_id == "CASE_000_BASELINE" else curve_scenario.level
    curve_color = curve_colors[curve_index % len(curve_colors)]
    curve_power_axis.plot(
        curve_frequency / 1e6,
        curve_response["p_rm_W"] * 1e3,
        color=curve_color,
        linewidth=2.0,
        label=f"{plot_label}：{curve_peak_frequency/1e6:.4f} MHz，{curve_peak_power*1e3:.1f} mW",
    )
    curve_power_axis.scatter(
        [curve_peak_frequency / 1e6], [curve_peak_power * 1e3],
        color=curve_color, s=32, zorder=3,
    )
    curve_voltage_axis.plot(
        curve_frequency / 1e6, curve_response["vport_vpp"],
        color=curve_color, linewidth=1.5,
    )
    curve_current_axis.plot(
        curve_frequency / 1e6, curve_response["iport_irms_A"] * 1e3,
        color=curve_color, linewidth=1.5,
    )
    voltage_soft = bool(np.any(curve_response["vport_vpp"] > model.VPP_SOFT))
    voltage_hard = bool(np.any(curve_response["vport_vpp"] > model.VPP_HARD))
    current_soft = bool(np.any(curve_response["iport_irms_A"] > model.IRMS_SOFT))
    current_hard = bool(np.any(curve_response["iport_irms_A"] > model.IRMS_HARD))
    if voltage_hard or current_hard:
        constraint_status = "未限幅扫频含硬限越限点"
    elif voltage_soft or current_soft:
        constraint_status = "未限幅扫频含软限触发点"
    else:
        constraint_status = "全扫频范围未触发软限"
    curve_rows.append({
        "场景编号": curve_scenario.case_id,
        "参数": FACTOR_DISPLAY_NAMES.get(factor_for_curves, factor_for_curves),
        "等级": curve_label,
        "峰值频率 (MHz)": curve_peak_frequency / 1e6,
        "有功功率峰值 (mW)": curve_peak_power * 1e3,
        "峰值点端口电压 (Vpp)": float(curve_response["vport_vpp"][curve_peak_index]),
        "峰值点端口电流 (mA RMS)": float(curve_response["iport_irms_A"][curve_peak_index] * 1e3),
        "扫频最大端口电压 (Vpp)": float(np.max(curve_response["vport_vpp"])),
        "扫频最大端口电流 (mA RMS)": float(np.max(curve_response["iport_irms_A"]) * 1e3),
        "未限幅扫频约束状态": constraint_status,
    })

curve_plot_titles = {
    "C0": r"静态电容 $C_0$ 单因素扰动响应",
    "Rm": r"机械支路电阻 $R_m$ 单因素扰动响应",
    "fs": r"串联谐振频率 $f_s$ 单因素扰动响应",
    "Lm": r"机械支路电感 $L_m$（Lm-only）单因素扰动响应",
    "Cm": r"机械支路电容 $C_m$ 单因素扰动下的 $P_{Rm}(f)$",
    "Rs": r"戴维南源阻抗 $R_s$ 单因素扰动响应",
    "Lmatch": r"匹配电感 $L_{match}$ 单因素扰动响应",
    "Cmatch": r"匹配电容 $C_{match}$ 单因素扰动响应",
    "inductor_Q": "匹配电感品质因数Q单因素扰动响应",
    "Qm": r"机械品质因数 $Q_m$ 单因素扰动响应",
}
curve_title = curve_plot_titles[factor_for_curves]
curve_figure.suptitle(curve_title, fontsize=15, fontweight="bold", y=0.985)
curve_figure.text(
    0.5, 0.952,
    "同一冻结戴维南源与v2.1匹配网络；假设模型参数，非实测数据",
    ha="center", va="top", fontsize=10, color="#555555",
)
curve_power_axis.set_ylabel(r"$P_{Rm}$ (mW)")
curve_power_axis.legend(fontsize=9, ncol=2, loc="lower right")
curve_voltage_axis.set_ylabel("端口电压 (Vpp)")
curve_voltage_axis.axhline(model.VPP_SOFT, color="#E28E2C", linestyle="--", linewidth=1.2, label="软阈值 130 Vpp")
curve_voltage_axis.axhline(model.VPP_HARD, color="#B64342", linestyle=":", linewidth=1.4, label="硬上限 160 Vpp")
curve_voltage_axis.legend(fontsize=8, ncol=2, loc="upper right")
curve_current_axis.set_ylabel("端口电流 (mA RMS)")
curve_current_axis.set_xlabel("频率 (MHz)")
curve_current_axis.axhline(model.IRMS_SOFT * 1e3, color="#E28E2C", linestyle="--", linewidth=1.2, label="软阈值 5.5 mA")
curve_current_axis.axhline(model.IRMS_HARD * 1e3, color="#B64342", linestyle=":", linewidth=1.4, label="硬上限 6.0 mA")
curve_current_axis.legend(fontsize=8, ncol=2, loc="upper right")
for curve_axis in (curve_power_axis, curve_voltage_axis, curve_current_axis):
    curve_axis.grid(alpha=0.22)
curve_figure.tight_layout(rect=(0, 0, 1, 0.93))
st.pyplot(curve_figure, width="stretch")
plt.close(curve_figure)

st.caption(
    "上图为运动支路有功功率；下两图是归一化幅度a=1时的未限幅电压/电流包络。"
    "越过阈值表示该扫频点需要保护状态机降幅，不表示受保护控制时序实际发生硬越限。"
)

curve_summary = pd.DataFrame(curve_rows)
st.dataframe(
    curve_summary.style.format({
        "峰值频率 (MHz)": "{:.4f}",
        "有功功率峰值 (mW)": "{:.1f}",
        "峰值点端口电压 (Vpp)": "{:.1f}",
        "峰值点端口电流 (mA RMS)": "{:.3f}",
        "扫频最大端口电压 (Vpp)": "{:.1f}",
        "扫频最大端口电流 (mA RMS)": "{:.3f}",
    }),
    width="stretch",
    hide_index=True,
)

st.success(
    "机械支路电感 Lₘ（Lm-only）与机械支路电容 Cₘ（Cm-only）已纳入正式扫描：各为+5%、+10%、+20%。"
    "only表示其余BVD元件冻结；因此对应fₛ和Qₘ是派生变化量。"
    "原有fₛ扫描仍是另一种口径：指定fₛ变化并在保持Rₘ、Qₘ时联合反推Lₘ/Cₘ。"
)

st.divider()
st.header("历史扩展结果：可观测扰动检测与扫描辅助P&O")
st.warning("以下P&O时序及旧统计属于历史批次；当前计划书三策略统一结果请到独立结果页查阅，不混用排名。")
control_dir = HERE / "results" / "tables" / "stage4_5"
control_figure = HERE / "figures" / "stage4_5" / "stage4_04_observable_disturbance_detector.png"
trigger_table_path = control_dir / "stage4_observable_trigger_evaluation.csv"
control_audit_path = control_dir / "stage4_5_audit.json"

st.info(
    "控制器不读取场景切换时刻或当前场景真实最优功率。重捕获只能由端口功率、"
    "复阻抗、相位和反射代理的2-of-4连续判据，或软/硬安全限事件触发。"
    "扰动时间表和P*只保留给仿真对象及事后评分。"
)

if control_figure.is_file():
    st.image(str(control_figure), width="stretch")
    st.caption(
        "上图为按幅度平方归一化的端口有功功率；中图为异常投票和确认触发；"
        "下图为空心圆标出的低幅重捕获扫描起点及随后控制频率。灰色竖线只用于事后对照真实扰动边界。"
    )
else:
    st.error(f"缺少图片：{control_figure}")

if trigger_table_path.is_file():
    trigger_table = pd.read_csv(trigger_table_path)
    visible_columns = [
        "state_index", "case_id", "trigger_observed", "trigger_source",
        "trigger_delay_ms", "scan_started", "scan_start_delay_ms",
        "scan_points_in_segment", "detector_reason",
    ]
    st.subheader("事后触发评估表")
    st.dataframe(trigger_table[visible_columns], width="stretch", hide_index=True)
    st.download_button(
        "下载可观测触发评估CSV",
        data=trigger_table_path.read_bytes(),
        file_name=trigger_table_path.name,
        mime="text/csv",
    )

if control_audit_path.is_file():
    control_audit = json.loads(control_audit_path.read_text(encoding="utf-8"))
    detector_config = control_audit.get("disturbance_detector", {})
    st.success(
        f"控制审核：{control_audit.get('status', 'UNKNOWN')}；"
        f"检测逻辑={control_audit.get('detector_logic_pass')}；"
        f"扫描触发来源审核={control_audit.get('observable_scan_reason_pass')}；"
        f"实际硬越限={control_audit.get('actual_hard_violation_total')}。"
    )
    st.warning(
        "当前检测阈值、20 ms控制周期、0.4 s冷却时间及无噪声相量均为仿真假设。"
        "尚未包含ADC噪声、采样同步误差、功放动态、通信延迟或真实换能器数据。"
    )
    with st.expander("查看扰动检测器假设参数"):
        st.json(detector_config)

st.divider()
st.header("历史约束审核与结构—声场接口")
st.caption("以下审核保留原批次身份，不代表当前统一结果已通过全部约束；接口模板不是声场求解结果。")
constraint_audit_path = HERE / "results" / "audits" / "constrained_control_audit.json"
plan_audit_path = HERE / "results" / "audits" / "plan_control_coupling_audit.json"
interface_dir = HERE / "interfaces" / "electro_acoustic_v1"
interface_audit_path = HERE / "results" / "interfaces" / "electro_acoustic_v1" / "electro_acoustic_interface_audit.json"

if constraint_audit_path.is_file():
    constraint_audit = json.loads(constraint_audit_path.read_text(encoding="utf-8"))
    checks = constraint_audit.get("checks", {})
    st.success(
        f"控制问题审核：{constraint_audit.get('status')}。"
        f"频率边界={checks.get('frequency_hard_boundary_enforced')}；"
        f"电压/电流硬限={checks.get('voltage_and_current_hard_limits_enforced_in_saved_timeline')}；"
        f"保护状态机={checks.get('protection_state_machine_exercised')}。"
    )
    st.warning(
        "反射代理目前参与异常检测和重捕获触发，但没有独立硬上限；"
        "壁面声压代理因没有COMSOL/ANSYS结果，尚未接入幅度保护。"
    )

if plan_audit_path.is_file():
    plan_audit = json.loads(plan_audit_path.read_text(encoding="utf-8"))
    st.caption(
        f"计划书条目审核：完成{plan_audit.get('completed_count')}项，"
        f"部分完成{plan_audit.get('partial_count')}项，"
        f"未开始{plan_audit.get('not_started_count')}项。"
    )

plan_phase_table_path = HERE / "results" / "tables" / "stage4_5" / "plan_fixed_periodic_phase_integrated.csv"
if plan_phase_table_path.is_file():
    with st.expander("查看计划书口径的固定—周期扫频—相位闭环补充表"):
        st.warning(
            "这张表使用共同代表扰动时间表，但相位闭环仍是Kphi=5 Hz/deg消融；"
            "它不替代正式固定—周期扫频—扫描辅助P&O综合表。"
        )
        st.dataframe(pd.read_csv(plan_phase_table_path), width="stretch", hide_index=True)
        st.download_button(
            "下载固定—周期扫频—相位闭环补充表",
            plan_phase_table_path.read_bytes(),
            file_name=plan_phase_table_path.name,
            mime="text/csv",
        )

interface_csv = interface_dir / "electrical_to_acoustic_operating_points.csv"
coupled_template = interface_dir / "coupled_lookup_template.csv"
return_template = interface_dir / "acoustic_results_return_template.csv"
field_dictionary = interface_dir / "interface_field_dictionary.csv"

if interface_csv.is_file():
    st.subheader("可交给结构—声场求解器的电学工作点")
    interface_table = pd.read_csv(interface_csv)
    st.dataframe(
        interface_table[[
            "record_id", "scenario_id", "frequency_Hz", "vport_Vpp",
            "vport_phase_deg", "p_port_W", "p_rm_W", "eta_elec",
            "reflection_proxy_gamma", "admissible_for_fem_run", "electrical_status",
        ]],
        width="stretch",
        hide_index=True,
    )
    st.info(
        "有限元端建议使用 frequency_Hz 与复端口电压作为谐波激励；"
        "预测电流只用于回算校核。P_Rm不是声功率，eta_elec不是声电效率。"
    )
    download_columns = st.columns(4)
    for column, path, label in [
        (download_columns[0], interface_csv, "下载电学激励CSV"),
        (download_columns[1], coupled_template, "下载耦合查找表模板"),
        (download_columns[2], return_template, "下载声场回传模板"),
        (download_columns[3], field_dictionary, "下载字段字典"),
    ]:
        if path.is_file():
            with column:
                st.download_button(label, path.read_bytes(), file_name=path.name, mime="text/csv")

if interface_audit_path.is_file():
    interface_audit = json.loads(interface_audit_path.read_text(encoding="utf-8"))
    st.caption(
        f"接口内部一致性审核：{interface_audit.get('status')}；"
        f"电学记录数={interface_audit.get('electrical_record_count')}；"
        f"结构/声场求解器已运行={interface_audit.get('finite_element_solver_was_run')}。"
    )
