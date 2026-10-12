from copy import deepcopy
import json
import unittest
from current.catalog import PLATFORM, inside
from current.parameter_sources import (REQUIRED, bound_value, check_registry, expand_registry,
                                      format_value, load_registry, numeric_setting, registry_json)


class ParameterSourceTests(unittest.TestCase):
    def setUp(self):
        self.data = load_registry()

    def entries(self):
        return {e['id']: e for e in expand_registry(self.data)}

    def test_required_metadata_and_sources_present(self):
        result = check_registry(self.data)
        self.assertTrue(result['ok'], result['issues'])
        for e in result['entries']:
            self.assertTrue(all(e[k] for k in REQUIRED))
            for src in e['sources']:
                if 'path' in src:
                    self.assertTrue(inside(PLATFORM, src['path']).is_file())

    def test_every_numeric_config_input_registered(self):
        result = self.entries()
        cfg = json.loads((PLATFORM/'current/unified/config.json').read_text(encoding='utf-8'))
        self.assertEqual({e['config_key'] for e in result.values() if 'config_key' in e},
                         {k for k, v in cfg.items() if numeric_setting(v)})

    def test_removed_registration_is_detected(self):
        self.data['entries'] = [e for e in self.data['entries'] if e['id'] != 'scan_period_us']
        r = check_registry(self.data)
        self.assertFalse(r['ok'])
        self.assertIn('配置数值参数尚未登记：scan_period_us', r['issues'])

    def test_changed_value_not_silently_adopted(self):
        next(e for e in self.data['entries'] if e['id'] == 'source.rs')['value'] = 75
        r = check_registry(self.data)
        e = next(e for e in r['entries'] if e['id'] == 'source.rs')
        self.assertFalse(r['ok'])
        self.assertEqual((e['value'], e['source_value']), (75, 50))

    def test_missing_field_fails_closed(self):
        self.data['profiles']['bvd']['measurement_conditions'] = ''
        with self.assertRaises(ValueError):
            expand_registry(self.data)

    def test_duplicate_id_rejected(self):
        self.data['entries'].append(deepcopy(self.data['entries'][0]))
        with self.assertRaises(ValueError):
            expand_registry(self.data)

    def test_saijo_may_not_be_bound_or_adopted(self):
        e = next(e for e in self.data['entries'] if e['profile'] == 'saijo')
        e['binding'] = {'source': 'config', 'path': ['scan_amplitude']}
        with self.assertRaises(ValueError):
            expand_registry(self.data)
        del e['binding']
        e['formal_use'] = True
        with self.assertRaises(ValueError):
            expand_registry(self.data)

    def test_saijo_keeps_units_sd_frequency_and_no_density(self):
        entries = self.entries()
        refs = [e for e in entries.values() if e['profile'] == 'saijo']
        self.assertEqual(len(refs), 12)
        for e in refs:
            self.assertFalse(e['formal_use'])
            self.assertIn('100–200 MHz', e['frequency_scope'])
            self.assertIn('未测密度', e['limitations'])
        self.assertEqual((entries['saijo.calcification.c']['value'],
                          entries['saijo.calcification.c']['sd']), (1760, 14))
        self.assertEqual(entries['saijo.calcification.attenuation']['unit'], 'dB/(mm·MHz)')

    def test_pending_range_is_not_a_literature_default(self):
        e = self.entries()['pending.calcif.impedance']
        self.assertEqual(e['status'], '待核实')
        self.assertFalse(e['formal_use'])
        self.assertNotIn('binding', e)
        self.assertEqual(e['source_ids'], ['unverified_range'])
        self.assertIn('不作为', e['adoption_reason'])

    def test_reference_load_defaults_untouched(self):
        entries = self.entries()
        for key, expected in [('load.calcif.rho', 1900), ('load.calcif.c', 3600)]:
            e = entries[key]
            self.assertEqual(bound_value(e['binding'], self.data['sources']), expected)
            self.assertFalse(e['formal_use'])

    def test_design_quantities_not_component_ratings(self):
        for key in ['source.rs', 'operating.vpp', 'operating.irms']:
            e = self.entries()[key]
            self.assertEqual(e['profile'], 'operating')
            self.assertIn('非器件辨识', e['identity'])
        self.assertEqual(self.entries()['current_hard_Arms']['profile'], 'control')

    def test_ast_reads_keyword_and_media_without_execution(self):
        self.assertEqual(bound_value(self.entries()['bvd.qm']['binding'], self.data['sources']), 800)
        self.assertEqual(bound_value(self.entries()['load.blood.c']['binding'], self.data['sources']), 1570)

    def test_binding_cannot_escape_platform(self):
        self.data['sources']['load']['path'] = '../outside.py'
        with self.assertRaises(ValueError):
            bound_value(self.entries()['load.blood.c']['binding'], self.data['sources'])

    def test_missing_source_surfaces_failure(self):
        self.data['sources']['model']['path'] = 'current/DOES_NOT_EXIST.py'
        self.assertFalse(check_registry(self.data)['ok'])

    def test_export_complete_and_load_does_not_mutate_input(self):
        original = deepcopy(self.data)
        result = check_registry(self.data)
        parsed = json.loads(registry_json(result))
        self.assertEqual(self.data, original)
        self.assertTrue(all('measurement_conditions' in e for e in parsed['entries']))

    def test_display_conversions_and_scan_units(self):
        e = self.entries()
        self.assertEqual(format_value(e['scan_levels_Hz']), '±50 / 5 → ±5 / 1 → ±1 / 0.1 kHz')
        self.assertEqual(format_value(e['current_hard_Arms']), '6 mA RMS')
        self.assertEqual(format_value(e['saijo.calcification.c']), '1760 ± 14 m/s（均值±SD）')

    def test_source_amplitude_uses_runtime_calibration_not_design_rounding(self):
        e = self.entries()['source.a1']
        self.assertEqual(e['binding']['source'], 'calibration')
        self.assertEqual(e['value'], 6.217360894531728)


if __name__ == '__main__':
    unittest.main()
