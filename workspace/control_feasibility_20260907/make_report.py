"""Python-only evidence figures and an explicit limited-scope report."""
import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import run_experiments as exp

OUT = exp.HERE / "deliverables"
VERSIONS = ["E00", "E01", "E02"]
COLORS = {"E00": "#737C87", "E01": "#C18536", "E02": "#2875AD"}
LABELS = {"E00": "E00 原版复现", "E01": "E01 保护一致性修正", "E02": "E02 保护后优先重扫"}
STYLES = {"E00": ("-", 1.7), "E01": ("--", 1.9), "E02": ("-", 2.3)}
STRATEGIES = {"FIXED_0P9": "固定频率", "PERIODIC_SCAN": "周期扫频", "P_AND_O": "扫描辅助P&O"}
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
                     "font.size": 13, "axes.titlesize": 15, "axes.labelsize": 14,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "svg.fonttype": "none", "pdf.fonttype": 42})


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def num(r, key):
    return float(r[key]) if r[key] != "" else math.nan


def save(fig, stem):
    for ext in ("png", "svg", "pdf"):
        fig.savefig(OUT / f"{stem}.{ext}", dpi=200, facecolor="white")
    plt.close(fig)


def step_series(rows, key, start=2.4, end=3.2, scale=1):
    x, y = [], []
    for r in rows:
        left, right = max(num(r, "time_s"), start), min(num(r, "time_s") + num(r, "duration_s"), end)
        if right - left <= 1e-12:
            continue
        x.extend([left - start, right - start])
        y.extend([num(r, key) * scale] * 2)
    return x, y


def figure_recovery():
    fig, axes = plt.subplots(3, 2, figsize=(16, 12), sharex=True,
                             gridspec_kw={"height_ratios": [1.25, 1, 1]})
    fig.subplots_adjust(left=.085, right=.975, bottom=.17, top=.80, wspace=.18, hspace=.25)
    fig.suptitle("改变恢复顺序后，频移段出现了符合原标准的连续窗口", fontsize=21, fontweight="bold", y=.97)
    fig.text(.5, .928, "原0.8 s扰动段；所有扫描、保护、试探样本均显示；不是持续满功率或硬件安全证明", ha="center", color="#53606D")
    for col, strategy in enumerate(("PERIODIC_SCAN", "P_AND_O")):
        for version in VERSIONS:
            folder = exp.RESULTS / f"{version}_dwell_0.8s"
            rows = [r for r in read_csv(folder / "timeline.csv") if r["strategy"] == strategy]
            metrics = next(r for r in read_csv(folder / "acceptance_and_energy.csv")
                           if r["strategy"] == strategy and r["case_id"] == "CASE_FS_M5")
            for row, key, scale in ((0, "safe_power_capture_ratio", 100), (1, "frequency_Hz", 1e-6), (2, "amplitude_command", 1)):
                x, y = step_series(rows, key, scale=scale)
                ls, lw = STYLES[version]
                axes[row, col].plot(x, y, ls=ls, lw=lw, color=COLORS[version], label=LABELS[version])
            if version == "E02":
                t1 = num(metrics, "accepted_start_s") - 2.4
                t2 = num(metrics, "confirmation_s") - 2.4
                axes[0, col].axvspan(t1, t2, color=COLORS[version], alpha=.09)
                axes[0, col].plot(t2, 100, "o", color=COLORS[version], ms=7)
                axes[0, col].annotate(f"第10个样本：{t2*1000:.0f} ms", (t2, 100),
                                     xytext=(.38, 116), textcoords="data", color=COLORS[version],
                                     arrowprops={"arrowstyle": "->", "color": COLORS[version]}, fontsize=13)
        axes[0, col].set_title(STRATEGIES[strategy], loc="left", fontweight="bold", pad=14)
        axes[0, col].axhline(98, color="#444444", lw=.8, ls=":")
        axes[0, col].set_ylim(-4, 132)
        axes[0, col].set_yticks([0, 50, 100])
        axes[1, col].axhline(.8548, color="#97A4AF", ls=":", lw=.8)
        axes[1, col].set_ylim(.8, .96)
        axes[1, col].set_yticks([.80, .8548, .90, .95], ["0.8000", "0.8548", "0.9000", "0.9500"])
        axes[2, col].set_ylim(-.03, 1.1)
        axes[2, col].set_xlabel("距扰动开始时间（s）")
        for row in range(3):
            axes[row, col].set_xlim(0, .8)
            axes[row, col].grid(axis="y", color="#DFE5EB", lw=.7)
    for a, label in zip(axes[:, 0], ["记录的功率捕获率（%）", "控制及扫描频率（MHz）", "实际源幅度比例 a"]):
        a.set_ylabel(label)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .89), ncol=3, frameon=False)
    fig.text(.085, .04, "原验收：NORMAL、CONTROL、频率控制未冻结、捕获率≥98%，连续10个样本（20 ms周期）。\n"
             "按各记录对应场景安全最优归一化；本频移场景为140.2 mW。周期扫频通过窗口后仍会再次扫描。\n"
             "曲线按记录值保持显示，不表示采样间隙内的真实变化；间隙风险另行重放核查。假设BVD模型，非实测。", fontsize=12, color="#53606D")
    save(fig, "01_fs_recovery_ablation")


