"""Postprocess existing recorded power; no controller or circuit simulation."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

B=Path(__file__).resolve().parent
O=B.parent/'output'
ROOT=B.parents[1]
SRC=ROOT/'ppt_control_fix_20260906/build/data'
def read(name):
    with (SRC/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
rows=read('stage4_control_timeline.csv')
old=read('stage5_integrated_strategy_table.csv')
ref={}
for r in rows:
    si=int(r['state_index'])
    if si>0:
        v=float(r['optimal_safe_power_W'])
        if si in ref:assert abs(ref[si]-v)<1e-12
        ref[si]=v
assert sorted(ref)==list(range(1,8))
reference=sum(ref.values())*.8
order=['FIXED_0P9','PERIODIC_SCAN','P_AND_O']
names=['固定频率＋共同保护','周期扫频','扫描辅助P&O']
results=[]; contributions=[]
for strategy,name in zip(order,names):
    selected=sorted((r for r in rows if r['strategy']==strategy),key=lambda r:float(r['time_s']))
    energy=0;duration=0;end=.8
    for r in selected:
        start=max(.8,float(r['time_s']))
        stop=min(6.4,float(r['time_s'])+float(r['duration_s']))
        dt=max(0,stop-start)
        if dt<=1e-12:continue
        assert abs(start-end)<1e-10,(strategy,start,end)
        end=stop;duration+=dt
        ej=float(r['p_rm_W'])*dt;energy+=ej
        contributions.append(dict(strategy=strategy,start_s=start,end_s=stop,duration_s=dt,
            action=r['action'],protection_state=r['protection_state'],p_rm_W=float(r['p_rm_W']),energy_J=ej))
    assert abs(duration-5.6)<1e-10
    m=next(r for r in old if r['strategy']==strategy)
    results.append(dict(strategy=strategy,name=name,energy_J=energy,reference_J=reference,
        capture_pct=100*energy/reference,steady_error_pct=float(m['steady_error_pct']),
        unsettled_segments=int(m['unsettled_segments']),recovery_ms=float(m['mean_recovery_time_ms_penalized']),
        sampled_hard_violations=int(m['actual_hard_violations']),duration_s=duration))
assert [round(r['energy_J'],3) for r in results]==[.588,.474,.525]
assert [round(r['capture_pct'],1) for r in results]==[75.8,61.1,67.7]
for name,records in [('第15页_电能复算表.csv',results),('第15页_逐记录积分.csv',contributions)]:
    with (O/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
manifest=[dict(file=n,sha256=hashlib.sha256((SRC/n).read_bytes()).hexdigest()) for n in
    ['stage4_control_timeline.csv','stage5_integrated_strategy_table.csv','stage5_per_segment_metrics.csv']]
data=dict(rows=results,reference_J=reference,source_dir=str(SRC),sources=manifest,
    interval_s=[.8,6.4],controller_rerun=False,LTspice_rerun=False,
    method='Each recorded p_rm_W is held for its recorded duration_s, clipped to [0.8,6.4). All actions retained. Shared denominator: sum of seven scheduled safe-power references times 0.8 s.',
    limitation='Does not recompute physical responses during unrecorded intersample disturbance changes. Not acoustic efficiency or hard-safety proof.',
    figure_contract={'conclusion':'Zero selected-tail error coexists with substantial full-interval energy deficit.',
        'archetype':'quantitative grid','backend':'Python','statistics':'Deterministic single saved run per strategy. No inferential statistics.',
        'formats':['PNG','SVG','PDF'],'image_integrity':'No crop, no data shifts, linear 0–100% axis.'})
(B/'data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','DejaVu Sans'],
    'font.size':16,'svg.fonttype':'none','pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
fig,ax=plt.subplots(figsize=(6.3,4.8),facecolor='#F5F7FA')
ax.set_facecolor('#F5F7FA');fig.subplots_adjust(left=.34,right=.94,bottom=.18,top=.90)
colors=['#767676','#3775BA','#B64342']
y=np.arange(3)
v=[r['capture_pct'] for r in results]
ax.barh(y,v,height=.48,color=colors)
ax.invert_yaxis();ax.set_yticks(y,['固定频率\n＋共同保护','周期扫频','扫描辅助P&O'])
ax.set_xlim(0,100);ax.set_xticks([0,25,50,75,100]);ax.set_xlabel('相对安全最优电能（%）',labelpad=14)
ax.tick_params(axis='y',length=0,pad=12);ax.spines['left'].set_visible(False)
ax.spines['bottom'].set_color('#C8D1DB');ax.tick_params(axis='x',colors='#5F6B76')
ax.set_axisbelow(True);ax.grid(axis='x',color='#DEE4EA',lw=.8)
ax.axvline(100,color='#8796A4',linestyle=':',lw=1.3)
for yi,vi in zip(y,v):ax.text(vi+2,yi,f'{vi:.1f}%',va='center',fontsize=17,fontweight='bold',color='#17324D')
for ext in ['png','svg','pdf']:fig.savefig(O/f'第15页_全过程电能比较.{ext}',dpi=240,facecolor=fig.get_facecolor())
plt.close(fig)
print(json.dumps(results,ensure_ascii=False,indent=2))
