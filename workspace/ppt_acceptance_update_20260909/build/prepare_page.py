"""Postprocess saved candidate data only. No controller or LTspice rerun."""
import csv
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BUILD=Path(__file__).resolve().parent
ROOT=BUILD.parents[1]
STUDY=ROOT/"po_scheduling_20260909"
OUT=BUILD.parent/"output"
OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(STUDY))
import run_study as r
from validate_and_recover import read,numeric

NAME="B0_T500_A90_R2"
FOLDER=STUDY/"results"/f"{NAME}_dwell_0.8s"
rows=[numeric(x) for x in read(FOLDER/"timeline.csv")]
metric=next(numeric(x) for x in read(FOLDER/"acceptance_and_energy.csv") if x["case_id"]=="CASE_FS_M5")
cfg=json.loads((FOLDER/"config.json").read_text(encoding="utf-8"))
assert metric["settled"]==1 and metric["max_consecutive_good"]==12
assert cfg["dwell_s"]==.8 and not cfg["setup"]["pi"]
previous,base,model,legacy=r.load()
scenarios=model.scenario_map()
optima=legacy.optimal_tables(scenarios)
replay=[]
for x in rows:
    for seg in cfg["schedule"]:
        left=max(x["time_s"],seg["start_s"],2.2)
        right=min(x["time_s"]+x["duration_s"],seg["end_s"],3.2)
        if right-left<=1e-12: continue
        q=model.response(x["frequency_Hz"],scenarios[seg["case_id"]],x["amplitude_command"])
        replay.append(dict(time_s=left,duration_s=right-left,frequency_MHz=x["frequency_Hz"]/1e6,
            capture_pct=float(q["p_rm_W"][0])/optima[seg["case_id"]]["power_W"]*100,
            vpp=float(q["vport_vpp"][0]),p_rm_W=float(q["p_rm_W"][0]),
            action=x["action"],state=x["protection_state"],amplitude=x["amplitude_command"],case_id=seg["case_id"]))
base.save_csv(OUT/"第14页_作图源数据.csv",replay)
fs=[x for x in replay if x['case_id']=="CASE_FS_M5"]
assert abs(sum(x['duration_s']*x['p_rm_W'] for x in fs)-metric['held_command_energy_J'])<1e-12
assert abs(max(x['vpp'] for x in fs)-metric['held_command_peak_vpp'])<1e-8

# Figure contract: the accepted window, energy cost and hard-limit gap each
# receive one panel. Full local time axis and all actions are retained.
plt.rcParams.update({"font.family":"sans-serif","font.sans-serif":["Microsoft YaHei","DejaVu Sans"],
    "font.size":15,"axes.titlesize":17,"axes.labelsize":15,"xtick.labelsize":14,"ytick.labelsize":14,
    "axes.titleweight":"bold","axes.spines.top":False,"axes.spines.right":False,
    "axes.unicode_minus":False,"svg.fonttype":"none","pdf.fonttype":42})
BLUE="#2F73B7"; RED="#C84444"; NAVY="#17324D"
fig,axes=plt.subplots(3,1,figsize=(11.9,7.7),sharex=True)
fig.subplots_adjust(left=.105,right=.975,bottom=.105,top=.94,hspace=.52)
times=[x['time_s'] for x in replay]+[3.2]
for ax,key,title,ylabel,lim in zip(axes,('capture_pct','frequency_MHz','vpp'),
    ('a  功率捕获率：保留保护、扫描与恢复','b  控制与扫描频率','c  端口电压：包含采样间隙保持指令重放'),
    ('功率捕获率 (%)','频率 (MHz)','端口电压 (Vpp)'),((0,118),(.835,.965),(0,220))):
    vals=[x[key] for x in replay]+[replay[-1][key]]
    ax.step(times,vals,where='post',color=BLUE,lw=1.7)
    ax.set(ylabel=ylabel,ylim=lim,xlim=(2.2,3.2))
    ax.set_title(title,loc='left',color=NAVY,pad=10)
    ax.grid(axis='y',color='#dfe4ea',lw=.8)
    ax.axvline(2.4,color='#8b939d',ls=':',lw=1.3)
    ax.set_xticks(np.arange(2.2,3.21,.2))
start,end=metric['accepted_start_s'],metric['confirmation_s']
axes[0].axhline(98,color='#7d8790',ls=':',lw=1)
axes[0].axvspan(start,end,color='#D8E9F4',alpha=.8)
good=[x for x in rows if 2.4<=x['time_s']<3.2 and x['action']=='CONTROL' and x['protection_state']=='NORMAL'
      and x['frequency_frozen']==0 and x['safe_power_capture_ratio']>=.98]
axes[0].plot([x['time_s'] for x in good],[x['safe_power_capture_ratio']*100 for x in good],'o',
             ms=4.5,mfc='white',mec=BLUE,zorder=5)
axes[0].annotate(f"首次合格 {start:.3f} s\n第10样本确认 {end:.3f} s",xy=(3.045,99),xytext=(2.51,65),
                 fontsize=13,color=NAVY,arrowprops=dict(arrowstyle='->',color=NAVY,lw=1))
axes[0].text(2.405,9,"扰动开始",fontsize=12,color='#737e87')
axes[1].axhline(.8548,color=BLUE,ls=':',lw=.8)
axes[1].text(3.19,.862,"0.8548 MHz",ha='right',color=BLUE,fontsize=14)
axes[1].text(2.25,.907,"0.9000 MHz",color='#657180',fontsize=13)
axes[2].axhline(160,color=RED,ls=':',lw=1.7)
axes[2].text(3.19,169,"硬限 160 Vpp",ha='right',color=RED,fontsize=13)
peak=max(fs,key=lambda x:x['vpp'])
axes[2].annotate(f"{peak['vpp']:.1f} Vpp\n越限累计 {metric['held_command_hard_violation_ms']:.1f} ms",xy=(peak['time_s'],peak['vpp']),
                 xytext=(2.56,181),fontsize=13,color=RED,arrowprops=dict(arrowstyle='->',color=RED,lw=1))
axes[2].set_xlabel("离散准稳态时间 (s)，非LTspice瞬态")
for ext in ('png','svg','pdf'):
    fig.savefig(OUT/f"第14页_验收与风险证据图.{ext}",dpi=230)
plt.close(fig)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
inputs=[FOLDER/n for n in ('timeline.csv','config.json','acceptance_and_energy.csv')]
manifest=[dict(path=str(p),sha256=sha(p)) for p in inputs]
payload=dict(candidate=NAME,metric=metric,config=cfg,source_manifest=manifest,controller_rerun=False,
    LTspice_rerun=False,candidate_role="Frozen reference for next experiments, not released controller",
    unchanged_conditions="0.8 s; >=98%; 10 samples; anomaly detection retained; 160 Vpp/6 mA RMS")
(BUILD/"page_data.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/"固定候选与数据出处.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(candidate=NAME,confirmation_s=end,energy_pct=metric['held_energy_capture_pct'],
    peak_vpp=metric['held_command_peak_vpp']),ensure_ascii=False))
