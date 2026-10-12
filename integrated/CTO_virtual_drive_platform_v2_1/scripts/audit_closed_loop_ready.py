"""Read-only audit of existing real-solver evidence plus Streamlit render checks.

This does not launch LTspice and does not constitute a new simulation or browser QA.
"""
from datetime import datetime
from pathlib import Path
import sys, tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import ltspice_closed_loop as cl


def main():
    # Keep Streamlit's temporary script under the writable workspace on Windows.
    test_temp = ROOT / 'results/run_logs/closed_loop_readiness_tmp'
    test_temp.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(test_temp)
    from streamlit.testing.v1 import AppTest
    session_dir = ROOT / 'results/ltspice_closed_loop/CL_20260914_124949_410d5f9d'
    cfg = cl.load(session_dir / 'config.json')
    session = cl.load(session_dir / 'session.json')
    state = dict(direction=1, previous=None, hold_left=0, trip=False)
    checks = []
    for k, record in enumerate(session['records']):
        step = session_dir / f'step_{k:03d}'
        execution = cl.load(step / 'execution.json')
        stimulus = cl.load(step / 'stimulus.json')
        next_cmd, state, status, reason, saturated = cl.decide(cfg, state, record['command'], record['measurement'])
        hashes = {
            'cir': cl.sha(step / 'circuit.cir') == execution['cir_sha256'],
            'raw': cl.sha(step / 'circuit.raw') == execution['raw_sha256'],
            'log': cl.sha(step / 'circuit.log') == execution['log_sha256'],
            'parent_feedback': stimulus['parent_feedback_sha256'] == (
                cl.sha(session_dir / f'step_{k-1:03d}/feedback.json') if k else None),
        }
        checks.append(dict(iteration=k+1, hashes=hashes,
            solver_return_zero=execution['return_code'] == 0,
            full_prefix_matches=stimulus['commands'] == [r['command'] for r in session['records'][:k+1]],
            command_matches_parent=k == 0 or record['command'] == session['records'][k-1]['next_command'],
            decision_reproduced=next_cmd == record['next_command'] and status == record['state']
                and reason == record['reason'] and saturated == record['frequency_saturated']))
    app = AppTest.from_file(str(ROOT / 'pages/03_LTspice闭环验证.py'))
    app.run(timeout=30)
    empty_errors = [e.message for e in app.exception]
    example_button = next(b for b in app.button if b.label == '查看历史5轮反馈示例（不启动求解）')
    example_button.click().run(timeout=30)
    loaded_errors = [e.message for e in app.exception]
    report = dict(checked_at=datetime.now().astimezone().isoformat(),
        source_session=str(session_dir), new_simulation=False, browser_screenshot_test=False,
        evidence_checks=checks, empty_page_errors=empty_errors, loaded_page_errors=loaded_errors,
        example_button_loads_expected_session=app.session_state['closed_loop_dir'] == str(session_dir),
        decision_source_matches_run=cl.sha(cl.__file__) == cfg['controller_source_sha256'],
        scope='现有五轮真实RAW文件完整性、指令因果链、决策复算与页面脚本渲染；不是新的LTspice运行或控制性能验收',
        environment_note='本机Windows Store Python曾在测试退出清理临时目录时提示WinError 5；本报告只判定此前完成的功能及证据检查，不包含临时目录清理成功保证。')
    passed = not empty_errors and not loaded_errors and all(
        all(c['hashes'].values()) and all(c[key] for key in [
            'solver_return_zero', 'full_prefix_matches', 'command_matches_parent', 'decision_reproduced'])
        for c in checks)
    report['passed'] = passed and report['decision_source_matches_run'] and report['example_button_loads_expected_session']
    path = ROOT / 'results/run_logs/closed_loop_readiness_audit_20260914.json'
    cl.dump(path, report)
    print(f'Audit passed: {report["passed"]}; {len(checks)} real-solver records checked; report: {path}')
    if not report['passed']:
        raise SystemExit('Existing evidence or page check failed; inspect the report.')


if __name__ == '__main__':
    main()
