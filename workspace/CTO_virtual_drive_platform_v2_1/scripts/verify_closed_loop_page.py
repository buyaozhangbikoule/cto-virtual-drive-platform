"""Streamlit script tests, not browser screenshots or solver validation."""
from pathlib import Path
import json,tempfile,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from streamlit.testing.v1 import AppTest

if __name__=='__main__':
    tmp=ROOT/'results/run_logs/closed_loop_page_test_tmp';tmp.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir=str(tmp)
    app=AppTest.from_file(str(ROOT/'pages/03_LTspice闭环验证.py'))
    app.run(timeout=30)
    empty_errors=[e.message for e in app.exception]
    app.session_state['closed_loop_dir']=str(ROOT/'results/ltspice_closed_loop/CL_20260914_112350_f3ffea20')
    app.run(timeout=30)
    loaded_errors=[e.message for e in app.exception]
    out={'empty_page_exceptions':empty_errors,'existing_results_exceptions':loaded_errors,
        'button_labels':[b.label for b in app.button],
        'scope':'Streamlit脚本渲染检查；没有点击求解按钮；不是浏览器截图测试或新仿真'}
    (ROOT/'results/run_logs/closed_loop_page_test_20260914.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(out,ensure_ascii=False))
    assert not empty_errors and not loaded_errors
