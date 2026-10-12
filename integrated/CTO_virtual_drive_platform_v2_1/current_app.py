"""Version-separated platform entrypoint. UI does not rerun or optimize controllers."""
import streamlit as st

st.set_page_config(page_title='CTO虚拟电学平台 · 当前交付入口', layout='wide')
page = st.navigation({
    '当前统一结果': [st.Page('pages/04_统一三策略结果.py', title='统一三策略结果', default=True),
                    st.Page('pages/05_版本与证据分区.py', title='版本、补丁与证据分区')],
    '参数与依据': [st.Page('pages/06_参数来源登记.py', title='参数来源登记')],
    '历史与独立实验': [st.Page('pages/02_参数探索与历史结果.py', title='参数探索／历史结果'),
                       st.Page('pages/03_LTspice闭环验证.py', title='LTspice反馈接口（独立实验）')],
})
with st.sidebar:
    st.caption('当前正式比较：固定／扫频／相位反馈。P&O、幅度PI、去嵌相位和负载层为扩展研究。')
    st.caption('假设线性BVD电学仿真，非器件／声学／临床验证。')
page.run()
