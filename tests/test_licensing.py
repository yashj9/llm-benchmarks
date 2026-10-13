from pathlib import Path
import json
import unittest

ROOT=Path(__file__).resolve().parents[1]

class LicensingTests(unittest.TestCase):
    def test_code_and_data_have_separate_attribution_licenses(self):
        self.assertTrue((ROOT/'LICENSE').is_file(), 'MIT licence missing')
        text=(ROOT/'LICENSE').read_text()
        self.assertIn('MIT License',text)
        self.assertIn('Copyright (c) 2026 YashJ',text)
        self.assertTrue((ROOT/'data/LICENSE').is_file(),'Data licence missing')
        data=(ROOT/'data/LICENSE').read_text()
        self.assertIn('CC BY 4.0',data)
        self.assertIn('third-party',data)

    def test_public_data_carries_attribution_and_upstream_credits(self):
        data=json.loads((ROOT/'data/snapshot.json').read_text())
        self.assertTrue('licensing' in data,'Portable attribution missing')
        self.assertEqual(data['licensing']['code_spdx'],'MIT')
        self.assertEqual(data['licensing']['original_compilation_spdx'],'CC-BY-4.0')
        self.assertIn('YashJ',data['licensing']['attribution'])
        sources={s['id']:s for s in data['sources']}
        for run in data['quality_runs']:
            self.assertTrue(run['source_ids'],run['id'])
            self.assertTrue(set(run['source_ids']).issubset(sources),run['id'])
        for identifier in ('artifactsbench','livecodebench-data'):
            self.assertEqual(sources[identifier]['unrestricted_asset_redistribution'],'not-cleared')
        self.assertEqual(sources['screenspot-v2']['status'],'publisher-declared-not-snapshot-verified')
        self.assertFalse(any('prompt' in s or 'raw_data' in s for s in data['sources']))

if __name__=='__main__':unittest.main()
