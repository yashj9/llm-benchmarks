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


GUFO_DIGEST = 'sha256:4d784ef0043efe8ca07b8e7d519903a14345b068be2b4762c4896eb449704e81'
# SYNTHETIC case table. engine, model id, quantization/spec (None = legacy staging without new fields), text-only flag.
CASES = {
    'halogen': dict(engine='halogen', quant=None, spec=None),
    'strata': dict(engine='strata', quant=None, spec=None),
    'gufo-flash': dict(engine='gufo', quant='UD-Q4_K_XL', spec='mtp', label='Flash-Next'),
    'gufo-27b': dict(engine='gufo', quant='UD-Q4_K_XL', spec='dflash2', label='Qwen3.8-27B'),
    'gufo-deepseek': dict(engine='gufo', quant='IQ2XXS', spec='dspark', label='DeepSeek V4 Flash', text_only=True),
    'ollama-27b': dict(engine='ollama', quant='UD-Q4_K_XL', spec='mtp', label='Qwen3.8-27B',
                       model='qwen3.8-27b:ud-q4_k_xl-mmproj-f16-mtp-q4_0-128k'),
}


GUFO_MODELS = {'gufo-flash': 'gufo-qwen3.8-flash-next-ud-q4_k_xl', 'gufo-27b': 'gufo-qwen3.8-27b-ud-q4_k_xl',
               'gufo-deepseek': 'gufo-deepseek-v4-flash-iq2xxs'}
OLLAMA_TAG = 'qwen3.8-27b:ud-q4_k_xl-mmproj-f16-mtp-q4_0-128k'
OLLAMA_DIGEST, OLLAMA_DRAFT = '6' * 64, '5' * 64
CANARY_SHA = 'c' * 64


