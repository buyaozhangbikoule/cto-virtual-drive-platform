"""Route wrapper; legacy calculations and records retain their original identity."""
from pathlib import Path
import runpy
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from current.provenance_ui import source_page_link
source_page_link()
runpy.run_path(str(ROOT/'streamlit_app.py'),run_name='__main__')
