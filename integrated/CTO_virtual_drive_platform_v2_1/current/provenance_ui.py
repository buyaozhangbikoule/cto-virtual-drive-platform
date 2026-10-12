"""Parameter source browser. No write-back, simulation, or automatic adoption."""
import csv
import io
import json
import pandas as pd
import streamlit as st
from current.catalog import PLATFORM, inside
from current.parameter_sources import check_registry, format_value, registry_json

PAGE = 'pages/06_参数来源登记.py'


def source_page_link():
    st.page_link(PAGE, label='查看参数来源、单位、适用条件与采用理由')


def render_parameter_sources():
    st.title('参数来源登记')
    st.caption('只读溯源 · 不修改冻结BVD、控制配置或当前批次 · 文献数值不自动接入模型')
    st.info('100 Vpp、5 mA RMS、50 Ω是设计工况或推荐量级，不是器件辨识结果。'
            'Saijo参考仅适用于所述100–200 MHz测量条件；2.5–7.8 MRayl仍待核实。')
    try:
        result = check_registry()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f'参数来源登记不完整，停止展示：{exc}')
        st.stop()
    if result['ok']:
        st.success('有数值绑定的条目与所列本地配置／代码一致；文献适用性和待核实条目不因此通过。')
    else:
        st.error('登记与源文件存在差异；以下是登记快照，不能冒充更新后的运行值。')
        for issue in result['issues']:
            st.write('• ' + issue)
    st.caption(result['scope'])
    entries = result['entries']
    groups = list(dict.fromkeys(e['group'] for e in entries))
    left, right = st.columns([1, 2])
    with left:
        group = st.selectbox('来源分区', ['全部'] + groups, key='provenance_group')
    with right:
        query = st.text_input('搜索参数或来源（如 C0、50、Saijo、钙化）', key='provenance_query').strip().casefold()
    filtered = [e for e in entries if (group == '全部' or e['group'] == group)
                and (not query or query in ' '.join([e['id'], e['name'], e['identity'],
                    format_value(e), *[s['title'] for s in e['sources']]]).casefold())]
    if not filtered:
        st.warning('没有匹配条目；请清空搜索或切换分区。')
    else:
        selected = st.selectbox('选择参数，展开来源说明', [e['id'] for e in filtered],
            format_func=lambda key: next(e['name'] for e in filtered if e['id'] == key),
            key='provenance_parameter')
        entry = next(e for e in filtered if e['id'] == selected)
        st.subheader(entry['name'])
        st.markdown(f'**登记值：{format_value(entry)}**')
        st.write('参数身份：' + entry['identity'])
        st.write('是否在正式模型／配置中使用：' + ('是，仍保留假设身份' if entry['formal_use'] else '否'))
        st.caption(entry['value_check'])
        if 'source_value' in entry and entry['source_value'] != entry['value']:
            st.write('源文件当前原始值（非自动采用）：', entry['source_value'])
        if entry['status'] == '待核实':
            st.error('待核实：不能作为默认参数、有效文献范围或扫描上下界。')
        elif entry['profile'] in ('saijo', 'research'):
            st.warning('独立参考／研究原型：未接入正式模型，不覆盖钙化默认值。')
        with st.expander('来源、适用频段、测量条件和采用理由', expanded=True):
            for label, key in [('单位（源文件口径）', 'unit'), ('适用频段与证据范围', 'frequency_scope'),
                               ('测量／计算条件', 'measurement_conditions'), ('采用／保留理由', 'adoption_reason'),
                               ('限制与待补信息', 'limitations')]:
                st.markdown(f'**{label}**：{entry[key]}')
            for n, source in enumerate(entry['sources']):
                st.markdown('**来源：' + source['title'] + '**')
                st.write(source['note'])
                if source.get('locator'):
                    st.write('原文位置：' + source['locator'])
                if source.get('url'):
                    st.link_button('打开论文来源（DOI）', source['url'])
                    st.caption('PDF不随平台分发；本机原文：' + source['local_pdf'])
                    st.code('SHA256: ' + source['pdf_sha256'], language=None)
                if source.get('path'):
                    st.code(source['path'], language=None)
                    file = inside(PLATFORM, source['path'])
                    if file.is_file():
                        st.download_button('下载该来源文件 · ' + file.name,
                            file.read_bytes(), file_name=file.name,
                            key=f'provenance_source_{entry["id"]}_{n}')
                    else:
                        st.warning('来源文件当前不可用，不代表已经复核。')
            if entry.get('binding'):
                st.caption('只读数值定位（JSON字段或Python声明；不执行研究脚本）')
                st.json(entry['binding'], expanded=False)
        table = [{'参数': e['name'], '登记值': format_value(e), '身份': e['status'],
                  '正式使用': '是' if e['formal_use'] else '否', 'ID': e['id']} for e in filtered]
        with st.expander(f'分区速查表（{len(table)}条）'):
            st.dataframe(pd.DataFrame(table), hide_index=True, width='stretch')
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.download_button('下载完整登记与核对结果（JSON）', registry_json(result).encode('utf-8'),
            file_name='parameter_provenance.json', mime='application/json')
    rows = [{'参数': e['name'], '显示值': format_value(e),
             '原始数值': json.dumps(e['value'], ensure_ascii=False),
             '原始单位': e['unit'], '标准差SD（原始单位）': e.get('sd', ''), '来源': ' | '.join(
                s.get('path', s.get('url', s['title'])) for s in e['sources']),
             '身份': e['identity'], '适用频段': e['frequency_scope'], '测量条件': e['measurement_conditions'],
             '采用理由': e['adoption_reason'], '限制': e['limitations'], '正式使用': e['formal_use'],
             '核对': e['value_check']} for e in entries]
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    with col2:
        st.download_button('下载完整参数来源表（CSV）', buffer.getvalue().encode('utf-8-sig'),
            file_name='参数来源登记.csv', mime='text/csv')
    st.code('python -B -X utf8 -m current.parameter_sources', language='powershell')
    st.caption('本页核对本地声明与登记，不替代“统一三策略结果”页对保存批次的哈希及源码漂移核查。'
               '滑块探索值仍是扫描变量，不会改变基线身份；本次没有新的闭环或声场实验。')
