"""Package truthful revision evidence without altering historical simulation data."""
from pathlib import Path
import csv
import hashlib
import json
from PIL import Image,ImageOps,ImageDraw

B=Path(__file__).resolve().parent;D=B.parent;R=D.parent;O=D/'output';P=R/'CTO_virtual_drive_platform_v2_1'
report=P/'docs/验收缺口与版本边界_20260910.md'
(O/report.name).write_bytes(report.read_bytes())
contract=json.loads((B/'contract.json').read_text(encoding='utf-8'))
thumbs=[]
for i in range(1,29):
    im=Image.open(B/f'all-slides/{i:02}.png').convert('RGB')
    tile=Image.new('RGB',(400,250),'white')
    fit=ImageOps.contain(im,(400,225));tile.paste(fit,((400-fit.width)//2,22))
    ImageDraw.Draw(tile).text((8,5),f'Slide {i}',fill='#17324D');thumbs.append(tile)
sheet=Image.new('RGB',(1600,7*250),'#dce4ed')
for i,tile in enumerate(thumbs):sheet.paste(tile,((i%4)*400,(i//4)*250))
sheet.save(B/'contact-sheet.png')

modified=[R/'outputs/v2_self_consistent_rebuild/active_stage3_5/model_v2_1.py',P/'models/python/model_v2_1.py',
 P/'config.yaml',P/'README.md',P/'scenarios/stage3_scenario_registry_and_summary.csv',
 P/'results/tables/stage3_disturbance/stage3_scenario_registry_and_summary.csv',
 R/'outputs/v2_self_consistent_rebuild/active_stage3_5/stage3_disturbance/stage3_scenario_registry_and_summary.csv',report]
paths=modified+sorted((D/'before').glob('*'))+sorted(B.glob('*.py'))+sorted(B.glob('*.mjs'))
paths+=sorted(p for p in O.iterdir() if p.is_file() and p.name!='本次修订文件哈希.csv')
rows=[dict(path=p.as_posix(),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
with (O/'本次修订文件哈希.csv').open('w',encoding='utf-8-sig',newline='') as h:
    w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print(json.dumps(dict(manifest_entries=len(rows),output=str(O)),ensure_ascii=False))
