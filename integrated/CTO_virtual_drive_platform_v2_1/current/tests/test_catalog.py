import csv
import json
from pathlib import Path
import shutil
import uuid
import unittest
from current.catalog import EvidenceError, PLATFORM, inside, load_active, register_batch, sha, validate_batch


class CatalogTests(unittest.TestCase):
    def setUp(self):
        cache = PLATFORM/'current'/'test_tmp'
        cache.mkdir(exist_ok=True)
        self.root = (cache / ('catalog_' + uuid.uuid4().hex)).resolve()
        self.root.mkdir(mode=0o777)
        self.folder = self.root/'current/unified/outputs/UNIFIED_fixture'
        self.folder.mkdir(parents=True)
        self.audit = self.root/'current/unified/audits/receipt.json'
        self.audit.parent.mkdir()
        self.s = ['FIXED','PERIODIC_SCAN','PHASE_FEEDBACK']
        self.cases = ['CASE_'+str(i) for i in range(34)]
        self.json('run_metadata.json',dict(batch_id=self.folder.name,strategies=self.s,suite_count=35,tests_passed=41,source_hashes={}))
        for name in ['configuration.json','reference_optima.json','phase_calibration.json','schedules.json','integration_sources.json']:
            self.json(name,{})
        self.json('scenario_registry.json',[dict(case_id=c) for c in self.cases])
        (self.folder/'tests.txt').write_text('fixture, not experimental data',encoding='utf-8')
        rows=[]
        for suite in ['HISTORICAL_12']+['COVER_'+c for c in self.cases]:
            for s in self.s:
                row=dict(suite=suite,strategy=s,scan_failures=0,**{'scan_failures_'+c:0 for c in ['search','preemption','measurement','nonstationary']})
                rows.append(row)
                self.json(f'events/{suite}_{s}.json',[])
                self.csv(f'executions/{suite}_{s}.csv',[dict(dummy='fixture')])
        self.csv('formal_three_strategy_summary.csv',rows)
        self.csv('historical_12_three_strategy_table.csv',rows[:3])
        self.csv('registered34_target_segment_metrics.csv',[dict(case_id=c,strategy=s) for c in self.cases for s in self.s])
        self.csv('per_segment_metrics.csv',[dict(settled=False,steady_error_pct='')])
        self.seal()

    def tearDown(self):
        allowed = (PLATFORM/'current'/'test_tmp').resolve()
        if self.root.parent != allowed or not self.root.name.startswith('catalog_'):
            raise RuntimeError('Refuse unsafe fixture cleanup')
        shutil.rmtree(self.root)

    def json(self,name,value):
        p=self.folder/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value),encoding='utf-8')

    def csv(self,name,rows):
        p=self.folder/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

    def seal(self):
        files={p.relative_to(self.folder).as_posix():sha(p) for p in self.folder.rglob('*') if p.is_file() and p.name!='manifest.json'}
        self.json('manifest.json',dict(batch_id=self.folder.name,files=files))
        self.audit.write_text(json.dumps(dict(batch_id=self.folder.name,audit_pass=True,problems=[],timelines=105,manifest_files_verified=len(files))),encoding='utf-8')

    def valid(self):
        return validate_batch(self.folder,self.audit,self.root)

    def test_valid_complete_batch_registers(self):
        register_batch(self.folder,self.audit,self.root)
        self.assertEqual(load_active(self.root)['metadata']['batch_id'],self.folder.name)

    def test_no_implicit_newest_fallback(self):
        with self.assertRaises(EvidenceError):load_active(self.root)

    def test_tamper_rejected(self):
        (self.folder/'tests.txt').write_text('changed',encoding='utf-8')
        with self.assertRaises(EvidenceError):self.valid()

    def test_missing_data_rejected(self):
        (self.folder/'tests.txt').unlink()
        with self.assertRaises(EvidenceError):self.valid()

    def test_path_escape_rejected(self):
        with self.assertRaises(EvidenceError):inside(self.root,'../outside.json')

    def test_noncurrent_output_rejected(self):
        with self.assertRaises(EvidenceError):validate_batch(self.root,self.audit,self.root)

    def test_failed_audit_rejected(self):
        doc=json.loads(self.audit.read_text());doc['audit_pass']=False
        self.audit.write_text(json.dumps(doc))
        with self.assertRaises(EvidenceError):self.valid()

    def test_old_p_and_o_strategy_rejected(self):
        p=self.folder/'run_metadata.json';d=json.loads(p.read_text());d['strategies'][-1]='P_AND_O'
        self.json(p.name,d);self.seal()
        with self.assertRaises(EvidenceError):self.valid()

    def test_incomplete_target_coverage_rejected(self):
        self.csv('registered34_target_segment_metrics.csv',[dict(case_id=c,strategy=s) for c in self.cases[:-1] for s in self.s]);self.seal()
        with self.assertRaises(EvidenceError):self.valid()

    def test_fallback_steady_error_rejected(self):
        self.csv('per_segment_metrics.csv',[dict(settled=False,steady_error_pct=0)]);self.seal()
        with self.assertRaises(EvidenceError):self.valid()

    def test_scan_failure_count_recomputed(self):
        self.json('events/HISTORICAL_12_PERIODIC_SCAN.json',[dict(event='SCAN_FAILURE',budget_class='preemption')]);self.seal()
        with self.assertRaises(EvidenceError):self.valid()

    def test_changed_receipt_after_registration_rejected(self):
        register_batch(self.folder,self.audit,self.root)
        self.audit.write_text(self.audit.read_text()+' ')
        with self.assertRaises(EvidenceError):load_active(self.root)

    def test_actual_current_batch(self):
        if not (PLATFORM/'current/active_batch.json').exists():self.skipTest('first full run not yet registered')
        actual=load_active()
        self.assertEqual(actual['source_drift'],[])
        self.assertEqual(len(actual['targets']),102)
        self.assertEqual(actual['audit']['timelines'],105)


if __name__=='__main__':unittest.main()
