"""Source-grounded report and Python-only complete scientific figures."""
import csv
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import run_factorial as r
from run_diagnostics import stress_scenarios

OUT = r.HERE / "deliverables"
LABELS = {"E02_000": "000 对照", "E03_A": "A 相位辅助", "E04_B": "B 独立调幅", "E05_C": "C 约束评分",
          "E06_AB": "A+B", "E07_AC": "A+C", "E08_BC": "B+C", "E09_ABC": "A+B+C",
          "D01_LOCAL": "仅局部功率", "D02_LOCAL_BC": "局部功率+B+C"}
STRATEGIES = {"FIXED_0P9": "固定频率", "PERIODIC_SCAN": "周期扫频", "P_AND_O": "扫描辅助P&O"}
COLORS = {"PERIODIC_SCAN": "#327BA8", "P_AND_O": "#B8584C"}


def read(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as h:
        return list(csv.DictReader(h))


def save(fig, stem):
    for ext in ("png", "svg", "pdf"):
        fig.savefig(OUT / f"{stem}.{ext}", dpi=200, facecolor="white")
    plt.close(fig)


def pick(rows, name, strategy, dwell):
    return next(x for x in rows if x["name"] == name and x["strategy"] == strategy and float(x["segment_duration_s"]) == dwell)


def factorial_plot(rows):
    names = [x.name for x in r.VARIANTS[:8]]
    y = np.arange(8)
    fig, axes = plt.subplots(1, 3, figsize=(17, 10), sharey=True)
    fig.subplots_adjust(left=.15, right=.97, bottom=.21, top=.76, wspace=.25)
    fig.suptitle("完整组合验证：通过段数、全过程能量与采样间隙风险必须一起看", fontsize=21, fontweight="bold", y=.96)
    fig.text(.5, .908, "原0.8 s/段序列；同一限值、计时和连续验收；C未改变最终控制工作点，少量扫描路径不同", ha="center", color="#576574", fontsize=14)
    metrics = [("settled_segments_of_7", "a  连续窗口验收", "通过段数 / 7", 7.7),
               ("held_energy_capture_pct", "b  全过程电学能量", "能量捕获率（%）", 75),
               ("held_command_hard_violation_ms", "c  采样间隙重放风险", "准稳态重放越限时间（ms）", 24)]
    for axis, (field, title, xlabel, xmax) in zip(axes, metrics):
        for j, strategy in enumerate(("PERIODIC_SCAN", "P_AND_O")):
            values = [float(pick(rows, name, strategy, .8)[field]) for name in names]
            bars = axis.barh(y + (j-.5)*.33, values, height=.31, color=COLORS[strategy], label=STRATEGIES[strategy])
            axis.bar_label(bars, labels=[f"{v:.0f}" if field == "settled_segments_of_7" else f"{v:.1f}" for v in values], padding=4, fontsize=12)
        axis.set_xlim(0, xmax)
        axis.set_title(title, loc="left", fontsize=16, fontweight="bold", pad=14)
        axis.set_xlabel(xlabel, fontsize=14)
        axis.grid(axis="x", color="#E3E7EB", lw=.7)
        axis.set_axisbelow(True)
        axis.set_yticks(y, [LABELS[n] for n in names])
    axes[0].invert_yaxis()
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.55, .86), ncol=2, frameon=False, fontsize=14)
    fig.text(.15, .055, "A=相位提示+局部功率核验；B=独立幅度PI；C=允许幅度下功率评分。无统计重复或显著性推断。\n"
             "能量分母为各场景软限最优功率的时间积分，不是η_elec；越限区间的能量也在总量中，不能计作安全收益。\n"
             "记录点均无硬越限，但采样间隙重放存在越限；这不是LTspice瞬态或实测安全证明。假设BVD模型。", fontsize=12, color="#576574")
    save(fig, "01_factorial_main_tradeoffs")


