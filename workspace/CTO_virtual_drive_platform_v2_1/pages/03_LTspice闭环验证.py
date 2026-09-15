"""Separate experimental page; never substitutes analytic results for LTspice."""
from pathlib import Path
import json,sys
import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from scripts import ltspice_closed_loop as cl

st.set_page_config(page_title='LTspice闭环验证 · 实验页',layout='wide')
st.title('LTspice闭环验证')
st.caption('独立实验页 · 真实瞬态RAW反馈 · 不覆盖原正式验收结果')
st.warning('这是离线、采样式闭环联算，不是硬件实时控制。保护在一轮求解结束后才作决定，不能保证采样间隙不越限。')
st.markdown('**当前指令 → LTspice瞬态求解 → RAW测量 → 异常判断／局部功率搜索 → 下一条指令**')
with st.expander('与“已有指令重放”的区别及当前边界',expanded=False):
    st.markdown('''- 下一条指令由本轮真实RAW决定；不读取历史指令CSV，不调用解析模型寻找最优频率。
- 每轮从相同初态重算完整指令历史，**保留历史储能效应**；不是每段单独从零开始。耗时随轮数增加，不具备实时性。
- 当前负载在一次会话内冻结；可选基准或fs−5%场景，**尚未实现运行中的负载突变**。
- 频率控制为简单局部P&O；幅度只做设定目标以内的渐升、降额及保持。没有全频搜索、独立PI或全局最优保证。
- 控制目标采用端口平均有功功率P_port；P_Rm仅作模型内部诊断。瞬态时两者不必相等。相位是换能器端口V/I基波相位，不是匹配输入相位。
- 新增参数是**假设控制值**，不沿用原三策略的正式验收结论。无声学、实物、功放开关或临床结论。''')

with st.sidebar:
    st.header('新建独立会话')
    case=st.selectbox('冻结负载场景',['CASE_000_BASELINE','CASE_FS_M5'])
    f=st.number_input('起始频率 (MHz)',min_value=.8,max_value=1.,value=.899,step=.0005,format='%.4f')
    a=st.slider('起始幅度 a',0.,1.,.4,.05)
    target=st.slider('幅度目标上限 a',0.,1.,.4,.05)
    period=st.selectbox('每轮电路时间 (ms)',[1.,2.,5.,20.],index=1)
    df=st.selectbox('局部频率步长 (Hz)',[100.,200.,500.,1000.,2000.],index=2)
    max_steps=st.number_input('最多反馈轮数',min_value=1,max_value=30,value=12)
    exe=st.text_input('LTspice可执行文件',value='D:/LTspice.exe')
    st.caption('默认2 ms仅用于接口验证，不是原20 ms正式控制周期。最大积分步长2 ns；先建立3 ms；末200 μs估计功率；50 μs窗口检查保护。')
    st.caption(f'每轮保存完整历史RAW；按当前设置，总RAW体积粗估约{28/2e-9*(max_steps*.003+period/1000*max_steps*(max_steps+1)/2)/1e9:.2f} GB。3 ms建立段保存但不计入反馈验收。')
    st.caption('固定边界：0.8–1.0 MHz；160 Vpp / 6 mA RMS。软阈值130 Vpp / 5.5 mA RMS。')
    if st.button('新建会话',type='primary'):
        try:
            p=cl.create_session(case_id=case,frequency_hz=f*1e6,amplitude=a,amplitude_target=target,
                period_s=period/1000,step_hz=df,executable=exe,max_steps=int(max_steps))
            st.session_state['closed_loop_dir']=str(p);st.success('配置已冻结；尚未运行LTspice。')
        except Exception as e:st.error(str(e))

dirs=sorted(cl.OUT.glob('CL_*/session.json'),reverse=True) if cl.OUT.exists() else []
with st.expander('恢复／查看已有会话'):
    if dirs:
        selected=st.selectbox('独立运行记录',[str(p.parent) for p in dirs],format_func=lambda x:Path(x).name)
        if st.button('载入此会话'):st.session_state['closed_loop_dir']=selected
    else:st.caption('尚无运行记录。')

example=cl.OUT/'CL_20260914_124949_410d5f9d'
if (example/'session.json').is_file():
    if st.button('查看历史5轮反馈示例（不启动求解）'):
        st.session_state['closed_loop_dir']=str(example)
    st.caption('2026-09-14低幅、固定负载示例：RAW功率下降后反向调频，并实际执行下一指令。仅说明反馈链有效，不代表稳态或安全验收。')

current=st.session_state.get('closed_loop_dir')
if not current:
    st.info('请在左侧新建会话。页面不会自动启动LTspice，也不会用Python解析结果伪装成反馈。')
    st.stop()
