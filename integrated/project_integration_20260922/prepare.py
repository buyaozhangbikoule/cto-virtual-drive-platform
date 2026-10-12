"""Materialize a new official implementation without modifying frozen inputs."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PLATFORM = ROOT / 'CTO_virtual_drive_platform_v2_1'
TARGET = PLATFORM / 'current' / 'unified'
CHECKOUT = ROOT / 'github_update_three_strategy_20260917' / 'checkout'
SOURCE = CHECKOUT / 'workspace' / 'CTO_plan_three_strategy_v1_20260917'
REVIEW = ROOT / 'github_radiation_fix_20260922' / 'checkout'
GIT = r'C:\Users\24739\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe'
BASE = '650abdc87f3fcf10f5d4250aaf520efcfde3b56d'
FILES = ['README.md', 'requirements.txt', 'config.json', 'controllers.py',
         'engine.py', 'metrics.py', 'run_unified.py', 'audit_batch.py',
         'tests/test_unified.py', 'models/model_v2_1.py',
         'stage2_matching/stage2_控制源幅度校准.json',
         'stage2_matching/stage2_匹配设计参数.json']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def main():
    if TARGET.exists():
        raise RuntimeError('Integration already prepared; do not overwrite it')
    head = subprocess.check_output([GIT, 'rev-parse', 'HEAD'], cwd=CHECKOUT, text=True).strip()
    if head != BASE:
        raise RuntimeError('Unexpected validation source revision: '+head)
    records = []
    for name in FILES:
        src = SOURCE / name
        rel = src.relative_to(CHECKOUT).as_posix()
        blob = subprocess.check_output([GIT, 'rev-parse', BASE+':'+rel], cwd=CHECKOUT, text=True).strip()
        raw = src.read_bytes()
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() != blob:
            raise RuntimeError('Local source differs from Git: '+name)
        dest = TARGET / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        records.append(dict(path=name, base_sha256=sha(dest), git_blob=blob))
    config = TARGET / 'config.json'
    write_json(config, json.loads(config.read_text(encoding='utf-8')))
    archive = ROOT / 'project_integration_20260922' / 'original_platform_entrypoints'
    archive.mkdir(parents=True, exist_ok=True)
    backups = []
    for name in ['README.md', 'streamlit_app.py', 'run_all.py']:
        shutil.copy2(PLATFORM/name, archive/name)
        backups.append(dict(path=name, sha256=sha(PLATFORM/name)))
    patch_dir = PLATFORM / 'current' / 'patches'
    patch_dir.mkdir(parents=True, exist_ok=True)
    patch = REVIEW / 'review/patches/plan_three_strategy.scan_fault_taxonomy.patch'
    shutil.copy2(patch, patch_dir/patch.name)
    protected = {}
    for folder in [PLATFORM/'results/tables', PLATFORM/'models', PLATFORM/'interfaces',
                   ROOT/'outputs/v2_self_consistent_rebuild/active_stage3_5',
                   ROOT/'CTO_plan_three_strategy_v1_20260917']:
        for p in folder.rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix.lower() in ('.py','.json','.csv','.md','.yaml'):
                protected[p.relative_to(ROOT).as_posix()] = sha(p)
    write_json(ROOT/'project_integration_20260922/protected_history.json', protected)
    write_json(PLATFORM/'current/integration_sources.json', dict(
        schema_version=1, release='current-unified-20260922',
        repository='https://github.com/buyaozhangbikoule/cto-virtual-drive-platform',
        validation_branch='validation/plan-three-strategy-v1-20260917',
        validation_commit=BASE, review_commit_checked='dd1a58eda1116e54835a97bc0afff519316bc735',
        patch_source='review/patches/'+patch.name, patch_sha256=sha(patch),
        patch_status='PENDING', upstream_files=records, platform_backups=backups,
        frozen_history_files=len(protected),
        excludes=['PPT', 'speaker_notes', 'new_radiation_load', 'PI', 'P_AND_O', 'deembedded_phase'],
        numeric_parameters_changed=False, github_pushed=False))
    print('Prepared', TARGET, 'protected history files:',len(protected))

if __name__ == '__main__':
    main()