def native_fixture(root, name, case, text_only):
    """SYNTHETIC but shaped like the real Gufo/Ollama wrapper: multi-probe, 'speculative' claim, null
    quantization/weights, short plan_coverage token, evidence-typed readback with canary pin."""
    engine, version, spec = case['engine'], m.VERSIONS[case['engine']], case['spec']
    row_id = f'{name}-row'
    if engine == 'gufo':
        model = GUFO_MODELS[name]
        quant = case['quant']
        weights = root / 'weights'
        weights.mkdir(parents=True, exist_ok=True)
        files = []
        for fname, size in ((f'Model-{quant}.gguf', 1000), ('mmproj-BF16.gguf', 200), (f'{spec}-draft.gguf', 30)):
            (weights / fname).write_bytes(b'x' * size)
            files.append({'path': str(weights / fname), 'sha256': hashlib.sha256(fname.encode()).hexdigest()})
        mp = f'/models/Model-{quant}.gguf'
        draft = f'/models/{spec}-draft.gguf'
        vision = {'supported': not text_only, 'basis': 'SYNTHETIC basis'}
        row = dict(key='gufo', row_id=row_id, version=version, model=model, context=131072, image_id=GUFO_DIGEST,
                   model_path=files[0]['path'], speculative={'mode': spec, 'model_flag': '--mtp-model', 'model_path': files[2]['path']},
                   vision=vision, plan_coverage='text-only' if text_only else 'full', files=files,
                   request_extras={'chat_template_kwargs': {'enable_thinking': True}},
                   thinking_contract={'mode': 'explicit-native-request', 'template_evidence': 'compiled-in-formatter', 'template_sha256': None},
                   canary_evidence={'path': '/SYNTHETIC/canary.json', 'sha256': CANARY_SHA})
        if not text_only:
            row['mmproj_path'] = files[1]['path']
        modalities = ['text'] if text_only else ['text', 'image']
        version_re = r'^gufo version 0\.18\.0 \([0-9a-f]{7,40}\)$'
        log_re = r'event=load_completed kind=text .*speculative=' + spec + r' draft_limit=7'
        row['log_patterns'] = {'speculative': log_re, **({} if text_only else {'vision': r'event=vision_prepared resident_bytes=\d+'})}
        probes = [
            {'claim': 'version', 'evidence_type': 'unverifiable-by-endpoint', 'reason': 'no endpoint',
             'backing': {'type': 'container-exec', 'argv': ['gufo', '--version'], 'compare': 'regex', 'expected': version_re}},
            {'claim': 'identity', 'evidence_type': 'endpoint', 'endpoint': '/v1/models', 'path': ['data', 0, 'id'], 'expected': model},
            {'claim': 'identity', 'evidence_type': 'container-args', 'expected': [['--model', mp], ['--served-model-name', model]]},
            {'claim': 'context', 'evidence_type': 'endpoint', 'endpoint': '/v1/models', 'path': ['data', 0, 'context_length'], 'expected': 131072},
            {'claim': 'context', 'evidence_type': 'container-args', 'expected': [['--context', '131072'], ['--sessions', '1']]},
            {'claim': 'thinking', 'evidence_type': 'unverifiable-by-endpoint', 'reason': 'compiled-in', 'backing': {'type': 'canary'}},
            {'claim': 'vision', 'evidence_type': 'endpoint', 'endpoint': '/v1/models',
             'path': ['data', 0, 'architecture', 'input_modalities'], 'expected': modalities}]
        recorded = [
            {'claim': 'version', 'evidence_type': 'unverifiable-by-endpoint', 'source': 'backing:container-exec',
             'observed': 'gufo version 0.18.0 (6c682a2)', 'strength': 'container-backed', 'reason': 'no endpoint'},
            {'claim': 'identity', 'evidence_type': 'endpoint', 'source': '/v1/models', 'observed': model, 'strength': 'observed'},
            {'claim': 'identity', 'evidence_type': 'container-args', 'source': 'owned container',
             'observed': [['--model', mp], ['--served-model-name', model]], 'strength': 'launch-or-log-evidence'},
            {'claim': 'context', 'evidence_type': 'endpoint', 'source': '/v1/models', 'observed': 131072, 'strength': 'observed'},
            {'claim': 'context', 'evidence_type': 'container-args', 'source': 'owned container',
             'observed': [['--context', '131072'], ['--sessions', '1']], 'strength': 'launch-or-log-evidence'},
            {'claim': 'thinking', 'evidence_type': 'unverifiable-by-endpoint', 'source': '/SYNTHETIC/canary.json', 'observed': True,
             'strength': 'canary-backed', 'reason': 'compiled-in', 'canary_sha256': CANARY_SHA, 'reasoning_chars': 243},
            {'claim': 'vision', 'evidence_type': 'endpoint', 'source': '/v1/models', 'observed': modalities, 'strength': 'observed'}]
        if text_only:
            probes.append({'claim': 'vision', 'evidence_type': 'declared', 'expected': False, 'basis': 'SYNTHETIC basis'})
            recorded.append({'claim': 'vision', 'evidence_type': 'declared', 'source': 'manifest declaration', 'observed': False,
                             'strength': 'declared-unsupported', 'basis': 'SYNTHETIC basis'})
        else:
            probes += [{'claim': 'vision', 'evidence_type': 'container-args', 'expected': [['--mmproj', '/models/mmproj-BF16.gguf']]},
                       {'claim': 'vision', 'evidence_type': 'container-log', 'compare': 'regex', 'expected': row['log_patterns']['vision']}]
            recorded += [{'claim': 'vision', 'evidence_type': 'container-args', 'source': 'owned container',
                          'observed': [['--mmproj', '/models/mmproj-BF16.gguf']], 'strength': 'launch-or-log-evidence'},
                         {'claim': 'vision', 'evidence_type': 'container-log', 'source': 'owned container',
                          'observed': 'event=vision_prepared resident_bytes=927587264', 'strength': 'launch-or-log-evidence'}]
        seqs = [['--speculative', spec], ['--mtp-model', draft]]
        probes += [{'claim': 'speculative', 'evidence_type': 'container-args', 'expected': seqs},
                   {'claim': 'speculative', 'evidence_type': 'container-log', 'compare': 'regex', 'expected': log_re}]
        recorded += [{'claim': 'speculative', 'evidence_type': 'container-args', 'source': 'owned container', 'observed': seqs,
                      'strength': 'launch-or-log-evidence'},
                     {'claim': 'speculative', 'evidence_type': 'container-log', 'source': 'owned container',
                      'observed': f'event=load_completed kind=text elapsed_ms=1 model={model} speculative={spec} draft_limit=7',
                      'strength': 'launch-or-log-evidence'}]
        models_raw = {'object': 'list', 'data': [{'id': model, 'context_length': 131072, 'architecture': {'input_modalities': modalities}}]}
        runtime = {'claims': {'identity': model, 'context': 131072, 'vision': modalities}, 'evidence': recorded,
                   'thinking_request_contract': {'mode': 'explicit-native-request', 'template_sha256': None,
                                                 'template_evidence': 'compiled-in-formatter (unverifiable-by-endpoint; canary-backed)',
                                                 'request_extras': row['request_extras'], 'default_enablement': 'not asserted'},
                   'raw': {'/v1/models': models_raw}, 'models': models_raw, 'unverifiable_by_endpoint': ['version', 'thinking']}
        ident = {'commands': {'version': version}, 'files': files}
    else:
        model, files = OLLAMA_TAG, []
        template = 'SYNTHETIC OLLAMA TEMPLATE'
        template_hash = hashlib.sha256(template.encode()).hexdigest()
        row = dict(key='ollama', row_id=row_id, version=version, model=model, context=131072, digest=OLLAMA_DIGEST,
                   draft_blob_sha256=OLLAMA_DRAFT, draft_num_predict=4, vision={'supported': True, 'basis': 'SYNTHETIC'},
                   plan_coverage='full', request_extras={'reasoning_effort': 'medium'}, files=[],
                   thinking_contract={'mode': 'explicit-native-request', 'template_sha256': template_hash},
                   canary_evidence={'path': '/SYNTHETIC/canary.json', 'sha256': CANARY_SHA})
        params = 'top_k 20\ndraft_num_predict              4\nnum_ctx 131072'
        modelfile = 'FROM /SYNTHETIC/blob\nDRAFT /SYNTHETIC/sha256-' + OLLAMA_DRAFT + '\nPARAMETER draft_num_predict 4'
        show = {'template': template, 'capabilities': ['tools', 'thinking', 'completion', 'vision'], 'parameters': params,
                'modelfile': modelfile}
        ps = {'models': [{'name': model, 'digest': OLLAMA_DIGEST, 'context_length': 131072}]}
        body = {'method': 'POST', 'endpoint': '/api/show', 'body': {'model': model}}
        probes = [
            {'claim': 'version', 'evidence_type': 'endpoint', 'endpoint': '/api/version', 'path': ['version'], 'expected': version},
            {'claim': 'identity', 'evidence_type': 'endpoint', 'endpoint': '/api/ps',
             'path': ['models', {'where': {'name': model}}, 'digest'], 'expected': OLLAMA_DIGEST},
            {'claim': 'context', 'evidence_type': 'endpoint', 'endpoint': '/api/ps',
             'path': ['models', {'where': {'name': model}}, 'context_length'], 'expected': 131072},
            {**body, 'claim': 'thinking', 'evidence_type': 'endpoint', 'path': ['template'], 'transform': 'sha256', 'expected': template_hash},
            {**body, 'claim': 'thinking', 'evidence_type': 'endpoint', 'path': ['capabilities'], 'compare': 'contains', 'expected': 'thinking'},
            {'claim': 'thinking', 'evidence_type': 'unverifiable-by-endpoint', 'reason': 'canary needed', 'backing': {'type': 'canary'}},
            {**body, 'claim': 'vision', 'evidence_type': 'endpoint', 'path': ['capabilities'], 'compare': 'contains', 'expected': 'vision'},
            {**body, 'claim': 'speculative', 'evidence_type': 'endpoint', 'path': ['parameters'], 'compare': 'regex',
             'expected': r'^draft_num_predict\s+4$', 'evidence_strength': 'configured-not-observed'},
            {**body, 'claim': 'speculative', 'evidence_type': 'endpoint', 'path': ['modelfile'], 'compare': 'regex',
             'expected': r'^DRAFT .*sha256-' + OLLAMA_DRAFT + '$', 'evidence_strength': 'configured-not-observed'}]
        def ev(claim, source, observed, strength='observed'):
            return {'claim': claim, 'evidence_type': 'endpoint', 'source': source, 'observed': observed, 'strength': strength}
        recorded = [ev('version', '/api/version', version), ev('identity', '/api/ps', OLLAMA_DIGEST),
                    ev('context', '/api/ps', 131072), ev('thinking', '/api/show', template_hash),
                    ev('thinking', '/api/show', show['capabilities']),
                    {'claim': 'thinking', 'evidence_type': 'unverifiable-by-endpoint', 'source': '/SYNTHETIC/canary.json', 'observed': True,
                     'strength': 'canary-backed', 'reason': 'canary needed', 'canary_sha256': CANARY_SHA, 'reasoning_chars': 339},
                    ev('vision', '/api/show', show['capabilities']),
                    ev('speculative', '/api/show', params, 'configured-not-observed'),
                    ev('speculative', '/api/show', modelfile, 'configured-not-observed')]
        runtime = {'claims': {'version': version, 'identity': OLLAMA_DIGEST, 'context': 131072, 'thinking': template_hash},
                   'evidence': recorded,
                   'thinking_request_contract': {'mode': 'explicit-native-request', 'template_sha256': template_hash,
                                                 'request_extras': row['request_extras'], 'default_enablement': 'not asserted'},
                   'raw': {'/api/version': {'version': version}, '/api/ps': ps, '/api/show': show}, 'models': None,
                   'unverifiable_by_endpoint': ['thinking']}
        ident = {'commands': {'version': version}, 'files': []}
    row['probes'] = probes
    return row, runtime, ident, model


