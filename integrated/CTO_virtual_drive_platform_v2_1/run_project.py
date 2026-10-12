"""Current official entrypoint; historical run_all.py is NOT invoked."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from current.catalog import PLATFORM, load_active, register_batch

ENGINE = PLATFORM / 'current' / 'unified'


def run_logged(arguments, label, cwd=ENGINE):
    logs = PLATFORM / 'current' / 'logs'
    logs.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    dest = logs / f'{stamp}_{label}.txt'
    lines = []
    with dest.open('w', encoding='utf-8') as file:
        with subprocess.Popen([sys.executable, '-B', '-X', 'utf8', *arguments], cwd=cwd,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              encoding='utf-8', errors='replace') as process:
            for line in process.stdout:
                print(line, end='', flush=True)
                file.write(line)
                lines.append(line)
            if process.wait() != 0:
                raise RuntimeError(f'运行失败，未更新当前结果登记；查看 {dest}')
    return ''.join(lines)


def tagged_path(output, tag):
    matches = [line[len(tag)+1:] for line in output.splitlines() if line.startswith(tag+' ')]
    if len(matches) != 1:
        raise RuntimeError(f'必须收到唯一的 {tag} 路径；不自动选择最新目录')
    return Path(matches[0])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='校验证据并显示当前明确登记的批次')
    sub.add_parser('test', help='行为测试及平台接入测试')
    v = sub.add_parser('validate', help='新建完整批次→逐日志复核→登记为当前结果')
    v.add_argument('--suite', choices=['all','historical'], default='all')
    sub.add_parser('verify', help='再次核对当前批次哈希、覆盖及复核记录')
    ui = sub.add_parser('ui', help='打开分区后的平台（不自动运行仿真）')
    ui.add_argument('--port', type=int, default=8501)
    args = p.parse_args()
    if args.command == 'ui':
        return subprocess.call([sys.executable, '-m', 'streamlit', 'run', str(PLATFORM/'current_app.py'),
                                '--server.port', str(args.port), '--server.address', '127.0.0.1',
                                '--server.headless', 'true', '--browser.gatherUsageStats', 'false'], cwd=PLATFORM)
    if args.command == 'test':
        run_logged(['run_unified.py','--test-only'], 'behavior_tests')
        run_logged(['-m','unittest','discover','-s',str(PLATFORM/'current'/'tests'),'-v'],
                   'platform_tests',cwd=PLATFORM)
        return 0
    if args.command == 'validate':
        output = run_logged(['run_unified.py','--suite',args.suite], 'unified_run')
        batch = tagged_path(output, 'OUTPUT')
        audit = tagged_path(run_logged(['audit_batch.py',str(batch)],'independent_audit'), 'AUDIT')
        if args.suite == 'all':
            pointer = register_batch(batch,audit)
            print('已登记当前完整批次：'+pointer['batch_id'])
        else:
            print('仅12段诊断运行，未替换当前正式完整批次：'+str(batch))
        return 0
    evidence = load_active()
    print(json.dumps(dict(batch=evidence['metadata']['batch_id'],
        timelines=evidence['audit']['timelines'],tests=evidence['metadata']['tests_passed'],
        audit_pass=evidence['audit']['audit_pass'],source_drift=evidence['source_drift'],
        table=str(evidence['folder']/'historical_12_three_strategy_table.csv'),
        boundary='复核通过不代表控制全部通过，不是实测/声学/硬件安全验证'),ensure_ascii=False,indent=2))
    return 1 if evidence['source_drift'] else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        raise SystemExit(1)
