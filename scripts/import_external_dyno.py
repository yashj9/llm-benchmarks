"""Append real external practical-v1 sessions; never run source code or inference.

Only exact campaign ledger links are followed. Staging is not trusted on its own:
its fields must match native session/results and archived runtime probe readback.
The separate external_dyno extension never changes arena or Ollama campaign data.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


VERSIONS = {'halogen': '0.18.4', 'strata': '0.1.44.1'}
CATEGORIES = {'input', 'retention', 'agentic', 'compaction', 'output', 'image'}
PROJECTION = ('task_id', 'category', 'size', 'rep', 'turn', 'sub', 'score',
              'prompt_tokens', 'cached_prompt_tokens', 'completion_tokens', 'reasoning_tokens',
              'ttft_s', 'e2e_s', 'decode_tps', 'finish_reason', 'error', 'started_at')
RESOURCE_KEYS = {'ram_total_bytes', 'ram_free_bytes', 'ram_available_bytes',
                 'ram_used_bytes', 'swap_used_bytes', 'swap_free_bytes', 'cpu_percent'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse(text):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'Duplicate JSON key')
            out[key] = value
        return out
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def load(path):
    return parse(Path(path).read_text(encoding='utf-8'))


def lines(path):
    # No silent malformed-line skipping, unlike the native store's convenience reader.
    return [parse(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def token(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:+-]{1,160}', value)
            and not re.search(r'localhost|127\.0\.0\.1|github_pat_|gh[pousr]_', value, re.I),
            'Unsafe public identifier')
    return value


def numeric(value):
    require(value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0),
            'Invalid numeric field')
    return value


def pointer(value, root, expected=None):
    require(isinstance(value, str), 'Missing source link')
    p = Path(value)
    p = (p if p.is_absolute() else root / p).resolve()
    require(p.is_relative_to(root.resolve()) and p.is_file(), 'Missing/escaping source link')
    if expected is not None:
        require(p == expected.resolve(), 'Source link is not the selected canonical file')
    return p


def resources(summary):
    require(summary.get('schema') == 'dyno-external-resources-v1', 'Unknown resource schema')
    metrics = {}
    for key, stats in summary.get('metrics', {}).items():
        if key not in RESOURCE_KEYS and not re.fullmatch(
                r'card[0-9]+\.(package_power_w|temperature_c|utilization_pct|memory_used_vram_b|mem_info_gtt_used_b|clock_hz)', key):
            continue  # disk names/device inventory and all other fields stay private
        metrics[key] = {k: numeric(stats.get(k)) for k in ('count', 'min', 'max', 'mean', 'coverage_fraction')}
    return {'sample_count': numeric(summary.get('sample_count')), 'metrics': metrics,
            'error_count': len(summary.get('errors', [])),
            'scope': 'Host-wide, including concurrent workloads; not model-attributable.',
            'power_note': 'AMD PPT is shared package power, not CPU plus GPU or wall power.',
            'memory_note': 'GTT and VRAM aperture overlap system RAM; never sum with RAM.'}


def readback(manifest_row, evidence):
    require(not evidence.get('synthetic'), 'Synthetic runtime readback')
    probes = manifest_row['probes']
    require(len(probes) == 6 and {p['claim'] for p in probes} ==
            {'version', 'identity', 'context', 'thinking', 'vision', 'mtp'}, 'Missing native probes')
    claims = evidence['claims']
    for probe in probes:
        value = evidence['raw'][probe['endpoint']]
        require(isinstance(probe['path'], list) and probe['path'], 'Missing probe selector')
        for part in probe['path']:
            value = value[part]
        if probe.get('transform') == 'sha256':
            value = hashlib.sha256(value.encode('utf-8')).hexdigest()
        else:
            require(probe.get('transform') is None, 'Unknown readback transform')
        require(type(value) is type(probe['expected']) and value == probe['expected']
                and claims[probe['claim']] == value, 'Unproven native runtime claim')
    require(claims['version'] == manifest_row['version'] and claims['identity'] == manifest_row['model']
            and claims['context'] == 131072, 'Runtime identity/version/context mismatch')
    require([x['id'] for x in evidence['models']['data']] == [manifest_row['model']],
            'Ambiguous native model identity')
    require(claims['vision'] is True and claims['mtp'] ==
            ('mtp' if manifest_row['key'] == 'halogen' else 5), 'Vision/MTP enablement unproven')
    contract = manifest_row.get('thinking_contract') or {}
    extras = {'enable_thinking': True} if manifest_row['key'] == 'halogen' else {'chat_template_kwargs': {'enable_thinking': True}}
    expected_contract = {'mode': 'explicit-native-request', 'template_sha256': contract.get('template_sha256'),
                         'request_extras': extras, 'default_enablement': 'not asserted'}
    require(contract.get('mode') == 'explicit-native-request' and
            re.fullmatch(r'[0-9a-f]{64}', contract.get('template_sha256', '')) and
            manifest_row.get('request_extras') == extras and claims['thinking'] == contract['template_sha256']
            and evidence.get('thinking_request_contract') == expected_contract, 'Thinking request contract unproven')
    if manifest_row['key'] == 'halogen':
        template = evidence['raw']['/health']['chat_template']
        require(template.get('thinking_control') is True and template.get('probe') == 'passed',
                'Native thinking control unproven')
    else:
        require('enable_thinking' in evidence['raw']['/props']['chat_template'], 'Native thinking control unproven')
    # Raw template/native values are verified, never copied to public output.
    return claims


def records(native, staged, session, plan):
    require(native and len(native) == len(staged), 'Missing or mismatched result records')
    tasks = plan['tasks']
    require(tasks and len({t['id'] for t in tasks}) == len(tasks), 'Invalid task plan')
    # Frozen practical-v1, 128K, thinking-on and verified image support. A
    # truncated plan cannot turn a partial session into a finished score row.
    frozen = {f'{category}-{size}': (category, size, 2 if size <= 16384 else 1)
              for category in ('input', 'retention', 'agentic', 'compaction')
              for size in (4096, 8192, 16384, 32768, 65536, 131072)}
    frozen.update({f'output-{size}': ('output', size, 2) for size in (256, 1024, 4096, 8192)})
    frozen.update({f'image-{size}': ('image', size, 2) for size in (512, 1024)})
    require({t['id']: (t['category'], t['size'], t['repetitions']) for t in tasks} == frozen,
            'Partial or changed frozen practical-v1 plan')
    expected = set()
    task_map = {t['id']: t for t in tasks}
    for t in tasks:
        require(t['category'] in CATEGORIES and type(t['repetitions']) is int and t['repetitions'] > 0,
                'Invalid practical task')
        for rep in range(t['repetitions']):
            if t['category'] == 'agentic':
                for turn in range(1, (6 if t['size'] >= 8192 else 4) + 1):
                    expected.add((t['id'], rep, turn, None))
            elif t['category'] == 'compaction':
                expected.update({(t['id'], rep, None, 'summary'), (t['id'], rep, None, 'probe')})
            else:
                expected.add((t['id'], rep, None, None))
    identities = set()
    public = []
    for r, s in zip(native, staged):
        require(r.get('session_id') == session['id'] and not r.get('error') and not r.get('synthetic')
                and not (r.get('extra') or {}).get('partial'), 'Partial/error native result')
        require(all(s.get(k) == r.get(k) for k in PROJECTION), 'Staging differs from native result')
        require(r['task_id'] in task_map and r['category'] == task_map[r['task_id']]['category']
                and r['size'] == task_map[r['task_id']]['size'], 'Unplanned native task')
        key = (r['task_id'], r['rep'], r.get('turn'), r.get('sub'))
        require(key not in identities, 'Duplicate result identity')
        identities.add(key)
        cache = (r.get('extra') or {}).get('cache_evidence', 'unknown')
        require(cache in ('present', 'unknown') and s.get('cache_evidence') == cache,
                'Unknown or mismatched cache evidence')
        item = {k: numeric(r.get(k)) for k in ('size', 'rep', 'turn', 'score', 'prompt_tokens',
                'completion_tokens', 'reasoning_tokens', 'ttft_s', 'e2e_s', 'decode_tps')}
        require(all(item[k] is None or type(item[k]) is int for k in
                    ('size', 'rep', 'turn', 'prompt_tokens', 'completion_tokens', 'reasoning_tokens')),
                'Noninteger native token/identity field')
        require(item['score'] is None or item['score'] <= 1, 'Score outside unit interval')
        summary_row = r['category'] == 'compaction' and r.get('sub') == 'summary'
        require((item['score'] is None) == summary_row, 'Missing or unexpected native task score')
        require(item['completion_tokens'] is not None, 'Missing completion usage')
        item.update(task_id=token(r['task_id']), category=r['category'],
                    sub=token(r['sub']) if r.get('sub') else None,
                    cached_prompt_tokens=numeric(r.get('cached_prompt_tokens')) if cache == 'present' else None,
                    cache_evidence=cache, native_prefill_tps=None, mtp_acceptance=None,
                    finish_reason=r.get('finish_reason') if r.get('finish_reason') in ('stop', 'length') else None)
        require(item['cached_prompt_tokens'] is None or type(item['cached_prompt_tokens']) is int,
                'Noninteger cached token count')
        if 'host_resources' in s:
            item['host_resources'] = resources(s['host_resources'])
        public.append(item)
    require(identities == expected, 'Partial practical battery: planned requests missing or extra')
    return public


def campaign_export(directory):
    root = Path(directory).resolve()
    ledger = root / 'campaign.json'
    c = load(ledger)
    require(c.get('schema') == 'dyno-external-campaign-v1' and c.get('complete') is True
            and c.get('battery_finished') is True and c.get('cleanup_ok') is True
            and c.get('pinned_files_unchanged') is True and not c.get('failures')
            and not c.get('recovery_required') and not c.get('synthetic'), 'Campaign unfinished/unproven')
    manifest_path = root / 'manifest.json'
    manifest = load(manifest_path)
    require(manifest.get('reviewed_runtime_contract') is True and not manifest.get('synthetic'),
            'Unreviewed manifest')
    window_path = root / 'service-window.json'
    window = load(window_path)
    require(window.get('restored') is True and not window.get('recovery_errors'), 'Service restoration unproven')
    configured = {r['key']: r for r in manifest['engines']}
    require(len(configured) == len(manifest['engines']) and set(configured) == set(VERSIONS),
            'Unexpected or duplicate manifest engine')
    selected = c['models']
    require(len(selected) == len(configured) and {r['engine'] for r in selected} == set(configured),
            'Missing or duplicate selected engine')
    runs = []
    for link in selected:
        engine = link['engine']
        config = configured[engine]
        require(config['version'] == VERSIONS[engine] and link['status'] == 'finished', 'Unapproved engine/version')
        sid = token(link['session_id'])
        require(re.fullmatch(r'ses-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}', sid), 'Invalid selected session ID')
        folder = root / 'sessions' / sid
        staging_path = pointer(link['website_staging'], root, root / (engine + '-website-staging.json'))
        bundle = load(staging_path)
        require(bundle.get('schema') == 'dyno-external-website-staging-v1'
                and bundle.get('synthetic') is False and bundle.get('status') == 'finished'
                and not bundle.get('error'), 'Synthetic/unfinished staging bundle')
        require(bundle['engine'] == engine and bundle['version'] == config['version']
                and bundle['model'] == config['model'] and bundle['session_id'] == sid
                and bundle['context'] == 131072 and bundle.get('native_sampling') is True,
                'Staging identity mismatch')
        sources = bundle['sources']
        paths = {k: pointer(sources[k], root, expected) for k, expected in {
            'session': folder / 'session.json', 'results': folder / 'results.jsonl',
            'native_samples': folder / 'samples.jsonl', 'host_samples': root / engine / 'host-samples.jsonl',
            'host_summary': folder / 'host-resources.json'}.items()}
        require(pointer(link['session'], root) == paths['session'] and
                pointer(link['resource_summary'], root) == paths['host_summary'], 'Ledger link mismatch')
        session = load(paths['session'])
        require(session['id'] == sid and session['model'] == config['model']
                and session.get('engine') == 'openai-compat' and session.get('engine_label') == engine
                and session.get('status') == 'finished' and not session.get('error')
                and session.get('cleanup', {}).get('ok') is True
                and not session.get('provenance', {}).get('offline_mock')
                and not session.get('synthetic'), 'Native session unfinished/synthetic/mismatched')
        require(bundle['battery_version'] == 'practical-v1' and session['provenance']['battery_version'] == 'practical-v1'
                and bundle['fixture_version'] == session['provenance']['fixture_version']
                and session['plan']['battery_version'] == 'practical-v1'
                and session['plan']['effective_context'] == 131072, 'Battery/provenance mismatch')
        runtime_path = root / engine / 'runtime-readback.json'
        cleanup_path = root / engine / 'cleanup.json'
        identity_path = root / engine / 'identity.json'
        claims = readback(config, load(runtime_path))
        require(load(cleanup_path).get('ok') is True, 'Runtime cleanup unproven')
        ident = load(identity_path)
        require(not ident.get('synthetic') and ident.get('commands') and ident.get('files') == config['files'] and config['files']
                and all(re.fullmatch(r'[0-9a-f]{64}', x['sha256']) for x in config['files']),
                'Missing identity artifact evidence')
        native = lines(paths['results'])
        items = records(native, bundle['records'], session, session['plan'])
        require(session['summary']['headline']['rows'] == len(items)
                and session['summary']['headline']['errors'] == 0, 'Native summary mismatch')
        summary = load(paths['host_summary'])
        require(summary == bundle['resources'], 'Host summary link mismatch')
        # All linked evidence must be parseable. Neither sensor payload is copied.
        require(lines(paths['native_samples']) and lines(paths['host_samples']), 'Missing telemetry evidence')
        sustained = [r['decode_tps'] for r in items if r['completion_tokens'] >= 256 and
                     r['decode_tps'] is not None and r['decode_tps'] > 0]
        scored = [r['score'] for r in items if r['score'] is not None]
        cats = {}
        for category in sorted({r['category'] for r in items}):
            group = [r for r in items if r['category'] == category]
            scores = [r['score'] for r in group if r['score'] is not None]
            cats[category] = {'rows': len(group), 'scored_rows': len(scores),
                              'mean_score': statistics.mean(scores) if scores else None}
        evidence_paths = {**paths, 'staging': staging_path, 'runtime_readback': runtime_path,
                          'runtime_cleanup': cleanup_path, 'identity': identity_path}
        created = numeric(session['created_at'])
        if created is None:
            raise ValueError('Missing native session timestamp')
        runs.append({'id': sid, 'campaign': token(root.name), 'session_id': sid, 'engine': engine,
                     'runtime_version': config['version'], 'model': token(config['model']),
                     'platform': 'amd-strix-halo', 'placement': 'unified-memory', 'context': 131072,
                     'status': 'finished', 'created': datetime.fromtimestamp(created, timezone.utc).isoformat(),
                     'thinking': 'on', 'thinking_note': 'Explicit native request control; not native default.',
                     'native_sampling': True, 'battery_version': 'practical-v1',
                     'fixture_version': token(bundle['fixture_version']),
                     'identity_verified': True, 'runtime_cleanup_ok': True,
                     'source_sha256': {key: sha(path) for key, path in evidence_paths.items()},
                     'artifact_sha256': sorted(x['sha256'] for x in ident['files']),
                     'coverage': {'execution_complete': True,
                         'strict_evidence_complete': c.get('strict_evidence_complete') is True,
                         'near_window_occupancy_verified': False, 'cache_verified': False,
                         'native_prefill_measured': False, 'mtp_acceptance_measured': False},
                     'metrics': {'sustained_decode_tps': statistics.median(sustained) if sustained else None,
                         'sustained_n': len(sustained), 'excluded_from_sustained': len(items) - len(sustained),
                         'native_prefill_tps': None, 'mtp_acceptance': None},
                     'quality': {'method': 'practical-v1-row-mean', 'mean_score': statistics.mean(scored) if scored else None,
                         'scored_rows': len(scored), 'total_rows': len(items), 'by_category': cats,
                         'note': 'Arithmetic mean of native scored request rows, including multi-turn rows. Not arena Quality, tier weighting, confidence interval or Balanced score.'},
                     'resources': resources(summary), 'items': items})
    meta = {'id': token(root.name), 'complete': True, 'cleanup_ok': True, 'service_restored': True,
            'strict_evidence_complete': c.get('strict_evidence_complete') is True,
            'source_sha256': {'ledger': sha(ledger), 'manifest': sha(manifest_path), 'service_window': sha(window_path)},
            'selected_sessions': [r['id'] for r in runs]}
    return meta, runs


def append(snapshot, directories):
    out = copy.deepcopy(snapshot)
    extension = out.setdefault('external_dyno', {'schema_version': 1, 'method': 'external-practical-v1',
                                               'campaigns': [], 'runs': []})
    require(extension.get('schema_version') == 1 and extension.get('method') == 'external-practical-v1',
            'Unknown existing external schema')
    for directory in directories:
        meta, runs = campaign_export(directory)
        for name, incoming in (('campaigns', [meta]), ('runs', runs)):
            existing = {x['id']: x for x in extension[name]}
            require(len(existing) == len(extension[name]), 'Duplicate existing identity')
            for record in incoming:
                if record['id'] in existing:
                    require(existing[record['id']] == record, 'Append-only identity conflict: ' + record['id'])
                else:
                    extension[name].append(record)
                    existing[record['id']] = record
    for key, value in snapshot.items():
        if key != 'external_dyno':
            require(out[key] == value, 'Baseline changed')
    text = json.dumps(extension, allow_nan=False)
    require(not re.search(r'/home/|/usr/|/sys/|/proc/|https?://|localhost|127\.0\.0\.1|'
                         r'"(?:prompt|answer|reasoning|template|images|env|vectors|raw|endpoint|machine_id|error)"\s*:',
                         text, re.I), 'Public privacy scan failed')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', default='data/snapshot.json')
    parser.add_argument('--campaign', action='append', required=True, help='Exact finished campaign directory')
    parser.add_argument('--out', required=True, help='Candidate file, never the input snapshot')
    args = parser.parse_args()
    public_snapshot = Path(__file__).resolve().parents[1] / 'data/snapshot.json'
    require(Path(args.out).resolve() not in (Path(args.snapshot).resolve(), public_snapshot.resolve()),
            'Public/input snapshot overwrite forbidden; write a candidate')
    result = append(load(args.snapshot), args.campaign)
    Path(args.out).write_text(json.dumps(result, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(json.dumps({'external_campaigns': len(result['external_dyno']['campaigns']),
                      'external_runs': len(result['external_dyno']['runs']), 'baseline_preserved': True}))


if __name__ == '__main__':
    main()