def attribution_plot(rows, static):
    fig, axes = plt.subplots(1, 2, figsize=(15.5, 8.2))
    fig.subplots_adjust(left=.09, right=.97, bottom=.24, top=.76, wspace=.28)
    fig.suptitle("局部功率搜索的收益，不能全部归功于相位提示", fontsize=21, fontweight="bold", y=.95)
    names = ["E02_000", "E03_A", "D01_LOCAL"]
    labels = ["对照：原扫描", "相位提示+局部功率", "仅局部功率"]
    colors = ["#7C8793", "#327BA8", "#C28B3F"]
    means = [np.mean([float(x["elapsed_ms"]) for x in static if x["variant"] == name and x["scope"] == "registered"]) for name in names]
    bars = axes[0].bar(range(3), means, color=colors, width=.55)
    axes[0].bar_label(bars, labels=[f"{v:.2f} ms" for v in means], fontsize=13, padding=5)
    axes[0].set_xticks(range(3), ["原扫描", "相位+局部", "仅局部"])
    axes[0].set_ylim(0, 145)
    axes[0].set_ylabel("单次搜索平均耗时（ms）")
    axes[0].set_title("a  34场景静态搜索诊断", loc="left", fontweight="bold", pad=15)
    axes[0].text(.03, .92, "三者均32/34达到安全峰值的98%\n失败场景仍计入平均耗时", transform=axes[0].transAxes, va="top", fontsize=12)
    x, width = np.arange(2), .23
    for k, name in enumerate(names):
        values = [float(pick(rows, name, "PERIODIC_SCAN", dwell)["held_energy_capture_pct"]) for dwell in (.8, 1.6)]
        bars = axes[1].bar(x+(k-1)*width, values, width, color=colors[k], label=labels[k])
        axes[1].bar_label(bars, labels=[f"{v:.2f}" for v in values], padding=4, fontsize=12)
    axes[1].set_xticks(x, ["主测试：0.8 s/段", "补充：1.6 s/段"])
    axes[1].set_ylim(0, 80)
    axes[1].set_ylabel("全过程能量捕获率（%）")
    axes[1].set_title("b  周期扫频完整闭环", loc="left", fontweight="bold", pad=15)
    fig.legend(*axes[1].get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.5, .86), ncol=3, frameon=False, fontsize=12)
    for ax in axes:
        ax.grid(axis="y", color="#E3E7EB", lw=.7)
        ax.set_axisbelow(True)
    fig.text(.09, .055, "静态诊断每次从同一0.9000 MHz、a=0.25及已测基准相位开始，不含异常检测和保护恢复成本。\n"
             "闭环包括保护、扫描、恢复及所有试探。两者不是同一指标；扫描节奏也会改变后续动作与扰动的相对时刻。\n"
             "只有在本轮相位位置、参数和测试集合内，未见相位提示优于匹配的局部功率对照；不外推为一般结论。", fontsize=12, color="#576574")
    save(fig, "02_phase_matched_ablation")


def constraint_plot(model, objective, base):
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), sharex=True)
    fig.subplots_adjust(left=.09, right=.97, bottom=.19, top=.78, wspace=.22, hspace=.29)
    fig.suptitle("约束真正起作用时：最大原始功率点不等于最大允许功率点", fontsize=21, fontweight="bold", y=.96)
    fig.text(.5, .907, "探索性Rm负向扰动；不并入原序列成绩，不改变源上限或保护阈值", ha="center", color="#576574", fontsize=14)
    source = []
    for col, (key, scenario) in enumerate(stress_scenarios(model).items()):
        f = np.arange(898000., 902000.1, 100.)
        p = model.response(f, scenario)["p_rm_W"]
        safe = model.safe_power(f, scenario)
        allow = model.allowed_amplitude(f, scenario, use_soft_limits=True)
        row = next(x for x in objective if x["case_id"] == key)
        fp = float(row["safe_power_peak_Hz"])/1e6
        axes[0, col].plot(f/1e6, p*1000, color="#327BA8", lw=2, label="a=1原始功率（未限幅）")
        axes[0, col].plot(f/1e6, safe*1000, color="#B8584C", lw=2, ls="--", label="允许幅度下功率J(f)")
        axes[0, col].axvline(.9, color="#888888", lw=1, ls=":")
        axes[0, col].axvline(fp, color="#B8584C", lw=1, ls=":")
        axes[0, col].plot(fp, float(row["safe_peak_W"])*1000, "o", color="#B8584C", ms=6)
        axes[0, col].set_title(f"{'a' if col==0 else 'b'}  Rm{scenario.level}", loc="left", fontweight="bold")
        axes[0, col].text(.03, .94, f"原始峰位：0.9000 MHz\n约束峰位：{fp:.4f} MHz\n允许功率峰值：{float(row['safe_peak_W'])*1000:.1f} mW",
                          transform=axes[0, col].transAxes, va="top", fontsize=12,
                          bbox={"facecolor":"white", "edgecolor":"none", "alpha":.85})
        axes[0, col].set_ylim(0, 210)
        axes[0, col].set_ylabel("电学有功功率（mW）")
        axes[1, col].plot(f/1e6, allow, color="#327BA8", lw=2)
        axes[1, col].axhline(1, color="#888888", lw=1, ls=":")
        axes[1, col].axvline(.9, color="#888888", lw=1, ls=":")
        axes[1, col].set_ylim(0, 1.05)
        axes[1, col].set_ylabel("允许源幅度比例 a_allow")
        axes[1, col].set_xlabel("频率（MHz）")
        axes[1, col].text(.03, .09, f"原始峰位允许幅度：{float(row['allowed_amplitude_at_raw_peak']):.3f}",
                          transform=axes[1, col].transAxes, fontsize=12, color="#576574")
        for i, ff in enumerate(f):
            source.append({"case_id": key, "frequency_Hz": ff, "raw_power_W": p[i], "allowed_power_W": safe[i], "allowed_amplitude": allow[i]})
        for ax in axes[:, col]:
            ax.grid(color="#E3E7EB", lw=.7)
            ax.set_xticks([.898, .899, .900, .901, .902])
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(.5, .861), ncol=2, frameon=False, fontsize=13)
    fig.text(.09, .05, "J(f)=Pport(f,a)/a² × min(1,130a/Vpp,0.0055a/Irms)²；按100 Hz网格求峰，非1 Hz精度。\n"
             "原始蓝线不是安全驱动曲线。仅为假设线性BVD的电学目标对比，不能证明频率切换过程安全。", fontsize=12, color="#576574")
    base.save_csv(OUT / "03_constraint_figure_source.csv", source)
    save(fig, "03_binding_constraint_objective")


