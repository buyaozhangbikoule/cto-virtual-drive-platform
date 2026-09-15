"""Replot existing historical records only. Does not run any simulation."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

B = Path(__file__).resolve().parent
W = B.parent
R = W.parent
O = W / 'output'
F = B / 'figures'
for p in (O, F):
    p.mkdir(parents=True, exist_ok=True)
main_path = R / 'ppt_control_fix_20260906/build/data/stage4_control_timeline.csv'
phase_path = R / 'CTO_virtual_drive_platform_v2_1/results/phase_ablation/phase_timeline_selected_gain.csv'
audit_path = phase_path.parent / 'phase_ablation_audit.json'
source_deck = R / 'ppt_full_audit_20260911/output/CTO组会汇报_全28页图文核查版_2026-09-11.pptx'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
main = pd.read_csv(main_path)
phase = pd.read_csv(phase_path)
audit = json.loads(audit_path.read_text(encoding='utf-8'))
start, end = 2.2, 3.2
main_view = main[(main.time_s < end - 1e-9) & (main.time_s + main.duration_s > start + 1e-9) & main.strategy.isin(['FIXED_0P9', 'PERIODIC_SCAN'])].copy()
phase_view = phase[(phase.time_s >= start - 1e-9) & (phase.time_s < end - 1e-9)].copy()
assert main_view.action.str.startswith('SCAN').any()
assert phase_view.gain_Hz_per_deg.eq(5).all()
phase_fs = phase_view[phase_view.case_id.eq('CASE_FS_M5')]
assert phase_fs.frequency_frozen.eq(1).all()
assert np.allclose(phase_fs.frequency_update_Hz, 0)
assert np.isclose(phase_view.target_phase_deg.iloc[0], -1.0782096368565852)
periodic = main_view[main_view.strategy.eq('PERIODIC_SCAN')]
adopt = periodic[periodic.action.eq('CONTROL') & periodic.case_id.eq('CASE_FS_M5') & periodic.frequency_Hz.eq(854800)].iloc[0]
qualifying = periodic[periodic.case_id.eq('CASE_FS_M5') & periodic.action.eq('CONTROL') & periodic.protection_state.eq('NORMAL') & periodic.frequency_frozen.eq(0) & periodic.safe_power_capture_ratio.ge(.98)]
assert np.isclose(adopt.time_s, 2.977)
assert len(qualifying) == 6
main_view.to_csv(B / 'source_main_displayed.csv', index=False, encoding='utf-8-sig')
phase_view.to_csv(B / 'source_phase_displayed.csv', index=False, encoding='utf-8-sig')

contract = {
    'claim': 'Three control prototypes exist, but the displayed trials do not support a unified ranking.',
    'panels': {'left': 'Fixed and periodic frequency/power from the same historical run, retain every intersecting record including scan and protection.', 'right': 'Independent historical Kphi=5 trial, model input-phase error and power. Frequency is frozen throughout the displayed fs-5% segment.'},
    'archetype': 'quantitative grid with separate provenance frames',
    'backend': 'Python/matplotlib, user-established workflow',
    'new_simulation': False,
    'source_data': [{'path': str(p), 'sha256': sha(p)} for p in [main_path, phase_path, audit_path]],
    'source_deck': {'path': str(source_deck), 'sha256': sha(source_deck)},
    'statistics': 'Deterministic historical model records, no biological or hardware replicates, no uncertainty or significance claims.',
    'processing': 'Window 2.2 <= t < 3.2 s. Display zero-order holds with original durations for main timeline and 20 ms for historical phase samples. No smoothing, rescaling, offset, or removal of scan/protection records.',
    'risks': ['Different runs and schedules of protection/probes cannot be ranked together.', 'Phase is model arg(Zin), including during zero amplitude; it is not a measured phase during shutdown.', 'Gain 5 results alone do not prove small phase error and low power.', 'Power is electrical dissipation in Rm, not acoustic power.', 'At 2.2 s the prior segment is Rm+50%, not baseline.'],
    'verified_values': {'periodic_adoption_s': float(adopt.time_s), 'periodic_frequency_MHz': .8548, 'periodic_tail_power_mW': float(qualifying.p_rm_W.iloc[-1] * 1000), 'qualifying_samples': len(qualifying), 'required_samples': 10, 'phase_error_fs_deg': float(phase_fs.phase_error_deg.iloc[-1]), 'phase_fs_frequency_frozen_all': True, 'phase_fs_tail_power_mW': float(phase_fs.p_rm_W.iloc[-1] * 1000)},
}
(B / 'figure_contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding='utf-8')

plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': ['Microsoft YaHei', 'SimHei', 'DejaVu Sans'], 'font.size': 13, 'axes.labelsize': 13, 'xtick.labelsize': 12, 'ytick.labelsize': 12, 'axes.spines.top': False, 'axes.spines.right': False, 'axes.linewidth': .8, 'legend.frameon': False, 'axes.unicode_minus': False, 'svg.fonttype': 'none', 'pdf.fonttype': 42})
gray, blue, purple, navy = '#777F89', '#2B70B5', '#866090', '#17324D'

def axes_pair():
    fig, ax = plt.subplots(2, 1, figsize=(6.2, 3.45), sharex=True)
    fig.subplots_adjust(left=.17, right=.955, bottom=.17, top=.88, hspace=.32)
    for a in ax:
        a.grid(axis='y', color='#DDE3E9', lw=.7)
        a.axvline(2.4, color='#929BA5', ls=':', lw=1.2)
        a.set_xlim(start, end)
        a.tick_params(pad=3)
    ax[-1].set_xticks([2.2, 2.4, 2.8, 3.2])
    ax[-1].set_xlabel('离散准稳态时间 (s)', labelpad=2)
    ax[0].tick_params(labelbottom=False)
    return fig, ax

def held(a, q, col, scale, color, label=None, ls='-', lw=1.9, duration='duration_s'):
    xs, ys = [], []
    for _, row in q.sort_values('time_s').iterrows():
        left, right = max(start, row.time_s), min(end, row.time_s + (row[duration] if duration else .02))
        if right <= left: continue
        # Adjacent endpoints create a vertical step, never a diagonal interpolation.
        xs.extend([left, right]); ys.extend([row[col] * scale] * 2)
    a.plot(xs, ys, color=color, lw=lw, ls=ls, label=label)

def save(fig, name):
    # Fixed canvas retains all labels when placed into the intended slide frame.
    for ext in ['png', 'svg', 'pdf']:
        fig.savefig(F / f'{name}.{ext}', dpi=300, facecolor='white')
    plt.close(fig)

fig, ax = axes_pair()
for strategy, color, label, ls in [('FIXED_0P9', gray, '固定频率', '-'), ('PERIODIC_SCAN', blue, '周期扫频', '--')]:
    q = main_view[main_view.strategy.eq(strategy)]
    held(ax[0], q, 'frequency_MHz', 1, color, label, ls)
    held(ax[1], q, 'p_rm_W', 1000, color, ls=ls)
ax[0].legend(loc='lower left', bbox_to_anchor=(-.10, 1.05), ncol=2, fontsize=12, borderaxespad=0)
ax[0].set_ylabel('频率 (MHz)', labelpad=4)
ax[0].set_ylim(.84, .962)
ax[0].set_yticks([.85, .90, .95])
ax[0].yaxis.set_major_formatter(FormatStrFormatter('%.2f'))
ax[0].text(3.18, .864, '0.8548 MHz', color=blue, ha='right', va='bottom', fontsize=12, weight='bold')
ax[1].set_ylabel('P_Rm (mW)', labelpad=4)
ax[1].set_yticks([0, 80, 160]); ax[1].set_ylim(-8, 180)
ax[1].text(2.42, 166, 'fs −5%', fontsize=11, color=navy)
ax[1].text(2.62, 105, '尾段 140.2 mW', color=blue, ha='left', fontsize=11)
save(fig, 'fixed_periodic_history')

fig, ax = axes_pair()
held(ax[0], phase_view, 'phase_error_deg', 1, purple, '模型输入相位误差', duration=None)
held(ax[1], phase_view, 'p_rm_W', 1000, purple, duration=None)
ax[0].legend(loc='lower left', bbox_to_anchor=(-.10, 1.05), fontsize=12, borderaxespad=0)
ax[0].set_ylabel('相位误差 (°)', labelpad=4)
ax[0].set_ylim(-5, 53); ax[0].set_yticks([0, 20, 40])
ax[0].text(3.18, 43.7, '约 41.1°', color=purple, ha='right', fontsize=12, weight='bold')
ax[1].set_ylabel('P_Rm (mW)', labelpad=4)
ax[1].set_yticks([0, 80, 160]); ax[1].set_ylim(-8, 180)
ax[1].text(2.42, 166, 'fs −5%', fontsize=11, color=navy)
ax[1].text(2.78, 66, '本扰动段：保护冻结调频', color=purple, ha='center', fontsize=12)
ax[1].text(3.18, 13, '尾段 <0.1 mW', color=purple, ha='right', fontsize=11)
save(fig, 'phase_history')

notes = '''第15页：三种控制原型已实现：调频依据不同，扰动响应也不同
【建议时长】约2–3分钟，可按现场时间只讲上方方法与下方结论
【逐字讲稿】
这一页展示我们已经做出的控制方法和阶段性仿真结果。上方三列分别是计划书要求的固定频率、周期扫频和相位误差闭环。
固定频率正常保持0.9 MHz，不主动寻峰，但共同保护可以降幅或停机。周期扫频逐点比较功率，找到候选频率后交给控制器使用。相位方法使用匹配网络输入相位的误差，并结合局部斜率的正负决定调频方向；它的目标相位取自基准安全功率峰，不预设为零度。
先看左侧。灰色和蓝色来自同一历史主时序，分别是固定频率和周期扫频，图中保留了扫描点与保护过程。2.4秒开始fs减5%的扰动。灰线仍停在0.9 MHz，功率降得很低。蓝线经历扫描和恢复渐升，在2.977秒的控制记录中采用0.8548 MHz，尾段功率约140.2 mW。但本段结束前只有6个连续合格样本，未达到原定10个样本的稳态验收要求。所以这里能说重新定位了峰位，不能说已经通过稳态验收。
再看右侧。这是另外一次历史相位试验，增益5 Hz/度，目标为输入相位负1.0782度。该扰动段的相位误差约41.1度，功率仍然很低。更重要的是，原始记录显示整个fs减5%段都处于频率冻结状态，调频更新为零，因此这张图反映的是相位控制与保护逻辑组合后的响应，不能简单归因于增益小或相位算法本身失败。
两部分的来源和统计口径尚未统一，本页只展示实现和现象，不进行性能排名。我们还做了扫描辅助P&O，作为第四种扩展方法保留在后续页面，不用它替代计划书中的相位闭环。

【看图顺序】上方从左到右介绍方法；下方先左框的频率再功率，接着右框的相位误差再功率。无需额外切换截图。
【图文口径】
1. 左图：已有Python离散准稳态主时序，SHA256前10位a734eca013；没有新增仿真。右图：独立历史相位试验，目标与增益来自其自身审计文件。
2. 左右横轴均展示2.2–3.2 s，但是不是同一次运行，禁止将其当作统一对照实验排名。2.2–2.4 s是之前的Rm+50%段，不是基准段。
3. 纵轴P_Rm是等效机械支路电阻中的电学有功耗散，不是实测功率或声功率。140.2 mW是当前fs−5%场景峰值，不等于恢复基准170 mW。
4. 相位定义是arg(Zin)，不是换能器端口相位。误差e=目标相位−当前输入相位；正常且未冻结时Δf=clip[Kφ e sign(dφ/df),−500,+500] Hz，频率限制0.8–1.0 MHz。
5. 局部斜率采用模型±100 Hz探针，其探测耗时未计入这次历史相位试验。不能把它描述为已实现硬件相位测量或统一扫描时间预算。
6. 右图的相位是模型计算值，停机零幅度期间也能由模型给出，不表示真实系统在零电压、零电流时仍能测得相位。
7. 本图只有Kφ=5的历史数据，不证明“相位误差很小但功率低”。其他增益的结论应回到对应增益统计与证据页。
8. 本页不更改98%门槛、10样本窗口、扰动持续时间或电压/电流限值。固定/扫频/P&O其他页及其历史来源保持不变。
【模糊推测】本页不加入未经运行验证的效果预测。保护与相位调频衔接如何改进属于后续待验证设计。
【可能追问】相位方法为什么没恢复？答：本次fs−5%段每个样本的frequency_frozen均为1、frequency_update_Hz均为0。应先分析保护放行条件，再开展统一时序试验，当前不能仅从这张图判定相位控制本身优劣。
【来源】
'''
for p in (main_path, phase_path, audit_path, R / 'outputs/v2_self_consistent_rebuild/active_stage3_5/run_phase_ablation.py'):
    notes += f'{p.as_posix()}\nSHA256: {sha(p)}\n'
(B / 'notes.txt').write_text(notes, encoding='utf-8')
(O / '第15页_讲解稿.txt').write_text(notes, encoding='utf-8')
print(json.dumps(contract['verified_values'], ensure_ascii=False, indent=2))
