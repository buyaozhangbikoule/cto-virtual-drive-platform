"""Read-only dashboard backed by one explicitly registered, fully hashed batch."""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from current.catalog import PLATFORM, LABELS, load_active, read_json
from current.provenance_ui import source_page_link

ORDER = ['FIXED','PERIODIC_SCAN','PHASE_FEEDBACK']
STYLE = {'FIXED':('#667085','-',2.0), 'PERIODIC_SCAN':('#1765b5','--',2.2),
         'PHASE_FEEDBACK':('#c94a3a','-.',1.7)}
plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
                     'axes.unicode_minus':False,'font.size':11})


def evidence():
    try:
        result = load_active()
    except (ValueError, OSError, KeyError) as error:
        st.error(f'当前证据校验失败：{error}')
        st.info('不会回退显示旧表或把部分批次冒充完整结果。请执行 python run_project.py validate。')
        st.stop()
    if result['source_drift']:
        st.warning('当前代码与保存批次源码不一致：'+', '.join(result['source_drift'])+
                   '。以下仍是已登记批次，不是修改后代码的新结果；请重新验证。')
    return result


def download(path, label, key):
    st.download_button(label, Path(path).read_bytes(), file_name=Path(path).name, key=key)


def rename(frame, columns):
    result = frame[list(columns)].copy().rename(columns=columns)
    if '策略' in result:
        result['策略'] = result['策略'].map(LABELS)
    if '连续稳态验收' in result:
        result['连续稳态验收'] = result['连续稳态验收'].map({True:'通过',False:'未通过'})
    return result


def held(ax, frame, values, name):
    color, style, width = STYLE[name]
    x = np.r_[frame.start_us.to_numpy()/1e6, frame.end_us.iloc[-1]/1e6]
    y = np.r_[np.asarray(values), np.asarray(values)[-1]]
    ax.step(x,y,where='post',label=LABELS[name],color=color,linestyle=style,linewidth=width)


