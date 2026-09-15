"""Package only the source records and reproducible scripts used for slide 15."""
from pathlib import Path
import hashlib
import json
import zipfile
from PIL import Image, ImageChops
B=Path(__file__).resolve().parent
O=B.parent/'output'
R=B.parent.parent
same=[]
for n in range(1,29):
    if n==15: continue
    old=Image.open(R/'ppt_full_audit_20260911/build/final-render'/f'{n:02}.png').convert('RGB')
    new=Image.open(B/'final-render'/f'{n:02}.png').convert('RGB')
    assert ImageChops.difference(old,new).getbbox() is None,n
    same.append(n)
files=[B/x for x in ['prepare_evidence.py','build_slide.mjs','render_verify.mjs','finalize.mjs','validate_publish.py','notes.txt','source_main_displayed.csv','source_phase_displayed.csv','figure_contract.json','build_receipt.json','fallback_validation_receipt.json']]
files+=list((B/'figures').glob('*'))
with zipfile.ZipFile(O/'第15页_作图与证据.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in files:z.write(f,f.relative_to(B).as_posix())
manifest={'new_simulation':False,'changed_slide':15,'unchanged_slides_pixel_identical':same,'PowerPoint_GUI_verified':False,'notes_match_delivered_text':True,'artifacts':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in O.iterdir() if f.is_file()}}
(B/'final_delivery_receipt.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'outputs':list(manifest['artifacts']),'other_slides_identical':len(same)},ensure_ascii=False))
