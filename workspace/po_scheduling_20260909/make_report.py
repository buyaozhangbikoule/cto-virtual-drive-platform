"""Figures and report from saved results; no resimulation or result substitution."""
from dataclasses import asdict
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import run_study as r
from validate_and_recover import read, numeric

OUT = r.HERE / "deliverables"
BLUE, RED, GRAY = "#2468A2", "#C35142", "#757D86"
STYLE = {"font.family":"sans-serif", "font.sans-serif":["Microsoft YaHei","DejaVu Sans"],
    "font.size":11, "axes.titlesize":13, "axes.titleweight":"bold", "axes.labelsize":11,
    "axes.spines.top":False,"axes.spines.right":False,"svg.fonttype":"none","pdf.fonttype":42,
    "axes.unicode_minus":False,"savefig.facecolor":"white"}
plt.rcParams.update(STYLE)
SUM = [numeric(x) for x in read(r.RESULTS/"summary.csv")]
BENCH = [numeric(x) for x in read(r.HERE/"recovery/summary.csv")]


def get(name, dwell=.8):
    return next(x for x in SUM if x["name"] == name and x["segment_duration_s"] == dwell)


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.text(.5,-.018,"假设线性BVD电学模型 · Python离散准稳态仿真 · 非实测、非硬件安全证明",ha="center",fontsize=9,color="#646C75")
    for ext in ("png","svg","pdf"):
        fig.savefig(OUT/f"{name}.{ext}",dpi=220,bbox_inches="tight",pad_inches=.18)
    plt.close(fig)


def matrix():
    fig, axes = plt.subplots(2,3,figsize=(12.8,7.8),layout="constrained")
    for i, pi in enumerate((False,True)):
        for j,gate in enumerate(("R0","R1","R2")):
            ax = axes[i,j]
            data = np.array([[get(r.Configuration(pi,t,a,gate).name)["held_energy_capture_pct"]
                              for t in (.1,.3,.5)] for a in (.4,.7,.9)])
            im = ax.imshow(data,vmin=0,vmax=100,cmap="Blues",aspect="auto")
            for y,a in enumerate((.4,.7,.9)):
                for x,t in enumerate((.1,.3,.5)):
                    s = get(r.Configuration(pi,t,a,gate).name)
                    ax.text(x,y,f"{data[y,x]:.1f}%\n{int(s['settled_segments_of_7'])}/7",ha="center",va="center",
                            color="white" if data[y,x]>57 else "#172C43",fontsize=12)
            ax.set(xticks=[0,1,2],xticklabels=[100,300,500],yticks=[0,1,2],yticklabels=["0.4","0.7","0.9"],
                   xlabel="P&O等待参数 T (ms)",ylabel="P&O试探幅度上限 a",
                   title=f"{'无' if not pi else '有'}独立PI · {gate}")
    fig.colorbar(im,ax=axes,shrink=.84,pad=.02,label="全过程能量捕获率 (%)")
    fig.suptitle("54种配置完整对照：能量改善与连续稳态通过数不是同一指标\n"
                 "每格：全过程能量捕获率 / 通过段数；0.8 s/段；初始基准段不计入7段评分",fontsize=15)
    save(fig,"01_完整调度矩阵")


