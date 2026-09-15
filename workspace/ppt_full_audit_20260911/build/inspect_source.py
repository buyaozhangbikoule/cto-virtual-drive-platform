from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import json, hashlib, posixpath

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(__file__).resolve().parent
SOURCE=ROOT/'project_audit_20260910/output/CTO组会汇报_计划书口径与验收缺口修订_2026-09-10.pptx'
NS={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
def rels(z,p):
    rp=posixpath.join(posixpath.dirname(p),'_rels',posixpath.basename(p)+'.rels')
    return {e.get('Id'):posixpath.normpath(posixpath.join(posixpath.dirname(p),e.get('Target'))) for e in ET.fromstring(z.read(rp)) if e.get('TargetMode')!='External'} if rp in z.namelist() else {}
def text(e): return '\n'.join(''.join(p.itertext()) for p in e.findall('.//a:t',NS))
with ZipFile(SOURCE) as z:
    pr=rels(z,'ppt/presentation.xml')
    order=[pr[e.get('{'+NS['r']+'}id')] for e in ET.fromstring(z.read('ppt/presentation.xml')).findall('p:sldIdLst/p:sldId',NS)]
    out=[]
    for n,part in enumerate(order,1):
        e=ET.fromstring(z.read(part)); rr=rels(z,part)
        shapes=[]
        for el in e.find('p:cSld/p:spTree',NS):
            nameel=el.find('.//p:cNvPr',NS)
            shapes.append({'type':el.tag.split('}')[-1],'name':nameel.get('name') if nameel is not None else '', 'text':text(el),'blips':[rr.get(b.get('{'+NS['r']+'}embed')) for b in el.findall('.//a:blip',NS)]})
        note=next((v for v in rr.values() if '/notesSlides/' in v),None)
        notetext=[]
        if note:
            for s in ET.fromstring(z.read(note)).findall('.//p:sp',NS):
                ph=s.find('.//p:ph',NS)
                if ph is not None and ph.get('type')=='body': notetext.append(text(s))
        out.append({'page':n,'part':part,'shapes':shapes,'notes':'\n'.join(notetext)})
    (WORK/'source_inventory.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    (WORK/'source_pages.txt').write_text('\n\n'.join(f"PAGE {x['page']} ({x['part']})\n"+'\n'.join(f"{s['name']} [{s['type']}] {s['text']}" for s in x['shapes']) for x in out),encoding='utf-8')
    (WORK/'source_notes.txt').write_text('\n\n'.join(f"PAGE {x['page']}\n{x['notes']}" for x in out),encoding='utf-8')
    print(json.dumps({'pages':len(out),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'part_order':order}))