def staging_name(root):
    return json.loads((root / 'manifest.json').read_text())['engines'][0]['row_id'] + '-website-staging.json'


def fixture(root, cases=('halogen', 'strata')):
    """Full native-shaped frozen practical-v1 contract; entirely synthetic."""
    models, engines = [], []
    for index, name in enumerate(cases):
        case = CASES[name]
        engine = case['engine']
        version = m.VERSIONS[engine]
        text_only = case.get('text_only', False)
        sid = 'ses-20261014-1200%02d-%s' % (index, hashlib.md5(name.encode()).hexdigest()[:6])
        folder = root / 'sessions' / sid
        native_engine = engine in ('gufo', 'ollama')
        if native_engine:
            row, runtime, ident, model = native_fixture(root, name, case, text_only)
            extras = row['request_extras']
        else:
            model = case.get('model', engine + '-fixture-only')
            template_hash = hashlib.sha256(b'enable_thinking SYNTHETIC TEMPLATE').hexdigest()
            spec_claim = {'halogen': 'mtp', 'strata': 5}.get(engine, True)
            claims = dict(version=version, identity=model, context=131072, thinking=template_hash, mtp=spec_claim)
            if not text_only:
                claims['vision'] = True
            probes = [dict(claim=k, endpoint='/native', path=[k], expected=v) for k, v in claims.items()]
            files = [{'path': '/home/private/fixture-only', 'sha256': 'a' * 64}]
            extras = {'enable_thinking': True} if engine == 'halogen' else {'chat_template_kwargs': {'enable_thinking': True}}
            contract = {'mode': 'explicit-native-request', 'template_sha256': template_hash}
            row = dict(key=engine, version=version, model=model, probes=probes, files=files,
                       thinking_contract=contract, request_extras=extras)
            if engine == 'gufo':
                row['image_id'] = GUFO_DIGEST
            if text_only:
                row['vision'] = {'status': 'unsupported', 'evidence': 'SYNTHETIC declared evidence'}
        engines.append(row)
        tasks: list[dict] = [dict(id=f'{c}-{size}', category=c, size=size, repetitions=2 if size <= 16384 else 1)
                 for c in ('input', 'retention', 'agentic', 'compaction')
                 for size in (4096, 8192, 16384, 32768, 65536, 131072)]
        tasks += [dict(id=f'output-{size}', category='output', size=size, repetitions=2)
                  for size in (256, 1024, 4096, 8192)]
        if not text_only:
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
        if not native_engine:
            runtime = {'claims': claims,
                 'raw': {'/native': claims, '/health': {'chat_template': {'thinking_control': True, 'probe': 'passed'}},
                         '/props': {'chat_template': 'enable_thinking SYNTHETIC TEMPLATE'}},
                 'thinking_request_contract': {**contract, 'request_extras': extras, 'default_enablement': 'not asserted'},
                 'models': {'data': [{'id': model}]}}
            ident = {'commands': {'version': version}, 'files': files}
        save(root / engine / 'runtime-readback.json', runtime)
        save(root / engine / 'cleanup.json', {'ok': True})
        save(root / engine / 'identity.json', ident)
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
        if case['spec']:
            # Real wrapper shape: row_id, speculative_mode and the short coverage token; quantization and weights stay
            # absent/null for Gufo and are derived by the importer. Ollama weights are explicit (its blobs are not on this host).
            staging.update(row_id=row['row_id'], speculative_mode=case['spec'], quantization=None, weights_total_bytes=None,
                           plan_coverage='text-only' if text_only else 'full')
            if engine == 'ollama':
                staging.update(quantization='UD-Q4_K_XL', weights_total_bytes=12345678, plan_coverage='full-practical-v1')
        save(root / ((row.get('row_id') or engine) + '-website-staging.json'), staging)
        models.append(dict(engine=engine, session_id=sid, status='finished', session=str(folder/'session.json'),
            website_staging=str(root/((row.get('row_id') or engine)+'-website-staging.json')), resource_summary=str(folder/'host-resources.json')))
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


