"""Replot existing evidence. Does NOT run LTspice or any controller simulation.
Figure contract: explanatory lab-meeting figures, Python only, preserve all data
inside explicitly labelled frequency/time windows. No vertical data offsets,
invented samples, AI-generated screenshots or hidden limit violations.
"""
from pathlib import Path
import sys,json,hashlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

R=Path(__file__).resolve().parents[2]; B=Path(__file__).resolve().parent
O=B/'figures'; O.mkdir(exist_ok=True)
P=R/'CTO_virtual_drive_platform_v2_1'; A=R/'outputs/v2_self_consistent_rebuild'
plt.rcParams.update({'font.family':'Microsoft YaHei','font.size':12,'axes.spines.top':False,'axes.spines.right':False,'axes.labelsize':12,'axes.titlesize':13,'legend.fontsize':10,'svg.fonttype':'none','pdf.fonttype':42,'savefig.facecolor':'white','axes.unicode_minus':False})
blue='#2F73B8'; red='#B84040'; teal='#328898'; gray='#757B82'; orange='#DE8800'; navy='#17324D'
manifest=[]
def finish(fig,name,sources,claim,method):
    for ax in fig.axes:
        if ax.get_label()!='<colorbar>':
            ax.tick_params(labelsize=11)
    for ext in ('png','svg','pdf'):fig.savefig(O/f'{name}.{ext}',dpi=220,bbox_inches='tight',pad_inches=.06)
    plt.close(fig)
    manifest.append({'figure':name,'claim':claim,'method':method,'new_simulation':False,'sources':[{'path':str(s).replace('\\','/'),'sha256':hashlib.sha256(s.read_bytes()).hexdigest()} for s in sources]})

# Page 4: decode an existing real RAW and independently recompute the same BVD.
sys.path.insert(0,str(A/'ltspice_stage1'))
from analyze_v2_stage1 import read_ltspice_raw
rawpath=P/'evidence/ltspice/stage1/V2_1_BARE_BVD_Q800.raw'
raw=read_ltspice_raw(rawpath);f=raw['frequency'].real;zlt=raw['v(n)']/(-raw['i(vdrive)'])
w=2*np.pi*f;rm=7352.941176470586;lm=1.0402283862215377;cm=.030062600361803386e-12;c0=6.858064105198409e-12
zm=rm+1j*(w*lm-1/(w*cm));zpy=1/(1/zm+1j*w*c0)
glt=(raw['i(rm)']/raw['v(n)']).real
err=np.max(abs(zlt-zpy)/abs(zpy))
rawcheck={'complex_Z_relative_error_fraction':float(err),'magnitude_only_relative_error_fraction':float(np.max(abs(abs(zlt)-abs(zpy))/abs(zpy))),'Gpeak_LT_Hz':float(f[np.argmax(glt)]),'Gpeak_PY_Hz':float(f[np.argmax((1/zm).real)]),'Zmin_LT_Hz':float(f[np.argmin(abs(zlt))]),'Zmin_PY_Hz':float(f[np.argmin(abs(zpy))])}
(B/'stage1_independent_recheck.json').write_text(json.dumps(rawcheck,indent=2),encoding='utf-8')
fig,ax=plt.subplots(2,1,figsize=(7.6,5.1),sharex=True,layout='constrained')
for a,y1,y2 in zip(ax,[abs(zlt)/1e3,np.angle(zlt,deg=True)],[abs(zpy)/1e3,np.angle(zpy,deg=True)]):
    a.plot(f/1e6,y1,color=blue,lw=2,label='LTspice 已存RAW')
    a.plot(f/1e6,y2,color=orange,lw=1.1,ls='--',label='Python 解析复核')
    a.grid(alpha=.22);a.axvline(.9,color=gray,ls=':',lw=1)
ax[0].set_ylabel('|Zport| (kΩ)');ax[1].set_ylabel('arg Zport (°)');ax[1].set_xlabel('频率 (MHz)')
ax[0].legend(loc='upper right');ax[1].axhline(0,color=gray,lw=.6);ax[1].set_xlim(.5,1.5)
finish(fig,'p04_bare_bvd',[rawpath],'裸BVD两条求解路径在同一配置下吻合','解码已保存RAW，按原参数复核解析解；没有新LTspice运行。')

# Page 6: frozen 1 Vrms source CSV, not calibrated 170 mW curve.
s2path=A/'stage2_matching/stage2_LTspice逐频数据.csv';s2=pd.read_csv(s2path)
fig,ax=plt.subplots(2,1,figsize=(7.4,4.8),sharex=True,layout='constrained')
for key,color,label in [('BEFORE',gray,'未匹配'),('IDEAL',blue,'理想匹配'),('ACTIVE_LOSSY',orange,'有损匹配')]:
    q=s2[(s2.scenario==key)&s2.frequency_Hz.between(880000,920000)]
    if key!='BEFORE':ax[0].plot(q.frequency_Hz/1e6,q.zin_abs_ohm,color=color,lw=1.6,label=label)
    ax[1].plot(q.frequency_Hz/1e6,q.zin_phase_deg,color=color,lw=1.6,label=label)
