import os
from pathlib import Path
import tempfile
import unittest
from current.catalog import PLATFORM

# Streamlit's test harness also creates temporary files. Keep them inside a known
# workspace subtree (the Windows Store Python's default temp ACL can differ).
TEMP = PLATFORM/'current/ui_test_tmp'
TEMP.mkdir(exist_ok=True)
tempfile.tempdir = str(TEMP)
from streamlit.testing.v1 import AppTest


@unittest.skipUnless((PLATFORM/'current/active_batch.json').exists(),'requires a registered full batch')
class UITests(unittest.TestCase):
    def app(self):
        a=AppTest.from_file(str(PLATFORM/'current_app.py'),default_timeout=45).run()
        self.assertEqual(len(a.exception),0,[e.message for e in a.exception])
        return a

    def test_default_current_results_and_selection(self):
        a=self.app()
        self.assertEqual(a.title[0].value,'统一三策略结果')
        self.assertEqual(a.dataframe[0].value.shape[0],3)
        a.selectbox[1].set_value(3).run()
        self.assertEqual(len(a.exception),0)
        self.assertEqual(a.dataframe[4].value.shape[0],3)
        a.selectbox[0].set_value('COVER_CASE_COMBINED_HIGH').run()
        self.assertEqual(len(a.exception),0,[e.message for e in a.exception])

    def test_version_and_experimental_pages(self):
        a=self.app().switch_page('pages/05_版本与证据分区.py').run()
        self.assertEqual(len(a.exception),0,[e.message for e in a.exception])
        self.assertEqual(a.title[0].value,'版本、补丁与证据分区')
        a.switch_page('pages/03_LTspice闭环验证.py').run()
        self.assertEqual(len(a.exception),0,[e.message for e in a.exception])
        self.assertEqual(a.title[0].value,'LTspice闭环验证')

    def test_legacy_page_remains_available(self):
        a=self.app().switch_page('pages/02_参数探索与历史结果.py').run()
        self.assertEqual(len(a.exception),0,[e.message for e in a.exception])
        self.assertTrue(any('历史' in i.value for i in a.info))


if __name__=='__main__':unittest.main()
