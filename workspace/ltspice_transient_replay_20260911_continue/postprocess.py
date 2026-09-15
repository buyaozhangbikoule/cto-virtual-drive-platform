"""Process actual transient RAW; never substitute synthetic waveforms for RAW.

Figure contract: compare transient response with historical quasi-steady predictions,
not controller ranking. Quantitative grid; one deterministic command replay; no
replicates or inference statistics. PNG/PDF/SVG, separate from GUI screenshots.
"""
from pathlib import Path
import csv,importlib.util,json,sys,math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

D=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('validation_helpers',D/'run_validation.py')
h=importlib.util.module_from_spec(spec);sys.modules[spec.name]=h;spec.loader.exec_module(h)
trap=getattr(np,'trapezoid',None) or np.trapz

def savefig(fig,name):
    for ext in ['png','svg','pdf']:
        fig.savefig(D/(name+'.'+ext),dpi=220,facecolor='white')
    plt.close(fig)

def main():
    contract=json.loads((D/'replay_contract.json').read_text(encoding='utf-8'))
    receipt=json.loads((D/'PO_FS_M5_REPLAY_DT2NS_execution.json').read_text(encoding='utf-8'))
    assert receipt['return_code']==0
    rawpath=D/'PO_FS_M5_REPLAY_DT2NS.raw'
    raw=h.old.read_real_raw(rawpath);time=raw['time']
    with (D/'replayed_original_rows.csv').open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    start,end=contract['original_time_range_s'];warm=contract['warmup_s']
    rm=h.cases['CASE_FS_M5'].bvd.rm
    rowtimes=np.array([float(r['time_s']) for r in rows])
    width=50e-6
    edges=np.linspace(warm,contract['simulation_stop_s'],int(round((end-start)/width))+1)
    indices=np.searchsorted(time,edges)
    output=[]
    for j,(lo,hi) in enumerate(zip(edges[:-1],edges[1:])):
        a=max(0,int(indices[j])-1);b=min(len(time),int(indices[j+1])+1)
        tx=np.asarray(time[a:b]);inside=(tx>lo)&(tx<hi)
        tt=np.r_[lo,tx[inside],hi]
        data={}
        for key in ['v(n_port)','i(vprobe)','i(rm)']:
            values=np.asarray(raw[key][a:b],dtype=float)
            data[key]=np.r_[np.interp(lo,tx,values),values[inside],np.interp(hi,tx,values)]
        v=data['v(n_port)'];i=data['i(vprobe)'];im=data['i(rm)']
        orig=(lo+hi)/2-warm+start
        r=rows[max(0,min(len(rows)-1,int(np.searchsorted(rowtimes,orig,side='right')-1)))]
        output.append({'time_original_s':orig,'time_ltspice_s':(lo+hi)/2,'window_s':hi-lo,
            'vport_vpp_window':float(np.ptp(v)),'vport_peak_abs_V':float(np.max(np.abs(v))),
            'iport_irms_window_A':math.sqrt(trap(i*i,tt)/(hi-lo)),
            'iport_peak_abs_A':float(np.max(np.abs(i))),
            'p_rm_window_W':float(trap(im*im*rm,tt)/(hi-lo)),
            'p_port_window_W':float(trap(v*i,tt)/(hi-lo)),
            'frequency_command_Hz':float(r['frequency_Hz']),
            'amplitude_command':float(r['amplitude_command']),
            'python_steady_vpp':float(r['vport_vpp']),
            'python_steady_irms_A':float(r['iport_irms_A']),
            'python_steady_p_rm_W':float(r['p_rm_W'])})
    with (D/'transient_50us_windows.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
    d={key:np.array([r[key] for r in output]) for key in output[0]}
    iv=int(np.argmax(d['vport_vpp_window']));ii=int(np.argmax(d['iport_irms_window_A']))
    summary={'scope':contract['kind'],'raw_sha256':receipt['raw']['sha256'],
        'raw_points':len(time),'window_seconds':width,'windowing':'non-overlapping, exact boundary interpolation; peak-to-peak and time-integrated RMS',
        'maximum_50us_vpp_V':float(d['vport_vpp_window'][iv]),'time_of_max_vpp_original_s':float(d['time_original_s'][iv]),
        'maximum_50us_irms_mA':float(d['iport_irms_window_A'][ii]*1000),'time_of_max_irms_original_s':float(d['time_original_s'][ii]),
        'windows_vpp_above_160':int(np.count_nonzero(d['vport_vpp_window']>160)),
        'windows_irms_above_6mA':int(np.count_nonzero(d['iport_irms_window_A']>.006)),
        'maximum_absolute_instantaneous_voltage_V':float(np.max(d['vport_peak_abs_V'])),
        'maximum_absolute_instantaneous_current_mA':float(np.max(d['iport_peak_abs_A'])*1000),
        'motional_energy_J':float(np.sum(d['p_rm_window_W']*d['window_s'])),
        'hard_limit_interpretation':'160 Vpp/6 mA RMS are sinusoidal design limits. 50-us transient windows are an explicit analysis convention, not a hardware detector. Instantaneous current is not compared to an RMS limit.',
        'no_closed_loop_feedback':True,'no_hardware_safety_claim':True}
    (D/'transient_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

    plt.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','DejaVu Sans'],
        'font.size':12,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none','pdf.fonttype':42})
    x=d['time_original_s'];red='#B84B4B';gray='#69737C';blue='#2166AC'
    # Draw historical commands at their exact event times, not at bin centres.
    command_t=np.r_[np.maximum(start,rowtimes),end]
    command=lambda key:np.array([float(r[key]) for r in rows]+[float(rows[-1][key])])
    fig,axes=plt.subplots(4,1,figsize=(13.5,11.5),sharex=True,gridspec_kw={'height_ratios':[1.3,1.3,.85,.85]})
    fig.subplots_adjust(left=.105,right=.975,top=.87,bottom=.095,hspace=.18)
    fig.suptitle('真实LTspice瞬态：历史P&O指令开环重放',fontsize=22,fontweight='bold',y=.974)
    fig.text(.105,.925,'固定 fs−5% 模型；原始时间2.838–3.059 s；保留原指令持续时间',fontsize=12)
    axes[0].plot(x,d['vport_vpp_window'],color=red,lw=1.3,label='LTspice RAW：50 μs窗口统计')
    axes[0].step(command_t,command('vport_vpp'),where='post',color=gray,ls='--',lw=1.5,label='原Python准稳态预测')
    axes[0].axhline(160,color='#AD2424',ls=':',label='160 Vpp / 6 mA参考边界')
    axes[0].axhline(130,color='#CA8A2A',ls=':',alpha=.8)
    axes[0].set_ylabel('端口电压 (Vpp)');axes[0].set_ylim(bottom=0)
    axes[0].legend(loc='upper left',bbox_to_anchor=(0,1.28),ncol=3,fontsize=10,frameon=False)
    axes[1].plot(x,d['iport_irms_window_A']*1000,color=red,lw=1.3)
    axes[1].step(command_t,command('iport_irms_A')*1000,where='post',color=gray,ls='--',lw=1.5)
    axes[1].axhline(6,color='#AD2424',ls=':');axes[1].axhline(5.5,color='#CA8A2A',ls=':',alpha=.8)
    axes[1].set_ylabel('端口电流 (mA RMS)');axes[1].set_ylim(bottom=0)
    axes[2].step(command_t,command('amplitude_command'),where='post',color=blue,lw=1.4)
    axes[2].set_ylabel('幅度指令 a');axes[2].set_ylim(0,1.12)
    axes[3].step(command_t,command('frequency_Hz')/1e6,where='post',color=blue,lw=1.4)
    axes[3].set_ylabel('频率指令 (MHz)');axes[3].set_xlabel('映射回原始控制时序的时间 (s)')
    for letter,ax in zip('abcd',axes):
        ax.text(-.085,.96,letter,transform=ax.transAxes,weight='bold',fontsize=16)
        ax.grid(axis='y',alpha=.2);ax.set_xlim(start,end)
    fig.text(.105,.028,'假设线性BVD，非实测。仅一策略片段；无LTspice反馈闭环；本图为RAW后处理，不是GUI截图。',fontsize=10)
    savefig(fig,'RAW_replay_vs_quasisteady')

    tail_hi=contract['simulation_stop_s']-50e-6;tail_lo=tail_hi-10e-6
    ia,ib=np.searchsorted(time,[tail_lo,tail_hi]);ts=np.asarray(time[ia:ib]);tt=(ts-tail_lo)*1e6
    fig,ax=plt.subplots(2,1,figsize=(12,7),sharex=True,layout='constrained')
    fig.suptitle('真实RAW尾段载波：0.8548 MHz，幅度指令 a=1',fontsize=18)
    ax[0].plot(tt,raw['v(n_port)'][ia:ib],color=red,lw=1.2);ax[0].set_ylabel('瞬时电压 (V)')
    ax[1].plot(tt,raw['i(vprobe)'][ia:ib]*1000,color=blue,lw=1.2);ax[1].set_ylabel('瞬时电流 (mA)');ax[1].set_xlabel('选取窗口内时间 (μs)')
    for a in ax:a.grid(alpha=.2)
    fig.supxlabel(f'LTspice时间 {tail_lo*1e3:.3f}–{tail_hi*1e3:.3f} ms；瞬时峰值不等同于RMS。假设模型，非实测。',fontsize=10)
    savefig(fig,'RAW_tail_carrier')
    qa={'core_claim':'Actual transient replay can depart from historical quasi-steady samples; not a controller ranking.',
        'archetype':'quantitative grid','backend':'Python matplotlib','replicates':'one deterministic simulation, no statistical inference',
        'source':'actual LTspice binary RAW; separate original CSV predictions','exports':['PNG','SVG editable text','PDF embedded fonts'],
        'window_seconds':width,'screenshots':'not generated by this script; must be genuine app captures',
        'image_integrity':'No image crop, synthetic carrier, curve shift, smoothing or artificial uncertainty band.',
        'visual_review':'pending'}
    (D/'figure_qa.json').write_text(json.dumps(qa,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