def render_results():
    st.title('统一三策略结果')
    st.caption('当前同批次、同口径准稳态比较 · 非历史结果拼表 · 不包含P&O扩展策略')
    ev = evidence()
    folder, audit, meta = ev['folder'], ev['audit'], ev['metadata']
    st.code(meta['batch_id'],language=None)
    st.success(f"证据核验通过：{audit['manifest_files_verified']}个文件；{audit['timelines']}条执行时序；"
               f"{audit['executed_rows']:,}条执行记录；{meta['tests_passed']}项控制行为测试。")
    st.warning('统一比较已经完成，但不代表三种策略均通过稳态验收，更不代表全过程硬限已获证明。'
               '本页结果仅适用于冻结假设模型、登记扰动、当前控制参数。')
    hist = pd.read_csv(folder/'historical_12_three_strategy_table.csv')
    target = pd.read_csv(folder/'registered34_target_segment_metrics.csv')
    cfg, refs = read_json(folder/'configuration.json'), read_json(folder/'reference_optima.json')
    tabs = st.tabs(['综合结果与覆盖','时序与逐段验收','采用配置与复现'])
    with tabs[0]:
        st.subheader('原12段日程 · 当前重新运行的统一结果')
        st.caption('每段0.8 s，全程0–9.6 s。此处“HISTORICAL_12”是日程名称，不代表读取旧实验结果。')
        table = rename(hist,{'strategy':'策略','settled_segments':'通过段数 / 12','energy_J':'全过程P_Rm电能 (J)',
            'energy_capture_pct':'相对策略可行参考电能 (%)','scan_failures':'扫描失败总数'})
        st.dataframe(table,hide_index=True,width='stretch')
        st.info('电能包含扫描、相位试探、停机、等待及渐升；是准稳态采样保持积分，不是声学效率或LTspice瞬态电能。'
                '固定策略在这套短时扰动与参数下的数值更高，不能外推为普遍优于自适应控制。')
        st.subheader('34个登记条目 · 各自中间0.8 s目标段')
        coverage = pd.DataFrame([{'策略':LABELS[s], '通过目标段数 / 34':int(target.loc[target.strategy==s,'settled'].sum())}
                                for s in ORDER])
        st.dataframe(coverage,hide_index=True,width='stretch')
        st.caption('每条为基准0.8 s→目标0.8 s→基准0.8 s；只统计中间段。34是登记条目数，含与基准等价的别名，'
                   '不能声称34种独立物理负载，也未计算加权总体排名。')
        st.subheader('保护与扫描失败分开披露')
        st.dataframe(rename(hist,{'strategy':'策略','peak_pre_guard_voltage_Vpp':'保护前预测峰值 (Vpp)',
            'peak_post_guard_and_hold_voltage_Vpp':'保护后／保持峰值 (Vpp)',
            'peak_current_mArms':'全记录含保护前峰值 (mA RMS)',
            'pre_guard_hard_observations':'保护前硬越限观测数','protection_trigger_events':'保护触发事件数',
            'actual_hard_violation_duration_ms':'施加后记录越限时长 (ms)'}),hide_index=True,width='stretch')
        st.error(f"全35套试验中，保护前旧命令在新负载下的预测峰值达 {audit['max_pre_guard_voltage_Vpp']:.2f} Vpp。"
                 '该值不是实测或LTspice瞬态尖峰；保护后的低值不能抹去这一限制。')
        st.dataframe(rename(hist,{'strategy':'策略','scan_failures_search':'寻峰失败','scan_failures_preemption':'保护抢占',
            'scan_failures_measurement':'无效测量','scan_failures_nonstationary':'非平稳扫描',
            'scan_truncated_by_run_end':'终点截断','scan_exhaustions':'重试耗尽'}),hide_index=True,width='stretch')
        a,b,c = st.columns(3)
        with a: download(folder/'historical_12_three_strategy_table.csv','下载12段综合表','hist_csv')
        with b: download(folder/'registered34_target_segment_metrics.csv','下载34条目×3策略表','target_csv')
        with c: download(folder/'formal_three_strategy_summary.csv','下载105条综合结果','all_csv')
    with tabs[1]:
        schedules = read_json(folder/'schedules.json')
        suite = st.selectbox('选择日程',['HISTORICAL_12']+sorted(s for s in schedules if s!='HISTORICAL_12'),
            format_func=lambda s:'原12段日程（当前批次）' if s=='HISTORICAL_12' else '独立覆盖：'+s.removeprefix('COVER_'))
        frame = pd.read_csv(folder/'per_segment_metrics.csv')
        per = frame[frame.suite==suite]
        segments = schedules[suite]
        selected = st.selectbox('观察区间',[-1]+[s['index'] for s in segments],
            format_func=lambda i:'全程（保留所有执行阶段）' if i==-1 else
                f"第{i+1}段 · {segments[i]['case_id']} · {segments[i]['start_us']/1e6:.1f}–{segments[i]['end_us']/1e6:.1f} s")
        lo,hi = (0,segments[-1]['end_us']/1e6) if selected==-1 else (segments[selected]['start_us']/1e6,segments[selected]['end_us']/1e6)
        fig, axs = plt.subplots(3,1,figsize=(12,8),sharex=True,layout='constrained')
        executions = {}
        for strategy in ORDER:
            rows = pd.read_csv(folder/'executions'/f'{suite}_{strategy}.csv')
            rows = rows[(rows.end_us>lo*1e6)&(rows.start_us<hi*1e6)]
            executions[strategy] = rows
            held(axs[0],rows,rows.frequency_Hz/1e6,strategy)
            held(axs[1],rows,rows.p_rm_W*1000,strategy)
            capture = 100*rows.p_rm_W.to_numpy()/np.array([refs[c]['policy']['power_W'] for c in rows.case_id])
            held(axs[2],rows,capture,strategy)
        axs[0].legend(loc='lower left',bbox_to_anchor=(0,1.02),ncol=3,frameon=False)
        for ax,label in zip(axs,['频率 (MHz)','运动支路有功功率 (mW)','功率捕获率 (%)']):
            ax.set_ylabel(label); ax.set_xlim(lo,hi); ax.grid(alpha=.2)
            for seg in segments:
                if lo<seg['start_us']/1e6<hi: ax.axvline(seg['start_us']/1e6,color='#9aa4b2',ls=':',lw=.8)
        axs[2].axhline(cfg['capture_threshold']*100,color='black',linestyle=':',linewidth=1)
        axs[2].set_xlabel('离散准稳态时间 (s)')
        st.pyplot(fig,width='stretch'); plt.close(fig)
        st.caption('阶梯曲线保留全部执行阶段、原始时间及重合数据，不上下平移。'
                   '100%按当前场景自身的软阈值策略可行最大P_Rm归一化；不等于基准绝对功率，亦非电声效率。')
        shown = per if selected==-1 else per[per.segment_index==selected]
        st.dataframe(rename(shown,{'strategy':'策略','case_id':'场景','start_s':'开始 (s)','settled':'连续稳态验收',
            'max_consecutive_qualified_samples':'最长合格串','recovery_enter_ms':'进入成功窗口 (ms)',
            'recovery_confirm_ms':'完成连续确认 (ms)','steady_error_pct':'已验收稳态误差 (%)',
            'fixed_tail_error_pct':'固定尾窗缺额 (%)','energy_capture_pct':'全过程电能捕获率 (%)',
            'frequency_saturation_events':'频率饱和事件数'}),hide_index=True,width='stretch')
        st.caption('未通过时稳态误差和恢复时间留空（NA），没有回退样本；尾窗缺额另列，不冒充稳态结果。'
                   '连续验收：NORMAL、普通有效CONTROL、频率未冻结、捕获率≥98%、相邻20 ms、连续10样本。')
        with st.expander('电压、电流、实际幅度与保护前观测'):
            strategy = st.selectbox('查看策略',ORDER,format_func=LABELS.get)
            rows = executions[strategy]
            fig, ax = plt.subplots(3,1,figsize=(12,7),sharex=True,layout='constrained')
            held(ax[0],rows,rows.vport_Vpp,strategy)
            observed = rows[rows.pre_guard_sample_here]
            ax[0].scatter(observed.start_us/1e6,observed.pre_guard_vport_Vpp,color='#be123c',s=10,label='保护前预测（点，不积分）')
            ax[0].axhline(160,color='red',ls=':',label='160 Vpp硬边界'); ax[0].axhline(130,color='#d97706',ls='--')
            held(ax[1],rows,rows.iport_Arms*1000,strategy)
            ax[1].scatter(observed.start_us/1e6,observed.pre_guard_iport_Arms*1000,color='#be123c',s=10)
            ax[1].axhline(6,color='red',ls=':'); ax[1].axhline(5.5,color='#d97706',ls='--')
            held(ax[2],rows,rows.applied_amplitude,strategy)
            for a,label in zip(ax,['端口电压 (Vpp)','端口电流 (mA RMS)','实际幅度 a']):
                a.set_ylabel(label);a.set_xlim(lo,hi);a.grid(alpha=.2)
            ax[0].legend(ncol=3,loc='lower left',bbox_to_anchor=(0,1.02),frameon=False)
            ax[2].set_xlabel('离散准稳态时间 (s)')
            st.pyplot(fig,width='stretch');plt.close(fig)
            st.dataframe(rows[['start_us','end_us','kind','protection_state','frequency_frozen','applied_amplitude',
                               'protection_amplitude','measurement_valid']],hide_index=True,width='stretch')
            download(folder/'executions'/f'{suite}_{strategy}.csv','下载本策略完整执行日志','exec_csv')
            download(folder/'events'/f'{suite}_{strategy}.json','下载本策略事件日志','events_json')
        download(folder/'per_segment_metrics.csv','下载全部逐段验收表','per_csv')
    with tabs[2]:
        source_page_link()
        st.markdown('''### 当前采用方案

- 正式运行：`python run_project.py validate`；独立新目录，旧结果不覆盖。
- 周期扫频：±50 kHz/5 kHz → ±5 kHz/1 kHz → ±1 kHz/0.1 kHz；异常分类、边缘重定位和有界粗扫回退按配置执行，不等于单次±100 kHz均匀扫频。
- 相位：匹配输入相位 arg(V_input/I_source)，基准标定后冻结；邻频试探计时，不用扰动真值更新目标。
- 共用保护、执行时钟、测量有效性、指标函数和源／匹配／BVD配置。
- 采用扫描失败分类补丁；旧P&O边缘扫描补丁、独立PI、去嵌相位及辐射负载参考未接入正式引擎。
''')
        phase = read_json(folder/'phase_calibration.json')
        st.write(f"本批次冻结目标输入相位：{phase['target_deg']:.6f}°。")
        st.info('采样20 ms、每扫频点1.5 ms、各保护保持时长、增益、失败预算均为假设控制参数，不是实测实时性能。'
                '当前理想保护使用精确模型判断允许幅度，尚未证明真实传感／执行延迟下的硬限。')
        st.json(cfg,expanded=False)
        st.json(read_json(folder/'integration_sources.json'),expanded=False)
        st.code('python run_project.py test\npython run_project.py validate\npython run_project.py verify\npython run_project.py ui',language='powershell')
        st.write('结果位置：',str(folder))
        download(folder/'统一验证报告.md','下载本批次完整报告','report_md')
        download(folder/'configuration.json','下载冻结配置','cfg_json')
        download(folder/'manifest.json','下载文件哈希清单','manifest_json')
        download(ev['audit_file'],'下载逐日志复算记录','audit_json')
        st.caption('反射代理仅监测；独立绝对功率上限、动态硬件保护、结构声场均不因本次接入而自动完成。')


