"""EXPLICITLY SYNTHETIC offline fixtures; no inference, no publishable snapshots.

All fixture bundles/session/manifests are marked synthetic=True on disk. Happy
path tests patch ONLY the reader to simulate the real-source gate in memory;
production importer always rejects these files. No bypass exists in its CLI.
"""
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('external', REPO / 'scripts/import_external_dyno.py')
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root):
    """Full native-shaped frozen practical-v1 contract; entirely synthetic."""
    models, engines = [], []
    for index, (engine, version) in enumerate(m.VERSIONS.items()):
        sid = f'ses-20261014-12000{index}-abcdef'
        folder = root / 'sessions' / sid
        model = engine + '-fixture-only'
        template_hash = hashlib.sha256(b'enable_thinking SYNTHETIC TEMPLATE').hexdigest()
        claims = dict(version=version, identity=model, context=131072, thinking=template_hash,
                      vision=True, mtp='mtp' if engine == 'halogen' else 5)
        probes = [dict(claim=k, endpoint='/native', path=[k], expected=v) for k, v in claims.items()]
        files = [{'path': '/home/private/fixture-only', 'sha256': 'a' * 64}]
        extras = {'enable_thinking': True} if engine == 'halogen' else {'chat_template_kwargs': {'enable_thinking': True}}
        contract = {'mode': 'explicit-native-request', 'template_sha256': template_hash}
        engines.append(dict(key=engine, version=version, model=model, probes=probes, files=files,
                            thinking_contract=contract, request_extras=extras))
        tasks: list[dict] = [dict(id=f'{c}-{size}', category=c, size=size, repetitions=2 if size <= 16384 else 1)
                 for c in ('input', 'retention', 'agentic', 'compaction')
                 for size in (4096, 8192, 16384, 32768, 65536, 131072)]
        tasks += [dict(id=f'output-{size}', category='output', size=size, repetitions=2)
                  for size in (256, 1024, 4096, 8192)]
        tasks += [dict(id=f'image-{size}', category='image', size=size, repetitions=2) for size in (512, 1024)]
        native = []
        for t in tasks:
            count = (6 if t['size'] >= 8192 else 4) if t['category'] == 'agentic' else 2 if t['category'] == 'compaction' else 1
            for rep in range(t['repetitions']):
              for turn in range(count):
                native.append(dict(session_id=sid, task_id=t['id'], category=t['category'], size=t['size'],
                    rep=rep, turn=turn + 1 if t['category'] == 'agentic' else None,
                    sub=('summary' if turn == 0 else 'probe') if t['category'] == 'compaction' else None,
                    score=None if t['category'] == 'compaction' and turn == 0 else 0.5,
                    prompt_tokens=100, cached_prompt_tokens=0,
                    completion_tokens=300 if t['category'] == 'output' else 20, reasoning_tokens=None,
                    ttft_s=0.3, e2e_s=2, decode_tps=150, finish_reason='stop', error=None, started_at=100,
                    content='/home/private/ANSWER-SECRET', extra={'cache_evidence': 'unknown'}))
        session = dict(id=sid, model=model, engine='openai-compat', engine_label=engine,
            status='finished', error=None, cleanup={'ok': True}, created_at=100,
            synthetic=True, provenance={'battery_version': 'practical-v1', 'fixture_version': 'fixture-v1'},
            plan={'battery_version': 'practical-v1', 'effective_context': 131072, 'tasks': tasks},
            summary={'headline': {'rows': len(native), 'errors': 0}})
        save(folder / 'session.json', session)
        (folder / 'results.jsonl').write_text('\n'.join(json.dumps(r) for r in native) + '\n')
        (folder / 'samples.jsonl').write_text('{"synthetic":true,"machine_id":"PRIVATE-MACHINE"}\n')
        save(root / engine / 'runtime-readback.json', {'claims': claims,
             'raw': {'/native': claims, '/health': {'chat_template': {'thinking_control': True, 'probe': 'passed'}},
                     '/props': {'chat_template': 'enable_thinking SYNTHETIC TEMPLATE'}},
             'thinking_request_contract': {**contract, 'request_extras': extras, 'default_enablement': 'not asserted'},
             'models': {'data': [{'id': model}]}})
        save(root / engine / 'cleanup.json', {'ok': True})
        save(root / engine / 'identity.json', {'commands': {'version': version}, 'files': files})
        (root / engine / 'host-samples.jsonl').write_text('{"synthetic":true,"timestamp":100}\n')
        summary = {'schema': 'dyno-external-resources-v1', 'sample_count': 1, 'errors': [],
            'metrics': {'ram_used_bytes': {'count': 1, 'min': 1024**3, 'max': 1024**3,
                'mean': 1024**3, 'coverage_fraction': 1},
                'card0.package_power_w': {'count': 1, 'min': 80, 'max': 80, 'mean': 80, 'coverage_fraction': 1},
                'disk.PRIVATE-MACHINE': {'count': 1}}}
        save(folder / 'host-resources.json', summary)
        staging = dict(schema='dyno-external-website-staging-v1', publication_ready=False, synthetic=True,
            engine=engine, version=version, model=model, session_id=sid, status='finished', error=None,
            battery_version='practical-v1', fixture_version='fixture-v1', native_sampling=True, context=131072,
            resources=summary, records=[{**{k: r.get(k) for k in m.PROJECTION}, 'cache_evidence': 'unknown'} for r in native],
            sources={k: str(p) for k, p in {'session': folder/'session.json', 'results': folder/'results.jsonl',
                'native_samples': folder/'samples.jsonl', 'host_samples': root/engine/'host-samples.jsonl',
                'host_summary': folder/'host-resources.json'}.items()})
        save(root / (engine + '-website-staging.json'), staging)
        models.append(dict(engine=engine, session_id=sid, status='finished', session=str(folder/'session.json'),
            website_staging=str(root/(engine+'-website-staging.json')), resource_summary=str(folder/'host-resources.json')))
    save(root/'manifest.json', {'reviewed_runtime_contract': True, 'synthetic': True, 'engines': engines})
    save(root/'service-window.json', {'restored': True, 'recovery_errors': []})
    save(root/'campaign.json', dict(schema='dyno-external-campaign-v1', complete=True, battery_finished=True,
        cleanup_ok=True, pinned_files_unchanged=True, strict_evidence_complete=False, failures=[], models=models))
    save(root/'SYNTHETIC-FIXTURE-RECEIPT.json', {'synthetic': True, 'publishable': False})


class ExternalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='external-SYNTHETIC-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'SYNTHETIC-campaign'
        fixture(self.root)
        self.baseline = m.load(REPO/'data/snapshot.json')
        self.baseline.pop('external_dyno', None)  # published real runs are not part of the synthetic fixture baseline
        self.real_load = m.load

    def simulate_live_reader(self, path):
        value = self.real_load(path)
        # Explicit in-memory simulation only; disk fixtures remain rejected by CLI.
        if isinstance(value, dict) and value.get('synthetic') is True:
            value['synthetic'] = False
        return value

    def export(self, baseline=None):
        with patch.object(m, 'load', self.simulate_live_reader):
            return m.append(self.baseline if baseline is None else baseline, [self.root])

    def alter(self, name, fn):
        path = self.root / name
        d = self.real_load(path)
        fn(d)
        save(path, d)

    def test_synthetic_always_rejected_in_production(self):
        with self.assertRaisesRegex(ValueError, 'Unreviewed manifest'):
            m.append(self.baseline, [self.root])

    def test_cli_failure_writes_no_candidate_or_public_snapshot(self):
        candidate = Path(self.tmp.name) / 'SYNTHETIC-never-written.json'
        public = REPO/'data/snapshot.json'
        before = m.sha(public)
        for out in (candidate, public):
            result = subprocess.run([sys.executable, str(REPO/'scripts/import_external_dyno.py'),
                '--snapshot', str(public), '--campaign', str(self.root), '--out', str(out)],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(candidate.exists())
        self.assertEqual(m.sha(public), before)

    def test_deep_preservation_idempotency_metrics(self):
        original = copy.deepcopy(self.baseline)
        result = self.export()
        for k, v in self.baseline.items():
            self.assertEqual(result[k], v, k)
        self.assertEqual(self.baseline, original)
        self.assertEqual(result, self.export(result))
        self.assertEqual(len(result['dyno_campaigns']['campaigns']), 3)
        self.assertEqual(len(result['dyno_campaigns']['runs']), 13)
        self.assertEqual(len(result['external_dyno']['runs']), 2)
        r = result['external_dyno']['runs'][0]
        self.assertEqual(r['metrics']['sustained_n'], 8)
        self.assertEqual(r['metrics']['sustained_decode_tps'], 150)
        self.assertIsNone(r['metrics']['native_prefill_tps'])
        self.assertIsNone(r['metrics']['mtp_acceptance'])
        self.assertIsNone(r['items'][0]['cached_prompt_tokens'])
        self.assertEqual(r['quality']['mean_score'], 0.5)
        self.assertFalse(r['coverage']['strict_evidence_complete'])

    def test_privacy_fresh_allowlist(self):
        self.alter('halogen-website-staging.json', lambda d: d.update(
            env={'KEY': 'ENV-SECRET'}, prompt='PROMPT-SECRET', template='TEMPLATE-SECRET',
            machine_id='MACHINE-SECRET', images=['IMAGE-SECRET'], vectors=[12], endpoint='http://private'))
        text = json.dumps(self.export()['external_dyno'])
        for private in ('/home/', 'http://', 'PRIVATE-MACHINE', 'ANSWER-SECRET', 'ENV-SECRET',
                        'PROMPT-SECRET', 'TEMPLATE-SECRET', 'MACHINE-SECRET', 'IMAGE-SECRET', 'vectors'):
            self.assertNotIn(private, text)

    def test_identity_conflict(self):
        first = self.export()
        self.alter('halogen-website-staging.json', lambda d: d.update(publication_gate='changed evidence'))
        with self.assertRaisesRegex(ValueError, 'identity conflict'):
            self.export(first)

    def test_native_readback_mismatch(self):
        self.alter('halogen/runtime-readback.json', lambda d: d['raw']['/native'].update(version='wrong'))
        with self.assertRaisesRegex(ValueError, 'native runtime claim'):
            self.export()

    def test_missing_thinking_contract(self):
        self.alter('halogen/runtime-readback.json', lambda d: d.pop('thinking_request_contract'))
        with self.assertRaisesRegex(ValueError, 'Thinking request contract'):
            self.export()

    def test_truncated_plan_is_not_complete(self):
        sid = self.real_load(self.root/'campaign.json')['models'][0]['session_id']
        self.alter(f'sessions/{sid}/session.json', lambda d: d['plan'].update(tasks=d['plan']['tasks'][:-1]))
        with self.assertRaisesRegex(ValueError, 'frozen practical-v1 plan'):
            self.export()

    def test_no_stale_fallback(self):
        (self.root/'halogen-website-staging.json').rename(self.root/'stale-staging.json')
        with self.assertRaisesRegex(ValueError, 'source link'):
            self.export()

    def test_source_escape(self):
        self.alter('campaign.json', lambda d: d['models'][0].update(website_staging='/etc/passwd'))
        with self.assertRaisesRegex(ValueError, 'source link'):
            self.export()

    def test_partial_request_battery(self):
        sid = self.real_load(self.root/'campaign.json')['models'][0]['session_id']
        path = self.root/'sessions'/sid/'results.jsonl'
        rows = m.lines(path)[:-1]
        path.write_text('\n'.join(json.dumps(r) for r in rows))
        self.alter('halogen-website-staging.json', lambda d: d.update(records=d['records'][:-1]))
        with self.assertRaisesRegex(ValueError, 'Partial practical battery'):
            self.export()

    def test_unfinished_cleanup_and_services(self):
        for name, update in [('campaign.json', {'complete': False}),
                             ('halogen/cleanup.json', {'ok': False}),
                             ('service-window.json', {'restored': False})]:
            with self.subTest(name=name):
                old = self.real_load(self.root/name)
                self.alter(name, lambda d: d.update(update))
                with self.assertRaises(ValueError):
                    self.export()
                save(self.root/name, old)

    def test_staging_native_mismatch(self):
        self.alter('halogen-website-staging.json', lambda d: d['records'][0].update(score=1))
        with self.assertRaisesRegex(ValueError, 'Staging differs'):
            self.export()

    def test_malformed_native_jsonl(self):
        sid = self.real_load(self.root/'campaign.json')['models'][0]['session_id']
        with (self.root/'sessions'/sid/'results.jsonl').open('a') as f:
            f.write('\nNOT JSON\n')
        with self.assertRaises(ValueError):
            self.export()

    def test_present_zero_remains_zero(self):
        sid = self.real_load(self.root/'campaign.json')['models'][0]['session_id']
        path = self.root/'sessions'/sid/'results.jsonl'
        rows = m.lines(path)
        rows[0]['extra']['cache_evidence'] = 'present'
        path.write_text('\n'.join(json.dumps(r) for r in rows))
        self.alter('halogen-website-staging.json', lambda d: d['records'][0].update(cache_evidence='present'))
        self.assertEqual(self.export()['external_dyno']['runs'][0]['items'][0]['cached_prompt_tokens'], 0)


if __name__ == '__main__':
    unittest.main()
