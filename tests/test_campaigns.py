import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('campaign_import', ROOT / 'scripts/import_campaigns.py')
assert spec is not None and spec.loader is not None
imp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(imp)


class CampaignTests(unittest.TestCase):
    def test_sustained_excludes_calibration_tiny_errors_and_warmup(self):
        rows = [{'label': 'output-1024 #1', 'completion_tokens': 1024, 'decode_tps': 70},
                {'label': 'calibration', 'completion_tokens': 1, 'decode_tps': 1000000},
                {'label': 'warmup', 'completion_tokens': 512, 'decode_tps': 200},
                {'label': 'tool', 'completion_tokens': 50, 'decode_tps': 99},
                {'label': 'output', 'completion_tokens': 512, 'decode_tps': 100, 'error': True}]
        self.assertEqual(imp.summarize(rows)['sustained_decode_tps'], 70)
        self.assertEqual(imp.summarize(rows)['sustained_n'], 1)
        self.assertIsNone(imp.summarize([])['sustained_decode_tps'])

    def test_nonfinite_and_unsafe_identifiers_fail_closed(self):
        self.assertIsNone(imp.num(float('nan')))
        self.assertIsNone(imp.num(True))
        for value in ('/home/user/private', 'https://endpoint', '<script>', None):
            with self.assertRaises(ValueError):
                imp.identity(value)
        self.assertEqual(imp.label('agentic-131072 #1'), 'agentic-131072 #1')

    def test_source_paths_cannot_escape_campaign(self):
        with self.assertRaises(ValueError):
            imp.selected_path('/etc/passwd', ROOT)

    def test_all_legacy_values_and_record_identities_preserved(self):
        # Baseline pinned in git for this additive publication; not a count-only check.
        before = json.loads(subprocess.check_output(['git', 'show', '999a750:data/snapshot.json'], cwd=ROOT))
        after = imp.load(ROOT / 'data/snapshot.json')
        for key, value in before.items():
            if key != 'dyno_campaigns':
                if key == 'external_dyno':  # additive publication: campaign-003's records stay as the prefix
                    self.assertEqual(after[key]['runs'][:len(value['runs'])], value['runs'])
                    self.assertEqual(after[key]['campaigns'][:len(value['campaigns'])], value['campaigns'])
                    continue
                self.assertEqual(after[key], value, key)
        self.assertEqual(after['dyno_campaigns'], before['dyno_campaigns'])
        for collection in ('dyno_runs', 'quality_runs', 'dyno_setups', 'arenas', 'resource_comparisons', 'quality_resource_jobs'):
            self.assertEqual(len(before[collection]), len(after[collection]))

    def test_published_counts_cache_prefixes_repeats_and_embeddings(self):
        e = imp.load(ROOT / 'data/snapshot.json')['dyno_campaigns']
        self.assertEqual(len(e['campaigns']), 3)
        self.assertEqual(len(e['runs']), 13)
        self.assertEqual(len({r['id'] for r in e['runs']}), 13)
        self.assertEqual(sum(r['kind'] == 'chat' for r in e['runs']), 11)
        self.assertEqual(sum(r['kind'] == 'embedding' for r in e['runs']), 2)
        nail = [r for r in e['runs'] if r['model'].startswith('nail-')]
        self.assertEqual(len(nail), 2)
        for r in nail:
            self.assertIsNone(r['metrics']['cold_new_token_prefill_tps'])
            self.assertFalse(r['cache_verified'])
            self.assertEqual({c['cached_prompt_tokens'] for c in r['cache_cells'] if c['mode'] == 'uncached'}, {182})
        for r in e['runs']:
            self.assertIsNone(r['runtime_version'])
            self.assertNotIn('payload', r)
            if r['kind'] == 'embedding':
                self.assertIsNone(r['session_id'])
                self.assertIsNone(r['metrics']['sustained_decode_tps'])
                self.assertEqual(len(r['embedding_measurements']), 6)
                self.assertGreater(r['embedding_latency_s']['8'], 0)
        self.assertEqual([c['complete'] for c in e['campaigns']], [False, False, True])
        self.assertEqual(len(e['campaigns'][0]['unselected_attempts']), 3)

    def test_privacy_of_entire_extension(self):
        e = imp.load(ROOT / 'data/snapshot.json')['dyno_campaigns']
        forbidden = {'payload', 'response', 'content', 'prompt', 'output', 'journal', 'template', 'modelfile', 'raw_path', 'api_key'}
        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for v in value.values():
                    visit(v)
            elif isinstance(value, list):
                for v in value:
                    visit(v)
            elif isinstance(value, str):
                self.assertNotRegex(value, r'/home/|/usr/|/sys/|/proc/|localhost|127\.0\.0\.1|github_pat_')
        visit(e)

    @unittest.skipUnless(os.environ.get('DYNO_CAMPAIGN_ROOT'), 'Set DYNO_CAMPAIGN_ROOT for real-source reproduction')
    def test_real_source_reproduction_and_idempotence(self):
        root = Path(os.environ['DYNO_CAMPAIGN_ROOT'])
        dirs = [root / name for name in ('campaign-001', 'campaign-002-nail-repeat', 'campaign-003-unsloth-q8kxl')]
        published = imp.load(ROOT / 'data/snapshot.json')
        baseline = {k: v for k, v in published.items() if k != 'dyno_campaigns'}
        rebuilt = imp.append(baseline, dirs)
        self.assertEqual(rebuilt, published)
        self.assertEqual(imp.append(rebuilt, dirs), rebuilt)
        conflict = copy.deepcopy(rebuilt)
        conflict['dyno_campaigns']['runs'][0]['metrics']['sustained_decode_tps'] = -1
        with self.assertRaisesRegex(ValueError, 'Append-only identity conflict'):
            imp.append(conflict, dirs)


if __name__ == '__main__':
    unittest.main()
