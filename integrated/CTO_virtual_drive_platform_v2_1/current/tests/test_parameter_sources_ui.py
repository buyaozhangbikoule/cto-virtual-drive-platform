import tempfile
import unittest
from current.catalog import PLATFORM
from current.provenance_ui import PAGE

TEMP = PLATFORM/'current/ui_test_tmp'
TEMP.mkdir(exist_ok=True)
tempfile.tempdir = str(TEMP)
from streamlit.testing.v1 import AppTest


class ProvenanceUITests(unittest.TestCase):
    def app(self):
        a = AppTest.from_file(str(PLATFORM/'current_app.py'), default_timeout=45).run()
        a.switch_page(PAGE).run()
        self.assertEqual(len(a.exception), 0, [e.message for e in a.exception])
        return a

    def test_sources_page_and_saijo_details(self):
        a = self.app()
        self.assertEqual(a.title[0].value, '参数来源登记')
        a.selectbox(key='provenance_group').set_value('Saijo文献参考（不采用）').run()
        a.selectbox(key='provenance_parameter').set_value('saijo.calcification.c').run()
        self.assertEqual(len(a.exception), 0, [e.message for e in a.exception])
        text = '\n'.join(m.value for m in a.markdown)
        self.assertIn('1760 ± 14', text)
        self.assertIn('100–200 MHz', text)
        self.assertIn('Table 2', text)
        self.assertTrue(any('不覆盖钙化' in m.value for m in a.warning))

    def test_pending_range_and_empty_search(self):
        a = self.app()
        a.selectbox(key='provenance_group').set_value('待核实（禁止作为默认）').run()
        self.assertTrue(any('不能作为默认参数' in e.value for e in a.error))
        a.text_input(key='provenance_query').set_value('no_match_123').run()
        self.assertEqual(len(a.exception), 0)
        self.assertTrue(any('没有匹配' in e.value for e in a.warning))

    def test_switch_groups_resets_selection_safely(self):
        a = self.app()
        for group in ['负载研究原型（未接入）', '设计工况与源', '控制与验收假设', 'BVD与匹配基线']:
            a.selectbox(key='provenance_group').set_value(group).run()
            self.assertEqual(len(a.exception), 0, [e.message for e in a.exception])
        a.text_input(key='provenance_query').set_value('C0').run()
        self.assertIn('静态电容', a.subheader[0].value)


if __name__ == '__main__':
    unittest.main()