p=Path(current);cfg=cl.load(p/'config.json');session=cl.load(p/'session.json')
st.caption(f'当前证据目录：{p}')
st.info(f"冻结配置：{cfg['plant']['case']['case_id']} · 每轮{cfg['period_s']*1000:g} ms · 步长{cfg['step_hz']:g} Hz。修改侧栏只影响下一次新建会话。")
c1,c2,c3=st.columns(3)
c1.metric('已完成真实反馈轮数',len(session['records']))
c2.metric('会话状态',{'READY':'可继续运行','COMPLETE':'达到轮数上限','HALTED':'硬停机锁存','ERROR':'计算失败'}.get(session['status'],session['status']))
c3.metric('下一条频率指令',f"{session['next_command']['frequency_hz']/1e6:.4f} MHz")
st.caption(f"下一条幅度指令 a={session['next_command']['amplitude']:.4f}；只有执行下一轮后，该指令才有对应的LTspice响应。")
st.caption('达到轮数上限仅表示本次运行结束，不代表寻优收敛或通过连续稳态验收。')
if session.get('error'):st.error(session['error'])
active=session['status']=='READY'
left,right=st.columns(2)
one=left.button('执行下一轮真实LTspice反馈',disabled=not active,type='primary')
batch=right.button('执行最多3轮（小规模检查）',disabled=not active)
if one or batch:
    try:
        with st.status('真实LTspice联算中；本次按钮执行结束后可停止追加。没有实时中断按钮，请勿重复提交。',expanded=True) as status:
            for _ in range(3 if batch else 1):
                if cl.load(p/'session.json')['status']!='READY':break
                r=cl.run_step(p)
                st.write(f"第{r['iteration']+1}轮：{r['state']}；{r['reason']}；计算耗时{r['wall_seconds']:.1f} s")
                if r['state']=='TRIP_TO_ZERO':
                    st.warning('检测到硬越限：现在额外求解零幅指令，随后锁存停机。')
                    cl.run_step(p);break
            status.update(label='本次真实反馈计算结束',state='complete')
    except Exception as e:st.error(f'本次停止，未使用解析回退：{e}')
    else:st.rerun()

records=session['records']
if records:
    r=records[-1];m=r['measurement'];cols=st.columns(4)
    cols[0].metric('末窗口端口电压',f"{m['vpp']:.2f} Vpp")
    cols[1].metric('末窗口端口电流（RMS）',f"{m['irms_A']*1000:.3f} mA")
    cols[2].metric('反馈端口有功功率',f"{m['p_port_W']*1000:.3f} mW")
    cols[3].metric('换能器端口基波相位','不可定义' if m['phase_port_deg'] is None else f"{m['phase_port_deg']:.2f}°")
    st.success('数据来源：真实LTspice RAW。')
    st.write(f"**最新决策：{r['state']}** — {r['reason']}")
    rows=[]
    for rec in records:
        mm=rec['measurement'];cc=rec['command']
        rows.append({'轮次':rec['iteration']+1,'电路时间(s)':rec['time_s'],'频率(MHz)':cc['frequency_hz']/1e6,
            '幅度a':cc['amplitude'],'端口功率(mW)':mm['p_port_W']*1000,'尾段Vpp':mm['vpp'],
            '尾段Irms(mA)':mm['irms_A']*1000,'本轮最大窗口Vpp':mm['max_window_vpp'],
            '本轮最大窗口Irms(mA)':mm['max_window_irms_A']*1000,'状态':rec['state'],
            '下一频率(MHz)':rec['next_command']['frequency_hz']/1e6,'下一幅度':rec['next_command']['amplitude'],
            '真实求解耗时(s)':rec['wall_seconds'],'原因':rec['reason']})
    table=pd.DataFrame(rows)
    st.subheader('反馈时间序列（控制样本，不是载波波形）')
    st.line_chart(table,x='电路时间(s)',y='端口功率(mW)')
    l,rr=st.columns(2)
    l.line_chart(table,x='电路时间(s)',y='频率(MHz)');rr.line_chart(table,x='电路时间(s)',y='幅度a')
    st.dataframe(table,hide_index=True,width='stretch')
    st.download_button('下载本会话反馈表CSV',table.to_csv(index=False).encode('utf-8-sig'),'closed_loop_feedback.csv')
    st.subheader('逐轮证据：反馈是否真正影响了下一轮')
    idx=st.selectbox('检查轮次',list(range(len(records))),format_func=lambda i:f'第{i+1}轮')
    step=p/f'step_{idx:03d}';audit=cl.load(step/'execution.json');stim=cl.load(step/'stimulus.json')
    st.json({'本轮真实RAW_SHA256':audit.get('raw_sha256'),'上一轮反馈SHA256':stim['parent_feedback_sha256'],
             '求解返回码':audit.get('return_code'),'本轮使用指令':records[idx]['command'],
             '由本轮RAW产生的下一指令':records[idx]['next_command']})
    with st.expander('查看真实LTspice日志'):
        st.code((step/'circuit.log').read_text(encoding='utf-8',errors='replace'),language='text')
    st.caption(f"可在LTspice打开：{step/'circuit.raw'}")
    st.download_button('下载该轮网表',(step/'circuit.cir').read_bytes(),f'closed_loop_step_{idx:03d}.cir')
with st.expander('本会话冻结参数及模型来源'):st.json(cfg)