def matched():
    configs = [(.1,.4,"R0"),(.3,.4,"R0"),(.5,.4,"R0"),(.1,.7,"R0"),(.1,.9,"R0"),(.1,.4,"R1"),(.1,.4,"R2")]
    labels = ["原设置","仅T=300 ms","仅T=500 ms","仅a=0.7","仅a=0.9","仅规则R1","仅规则R2"]
    fig, axes = plt.subplots(2,1,figsize=(12.4,7.0),sharex=True,layout="constrained")
    for ax,key,title,limit in zip(axes,("held_energy_capture_pct","settled_segments_of_7"),
                                ("a  全过程能量捕获率 (%)","b  连续稳态通过段数 (/7)"),((0,78),(0,8))):
        for pi,color,offset,label in ((False,GRAY,-.18,"无独立PI"),(True,BLUE,.18,"有独立PI")):
            values = [get(r.Configuration(pi,*c).name)[key] for c in configs]
            bars = ax.bar(np.arange(7)+offset,values,width=.34,color=color,label=label)
            ax.bar_label(bars,labels=[f"{v:.1f}" if key.startswith("held") else str(int(v)) for v in values],padding=3,fontsize=10)
        ax.set(ylim=limit,title=title)
        ax.set_axisbelow(True)
        ax.grid(axis="y",alpha=.2)
        for x in (.5,2.5,4.5):
            ax.axvline(x,color="#d4d9df",ls=":",lw=1)
    axes[0].legend(loc="upper left",ncol=2,frameon=False)
    axes[1].set_xticks(np.arange(7),labels)
    axes[1].set_xlabel("每项仅改变一个调度因素，其余保持原T=100 ms、a=0.4、R0；0.8 s/段")
    fig.suptitle("单因素验证：延长等待、提高试探幅度或等待恢复，各自的效果不同",fontsize=15)
    save(fig,"02_匹配单因素效果")


def replay(rows, schedule, model, scenarios, optima):
    result=[]
    for x in rows:
        for seg in schedule:
            left=max(x["time_s"],seg["start_s"])
            right=min(x["time_s"]+x["duration_s"],seg["end_s"])
            if right-left <= 1e-12:
                continue
            q=model.response(x["frequency_Hz"],scenarios[seg["case_id"]],x["amplitude_command"])
            result.append(dict(time_s=left,duration_s=right-left,frequency_Hz=x["frequency_Hz"],
                amplitude=x["amplitude_command"],action=x["action"],case_id=seg["case_id"],
                capture_pct=float(q["p_rm_W"][0])/optima[seg["case_id"]]["power_W"]*100,
                vpp=float(q["vport_vpp"][0]),irms_A=float(q["iport_irms_A"][0]),
                p_rm_W=float(q["p_rm_W"][0])))
    return result


def full_trace(base,model,legacy):
    scenarios=model.scenario_map()
    optima=legacy.optimal_tables(scenarios)
    fig,axes=plt.subplots(4,1,figsize=(13.3,10.5),sharex=True,layout="constrained")
    audits=[]
    for name,color,ls,label in (("B1_T100_A40_R0",GRAY,"-","原PI设置：100 ms / 0.4 / R0"),
                                ("B1_T500_A90_R2",BLUE,"--","联合候选：500 ms / 0.9 / R2")):
        folder=r.RESULTS/f"{name}_dwell_0.8s"
        rows=[numeric(x) for x in read(folder/"timeline.csv")]
        cfg=json.loads((folder/"config.json").read_text(encoding="utf-8"))
        rr=replay(rows,cfg["schedule"],model,scenarios,optima)
        base.save_csv(OUT/f"source_03_{name}_held_replay.csv",rr)
        for ax,key,scale in zip(axes,("amplitude","capture_pct","frequency_Hz","vpp"),(1,1,1e-6,1)):
            xx=[x["time_s"] for x in rr]+[6.4]
            yy=[x[key]*scale for x in rr]+[rr[-1][key]*scale]
            ax.step(xx,yy,where="post",color=color,ls=ls,lw=1.35,label=label)
        energy=sum(x["p_rm_W"]*max(0,x["time_s"]+x["duration_s"]-max(x["time_s"],.8)) for x in rr if x["time_s"]+x["duration_s"]>.8)
        expected=get(name)["held_energy_J"]
        assert abs(energy-expected)<1e-12
        audits.append(dict(name=name,replay_energy_J=energy,summary_energy_J=expected,matched=True))
    names=["初始基准","C0+30%","Rm+50%","fs−5%","L匹配+10%","QL=20","高组合","回到基准"]
    for i,label in enumerate(names):
        axes[0].text(i*.8+.4,1.09,label,ha="center",va="bottom",fontsize=9)
    titles=["a  实际幅度指令：包括试探、扫描与恢复","b  全部动作功率捕获率：按当前场景自身安全最优归一化",
            "c  全部动作频率：保留重捕获扫描","d  保持指令重放电压：包含采样间隙的负载变化"]
    for ax,title,ylabel,lim in zip(axes,titles,("相对源幅度 a","功率捕获率 (%)","频率 (MHz)","端口电压 (Vpp)"),
                                  ((0,1.2),(0,115),(.795,1.005),(0,215))):
        ax.set(title=title,ylabel=ylabel,ylim=lim,xlim=(0,6.4))
        ax.grid(axis="y",alpha=.18)
        for x in np.arange(.8,6.4,.8): ax.axvline(x,color="#D1D6DB",lw=.7,ls=":")
    axes[0].legend(loc="lower left",frameon=True,fontsize=10)
    axes[1].axhline(98,color="#737D85",ls=":",lw=.8)
    axes[3].axhline(160,color=RED,ls=":",lw=1.5)
    axes[3].text(6.35,165,"硬限160 Vpp",ha="right",color=RED)
    axes[3].set_xlabel("离散准稳态时间 (s)，非LTspice瞬态；所有扫描/试探均计入")
    fig.suptitle("候选提高功率保持表现，但本序列仍有短暂越限，不能宣称完成硬安全验收",fontsize=15)
    save(fig,"03_完整时序与间隙越限")
    r.save_json(OUT/"replay_energy_check.json",audits)