def figure_summary(summary):
    fig, axes = plt.subplots(2, 2, figsize=(16, 10.5))
    fig.subplots_adjust(left=.085, right=.98, bottom=.17, top=.80, wspace=.22, hspace=.42)
    fig.suptitle("局部验收改善，不代表全过程性能全面优于原版", fontsize=21, fontweight="bold", y=.97)
    fig.text(.5, .925, "0.8 s主测试；统计第1—7评价段（不含初始基线）；全部动作均计入能量", ha="center", color="#53606D")
    strategies = list(STRATEGIES)
    fields = [("settled_segments_of_7", "a 通过连续窗口验收的段数", "段数 / 7", (0, 7.9)),
              ("held_energy_capture_pct", "b 全过程电学能量捕获率", "能量比例（%）", (0, 100)),
              ("scan_action_time_ms", "c 扫描及准备动作总时间", "时间（ms）", (0, 1100)),
              ("held_command_hard_violation_ms", "d 采样间隙：保持指令重放风险", "准稳态重放越限时间（ms）", (0, 48))]
    x, width = np.arange(3), .24
    for ax, (field, title, ylabel, ylim) in zip(axes.flat, fields):
        for j, version in enumerate(VERSIONS):
            values = [num(next(r for r in summary if r["variant"] == version and r["strategy"] == s and float(r["segment_duration_s"]) == .8), field) for s in strategies]
            bars = ax.bar(x + (j - 1) * width, values, width, color=COLORS[version], label=LABELS[version],
                          hatch="//" if version == "E01" else None)
            ax.bar_label(bars, labels=[f"{v:.0f}" if field in ("settled_segments_of_7", "scan_action_time_ms") else f"{v:.1f}" for v in values], padding=4, fontsize=12)
        ax.set_xticks(x, [STRATEGIES[s] for s in strategies])
        ax.set_ylim(*ylim)
        ax.set_title(title, loc="left", pad=12, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", color="#E1E6EB", lw=.7)
        ax.set_axisbelow(True)
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.5, .89), ncol=3, frameon=False)
    fig.text(.085, .04, "能量分母：各场景软限约束最优功率的时间积分；不是电学效率η_elec或声学效率。\n"
             "d图按采样间隔保持上一指令、负载在预定时刻改变重放；不是LTspice瞬态或实测越限。各版本记录点硬越限均为0。", fontsize=12, color="#53606D")
    save(fig, "02_whole_sequence_tradeoffs")


