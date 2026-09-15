"""Restore both original ZIP archives from verified 16 MiB release parts."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    manifest=json.loads((HERE/'ARCHIVE_MANIFEST.json').read_text(encoding='utf-8'))
    for archive in manifest['archives']:
        output=HERE/archive['name']
        if output.exists():
            if output.stat().st_size==archive['bytes'] and digest(output)==archive['sha256']:
                print('Already verified:',output.name);continue
            raise RuntimeError('Existing output differs; move it aside before retrying: '+output.name)
        for part in archive['parts']:
            path=HERE/part['name']
            if not path.is_file() or path.stat().st_size!=part['bytes'] or digest(path)!=part['sha256']:
                raise RuntimeError('Missing or corrupt part: '+part['name'])
        h=hashlib.sha256();total=0
        with output.open('xb') as out:
            for part in archive['parts']:
                with (HERE/part['name']).open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        out.write(block);h.update(block);total+=len(block)
        if total!=archive['bytes'] or h.hexdigest()!=archive['sha256']:
            raise RuntimeError('Combined archive verification failed: '+output.name)
        print('Restored and SHA256 verified:',output.name)
    print('Extract both ZIPs into the same parent directory; read 00_先读_项目交接说明.md.')

if __name__=='__main__':main()