def recovery_figure():
    fig,axes=plt.subplots(1,2,figsize=(11.4,4.8),layout="constrained")
    for ax,case,title in zip(axes,("CASE_000_BASELINE","BENCH_RM_M30"),("a  基准场景","b  Rm−30%诊断场景")):
        for pi,color in ((False,GRAY),(True,BLUE)):
            for step,ls,marker in ((.05,"-","o"),(.025,"--","s")):
                data=sorted([x for x in BENCH if x["case_id"]==case and x["pi"]==str(pi) and x["step_per_20ms"]==step],key=lambda x:x["initial_amplitude"])
                assert len(data)==3
                ax.plot([x["initial_amplitude"] for x in data],[x["first_power98_sample_complete_ms"] for x in data],
                        color=color,ls=ls,marker=marker,ms=10 if not pi else 6,mfc="white" if not pi else color,
                        label=f"{'有' if pi else '无'}PI，升幅{step}/20 ms")
        ax.set(title=title,xlabel="恢复起始幅度 a",ylabel="到达固定频率允许功率98%的时间 (ms)",
               xticks=[.4,.7,.9],ylim=(0,540),xlim=(.36,.94))
        ax.grid(alpha=.2)
    axes[1].legend(frameon=False,fontsize=10,loc="upper right")
    fig.suptitle("独立恢复诊断：更低起始幅度、更慢升幅增加恢复成本；PI在部分设置下有额外代价\n"
                 "固定0.900 MHz；从开始恢复到达标样本完成；不含此前保持，不进行扫描或P&O",fontsize=13)
    fig.text(.5,-.055,"空心大符号与实心小符号重合表示恢复时间相同；未平移数据",ha="center",fontsize=9,color="#646C75")
    save(fig,"04_独立恢复诊断")


