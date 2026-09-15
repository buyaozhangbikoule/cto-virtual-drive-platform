"""Reassemble the original RAW ZIP; validate each part and the complete SHA256."""
import argparse, hashlib, json
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,default=Path(__file__).resolve().parent);a=p.parse_args()
    folder=a.directory.resolve();m=json.loads((folder/'RELEASE_ASSETS.json').read_text(encoding='utf-8'))
    target=folder/'project_handoff_raw.zip'
    if target.exists():
        if sha(target)==m['original_raw_archive']['sha256']:
            print('Existing RAW archive verified:',target);return
        raise SystemExit('An unverified output already exists. It will not be overwritten.')
    h=hashlib.sha256();total=0
    for r in m['raw_parts']:
        name=r['name']
        if Path(name).name!=name:raise SystemExit('Unsafe part name')
        file=folder/name
        if not file.is_file() or file.stat().st_size!=r['bytes'] or sha(file)!=r['sha256']:
            raise SystemExit('Missing or damaged part: '+name)
    with target.open('xb') as out:
        for r in m['raw_parts']:
            with (folder/r['name']).open('rb') as f:
                for b in iter(lambda:f.read(8*1024*1024),b''):out.write(b);h.update(b);total+=len(b)
    if h.hexdigest()!=m['original_raw_archive']['sha256'] or total!=m['original_raw_archive']['bytes']:
        raise SystemExit('Complete checksum mismatch; do not use this ZIP.')
    print('Complete RAW ZIP SHA256 verified:',target)
    print('Extract project_handoff_main.zip and project_handoff_raw.zip to the same parent directory.')

if __name__=='__main__':main()
