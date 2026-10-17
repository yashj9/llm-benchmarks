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
        self.assertEqual(len(data['dyno_runs']), 60)
        self.assertEqual(len(data['quality_runs']), 128)
        self.assertEqual(len({r['id'] for r in data['dyno_runs']}), 60)
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


    def test_snapshot_adds_prefill_and_resource_evidence(self):
        import os, json
        if not os.environ.get('BENCHMARK_WORKSPACE'):
            self.skipTest('Local source datasets not mounted')
        root=Path(os.environ['BENCHMARK_WORKSPACE'])
        data=export.snapshot(root/'dyno',root/'quality-evals',root/'tools/lmstudio-matrix')
        self.assertTrue('resource_comparisons' in data, 'Resource comparison export missing')
        run=next(r for r in data['dyno_runs'] if r['id']=='ses-20261009-145223-e268f3')
        source=json.loads((root/'tools/lmstudio-matrix/batch-20261009-145222/01-5090/prefill-pair.json').read_text())
        self.assertEqual(run['prefill']['cold_tps'], round(source[0]['prompt_tps'],3))
        self.assertEqual(run['prefill']['hot_tps'], round(source[1]['prompt_tps'],3))
        self.assertFalse(run['prefill']['hot_cache_verified'])
        strata=next(r for r in data['dyno_runs'] if r['id']=='ses-20261012-233759-1322f3')
        self.assertIsNone(strata['prefill']['hot_tps'])
        self.assertGreater(strata['resources']['cpu_temp_peak_c'],0)
        self.assertLess(strata['resources']['ram_available_min_gib'],2)
        self.assertGreaterEqual(len(data['quality_resource_jobs']),1)
        self.assertEqual(len(data['resource_comparisons']),len(data['dyno_setups']))
        self.assertTrue(all('prefill' in s for s in data['arenas'][0]['models'][0]['setups']))

    def test_strata_runs_and_quality_passes_support_several_quantizations(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / '.hermes-contracts/strata-matrix'
            for name, results in (('run1', {'dyno': {'5090': {'session': 'ses-a', 'config': 'c1'}},
                                            'quality': {'load_s': 20, 'runs': [{'results': ['coding-1', 'mcp-1']}]}}),
                                  ('run2-iq3_s', {'dyno': {'5090': {'session': 'ses-b', 'config': 'c2'}},
                                                  'quality_passes': [{'telemetry': 'on.jsonl', 'load_s': 0, 'runs': [{'results': ['coding-2']}]},
                                                                     {'telemetry': 'off.jsonl', 'load_s': 0, 'runs': [{'results': ['coding-3']}]}]})):
                (base / name).mkdir(parents=True)
                (base / name / 'results.json').write_text(json.dumps(results))
            runs = export.strata_runs(Path(tmp))
            self.assertEqual([f.name for f, _ in runs], ['run1', 'run2-iq3_s'])
            passes = export.strata_quality_passes(runs)
            self.assertEqual([(p['telemetry'], sorted(p['expected'])) for p in passes],
                             [('telemetry-quality.jsonl', ['coding-1', 'mcp-1']), ('on.jsonl', ['coding-2']), ('off.jsonl', ['coding-3'])])
            self.assertEqual(passes[0]['load_s'], 20)
            self.assertEqual(export.strata_runs(Path(tmp) / 'missing'), [])


if __name__ == '__main__':
    unittest.main()