def render_versions():
    st.title('版本、补丁与证据分区')
    st.caption('不以文件修改日期推断成果身份；当前结果只由 active_batch.json 明确登记。')
    ev = evidence()
    st.success('当前统一批次：'+ev['metadata']['batch_id'])
    for category, body in [
        ('当前正式准稳态比较', 'current/unified：固定、周期扫频、相位反馈；冻结模型＋统一保护＋统一指标。新增批次已全量复核。完成比较不等于全部通过。'),
        ('历史结果／独立实验', '原 results/tables、figures、evidence、历史P&O、相位消融、LTspice AC、瞬态重放与五轮反馈记录保留原身份。不能与当前批次拼成同次控制实验。'),
        ('研究原型：尚未接入', 'research/radiation_load_layer1：第一层辐射负载参考快照；原型自检不等于34场景控制结果已使用该负载。独立PI、去嵌相位、8组合消融仍为扩展研究。'),
    ]:
        st.subheader(category);st.write(body)
    st.subheader('已采用与未采用的补丁')
    st.markdown('''- **已采用**：`plan_three_strategy.scan_fault_taxonomy.patch`，来自审核分支；覆盖 config/controllers/metrics/tests，41项行为测试。新增预算有界但未调优。
- **未采用到正式引擎**：针对历史P&O的 `run_stage4_5_control.edge_aware_scan.patch`、去嵌相位原型、独立PI、辐射负载层。不能把“有代码”当成“本批次已使用”。
- **本次额外整合**：官方CLI、批次登记／哈希校验、网页读表和证据说明；不改变既有物理阈值与验收门槛。
- **没有执行**：PPT／旧讲稿修改、GitHub推送、新的LTspice或COMSOL求解。''')
    sources = read_json(PLATFORM/'current'/'integration_sources.json')
    st.json(sources,expanded=False)
    ledger = PLATFORM/'current'/'artifact_registry.json'
    if ledger.is_file():
        items=read_json(ledger)['artifacts']
        st.dataframe(pd.DataFrame(items),hide_index=True,width='stretch')
        st.caption('上表是来源与身份索引，不宣称所有外部历史目录已打包到本目录；缺失时应回原仓库／归档查证。')
    st.page_link('pages/04_统一三策略结果.py',label='查看当前统一三策略表和时序')
    st.page_link('pages/02_参数探索与历史结果.py',label='查看参数探索与历史成果')
    st.page_link('pages/03_LTspice闭环验证.py',label='查看独立LTspice接口实验')
    source_page_link()
    guide = PLATFORM/'docs'/'当前入口与成果分区_20260922.md'
    if guide.is_file(): download(guide,'下载当前口径与操作说明','guide')