def figure_ltspice():
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.3))
    fig.subplots_adjust(left=.08, right=.98, bottom=.28, top=.78, wspace=.2)
    fig.suptitle("本次真实LTspice AC输出与Python解析模型交叉验证", fontsize=19, fontweight="bold", y=.97)
    fig.text(.5, .9, "fs−5%场景；0.25 / 0.40 / 1.00三档源幅度；同一冻结元件参数", ha="center", color="#53606D")
    for a, color in ((.25, "#777D84"), (.4, "#B77734"), (1, "#2875AD")):
        rows = read_csv(exp.HERE / f"ltspice_ac_verification/CASE_FS_M5_a{a:.2f}_comparison.csv")
        rows = [r for r in rows if .85e6 <= num(r, "frequency_Hz") <= .86e6]
        f = [num(r, "frequency_Hz") / 1e6 for r in rows]
        axes[0].plot(f, [num(r, "prm_lt_W") * 1000 for r in rows], color=color, lw=2, label=f"a={a:.2f} LTspice")
        axes[0].plot(f[::5], [num(r, "prm_python_W") * 1000 for r in rows][::5], "o", mfc="none", ms=4, color=color)
        axes[1].plot(f, [100 * abs(num(r, "prm_lt_W") / num(r, "prm_python_W") - 1) for r in rows], color=color, lw=1.8)
    axes[0].set_ylabel("P_Rm（mW）")
    axes[0].legend(frameon=False, fontsize=11)
    axes[0].set_title("实线：RAW；空心点：Python", loc="left")
    axes[1].set_ylabel("P_Rm相对误差（%）")
    axes[1].set_title("误差曲线重合反映线性幅度缩放", loc="left")
    for ax in axes:
        ax.set_xlabel("频率（MHz）")
        ax.grid(color="#E1E6EB", lw=.7)
    fig.text(.08, .04, "总计4个场景×3档幅度、每组2001频点。未施加控制限幅的AC验证曲线，不代表全部频点可安全驱动。\n"
             "此图由Python读取真实RAW生成，不是LTspice GUI截图；未验证控制切换瞬态。", fontsize=11, color="#53606D")
    save(fig, "03_real_ltspice_ac_check")