for a in ax:a.grid(alpha=.22);a.axvline(.9,color=gray,ls=':',lw=.9)
ax[0].set_ylabel('|Zin| (Ω)');ax[0].legend(loc='upper right');ax[0].set_title('匹配后输入阻抗幅值（未匹配值见右表）',loc='left')
ax[1].set_ylabel('arg Zin (°)');ax[1].set_xlabel('频率 (MHz)');ax[1].set_xlim(.88,.92);ax[1].legend(loc='lower right',ncol=3)
finish(fig,'p06_input_impedance',[s2path],'输入端阻抗与换能器端口阻抗不同','读取原有LTspice逐频CSV，显示0.88–0.92 MHz；上图不绘未匹配高阻值，以右表报告。')

# Page 8: raw frozen-amplitude scans including all current/voltage limit data.
cmpath=P/'results/tables/stage3_disturbance/stage3_cm_only_power_safety_curves.csv';cmdata=pd.read_csv(cmpath)
fig,ax=plt.subplots(3,1,figsize=(7.3,5.5),sharex=True,layout='constrained',gridspec_kw={'height_ratios':[1.6,1,1]})
for key,color,label,ls in [('CASE_000_BASELINE',gray,'基准','-'),('CASE_CM_P5','#8EADD5','Cm +5%','--'),('CASE_CM_P10',blue,'Cm +10%','-.'),('CASE_CM_P20',navy,'Cm +20%',':')]:
    q=cmdata[cmdata.case_id==key]
    for a,col,mul in zip(ax,['p_rm_W','vport_Vpp','iport_Arms'],[1000,1,1000]):a.plot(q.frequency_Hz/1e6,q[col]*mul,color=color,ls=ls,lw=1.6,label=label)
ax[0].legend(ncol=2,loc='upper right');ax[0].set_ylim(0,195)
ax[1].axhline(160,color=red,ls=':',lw=1.3);ax[1].axhline(130,color=orange,ls='--',lw=1)
ax[2].axhline(6,color=red,ls=':',lw=1.3);ax[2].axhline(5.5,color=orange,ls='--',lw=1)
ax[1].text(.998,162,'160 Vpp',ha='right',va='bottom',color=red,fontsize=10);ax[2].text(.998,6.05,'6 mA',ha='right',color=red,fontsize=10)
ax[1].text(.998,132,'130 Vpp',ha='right',va='bottom',color=orange,fontsize=10)
ax[2].text(.998,5.42,'5.5 mA',ha='right',va='top',color=orange,fontsize=10)
for a,label in zip(ax,['P_Rm (mW)','端口电压 (Vpp)','端口电流 (mA RMS)']):a.set_ylabel(label);a.grid(alpha=.22)
ax[2].set_xlabel('频率 (MHz)');ax[2].set_xlim(.8,1.0);ax[2].set_ylim(0,6.7)
finish(fig,'p08_cm_power_limits',[cmpath],'Cm单因素改变峰位峰高；未保护扫频有电压越限','完整0.8–1.0 MHz原始曲线；不裁切160 Vpp以上数据；a=1未保护。')

s3path=A/'active_stage3_5/stage3_disturbance/stage3_frequency_response_all_cases.csv';s3=pd.read_csv(s3path)
fig,ax=plt.subplots(2,1,figsize=(7.3,5.1),sharex=True,layout='constrained')
for key,color,label,ls in [('CASE_QM_500',blue,'Qm=500','--'),('CASE_QM_800',gray,'Qm=800','-'),('CASE_QM_1000',red,'Qm=1000',':')]:
    q=s3[s3.case_id==key]
    ax[0].plot(q.frequency_Hz/1e6,q.p_rm_W*1000,color=color,ls=ls,lw=1.8,label=label)
    ax[1].plot(q.frequency_Hz/1e6,q.zin_abs_ohm,color=color,ls=ls,lw=1.8)
ax[0].legend();ax[0].set_ylim(0,180);ax[0].set_ylabel('P_Rm (mW)');ax[1].set_ylabel('|Zin| (Ω)');ax[1].set_xlabel('频率 (MHz)');ax[1].set_xlim(.8,1.)
for a in ax:a.grid(alpha=.22)
finish(fig,'p09_qm_response',[s3path],'固定fs、Rm、C0时Qm增大使功率峰变窄','既有全频CSV；Qm通过联合重算Lm/Cm实现；无峰高偏移。')

