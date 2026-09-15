from pathlib import Path
import json,hashlib,csv
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[2]; B=Path(__file__).resolve().parent
P=ROOT/'CTO_virtual_drive_platform_v2_1'
def df(rel): return pd.read_csv(P/rel)
phase=df('results/phase_ablation/phase_timeline_selected_gain.csv')
phase_summary=phase.groupby('case_id').agg(capture_min=('safe_power_capture_ratio','min'),capture_max=('safe_power_capture_ratio','max'),max_W=('p_rm_W','max'),max_amp=('amplitude','max')).reset_index().to_dict('records')
old=pd.read_csv(ROOT/'ppt_control_fix_20260906/build/data/stage4_control_timeline.csv')
registry=df('results/tables/stage3_disturbance/stage3_scenario_registry_and_summary.csv')
trend=df('results/tables/stage3_disturbance/stage3_trend_table.csv')
sel=df('results/tables/stage3_selection/stage3_initial_three_criteria.csv')
result={'phase_current':phase_summary,'old_columns':list(old.columns),'old_counts':old.groupby('strategy').size().to_dict(),'phase_sha256':hashlib.sha256((P/'results/phase_ablation/phase_timeline_selected_gain.csv').read_bytes()).hexdigest(),'registry_cases':len(registry),'registry_families':registry.groupby('family').size().to_dict(),'trend_columns':list(trend.columns),'selection_fs5':sel[sel.case_id=='CASE_FS_M5'].to_dict('records'),'trend_selected':trend[trend.case_id.isin(['CASE_C0_P30','CASE_RM_P50','CASE_FS_M5','CASE_RS_P20','CASE_LMATCH_P10','CASE_QL_20'])].to_dict('records') if 'case_id' in trend else []}
(B/'data_inspection.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
