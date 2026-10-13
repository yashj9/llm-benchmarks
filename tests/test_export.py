import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('export', Path(__file__).resolve().parents[1] / 'scripts/export.py')
export = importlib.util.module_from_spec(spec)
if spec.loader:
    spec.loader.exec_module(export)


class ExportTests(unittest.TestCase):
    def test_public_rows_exclude_private_content(self):
        row = {'task_id': 'input-4096', 'size': 4096, 'score': 0.5, 'passed': False,
               'error': 'secret C:/Users/private', 'prompt': 'PRIVATE', 'output': 'PRIVATE',
               'extra': {'hit_token_limit': True, 'secret': 'PRIVATE'},
               'resources': {'ram_peak_mb': 62000, 'path': 'PRIVATE'}, 'decode_tps': 100}
        result = export.public_row(row)
        self.assertEqual(result['score'], 0.5)
        self.assertEqual(result['decode_tps'], 100)
        self.assertTrue(result['error'])
        self.assertTrue(result['hit_token_limit'])
        self.assertNotIn('PRIVATE', str(result))
        self.assertNotIn('secret', str(result))
        self.assertNotIn('prompt', result)
        self.assertNotIn('output', result)


    def test_snapshot_includes_history_without_ranking_archives(self):
        self.assertTrue(callable(getattr(export, 'snapshot', None)), 'Snapshot export not implemented')
        import os
        if not os.environ.get('BENCHMARK_WORKSPACE'):
            self.skipTest('Local source datasets not mounted; set BENCHMARK_WORKSPACE for read-only integration verification')
        root = Path(os.environ['BENCHMARK_WORKSPACE'])
        data = export.snapshot(root / 'dyno', root / 'quality-evals', root / 'tools/lmstudio-matrix')
        self.assertEqual(len(data['dyno_runs']), 57)
        self.assertEqual(len(data['quality_runs']), 120)
        self.assertEqual(len({r['id'] for r in data['dyno_runs']}), 57)
        self.assertTrue(any(r['archived'] for r in data['dyno_runs']))
        ranked = {s for r in data['dyno_setups'] for s in r['session_ids']}
        self.assertFalse(any(r['archived'] and r['id'] in ranked for r in data['dyno_runs']))
        strata = next(m for m in data['arenas'][0]['models'] if m['key'] == 'qwen3.8-flash-next-iq2_xs')
        self.assertEqual(strata['quality']['score'], 0.44)
        self.assertEqual(len(strata['setups']), 3)
        import json
        text = json.dumps(data).lower()
        for private in ('c:/users/', 'c:\\\\users', '127.0.0.1', 'localhost', 'authorization', 'api_key', '"base_url":'):
            self.assertNotIn(private, text)


if __name__ == '__main__':
    unittest.main()