def write_report(summary, static, objective):
    tests = json.loads((r.RESULTS / "independent_tests.json").read_text(encoding="utf-8"))
    lt = json.loads((r.HERE / "ltspice/audit.json").read_text(encoding="utf-8"))
    text = ["# 相位辅助、独立调幅与受约束选频：第二轮消融结果", "",
            "结论：三项均已编码并分别、组合运行；没有在原测试序列中全面胜出的组合。原序列未激活峰位处的软约束，C没有改变最终控制工作点，但少量扫描路径不同，能量存在很小差异。探索性电流受限测试显现了C改变工作点的作用。A/B的测试结果随组合和段时长而异，不能声称论文方法已经复现或硬件安全已经证明。", "",
            "## 1. 实际执行与版本", "",
            "8组2^3完整组合+2组去相位的匹配对照；各运行固定频率、周期扫频、扫描辅助P&O，在0.8 s/段和1.6 s/段两个相同序列下共60条策略时序。B开启时的固定频率策略有调幅，不能称固定幅度。",
            "另执行216次静态搜索诊断（34个注册场景+2个探索性约束场景，各6个搜索版本），及探索性负Rm序列8版本×3策略，共24条时序。静态诊断不是34场景闭环均已验收。",
            f"另写校验脚本通过{tests['check_count']}项检查，包括原E02两个时序精确复现、所有动作保护、保持时长、升幅、幅度状态、相位正负斜率/跨±180°及离线最优信息不影响指令。软件测试不是物理安全证明。", "",
            "|版本|相位提示A|独立调幅B|约束评分C|", "|---|---|---|---|"]
    for cfg in r.VARIANTS[:8]:
        text.append(f"|{cfg.name}|{'是' if cfg.phase else '否'}|{'是' if cfg.amplitude else '否'}|{'是' if cfg.constrained else '否'}|")
    text += ["", "D01_LOCAL保留局部功率括峰检查但不使用相位；D02_LOCAL_BC同样去掉ABC中的相位提示。它们用于检验相位本身是否额外有益。", "",
             "## 2. 具体实现，不混淆概念", "",
             "A：相位为匹配网络输入相位arg(Zin)，不是端口相位；参考来自先前稳定测量或实际扫描选点，不强制0°。±500 Hz采样估计相位斜率，相位只生成候选，最终必须通过局部功率核验，失败后回退原扫频。原频率已经局部括峰时也可直接细化，所以必须设置不含相位的局部功率对照。",
             "B：独立PI在a²坐标调节功率，Kp=0.6、Ki=0.8/s，条件积分抗饱和；保护/扫描时冻结或复位，功率目标由可测V/I/P估算的允许幅度决定，不降低目标来换取验收。保护器仍负责硬停机、保持和升幅限速；未实现电流内环或完整功放。",
             "C：按J=(Pport/a²)*a_allow²选频。a_allow=min(1,130a/Vpp,0.0055a/Irms)。新优化层不读取真实扰动参数或离线最优值；但继承的保护器仍利用当前真实模型预估候选电压/电流，属于理想化已知模型保护，不是完整的可部署测量闭环。",
             "所有控制增益、斜率阈值、时序等均为本次假设，不来自论文实测参数。当前C是软限、源幅度上限a≤1下的准稳态网格局部优化，不是全局动态优化或CBF安全控制。", "",
             "## 3. 原0.8 s/段序列：正式验收与能量", "",
             "|版本|周期扫频通过/7|周期扫频能量%|P&O通过/7|P&O能量%|",
             "|---|---:|---:|---:|---:|"]
    for cfg in r.VARIANTS:
        a, b = [pick(summary, cfg.name, strategy, .8) for strategy in ("PERIODIC_SCAN", "P_AND_O")]
        text.append(f"|{LABELS[cfg.name]}|{a['settled_segments_of_7']}|{float(a['held_energy_capture_pct']):.2f}|{b['settled_segments_of_7']}|{float(b['held_energy_capture_pct']):.2f}|")
    text += ["", "原标准保持为CONTROL、NORMAL、频率控制未冻结、功率捕获率≥98%，相邻控制样本≤30 ms，连续10样本。确认时刻为第10样本时刻，不等于第一次到达峰位或成功窗口起点。",
             "NORMAL有一项明确语义扩展：B调幅达到允许的a_goal<1且软保持已结束时可以正常工作，不要求a必须到1。为避免仅靠状态标签获得成绩，另报不依赖NORMAL标签的CONTROL连续功率窗口；不替代原正式验收。",
             "能量包含所有保护、扫描、试探和恢复。分母为各场景软限最优功率的时间积分，不是源功率效率η_elec或声学效率；重放越限期间的能量也纳入总量，不能当作安全收益。",
             "ABC在P&O的能量高于000，但通过段数较少；周期扫频ABC在两项均不优。因此不能随机选一个更复杂组合后称其整体更好。", "",
             "## 4. fs−5%段：新的确认结果", "",
             "|版本|周期扫频确认延迟ms|P&O确认延迟ms|", "|---|---:|---:|"]
    for cfg in r.VARIANTS[:8]:
        vals = []
        for strategy in ("PERIODIC_SCAN", "P_AND_O"):
            row = pick(summary, cfg.name, strategy, .8)
            vals.append(f"{float(row['fs_confirmation_delay_ms']):.1f}" if row["fs_confirmation_delay_ms"] else "未通过")
        text.append(f"|{LABELS[cfg.name]}|{vals[0]}|{vals[1]}|")
    text += ["", "较快的某段确认并不自动带来更高全程能量或更多通过段；新算法改变动作耗时，后续扫描与同一绝对时刻扰动的相对关系也随之改变。", "",
             "## 5. 相位是否带来额外收益？", "",
             "静态34场景中，原扫描、相位+局部、仅局部功率均有32场景达到安全峰值的98%；两处失败来自Lm-only/Cm-only+20%峰位超出原±50 kHz搜索覆盖。没有扩大窗口掩盖失败。三者平均耗时分别约101.00、69.46、66.59 ms，失败搜索仍计入。",
             "因此本轮速度收益主要存在于局部功率捷径；不能全部归于相位。原0.8 s段周期扫频能量，相位+局部50.28%、仅局部50.90%，均低于原扫描58.08%；在1.6 s段分别60.46%、61.06%，高于对照57.86%。不混用静态搜索时间和闭环总能量。",
             "本次输入相位位置、历史相位参考及局部斜率预测在大漂移下经常不能给出有效候选，均保留回退记录。这是本实现和测试范围内的结果，不足以否定所有相位辅助算法。", "",
             "## 6. 约束评分为何在原序列没有效果？", "",
             "34个注册场景的单位源幅度功率峰值处，允许幅度均为1；所以原功率最大点也是本模型的软约束最优点。但峰外采样点可能受限，C仍可能改变中间扫描路径。逐行比较显示最终CONTROL工作指令相同，不应把它写成整个扫描过程完全等效。原0.8 s段P&O的C版本能量比对照仅增加约0.000044个百分点，没有实质收益；差异记录见deliverables/C_command_comparison.json。",
             "发现上述不激活情况后，另立探索性Rm−30%及−50%诊断，冻结C0/Lm/Cm、匹配网络和源；只降低Rm，派生Qm随之升高。此设计是后验的约束激活诊断，不用于调整增益，也不替换原序列成绩。", "",
             "|探索性场景|原功率峰位MHz|约束峰位MHz|原峰位允许功率mW|约束峰值mW|",
             "|---|---:|---:|---:|---:|"]
    for x in objective:
        if x["scope"] == "exploratory":
            text.append(f"|{x['case_id']}|{float(x['raw_power_peak_Hz'])/1e6:.4f}|{float(x['safe_power_peak_Hz'])/1e6:.4f}|{float(x['safe_power_at_raw_peak_W'])*1000:.1f}|{float(x['safe_peak_W'])*1000:.1f}|")
    text += ["", "这证明在所构造的电流受限模型里，评分目标确实需要区别；不证明任意扰动下约束选频均更优。频率基于100 Hz网格，不声称1 Hz精度。",
             "探索性闭环中的通过只表示存在合格连续窗口；之后周期扫描仍可能降功率，尾段捕获率也可能较低。各段完整成绩另见diagnostics/stress_summary.csv，含去状态标签的连续窗口，不能只摘录通过状态。", "",
             "## 7. 安全仍未完成", "",
             "各版本记录点没有硬越限；但保持指令、按实际扰动边界重放时仍有越限。主测试周期扫频000/C约4 ms，A/AB/AC/ABC约18 ms；P&O对应约1 ms与5.5 ms。重放峰值电压可超过160 Vpp，因此无一个新组合可宣布满足连续时间硬限。",
             "这是准稳态零阶保持风险，不是LTspice .tran，也不是实测。当前没有测量噪声、辨识误差、真实执行延迟、储能振铃、功放或声场模型。尚未重新完成原计划中相位闭环作为独立策略的正式三策略验收。", "",
             "## 8. 本轮真实LTspice证据", "",
             f"实际调用LTspice生成12组新AC网表/RAW/LOG，覆盖基准、高组合以及两组负Rm模型，每组2001频点。最大输入阻抗相对误差{max(x['zin_error_pct'] for x in lt['runs']):.6f}%，最大P_Rm相对误差{max(x['prm_error_pct'] for x in lt['runs']):.6f}%，均低于原5%交叉验证门槛。",
             "三档源幅度为0.25、0.40和该场景网格安全峰位对应允许幅度。最后一档只在对应选点满足该设定，不代表整条扫频所有点均安全。保留返回码、SHA256、逐点误差；图不是LTspice GUI截图。本轮没有控制切换瞬态或GUI截图。", "",
             "## 9. 当前决策与下一步", "",
             "- 不直接替换正式平台/PPT；保留E02对照，所有新组合列为实验版本。",
             "- C的电学目标定义在约束激活时有必要，但当前局部扫描仍不能保证全局最优，连续时间安全也未解决。",
             "- A应先与不使用相位的局部功率搜索比较，进一步检验相位参考、适用频段和错误方向回退。",
             "- B要与P&O试探调度共同审查：固定低幅试探、恢复渐升和参考建立消耗时间；不能简单缩短保持、删掉试探样本或降低功率目标换成绩。",
             "- 下一轮优先处理采样/执行延迟、保护模型不确定性及自适应试探调度，再谈算法最终优劣。",
             "", "## 10. 工作痕迹与复现", "",
             "results为本轮最终结果，results_draft1只保留开发记录且不用于报告。输入冻结于frozen；README载明参数和假设。run_factorial.py拒绝覆盖已有结果目录，可用--out指定新目录；validate_factorial.py支持--results指定复核目录。diagnostics及ltspice重跑也应使用新的工作副本，禁止覆盖证据。",
             "科研图像由Python生成，保留全部动作、失败及风险；PNG、SVG、PDF配套，未自动改写网页或PPT。"]
    (OUT / "第二轮控制消融验证报告.md").write_text("\n".join(text)+"\n", encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    base, model, legacy = r.load()
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
                         "font.size": 13, "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none", "pdf.fonttype": 42})
    summary = read(r.RESULTS / "summary.csv")
    static = read(r.HERE / "diagnostics/static_scan_summary.csv")
    objective = read(r.HERE / "diagnostics/objective_landscape.csv")
    factorial_plot(summary)
    attribution_plot(summary, static)
    constraint_plot(model, objective, base)
    write_report(summary, static, objective)
    r.save_json(OUT / "figure_contract.json", {"backend": "Python matplotlib only", "archetype": "quantitative grids",
        "claim": "No universally superior tested combination; objective differs when limits bind; phase attribution requires matched controls",
        "formats": ["PNG", "SVG", "PDF"], "replicates": "deterministic model runs, not biological or statistical repeats",
        "integrity": "main and exploratory results separated; failures and held-command risk retained; no curve offsets or fabricated data",
        "source": ["results/summary.csv", "diagnostics/static_scan_summary.csv", "diagnostics/objective_landscape.csv"],
        "not_hardware_or_acoustic_results": True})
    print("Three figures and Chinese report generated.")


if __name__ == "__main__":
    main()