def report(base,model):
    chosen=[("原PI设置","B1_T100_A40_R0"),("仅T=300 ms","B1_T300_A40_R0"),("仅T=500 ms","B1_T500_A40_R0"),
            ("仅试探幅度0.7","B1_T100_A70_R0"),("仅试探幅度0.9","B1_T100_A90_R0"),("仅R2门槛","B1_T100_A40_R2"),
            ("联合候选","B1_T500_A90_R2"),("同调度、无PI对照","B0_T500_A90_R2"),
            ("本矩阵PI组能量最高（非总体验收最优）","B1_T100_A90_R1")]
    lines=["|配置|能量捕获率|主验收通过|全部动作≥98%时间占比|间隙越限时长|",
           "|---|---:|---:|---:|---:|"]
    for label,name in chosen:
        s=get(name)
        lines.append(f"|{label} `{name}`|{s['held_energy_capture_pct']:.2f}%|{int(s['settled_segments_of_7'])}/7|{s['all_action_power_98_time_pct']:.2f}%|{s['held_command_hard_violation_ms']:.1f} ms|")
    base.save_csv(OUT/"汇报用匹配对照表.csv",[dict(label=label,**get(name)) for label,name in chosen])
    recovery_lines=["|初始幅度|无PI：98%功率 / NORMAL|有PI：98%功率 / NORMAL|","|---|---:|---:|"]
    for a in (.4,.7,.9):
        values=[]
        for pi in (False,True):
            b=next(x for x in BENCH if x['case_id']=='CASE_000_BASELINE' and x['pi']==str(pi) and x['initial_amplitude']==a and x['step_per_20ms']==.05)
            values.append(f"{b['first_power98_sample_complete_ms']:.0f} / {b['first_NORMAL_sample_complete_ms']:.0f} ms")
        recovery_lines.append(f"|{a}|{values[0]}|{values[1]}|")
    summary108=len(SUM)
    tests=json.loads((r.HERE/"independent_tests.json").read_text(encoding="utf-8"))
    basecase=model.scenario_map()["CASE_000_BASELINE"].bvd
    text=f"""# 独立PI调幅与P&O调度：第三轮隔离验证报告

## 1. 可以确认的结论

**本轮已实际完成Python离散准稳态仿真：54种调度配置×两种段长={summary108}条时序，另有24组固定频率恢复诊断。** 主矩阵独立完整重跑，字节一致性结果见`../reproducibility.json`；程序约束检查通过{tests['count']}项。检查通过不是物理安全通过。

独立PI本身能够在固定频率条件下恢复到允许目标；与P&O组合的主要成本包括低幅试探造成的功率中断、恢复上升时间和PI尾段接近目标的时间。调整调度能够改善本测试集成绩，但不能由此宣称PI比无PI更好，也尚未消除采样间隙的硬限风险。

## 2. 怎么拆开验证

- B0：无独立幅度PI，但保留相同保护与升幅限制；B1：独立功率误差PI。相位辅助A、约束选频评分C均关闭。
- T=100/300/500 ms；P&O试探上限a=0.4/0.7/0.9；恢复门槛R0/R1/R2。完整交叉，非随机挑组合。
- R0是旧调度；R1在旧条件外要求恢复后NORMAL持续T；R2再要求10个稳定NORMAL控制样本。R2看频率/幅度稳定和异常票数，不读取离线功率最优或98%验收比。
- 硬限160 Vpp、6 mA RMS，软限130 Vpp、5.5 mA RMS均冻结。硬保持60 ms、恢复保持100 ms、软稳定100 ms不缩短。每20 ms升幅上限0.05不提高。
- 仅P&O参考/试探/返回幅度改变；重捕获扫描始终≤0.4，所有动作调用统一保护接口。首轮试探保留旧行为，紧急重捕获不受R1/R2的日常等待限制。
- 输入源为冻结戴维南源，Rs=50 Ω，a=1时源约{model.SOURCE_A1_VRMS:.6f} V RMS；不是源100 Vpp。基准换能器端约100 Vpp、5 mA RMS、170 mW。
- 基准Rm={basecase.rm:.6f} Ω，C0={basecase.c0:.8g} F；全部为假设基线，非实测。完整元件及派生fs/Qm在`parameter_registry.json`。不能换回早期冲突的Rm=100 Ω参数组。

## 3. 主结果：原0.8 s/段，7个评分段

{"\n".join(lines)}

初始基准段只用于初始化，评分7段为C0+30%、Rm+50%、fs−5%、匹配电感+10%、QL=20、高组合、回到基准。主验收始终要求CONTROL、NORMAL、频率未冻结、功率≥当前场景安全最优98%，连续10样本，相邻CONTROL间隔≤30 ms。延长日常试探间隔确实会让连续窗口更容易出现，所以同时报告能量和全部动作高功率时间，不能只数通过段。

能量捕获率=评分区间内实际保持指令的P_Rm积分 / 各当前场景安全最优P_Rm积分。它不是源到负载的电学效率，也不是相对固定170 mW的恢复率。安全最优使用相同源幅度上限a≤1、相同软限和频段。RMS复相量功率P_port=Re(V_port I_port*)；本理想C0无损模型内P_port=P_Rm。相位字段仍是匹配网络输入相位arg(Zin)，不冒称换能器端口相位。

**单因素不能简单归纳为“越大越好”。** 有PI时，仅T从100改为300 ms，能量45.16%降至42.53%；改500 ms升至50.11%。仅试探幅度0.7时能量小升，但通过数由2/7降至1/7。仅增加R2门槛，能量升至53.78%，通过3/7。

**联合候选不是通用最优。** `B1_T500_A90_R2`得到67.00%、5/7；同调度去掉PI则67.16%、7/7。PI组能量最高为另一组68.56%，但仅3/7；本次不存在单一指标能代表全面更优。R1与R2在500 ms下若产生相同结果，是额外10稳定样本条件未成为新的限制，不是两者被写成同一算法。

**补充段长不替代主验收。** 联合候选在1.6 s/段得到81.61%、7/7，原PI设置为44.08%、2/7。这只证明更长驻留提供更多恢复/确认时间；不能修改0.8 s主表为已通过。

## 4. 恢复台架：为何0.4倍试探代价较大

在基准场景固定0.900 MHz、升幅上限0.05/20 ms下，下表从第一次恢复更新开始，计至达标样本完成。此前低幅测量占20 ms单独保留；不计入此前硬/软保持。这里的目标是**固定频率允许功率**，不是全频最大功率。

{"\n".join(recovery_lines)}

从0.4→1至少12次0.05更新，更新预算约240 ms。PI不仅受相同升幅约束，还需尾段接近目标，因此首次NORMAL样本完成约300 ms。原始NORMAL时间戳相对于恢复起点分别为220/280 ms，与样本完成差20 ms，报告中不混用。

这不是说原算法在RAMP_UP时强行试探：原保护接口会阻止该行为。真正问题是**等待计时在恢复期间已经到期，刚达到NORMAL就可能再次试探，留给持续输出与连续验收的时间很短**。T也不是实际两次试探起点之间的间隔，`probe_events.json`保存实际开始/结束；试探本身参考、偏移、返回通常还占3×20 ms。

0.4、0.7、0.9倍在同一频率、同一线性模型中分别约对应a²=16%、49%、81%的功率；实际频率试探还会改变功率系数。较高试探幅度减少恢复损失，但安全余量可能更小，不能把0.9当成天然安全档。

24组独立台架均达到固定频率98%功率，无台架功率过冲。有PI的12组均达到NORMAL。Rm−30%台架允许幅度约0.943：无PI可达到限幅功率，但状态可持续为SOFT_FOLDBACK；有PI可在允许的亚单位目标稳定。物理功率达到与状态标签达到分开记录。降低升幅到0.025只做恢复敏感性，不用于主矩阵刷成绩。

`median_probe_recovery_to_normal_ms`是试探返回结束到下个NORMAL的时间戳差；若途中发生保护/重捕获，该延迟一并计入，不能当成纯PI时间。纯恢复因果判断以独立台架为准。

## 5. 哪些问题尚未解决

1. **硬安全仍不通过。** 主矩阵所有采样点的后保护V/I合规，但原PI设置保持指令重放越限约1 ms，联合候选约3 ms，重放峰值约193.9 Vpp>160 Vpp。因此候选性能提高并不等于满足“160 Vpp绝不超过”。3 ms是两个扰动边界的保持时间累计，不是已测硬件脉冲宽度。
2. 模型预览保护使用当前准确BVD模型，且采样间隙重放仅按代数稳态切换负载；没有储能振铃、真实感知/执行延迟或误差。既不能当硬件安全证明，也不能宣称预测了真实过冲形状。
3. 联合候选在主序列fs−5%及匹配电感+10%段分别只有9个连续合格样本；虽然尾段功率100%，均不能算通过。没有降低98%或10样本门槛。
   原PI设置的fs−5%段本轮复现为通过，确认延迟约{get('B1_T100_A40_R0')['fs_confirmation_delay_ms']:.0f} ms；联合候选该段反而未通过。整体通过段数增加并不意味着每一个关键段都改善。
4. 旧可观测检测器在a<0.999时仍冻结，即亚单位NORMAL不一定能更新检测参考。当前先冻结该逻辑以隔离调度因素；R2仅代表自身稳定门槛，不代表原检测参考已就绪。下一轮应单列这个检测器修正因素。
5. 高频高幅试探与缓慢负载漂移、测量噪声、延迟、不同Qm的联合鲁棒性未在本轮验证。所有候选从同一矩阵内比较得出，没有独立留出数据集或统计置信区间。

## 6. 工作痕迹与真实性

- 本轮新增的是**实际执行的Python模型仿真**，不是手绘曲线；`results/*/timeline.csv`含所有保护/扫描/试探；图03还分割负载边界做保持指令重放。
- 4个原设置对照与第二轮已有时序逐字段零差异复现；8组篡改评价最优值的测试不改变控制指令，说明新门槛没有读取评价答案。
- 本轮**没有新增LTspice GUI截图、LTspice控制瞬态、真实器件测量或COMSOL结果**。`frozen/prior_AC`仅是第二轮12次真实AC交叉验证的审计副本，保留历史来源，不冒充本轮新仿真。仅AC一致不证明时序控制可行。
- 所有源文件、冻结输入及结果哈希见输入清单、复现审计及证据包清单。复现为确定性重复，不是生物学/统计重复。
- 原正式平台、网页、PPT及此前证据均未替换。本轮作为独立实验分支供审核；不自动把候选升为正式控制器。

## 7. 汇报时可以这样讲

“我把独立调幅与P&O的配合拆成三个调度因素，用54种配置进行完整交叉验证，并在两个驻留时间下重复比较。固定频率恢复试验说明PI本身能恢复，但低幅试探与尾段调节会占用连续输出时间。联合调度候选在0.8秒每段的能量捕获率由45.2%提升到67.0%，连续验收由2/7提升到5/7。不过同调度的无PI对照达到7/7，且保持指令重放仍有短暂硬限越限，所以目前只能称调度改进得到部分验证，不能声称PI更优或安全问题已经解决。”

## 8. 下一步排序（本轮未实施）

先独立修正亚单位幅度的检测参考资格；再将“恢复到允许幅度”与“功率微调”做明确分工，以同调度无PI为对照评估PI是否必要。对频率与幅度联合优化单开C因素试验。硬限问题需另做模型不确定性下安全裕量、采样/执行延迟与瞬态验证；不得靠抬高160 Vpp限值解决。

## 图表与生成方式

1. `01_完整调度矩阵`：54配置，保留所有不利结果。
2. `02_匹配单因素效果`：其余因素固定，才能讨论归因。
3. `03_完整时序与间隙越限`：包含全部动作；完整0—6.4 s，不删保护低功率段。
4. `04_独立恢复诊断`：24组，仅固定频率恢复，功率目标不同于全频最优。

均由`../make_report.py`生成PNG/SVG/PDF，数值源见对应CSV；字体、完整坐标及失败样本按科研制图检查，不使用“Nature已接收”或投稿合规认证表述。复现命令见README；本报告所有结论限于特定BVD模型与扰动范围内的电学稳定性。
"""
    (OUT/"独立调幅与P&O调度验证报告.md").write_text(text,encoding="utf-8")
    registry=[]
    for s in model.scenario_map().values():
        b=s.bvd
        registry.append(dict(scenario=asdict(s),derived_fs_Hz=1/(2*math.pi*math.sqrt(b.lm*b.cm)),
            derived_Qm=math.sqrt(b.lm/b.cm)/b.rm,source_class="HYPOTHETICAL_BASELINE_OR_SCAN_VARIABLE"))
    r.save_json(OUT/"parameter_registry.json",registry)


def main():
    OUT.mkdir(exist_ok=True)
    previous,base,model,legacy=r.load()
    # Frozen model imports have their own old matplotlib defaults.
    plt.rcParams.update(STYLE)
    matrix()
    matched()
    full_trace(base,model,legacy)
    recovery_figure()
    report(base,model)
    print("4 figures (PNG/SVG/PDF), source data and report written")


if __name__ == "__main__":
    main()