selpath=P/'results/tables/stage3_selection/stage3_initial_three_criteria.csv';sel=pd.read_csv(selpath)
fig,ax=plt.subplots(2,1,figsize=(8,5),sharex=True,layout='constrained')
for a,key,label in zip(ax,['CASE_000_BASELINE','CASE_FS_M5'],['a  基准场景','b  fs −5%场景']):
    q=s3[(s3.case_id==key)&s3.frequency_Hz.between(840000,960000)&(s3.frequency_Hz%500==0)]
    row=sel[sel.case_id==key].iloc[0]
    a.plot(q.frequency_Hz/1e6,q.p_rm_W*1000,color=gray,lw=1.7)
    for col,color,ls,lbl in [('max_power',red,'-','最大功率'),('min_abs_phase',blue,'--','最小绝对输入相位'),('min_reflection',teal,':','最小输入反射代理')]:
        a.axvline(row[f'{col}_frequency_Hz']/1e6,color=color,ls=ls,lw=1.5,label=lbl)
    a.set_title(label,loc='left');a.set_ylabel('P_Rm (mW)');a.grid(alpha=.2)
ax[0].legend(ncol=1,loc='upper right',fontsize=10);ax[1].set_xlabel('频率 (MHz)');ax[1].set_xlim(.84,.96);ax[1].set_xticks(np.arange(.84,.961,.02))
finish(fig,'p10_criteria',[s3path,selpath],'三个离散选频准则不总重合','严格取0.5 kHz网格，峰高fs−5%为130.06 mW，不用0.1 kHz峰高140.2 mW混标。')

aggpath=P/'results/tables/stage3_selection/stage3_window_step_aggregate.csv';agg=pd.read_csv(aggpath);agg=agg[agg.criterion=='max_power']
fig,ax=plt.subplots(1,2,figsize=(11,3.5),layout='constrained')
for a,col,scale,title in zip(ax,['max_total_error_vs_global_Hz','scan_time_proxy_ms'],[.001,1],['34场景最大频率偏差 (kHz)','扫描时间代理 (ms)']):
    table=agg.pivot(index='window_halfwidth_kHz',columns='step_kHz',values=col).sort_index().sort_index(axis=1)*scale
    vals=table.values;a.imshow(vals,cmap='Blues',aspect='auto',vmin=0)
    for i in range(3):
        for j in range(4):a.text(j,i,f'{vals[i,j]:.2f}' if scale==.001 else f'{vals[i,j]:.1f}',ha='center',va='center',color='white' if vals[i,j]>.55*vals.max() else navy,fontsize=12,fontweight='bold')
    a.set_xticks(range(4),['0.1','0.5','1','2']);a.set_yticks(range(3),['±20','±50','±100']);a.set_xlabel('步长 (kHz)');a.set_ylabel('窗口半宽 (kHz)');a.set_title(title)
finish(fig,'p11_windows',[aggpath],'扩大场景集后±50 kHz仍漏2场景，±100 kHz无峰被排除','当前34场景aggregate；不沿用早期热图。时间按1.5 ms/点假设计算，非实测。')

phpath=P/'results/phase_ablation/phase_timeline_selected_gain.csv';ph=pd.read_csv(phpath)
fig,ax=plt.subplots(3,1,figsize=(7.3,5.3),sharex=True,layout='constrained')
for a,col,color,label in zip(ax,['frequency_MHz','phase_error_deg','p_rm_W'],[blue,'#8D5590',red],['控制频率 (MHz)','相位误差 (°)','P_Rm (mW)']):
    a.step(ph.time_s,ph[col]*(1000 if col=='p_rm_W' else 1),where='post',color=color,lw=1.5)
    for t in np.arange(.8,6.4,.8):a.axvline(t,color=gray,lw=.6,alpha=.6)
    a.axvspan(2.4,3.2,color=orange,alpha=.1);a.grid(alpha=.15);a.set_ylabel(label)
ax[0].yaxis.set_major_formatter(FormatStrFormatter('%.4f'));ax[2].set_xlabel('离散准稳态时间 (s)');ax[2].set_xlim(0,6.4);ax[2].set_ylim(0,190)
ax[0].set_title('Kφ=5 Hz/°，淡色段为 fs −5%',loc='left')
finish(fig,'p14_phase_current',[phpath],'K=5历史相位控制在fs−5%段未追到功率峰','当前选定增益CSV逐样本保持绘图；下图改为有功功率mW，避免旧图错误的120%归一化。')
(B/'figure_contract_and_sources.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'figures':len(manifest),'stage1_recheck':rawcheck,'phase_power_max_mW':float(ph.p_rm_W.max()*1000),'max_window_error_kHz':agg.groupby('window_halfwidth_kHz').max_total_error_vs_global_Hz.max().div(1000).to_dict()},ensure_ascii=False))