def report(summary):
    lt = json.loads((exp.HERE / "ltspice_ac_verification/audit.json").read_text(encoding="utf-8"))
    tests = json.loads((exp.RESULTS / "independent_tests.json").read_text(encoding="utf-8"))
    lines = ["# 控制流程可行性验证：第一轮结果", "",
             "结论：保护后优先低幅重扫在fs−5%主测试段中具有局部可行性；两个自适应策略均出现符合原标准的连续窗口。但整体能量并未全面超过原版，且采样间隙风险仍存在。不能发布为硬件安全已证明或整体最优算法。", "",
             "## 1. 实际完成了什么", "",
             "- 原控制器重新执行，1795行×43字段与历史时序完全一致（数值差0）。历史6/10和9/10没有改写。",
             "- E01、E02及旧版均执行0.8 s主测试和1.6 s补充测试，共18条策略时序。所有版本配置、原始行数据和验收表独立保存。",
             "- 在新目录再次运行全部Python实验，20个结果CSV逐字节一致；本次复现记录见deliverables/repeatability_check.json。",
             "- 独立检查通过82项，包括全部动作保护调用、幅度状态一致性、保持时长、升幅速率、时间覆盖及离线最优信息不影响控制指令。",
             "- 真正执行LTspice 26.0.2.1命令行AC验证：4个场景×3档源幅度，每组2001点，共12个新RAW/LOG。未进行新的LTspice控制器瞬态或GUI截图。", "",
             "## 2. 版本定义与公平比较", "",
             "|版本|改动|", "|---|---|",
             "|E00|原始脚本精确复现，保留已知扫描幅度状态和动作成本缺陷，作为历史对照，不再视为经过完整保护审查的实现。|",
             "|E01|扫描/试探/控制全部经过统一保护；幅度状态同步；先低幅准备、再调频；显式计入选择/返回动作；统一恢复升幅速率；修复仅浮点精度级的场景时刻判断。仍在旧频率恢复后重扫。|",
             "|E02|只在E01基础上改变保护后重捕获就绪条件；保持期结束后允许低幅重扫、选频后恢复。周期扫频仍受原定时器限制，未改成事件触发策略。|", "",
             "因此E00→E01是多个关联实现修正的整体验证，不能把其差值归因为单独某一行代码；E01→E02是调度顺序消融。", "",
             "冻结参数：20 ms控制周期；60 ms硬保持+100 ms恢复保持；100 ms软降额稳定期；0.05/20 ms升幅上限；频段0.8—1.0 MHz；软限130 Vpp/5.5 mA RMS、硬限160 Vpp/6 mA RMS；同一冻结源。所有非实测设置均登记为假设。",
             "E02从0.25幅度保持结束后直接以不高于该幅度重扫；不是强行升到0.4。常规扫描仍以不高于0.4的幅度进行。频率选择与后续升幅是独立计时动作。", "",
             "## 3. 原0.8 s频移段的验收", "",
             "|版本|策略|最长连续合格样本|本段通过|第10样本确认延迟（ms）|本段能量捕获率（%）|",
             "|---|---|---:|---|---:|---:|"]
    for r in summary:
        if float(r["segment_duration_s"]) != .8 or r["strategy"] == "FIXED_0P9":
            continue
        confirm = "未确认" if not r["fs_confirmation_delay_ms"] else f"{float(r['fs_confirmation_delay_ms']):.1f}"
        lines.append(f"|{r['variant']}|{STRATEGIES[r['strategy']]}|{int(float(r['fs_max_consecutive_good']))}|{'是' if r['fs_settled']=='1' else '否'}|{confirm}|{float(r['fs_held_energy_capture_pct']):.2f}|")
    lines += ["", "验收仍为CONTROL、NORMAL、频率控制未冻结、捕获率≥98%，连续10个样本。20 ms周期下，第1至第10个样本跨越180 ms。确认延迟与旧表的成功连续区间起点延迟不同，不可混用。",
              "捕获率按当前场景安全最优140.2 mW归一化，不等于恢复基准170.0 mW。",
              "E02周期扫频第10个样本为3.145 s；3.165 s又开始常规低幅扫描。因此本表只证明存在合格连续窗口，不证明此后一直保持满功率。P&O第10个样本为3.141 s。", "",
              "## 4. 完整序列并非全面更优", "",
              "|版本|策略|通过段数/7|全过程能量捕获率（%）|记录点硬越限行|采样间隙重放越限时间（ms）|",
              "|---|---|---:|---:|---:|---:|"]
    for r in summary:
        if float(r["segment_duration_s"]) == .8:
            lines.append(f"|{r['variant']}|{STRATEGIES[r['strategy']]}|{r['settled_segments_of_7']}|{float(r['held_energy_capture_pct']):.2f}|{r['sampled_hard_violation_rows']}|{float(r['held_command_hard_violation_ms']):.2f}|")
    lines += ["", "能量统计包括保护、低幅扫描、试探和恢复过程，不剔除不利样本。分母是各场景软限最优功率的时间积分，不是源功率、声学功率或η_elec。时间范围为初始基线之后的7段。",
              "能量采用采样指令保持、按真实场景切换边界分段计算的准稳态重放，另保留直接积分记录功率的旧口径。高功率但越限的区间不能视为安全收益；所以只有记录点零越限仍不足以宣布安全优化成功。",
              "固定频率在本序列中能量比例较高，是因部分扰动不需重新寻峰，固定策略不承担扫描成本。不能外推固定频率普遍更好。",
              "E02中周期扫频仍有Q_L=20段未通过；P&O在C0+30%、Rm+50%及高组合段未通过。旧P&O定时试探及渐升会占用连续NORMAL测量时间，需下一轮单独验证试探调度/参考建立与异常检测的相互影响。", "",
              "## 5. 采样间隙与安全边界", "",
              "Guard仍使用精确已知模型预估每个动作的允许幅度，沿用虚拟保护假设。它不是有测量误差的硬件保护器。记录点全部小于硬限只说明动作执行后计算值合规。",
              "独立重放假设在两次控制/扫描采样之间保持上一指令，负载在既定时刻发生突变；E02仍产生正的越限持续时间。该结果揭示采样延迟风险，不是实测越限，也不是考虑储能和振铃的LTspice .tran结果。硬限绝不超过的连续时间要求尚未证明。", "",
              "## 6. 延长保持时间的补充测试", "",
              "|版本|策略|1.6 s频移段通过|全序列通过段数/7|能量捕获率（%）|", "|---|---|---|---:|---:|"]
    for r in summary:
        if float(r["segment_duration_s"]) == 1.6 and r["strategy"] != "FIXED_0P9":
            lines.append(f"|{r['variant']}|{STRATEGIES[r['strategy']]}|{'是' if r['fs_settled']=='1' else '否'}|{r['settled_segments_of_7']}|{float(r['held_energy_capture_pct']):.2f}|")
    lines += ["", "延长的是所有扰动段，控制器与采样相对相位会随之变化；不能把两组恢复时间差单纯解释成算法改善。旧版在长保持频移段也能通过，支持观察时长会影响验收，但不是原0.8 s结果已通过。", "",
              "## 7. LTspice工作点核验", "",
              f"12次进程返回码均为0，最大Zin相对误差{max(x['max_zin_relative_error_pct'] for x in lt['runs']):.6f}%，最大端口电压相对误差{max(x['max_vport_relative_error_pct'] for x in lt['runs']):.6f}%，最大端口电流相对误差{max(x['max_iport_relative_error_pct'] for x in lt['runs']):.6f}%，最大P_Rm相对误差{max(x['max_prm_relative_error_pct'] for x in lt['runs']):.6f}%。均小于既定5%交叉验证阈值。",
              "输入为基准、fs−5%、Lmatch+10%、高组合场景，源幅度比例0.25/0.40/1.00。RAW数据与网表、LOG、返回码及SHA256一并保存。未限幅的单位幅度AC扫频包括不安全工作点，只用于求解器对照，不可作为安全驱动结果。", "",
              "## 8. 未完成内容与下一道关口", "",
              "1. 连续时间硬限、实际采样/执行延迟及频率切换瞬态未验证；需要动态仿真、噪声及保护延迟测试。",
              "2. P&O的试探调度、稳态保持和参考建立需要单独消融，不能为凑10个样本删除不利动作。",
              "3. 目前搜索目标仍是幅度归一化端口功率，不是考虑各频点允许幅度后的受约束最优功率；需下一轮单独比较。",
              "4. Zhang多指标协同、Feng分层调幅、Ye ESC和Williams安全过滤尚未实施，不宣称复现文献算法。",
              "5. 本轮仍为固定/周期扫频/P&O；原计划相位闭环的统一正式比较不能被这组结果替代。",
              "6. 未覆盖所有34个参数场景的闭环；已覆盖的是相同8段、7种唯一场景。无测量数据或COMSOL声学结果。",
              "7. 当前模型Rm-only的历史Qm元数据不随Rm变化；本轮参数表另列由原始元件重算的Qm，未改动电路或覆盖历史文件。", "",
              "## 9. 可直接用于组会的表述", "",
              "> 在保持原扰动序列、限值及连续验收标准不变的情况下，先统一保护与幅度状态，再将保护恢复后的重扫提前，能够使两种自适应策略在fs−5%段中出现符合原验收要求的连续工作窗口。该结果仅证明局部恢复流程的可行性；全过程能量、其他扰动场景以及采样间隙安全仍未全面达标。", "",
              "## 10. 复现", "",
              "建议在保留原项目目录结构的情况下运行：`python rerun_in_new_folder.py`。该入口在新的同级时间戳目录重新执行18条Python控制时序和独立检查，并逐字节核对CSV，不覆盖本次结果；它需要原始项目输入可访问且未变，不是跨机器独立部署入口，也不重新运行LTspice。",
              "`run_experiments.py`和`validate_experiments.py`为本次真实执行源码；勿在证据目录内直接运行覆盖已存结果。`python make_report.py`可从已存数据重画图。LTspice新验证应在新工作副本中生成新RAW/LOG，不覆盖本轮12组。",
              "脚本、冻结输入、历史结果及本轮CSV/JSON均保留；PPT和正式网页未自动替换。"]
    (OUT / "第一轮仿真验证报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    summary = read_csv(exp.RESULTS / "summary.csv")
    figure_recovery()
    figure_summary(summary)
    figure_ltspice()
    report(summary)
    exp.save_json(OUT / "figure_contract.json", {
        "claim": "Recovery-first scan improves a local acceptance window, not overall dominance or continuous-time safety",
        "archetype": "quantitative grid", "backend": "Python matplotlib", "formats": ["PNG", "SVG", "PDF"],
        "replicates": "one deterministic run per registered configuration; no statistical inference",
        "data": "results_r1 timelines and summary; newly generated LTspice RAW comparisons",
        "integrity": "all action samples retained; explicit recorded-duration hold rendering; no smoothing, value offsets, or hidden scans",
        "normalization": "current scenario soft-constrained optimum, or its duration integral, never acoustic efficiency",
        "tests": "independent_tests.json", "editable_text": True,
        "controller_LTspice_transient_validated": False, "native_GUI_screenshot": False})
    print("Report and 3 PNG/SVG/PDF figures generated.")


if __name__ == "__main__":
    main()
