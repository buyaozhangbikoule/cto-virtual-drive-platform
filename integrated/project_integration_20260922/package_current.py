"""Package the current integrated release, with explicit exclusions and SHA-256 verification.

This archives existing code/results without changing their content. The legacy
RAW archive, PPT, third-party documents, credentials, and Python caches are not included.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

WORKSPACE=Path(__file__).resolve().parents[1]
PLATFORM=WORKSPACE/'CTO_virtual_drive_platform_v2_1'
sys.path.insert(0,str(PLATFORM))
from current.catalog import load_active, read_json, sha

ALLOWED={'.py','.md','.txt','.json','.yaml','.yml','.csv','.tsv','.patch','.log',
         '.asc','.net','.cir','.plt','.svg','.png','.jpg','.jpeg','.ps1','.bat','.toml'}
SKIP={'.git','__pycache__','.pytest_cache','.venv','venv','test_tmp','ui_test_tmp','node_modules'}
ROOTNAME='CTO_当前整合版_20260923'
OUT=WORKSPACE/'delivery_zip_20260923'


def selected_files():
    files={}
    omitted=Counter()
    def add(path):
        p=path.resolve()
        if not p.is_relative_to(WORKSPACE):raise ValueError('Outside workspace: '+str(p))
        rel=p.relative_to(WORKSPACE).as_posix()
        files[rel]=p
    for directory in ['CTO_virtual_drive_platform_v2_1',
                      'outputs/v2_self_consistent_rebuild/active_stage3_5',
                      'outputs/v2_self_consistent_rebuild/stage2_matching']:
        for folder,dirs,names in os.walk(WORKSPACE/directory,followlinks=False):
            dirs[:]=[d for d in dirs if d not in SKIP and not (Path(folder)/d).is_symlink()]
            for name in names:
                path=Path(folder)/name
                if path.is_symlink():continue
                if path.suffix.lower() not in ALLOWED and name!='.gitignore':
                    omitted[path.suffix.lower() or '<no extension>']+=1
                    continue
                if name.lower().startswith('.env') or 'credential' in name.lower():
                    omitted['credential_or_env_name']+=1
                    continue
                add(path)
    for rel in [
        'ltspice_transient_replay_20260911_continue/运行与核查报告.md',
        'control_factorial_20260907/deliverables/第二轮控制消融验证报告.md',
        'project_integration_20260922/prepare.py',
        'project_integration_20260922/collect_registry.py',
        'project_integration_20260922/finalize.py',
        'project_integration_20260922/package_current.py',
        'project_integration_20260922/protected_history.json',
    ]:
        add(WORKSPACE/rel)
    for path in (WORKSPACE/'project_integration_20260922/original_platform_entrypoints').iterdir():
        if path.is_file():add(path)
    return files,omitted


def startup_readme(batch):
    return f'''# 先读我：当前整合代码与说明包

打包日期：2026-09-23。当前统一批次：{batch}。

这是“本次整合代码＋说明＋当前验证结果＋轻量历史支撑”的ZIP，**不是整个历史项目／RAW证据的全量备份**。PPT与旧演讲稿不在本次交付范围；程序代码与已有实验文件未为打包而改写。

## 解压与启动

完整解压本ZIP；建议使用D:\\CTO或其他较短路径，避免Windows传统260字符路径限制。保持CTO_virtual_drive_platform_v2_1与outputs为同级目录。不要只拖出一个.py文件，也不要在ZIP内直接运行。

在解压目录打开终端：

```powershell
cd CTO_virtual_drive_platform_v2_1
python -m pip install -r requirements-ui.txt
python run_project.py verify
python run_project.py ui
```

浏览器打开 http://127.0.0.1:8501 。端口占用可改为 `python run_project.py ui --port 8502`。

可选：`python run_project.py test`运行软件测试；`python run_project.py validate`创建新的完整三策略仿真批次，核验后更新解压目录里的当前登记。原ZIP不会改变。

当前统一引擎不需要LTspice即可运行。LTspice独立功能仍需接收方自行安装程序及确认路径（原设置D:/LTspice.exe不一定适用）；不附带软件或许可证。

## 文件身份

- `CTO_virtual_drive_platform_v2_1/current/`：统一引擎、已采用补丁、当前批次、逐日志复核、来源与测试。
- `docs/当前成果整合验收记录_20260923.md`与README：当前正式口径。
- `research/radiation_load_layer1/`：负载参考原型及原始说明，**尚未接入正式控制链**。
- 原 `results/`、`figures/`、`evidence/`：打包范围内的历史表格、图和日志，身份不变；与当前结果不能拼成同次实验。
- 同级 `outputs/v2_self_consistent_rebuild/`：历史交互页面所需模型／标定及相关轻量材料。
- `project_integration_20260922/`：整合过程记录与原入口备份；prepare/finalize等依赖原审核checkout，仅供审阅，接收方正式运行用run_project.py。

## 明确没有打包

历史LTspice RAW及.op.raw、完整瞬态原始证据、历史ZIP、PPT/PPTX、Word/PDF文献、软件安装包、许可证、Git凭据、虚拟环境、缓存和测试临时目录。已有日志／报告提到的原Windows绝对路径与RAW哈希保留作历史出处，**不表示对应RAW已在本ZIP中**。

已保留瞬态重放和算法消融的历史报告供查阅，但没有复制它们的全部外部实验目录。负载原型上游回归测试仍保留原仓库workspace布局依赖；当前控制结果不使用该原型。旧run_all.py不作为正式入口，其完整历史流水线所需其他外部目录未全量收集。

## 核验与限制

ZIP根目录`文件清单_SHA256.json`列出所含文件；ZIP旁`.sha256`校验压缩包本体。当前完整批次的内部manifest和audit仍保留原值。

这是特定假设BVD模型内的准稳态电学仿真。统一比较已完成≠所有控制策略通过稳态验收≠真实硬件瞬态硬限、结构声场或临床安全得到证明。未通过、保护前越限预测和全过程能量损失均保留。

本ZIP不会自动更新GitHub，也不会覆盖D盘旧ZIP。
'''


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--build',action='store_true')
    args=parser.parse_args()
    ev=load_active()
    if ev['source_drift']:raise RuntimeError('Current source differs from registered simulation batch')
    delivery=read_json(PLATFORM/'current/delivery_manifest.json')
    for rel,h in delivery['files'].items():
        if sha(PLATFORM/rel)!=h:raise RuntimeError('Delivery file changed since integration receipt: '+rel)
    files,omitted=selected_files()
    count_by_ext=Counter()
    for p in files.values():count_by_ext[p.suffix.lower()]+=p.stat().st_size
    plan=dict(files=len(files),uncompressed_MiB=sum(p.stat().st_size for p in files.values())/2**20,
              size_MiB_by_extension={s:round(b/2**20,3) for s,b in count_by_ext.most_common()},
              excluded_extension_counts=dict(omitted),batch=ev['metadata']['batch_id'])
    print(json.dumps(plan,ensure_ascii=False,indent=2),flush=True)
    if not args.build:return 0
    OUT.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest=OUT/f'CTO_修正整合代码与说明_{stamp}.zip'
    if dest.exists():raise RuntimeError('Archive already exists')
    manifest={}
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for rel,path in sorted(files.items()):
            archive_name=ROOTNAME+'/'+rel
            z.write(path,archive_name)
            manifest[rel]={'sha256':sha(path),'bytes':path.stat().st_size}
        readme=startup_readme(ev['metadata']['batch_id']).encode('utf-8')
        z.writestr(ROOTNAME+'/00_先读我_打包范围与启动.md',readme)
        manifest['00_先读我_打包范围与启动.md']={'sha256':hashlib.sha256(readme).hexdigest(),'bytes':len(readme)}
        z.writestr(ROOTNAME+'/文件清单_SHA256.json',json.dumps(dict(
            created_utc=datetime.now(timezone.utc).isoformat(),scope=plan,
            note='Manifest excludes itself; all listed files verified from ZIP after compression',files=manifest),
            ensure_ascii=False,indent=2).encode('utf-8'))
    # A short workspace path tests normal Windows extraction without requiring
    # a global long-path setting or changing the user's system configuration.
    extract=WORKSPACE/('zipcheck_'+datetime.now(timezone.utc).strftime('%H%M%S'))
    extract.mkdir(exist_ok=False)
    with zipfile.ZipFile(dest) as z:
        bad=z.testzip()
        if bad:raise RuntimeError('CRC failure: '+bad)
        for rel,info in manifest.items():
            data=z.read(ROOTNAME+'/'+rel)
            if hashlib.sha256(data).hexdigest()!=info['sha256']:raise RuntimeError('Archive hash failure: '+rel)
        # Only extract this freshly built, enumerated archive; reject any path escape.
        for name in z.namelist():
            target=(extract/name).resolve()
            if not target.is_relative_to(extract.resolve()):raise RuntimeError('Unsafe archive entry')
        z.extractall(extract)
    package_sha=sha(dest)
    dest.with_suffix('.zip.sha256').write_text(package_sha+'  '+dest.name+'\n',encoding='utf-8')
    extracted_platform=extract/ROOTNAME/'CTO_virtual_drive_platform_v2_1'
    smoke=subprocess.run([sys.executable,'-B','-X','utf8','run_project.py','verify'],cwd=extracted_platform,
                         text=True,encoding='utf-8',capture_output=True)
    log=OUT/(dest.stem+'_解压核验.txt')
    log.write_text(smoke.stdout+'\n'+smoke.stderr,encoding='utf-8')
    if smoke.returncode!=0:raise RuntimeError('Extracted entry verification failed: '+str(log))
    report=dict(zip=str(dest),bytes=dest.stat().st_size,sha256=package_sha,files_verified=len(manifest),
                zip_crc_pass=True,all_members_sha256_pass=True,extracted_current_entry_verify_pass=True,
                extracted_platform=str(extracted_platform),smoke_log=str(log),scope=plan)
    report_path=OUT/(dest.stem+'_打包核验.json')
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