class NewEngineTests(unittest.TestCase):
    """SYNTHETIC single-engine campaigns for Gufo/Ollama; in-memory candidates only, never snapshot.json."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='external-SYNTHETIC-', dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.real_load = m.load
        # Pre-publication baseline: the pre-publication commit 999a750's snapshot holds only campaign-003's 2 real external runs.
        head = Path(self.tmp.name) / 'head-snapshot.json'
        head.write_bytes(subprocess.check_output(['git', 'show', '999a750:data/snapshot.json'], cwd=REPO))
        self.full = m.load(head)
        self.assertEqual(len(self.full['external_dyno']['runs']), 2)
        self.baseline = copy.deepcopy(self.full)

    def campaign(self, case, name=None):
        root = Path(self.tmp.name) / (name or f'SYNTHETIC-{case}')
        fixture(root, (case,))
        return root

    def live(self, path):
        value = self.real_load(path)
        if isinstance(value, dict) and value.get('synthetic') is True:
            value['synthetic'] = False
        return value

    def export(self, roots, baseline=None):
        with patch.object(m, 'load', self.live):
            return m.append(self.baseline if baseline is None else baseline, roots)

    def alter(self, root, name, fn):
        d = self.real_load(root / name)
        fn(d)
        save(root / name, d)

    def test_each_new_engine_is_accepted_and_exposes_identity_fields(self):
        expected = {'gufo-flash': ('gufo', '0.18.0', 'Flash-Next', 'UD-Q4_K_XL', 'mtp', 'full-practical-v1', 'verified'),
                    'gufo-27b': ('gufo', '0.18.0', 'Qwen3.8-27B', 'UD-Q4_K_XL', 'dflash2', 'full-practical-v1', 'verified'),
                    'gufo-deepseek': ('gufo', '0.18.0', 'DeepSeek V4 Flash', 'IQ2XXS', 'dspark', 'text-only', 'unsupported-declared'),
                    'ollama-27b': ('ollama', '0.40.5', 'Qwen3.8-27B', 'UD-Q4_K_XL', 'mtp', 'full-practical-v1', 'verified')}
        roots = [self.campaign(case) for case in expected]
        result = self.export(roots)
        runs = result['external_dyno']['runs']
        self.assertEqual(len(runs), 2 + len(expected))
        for r, want in zip(runs[2:], expected.values()):
            self.assertEqual((r['engine'], r['runtime_version'], r['model_label'], r['quantization'],
                              r['speculative_mode'], r['plan_coverage'], r['vision']), want)
            self.assertEqual(r['weights_total_bytes'], 12345678 if r['engine'] == 'ollama' else 1230)
            self.assertIn('speculative', r['evidence_notes'])
            self.assertIsNone(r['metrics']['native_prefill_tps'])
            self.assertIsNone(r['metrics']['mtp_acceptance'])
            self.assertFalse(r['coverage']['mtp_acceptance_measured'])

    def test_deep_preservation_of_all_sections_and_existing_runs(self):
        original = copy.deepcopy(self.baseline)
        result = self.export([self.campaign('gufo-flash')])
        for k, v in original.items():
            if k != 'external_dyno':
                self.assertEqual(result[k], v, k)
        self.assertEqual(len(result['dyno_campaigns']['campaigns']), 3)
        self.assertEqual(len(result['dyno_campaigns']['runs']), 13)
        self.assertEqual(result['external_dyno']['runs'][:2], original['external_dyno']['runs'])
        self.assertEqual(result['external_dyno']['campaigns'][:1], original['external_dyno']['campaigns'])
        self.assertEqual(self.baseline, original)
        self.assertEqual(len(result['external_dyno']['runs']), 3)
        for old in result['external_dyno']['runs'][:2]:
            self.assertNotIn('speculative_mode', old)  # legacy records are never rewritten

    def test_idempotent_and_order_stable(self):
        roots = [self.campaign('gufo-27b'), self.campaign('ollama-27b')]
        first = self.export(roots)
        self.assertEqual(first, self.export(roots, first))
        self.assertEqual(json.dumps(first), json.dumps(self.export(roots, first)))

    def test_text_only_accepted_only_for_declared_unsupported_vision(self):
        run = self.export([self.campaign('gufo-deepseek')])['external_dyno']['runs'][-1]
        self.assertEqual(run['plan_coverage'], 'text-only')
        self.assertNotIn('image', run['quality']['by_category'])
        self.assertTrue(all(i['category'] != 'image' for i in run['items']))
        self.assertEqual(run['quality']['total_rows'], len(run['items']))

    def test_text_only_for_vision_capable_model_rejected(self):
        for case, engine in (('gufo-flash', 'gufo'), ('ollama-27b', 'ollama'), ('gufo-27b', 'gufo')):
            with self.subTest(case=case):
                root = self.campaign(case)
                self.alter(root, staging_name(root), lambda d: d.update(plan_coverage='text-only'))
                with self.assertRaisesRegex(ValueError, 'Plan coverage'):
                    self.export([root])

    def test_text_only_plan_with_full_label_or_vision_model_rejected(self):
        # genuinely text-only plan/results for a vision-capable model, labelled text-only: still rejected
        root = self.campaign('gufo-deepseek')
        self.alter(root, staging_name(root), lambda d: d.update(speculative_mode='mtp', quantization='UD-Q4_K_XL'))
        self.alter(root, 'manifest.json', lambda d: d['engines'][0].pop('vision'))
        with self.assertRaises(ValueError):
            self.export([root])

    def test_full_coverage_label_for_text_only_model_rejected(self):
        root = self.campaign('gufo-deepseek')
        self.alter(root, staging_name(root), lambda d: d.update(plan_coverage='full-practical-v1'))
        with self.assertRaisesRegex(ValueError, 'Plan coverage'):
            self.export([root])

    def test_text_only_requires_declared_evidence(self):
        for change in (lambda d: d['engines'][0].pop('vision'),
                       lambda d: d['engines'][0].update(vision={'supported': False, 'basis': ''}),
                       lambda d: d['engines'][0].update(vision={'supported': True, 'basis': 'x'})):
            root = self.campaign('gufo-deepseek', name=f'SYNTHETIC-d{id(change)}')
            self.alter(root, 'manifest.json', change)
            with self.assertRaisesRegex(ValueError, 'declared unsupported-vision'):
                self.export([root])

    def test_text_only_plan_missing_non_image_tasks_rejected(self):
        root = self.campaign('gufo-deepseek')
        sid = self.real_load(root/'campaign.json')['models'][0]['session_id']
        self.alter(root, f'sessions/{sid}/session.json', lambda d: d['plan'].update(tasks=d['plan']['tasks'][:-1]))
        with self.assertRaisesRegex(ValueError, 'frozen practical-v1 plan'):
            self.export([root])

    def test_unapproved_engine_version_digest_model_rejected(self):
        cases = {
            'engine': ('gufo', 'manifest.json', lambda d: d['engines'][0].update(key='vllm'), 'engine'),
            'version': ('gufo', 'manifest.json', lambda d: d['engines'][0].update(version='0.18.1'), 'engine/version'),
            'digest': ('gufo', 'manifest.json', lambda d: d['engines'][0].update(image_id='sha256:' + 'b' * 64), 'image digest'),
            'ollama-version': ('ollama', 'manifest.json', lambda d: d['engines'][0].update(version='0.40.4'), 'engine/version'),
        }
        for name, (engine, file, fn, rx) in cases.items():
            with self.subTest(name):
                case = 'gufo-flash' if engine == 'gufo' else 'ollama-27b'
                root = self.campaign(case, name=f'SYNTHETIC-bad-{name}')
                self.alter(root, file, fn)
                with self.assertRaisesRegex(ValueError, rx):
                    self.export([root])

    def test_unapproved_model_quant_spec_and_partial_fields_rejected(self):
        for name, case, engine, fn, rx in [
                ('quant', 'gufo-flash', 'gufo', lambda d: d.update(quantization='Q8_0'), 'Unapproved engine/model'),
                ('spec', 'gufo-flash', 'gufo', lambda d: d.update(speculative_mode='dspark'), 'Unapproved engine/model|Model file does not match'),
                ('unknown-spec', 'gufo-flash', 'gufo', lambda d: d.update(speculative_mode='eagle'), 'Unknown speculative'),
                ('label', 'gufo-flash', 'gufo', lambda d: d.update(model_label='Other'), 'label mismatch'),
                ('weights', 'gufo-flash', 'gufo', lambda d: d.update(weights_total_bytes=0), 'weights_total_bytes'),
                ('partial', 'gufo-flash', 'gufo', lambda d: d.pop('speculative_mode'), 'Partial new-contract'),
                ('ollama-quant', 'ollama-27b', 'ollama', lambda d: d.update(quantization='Q4_K_M'), 'Unapproved engine/model'),
                ('ollama-id', 'ollama-27b', 'ollama', lambda d: d.update(model='qwen3.8-27b:other'), 'identity mismatch|served')]:
            with self.subTest(name):
                root = self.campaign(case, name=f'SYNTHETIC-m-{name}')
                self.alter(root, staging_name(root), fn)
                with self.assertRaisesRegex(ValueError, rx):
                    self.export([root])

    def test_new_engine_requires_new_contract_fields(self):
        root = self.campaign('gufo-flash')
        def strip(d):
            for k in m.NEW_FIELDS:
                d.pop(k)
        self.alter(root, staging_name(root), strip)
        with self.assertRaisesRegex(ValueError, 'new-contract'):
            self.export([root])

    def test_real_wrapper_shape_is_accepted_with_derived_fields(self):
        for case in ('gufo-flash', 'gufo-27b', 'gufo-deepseek', 'ollama-27b'):
            with self.subTest(case):
                root = self.campaign(case)
                staged = self.real_load(root / staging_name(root))
                if case.startswith('gufo'):  # null quantization/weights and the short coverage token, as emitted by the wrapper
                    self.assertIsNone(staged['quantization'])
                    self.assertIsNone(staged['weights_total_bytes'])
                    self.assertIn(staged['plan_coverage'], ('full', 'text-only'))
                run = self.export([root])['external_dyno']['runs'][-1]
                self.assertIn(run['plan_coverage'], ('full-practical-v1', 'text-only'))
                self.assertGreater(run['weights_total_bytes'], 0)
                self.assertIsNone(run['metrics']['native_prefill_tps'])
                self.assertIsNone(run['metrics']['mtp_acceptance'])
                notes = run['evidence_notes']
                self.assertEqual(set(notes), {'version', 'identity', 'context', 'thinking', 'speculative', 'vision'})
                self.assertIn('canary-backed', notes['thinking'])
                if case == 'ollama-27b':
                    self.assertEqual(notes['speculative'], ['configured-not-observed'])
                    self.assertEqual(sorted(run['artifact_sha256']), sorted([m_ for m_ in run['artifact_sha256']]))
                    self.assertEqual(len(run['artifact_sha256']), 2)
                else:
                    self.assertEqual(notes['version'], ['container-backed'])
                text = json.dumps(run)
                for private in ('/home/', '/SYNTHETIC', 'http', 'SYNTHETIC basis', 'resident_bytes', 'draft_limit'):
                    self.assertNotIn(private, text)

    def readback_case(self, case, name, runtime_fn=None, manifest_fn=None, staging_fn=None, rx=''):
        root = self.campaign(case, name=f'SYNTHETIC-r-{name}')
        engine = {'ollama-27b': 'ollama'}.get(case, 'gufo')
        if runtime_fn:
            self.alter(root, f'{engine}/runtime-readback.json', runtime_fn)
        if manifest_fn:
            self.alter(root, 'manifest.json', lambda d: manifest_fn(d['engines'][0]))
        if staging_fn:
            self.alter(root, staging_name(root), staging_fn)
        with self.assertRaisesRegex(ValueError, rx):
            self.export([root])

    def test_native_readback_rejections(self):
        def item(d, claim, kind=None, nth=0):
            return [e for e in d['evidence'] if e['claim'] == claim and (kind is None or e['evidence_type'] == kind)][nth]
        def drop_probe(claim, kind):
            def fn(row):
                row['probes'] = [p for p in row['probes'] if not (p['claim'] == claim and p['evidence_type'] == kind)]
            return fn
        def both(claim, kind, fn):
            return (lambda d: fn(item(d, claim, kind)))
        cases = [
            # wrong version (container string and endpoint)
            ('ver-gufo', 'gufo-flash', both('version', 'unverifiable-by-endpoint', lambda e: e.update(observed='gufo version 0.17.0 (6c682a2)')), None, 'approved version'),
            ('ver-gufo-fmt', 'gufo-flash', both('version', 'unverifiable-by-endpoint', lambda e: e.update(observed='gufo version 0.18.0 (6c682a2) extra')), None, 'approved version'),
            ('ver-ollama', 'ollama-27b', lambda d: (item(d, 'version').update(observed='0.40.4'), d['raw']['/api/version'].update(version='0.40.4')),
             lambda r: [p.update(expected='0.40.4') for p in r['probes'] if p['claim'] == 'version'], 'approved version'),
            # missing / extra probes or evidence
            ('missing-spec-probe', 'gufo-flash', None, drop_probe('speculative', 'container-log'), 'Missing or extra recorded evidence'),
            ('missing-all-spec', 'gufo-flash', None, lambda r: r.update(probes=[p for p in r['probes'] if p['claim'] != 'speculative']), 'Missing native probes'),
            ('missing-evidence', 'gufo-flash', lambda d: d['evidence'].pop(), None, 'Missing or extra recorded evidence'),
            ('missing-context-args', 'gufo-flash', lambda d: d['evidence'].pop(4), drop_probe('context', 'container-args'), 'context launch|Context launch'),
            ('missing-vision-probe', 'ollama-27b', None, drop_probe('vision', 'endpoint'), 'Missing native probes'),
            # failed probes
            ('failed-endpoint', 'gufo-flash', lambda d: d['raw']['/v1/models']['data'][0].update(id='other'), None, 'Unproven native runtime claim'),
            ('failed-args', 'gufo-flash', both('identity', 'container-args', lambda e: e.update(observed=[['--model', '/models/x']])), None, 'argument evidence'),
            ('failed-log', 'gufo-flash', both('speculative', 'container-log', lambda e: e.update(observed='nothing here')), None, 'log evidence'),
            ('failed-context', 'gufo-flash', both('context', 'container-args', lambda e: e.update(observed=[['--context', '4096'], ['--sessions', '1']])), None, 'argument evidence'),
            ('ollama-digest', 'ollama-27b', lambda d: d['raw']['/api/ps']['models'][0].update(digest='7' * 64), None, 'Unproven native runtime claim'),
            ('ollama-context', 'ollama-27b', lambda d: d['raw']['/api/ps']['models'][0].update(context_length=65536), None, 'Unproven native runtime claim'),
            # wrong speculative mode
            ('mode-args', 'gufo-flash', both('speculative', 'container-args', lambda e: e.update(observed=[['--speculative', 'dflash2'], ['--mtp-model', '/models/mtp-draft.gguf']])),
             lambda r: [p.update(expected=[['--speculative', 'dflash2'], ['--mtp-model', '/models/mtp-draft.gguf']]) for p in r['probes'] if p['claim'] == 'speculative' and p['evidence_type'] == 'container-args'],
             'approved mode'),
            ('mode-log', 'gufo-27b', both('speculative', 'container-log', lambda e: e.update(observed='event=load_completed speculative=mtp draft_limit=7')),
             lambda r: [p.update(expected='speculative=mtp') for p in r['probes'] if p['claim'] == 'speculative' and p['evidence_type'] == 'container-log'],
             'approved mode'),
            ('mode-staging', 'gufo-27b', None, None, 'Unapproved|approved'),
            ('ollama-observed-strength', 'ollama-27b', both('speculative', 'endpoint', lambda e: e.update(strength='observed')), None, 'strength mismatch'),
            ('ollama-draft', 'ollama-27b', lambda d: d['raw']['/api/show'].update(modelfile='FROM x\nDRAFT /y/sha256-' + '1' * 64),
             None, 'Unproven native runtime claim'),
            # vision
            ('text-only-manifest-for-vision-model', 'gufo-flash', None,
             lambda r: (r.update(vision={'supported': False, 'basis': 'x'}), r.update(probes=[p for p in r['probes'] if p['claim'] != 'vision'] +
                        [{'claim': 'vision', 'evidence_type': 'declared', 'expected': False, 'basis': 'x'}])),
             'Missing or extra recorded evidence|declared unsupported|Text-only'),
            ('vision-no-image', 'gufo-flash', lambda d: (item(d, 'vision', 'endpoint').update(observed=['text']), d['raw']['/v1/models']['data'][0]['architecture'].update(input_modalities=['text'])),
             lambda r: [p.update(expected=['text']) for p in r['probes'] if p['claim'] == 'vision' and p['evidence_type'] == 'endpoint'], 'Vision enablement unproven'),
            ('ollama-no-vision', 'ollama-27b', lambda d: (item(d, 'vision').update(observed=['tools', 'thinking']), d['raw']['/api/show'].update(capabilities=['tools', 'thinking'])), None, 'Unproven native runtime claim'),
            # canary / thinking
            ('canary-sha-differs', 'gufo-flash', both('thinking', 'unverifiable-by-endpoint', lambda e: e.update(canary_sha256='d' * 64)), None, 'canary'),
            ('canary-no-reasoning', 'gufo-flash', both('thinking', 'unverifiable-by-endpoint', lambda e: e.update(reasoning_chars=0)), None, 'canary'),
            ('canary-strength', 'ollama-27b', both('thinking', 'unverifiable-by-endpoint', lambda e: e.update(strength='observed')), None, 'canary'),
            ('canary-removed', 'gufo-flash', None, lambda r: r.update(probes=[p for p in r['probes'] if p['claim'] != 'thinking']), 'Missing native probes'),
            ('canary-pin-removed', 'gufo-flash', None, lambda r: r.pop('canary_evidence'), 'canary'),
            ('extras', 'gufo-flash', lambda d: d['thinking_request_contract'].update(request_extras={'enable_thinking': False}),
             lambda r: r.update(request_extras={'enable_thinking': False}), 'Unapproved thinking request extras'),
            ('extras-mismatch', 'ollama-27b', lambda d: d['thinking_request_contract'].update(request_extras={'think': True}), None, 'contract unproven'),
            ('ollama-template', 'ollama-27b', None, lambda r: r['thinking_contract'].update(template_sha256='e' * 64), 'contract unproven|Unproven'),
            ('identity-gufo-models', 'gufo-flash', lambda d: d['models']['data'].append({'id': 'second'}), None, 'identity'),
            ('declared-strength', 'gufo-deepseek', both('vision', 'declared', lambda e: e.update(strength='observed')), None, 'unsupported-vision|Unknown|Text-only'),
        ]
        for name, case, rt, mf, rx in cases:
            if name == 'mode-staging':
                continue
            with self.subTest(name):
                self.readback_case(case, name, rt, mf, None, rx)

    def test_wrong_speculative_mode_in_staging_rejected(self):
        self.readback_case('gufo-27b', 'mode-staging', staging_fn=lambda d: d.update(speculative_mode='mtp'), rx='Unapproved|approved')

    def test_ollama_weights_must_come_from_statable_blobs(self):
        root = self.campaign('ollama-27b', name='SYNTHETIC-ow')
        self.alter(root, staging_name(root), lambda d: d.update(weights_total_bytes=None))
        with self.assertRaisesRegex(ValueError, 'Ollama weight blobs not statable'):
            self.export([root])

    def test_gufo_weights_require_every_pinned_file(self):
        root = self.campaign('gufo-flash', name='SYNTHETIC-gw')
        next((root / 'weights').glob('*mmproj*')).unlink()
        with self.assertRaisesRegex(ValueError, 'Pinned weight files missing'):
            self.export([root])

    def test_real_gufo_and_ollama_campaigns_when_available(self):
        base = Path('/home/yj/agent-ecosystem/projects/plans/dyno-metric/patch/new-external-campaign')
        roots = [base / n for n in ('campaign-003', 'campaign-004-gufo-27b', 'campaign-005-gufo-fn', 'campaign-006-ollama-27b')]
        if not all(r.exists() for r in roots):
            self.skipTest('real campaigns not available')
        result = m.append(self.full, roots)
        runs = result['external_dyno']['runs']
        self.assertEqual(len(runs), 5)
        self.assertEqual(runs[:2], self.full['external_dyno']['runs'])
        self.assertEqual([r['speculative_mode'] for r in runs[2:]], ['dflash2', 'mtp', 'mtp'])
        self.assertTrue(all(r['metrics']['native_prefill_tps'] is None and r['metrics']['mtp_acceptance'] is None for r in runs[2:]))
        text = json.dumps(runs[2:])
        for private in ('/home/', 'http', 'localhost', 'reasoning"', 'prompt"'):
            self.assertNotIn(private, text)
        self.assertEqual(json.dumps(m.append(result, roots)), json.dumps(result))

    def test_identity_conflict_for_new_engine(self):
        root = self.campaign('gufo-27b')
        first = self.export([root])
        self.alter(root, staging_name(root), lambda d: d.update(publication_gate='changed'))
        with self.assertRaisesRegex(ValueError, 'identity conflict'):
            self.export([root], first)

    def test_synthetic_new_engine_always_rejected_in_production(self):
        with self.assertRaisesRegex(ValueError, 'Unreviewed manifest'):
            m.append(self.baseline, [self.campaign('gufo-flash')])

    def test_privacy_new_engine(self):
        root = self.campaign('gufo-deepseek')
        self.alter(root, staging_name(root), lambda d: d.update(env={'K': 'ENV-SECRET'}, prompt='PROMPT-SECRET'))
        text = json.dumps(self.export([root])['external_dyno'])
        for private in ('/home/', 'http://', 'PRIVATE-MACHINE', 'ANSWER-SECRET', 'ENV-SECRET', 'PROMPT-SECRET',
                        'SYNTHETIC declared evidence'):
            self.assertNotIn(private, text)

    def test_new_contract_for_halogen_and_legacy_mix_in_one_snapshot(self):
        legacy = Path(self.tmp.name) / 'SYNTHETIC-legacy'
        fixture(legacy, ('halogen',))
        new = Path(self.tmp.name) / 'SYNTHETIC-new-halogen'
        fixture(new, ('halogen',))
        self.alter(new, 'halogen-website-staging.json', lambda d: d.update(
            speculative_mode='mtp', quantization='hgn', weights_total_bytes=5, plan_coverage='full-practical-v1'))
        self.baseline.pop('external_dyno')
        with self.assertRaisesRegex(ValueError, 'identity conflict'):  # identical session ids, different record shape
            self.export([legacy, new])
        result = self.export([new])
        self.assertEqual(result['external_dyno']['runs'][0]['speculative_mode'], 'mtp')

    def test_real_campaign_003_reimport_is_identical_when_available(self):
        root = Path('/home/yj/agent-ecosystem/projects/plans/dyno-metric/patch/new-external-campaign/campaign-003')
        if not root.exists():
            self.skipTest('real campaign-003 not available')
        again = m.append(self.full, [root])
        self.assertEqual(json.dumps(again, separators=(',', ':')), json.dumps(self.full, separators=(',', ':')))
        self.assertEqual(len(again['external_dyno']['runs']), 2)

    def test_live_snapshot_holds_exactly_five_external_runs(self):
        live = m.load(REPO/'data/snapshot.json')
        runs = live['external_dyno']['runs']
        self.assertEqual(len(runs), 5)
        counts = {}
        for r in runs:
            counts[r['engine']] = counts.get(r['engine'], 0) + 1
        self.assertEqual(counts, {'halogen': 1, 'strata': 1, 'gufo': 2, 'ollama': 1})
        self.assertEqual(len({r['id'] for r in runs}), 5)
        self.assertEqual(runs[:2], self.full['external_dyno']['runs'])
        self.assertEqual(live['external_dyno']['campaigns'][:1], self.full['external_dyno']['campaigns'])
        self.assertEqual(len(live['external_dyno']['campaigns']), 4)
        for k, v in self.full.items():
            if k != 'external_dyno':
                self.assertEqual(live[k], v, k)

    def test_cli_failure_writes_nothing_for_new_engine(self):
        root = self.campaign('gufo-flash')
        out = Path(self.tmp.name) / 'SYNTHETIC-never.json'
        result = subprocess.run([sys.executable, str(REPO/'scripts/import_external_dyno.py'), '--snapshot',
            str(REPO/'data/snapshot.json'), '--campaign', str(root), '--out', str(out)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
