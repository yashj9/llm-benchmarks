"""Append sanitized sequential Dyno evidence without rewriting legacy records.

Standard library only; reads campaign -> selected report -> raw records. Never
executes source code or inference. Re-imports are idempotent; changed identities
fail closed. Separate schema/leaderboard: these workloads are not arena scores.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

PLATFORM = 'amd-strix-halo'
METHOD = 'sequential-sustained-v1'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:+-]+', value):
        raise ValueError('Unsafe or missing public identifier')
    return value


def label(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[A-Za-z0-9_.:+-]+(?: #[0-9]+)?|first request)', value):
        raise ValueError('Unsafe request label')
    return value


def num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def med(values):
    values = [num(v) for v in values if num(v) is not None]
    return statistics.median(v for v in values if v is not None) if values else None


def selected_path(value, root):
    path = Path(value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Source pointer escapes campaign directory')
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sustained(rows):
    return [x for x in rows if not x.get('error') and (num(x.get('completion_tokens')) or 0) >= 256
            and (num(x.get('decode_tps')) or 0) > 0
            and x.get('label') != 'first request'
            and not re.search(r'calibrat|warm.?up', x.get('label', ''), re.I)]


def summarize(rows):
    good = sustained(rows)
    return {'sustained_decode_tps': med(x.get('decode_tps') for x in good),
            'sustained_n': len(good),
            'sustained_min_tps': min((x['decode_tps'] for x in good), default=None),
            'sustained_max_tps': max((x['decode_tps'] for x in good), default=None),
            'requests': len(rows), 'request_errors': sum(bool(x.get('error')) for x in rows),
            'excluded_from_sustained': len(rows) - len(good)}


def export_report(path, campaign_name):
    r = load(path)
    if r['status'] != 'finished':
        raise ValueError('Selected report is not finished')
    ident = r['identity']
    if r['live_readback'].get('digest') != ident['digest']:
        raise ValueError('Model digest readback mismatch')
    session = r.get('session') or {}
    request = session.get('request') or {}
    provenance = session.get('provenance') or {}
    embedding = r.get('route') == 'embedding-only'
    sid = session.get('id')
    # Embedding route never created a Dyno session; do not fabricate one.
    rid = sid or f'{campaign_name}-{path.parent.name}'
    records = []
    hashes = []
    raw_by_path = {}
    for pointer in r['raw_records']:
        rawpath = selected_path(pointer, path.parent)
        x = load(rawpath)
        if (x.get('payload') or {}).get('model') != ident['name']:
            raise ValueError('Raw request model mismatch')
        raw_by_path[str(rawpath)] = x
        hashes.append(digest(rawpath))
        public: dict = {k: num(x.get(k)) for k in ('prompt_tokens', 'cached_prompt_tokens', 'completion_tokens',
                  'ttft_s', 'answer_start_s', 'elapsed_s', 'new_token_prefill_tps', 'decode_tps')}
        public.update(id=identity(x['id']), label=label(x['label']), error=bool(x.get('error')),
                      finish_reason=x.get('finish_reason') if x.get('finish_reason') in ('stop', 'length') else None)
        records.append(public)
    if len({x['id'] for x in records}) != len(records):
        raise ValueError('Duplicate raw request IDs')
    cache = []
    for cell in r.get('cache', []):
        x = raw_by_path[str(selected_path(cell['raw_path'], path.parent))]
        if cell.get('mode') not in ('uncached', 'cached', 'partial'):
            raise ValueError('Unknown cache mode')
        cache.append({'size': num(cell.get('size')), 'rep': num(cell.get('rep')), 'mode': cell['mode'],
                      **{k: cell.get(k) if isinstance(cell.get(k), bool) else None for k in ('actual_input_fit', 'cache_mode_verified', 'measurement_valid')},
                      'request_id': identity(x['id']),
                      **{k: num(x.get(k)) for k in ('prompt_tokens', 'cached_prompt_tokens', 'completion_tokens', 'ttft_s', 'new_token_prefill_tps', 'decode_tps')},
                      'error': bool(x.get('error'))})
    # Retain every cache cell, including invalid uncached prefixes, but only
    # valid cells contribute to ranked cold/fully-cached summaries.
    cold = [c for c in cache if c['mode'] == 'uncached' and c['measurement_valid'] is True and not c['error']]
    hot = [c for c in cache if c['mode'] == 'cached' and c['measurement_valid'] is True and not c['error']]
    depth = max((c['size'] for c in cold), default=None)
    hot_depth = max((c['size'] for c in hot), default=None)
    metrics = summarize(records)
    groups = sorted({re.sub(r' #[0-9]+$', '', x['label']) for x in sustained(records)})
    metrics['by_workload'] = {key: summarize([x for x in records if re.sub(r' #[0-9]+$', '', x['label']) == key]) for key in groups}
    metrics.update(cold_depth=depth, cold_new_token_prefill_tps=med(c['new_token_prefill_tps'] for c in cold if c['size'] == depth),
                   cold_ttft_s=med(c['ttft_s'] for c in cold if c['size'] == depth),
                   cached_depth=hot_depth, cached_ttft_s=med(c['ttft_s'] for c in hot if c['size'] == hot_depth))
    tensors = []
    for gguf in ident.get('show_from_gguf_identity', []):
        meta = gguf.get('general_metadata') or {}
        tensors.append({'role': meta.get('general.type') if meta.get('general.type') in ('model', 'mmproj') else 'unknown',
                        'file_type': num(meta.get('general.file_type')),
                        'tensor_type_ids': {identity(k): num(v) for k, v in (gguf.get('tensor_type_ids') or {}).items()},
                        'size_bytes': num(gguf.get('size_bytes'))})
    embed = []
    for x in r.get('embedding_results', []):
        embed.append({k: num(x.get(k)) for k in ('rep', 'batch_size', 'elapsed_s', 'prompt_tokens')})
        embed[-1]['finite_vectors'] = x.get('finite_vectors') if isinstance(x.get('finite_vectors'), bool) else None
        embed[-1]['dimensions'] = [num(v) for v in x.get('dimensions', [])]
        embed[-1]['error'] = bool(x.get('error'))
    sensors = provenance.get('amd_sensors') or {}
    fields = (r.get('telemetry_summary') or {}).get('fields') or {}
    # Only selected aggregate fields; disk/private system inventory stays local.
    resource_fields = ('memory.total', 'memory.available', 'memory.used', 'cpu_percent', 'swap.used',
                       'sensors.gpus.0.package_power_w', 'sensors.gpus.0.temperature_c',
                       'sensors.gpus.0.utilization_pct', 'sensors.gpus.0.mem_info_gtt_used_b',
                       'sensors.gpus.0.memory_used_vram_b')
    parameters = (ident.get('show') or {}).get('parameters', '')
    controls = {}
    for key in ('num_ctx', 'temperature', 'top_k', 'top_p', 'min_p', 'draft_num_predict'):
        match = re.search(r'^' + key + r'\s+(-?[0-9]+(?:\.[0-9]+)?)\s*$', parameters, re.M)
        if match:
            controls[key] = float(match.group(1))
    return {'id': identity(rid), 'session_id': identity(sid) if sid else None,
            'campaign': identity(campaign_name), 'attempt': identity(path.parent.name),
            'platform': PLATFORM, 'placement': 'unified-memory', 'method': METHOD,
            'model': identity(ident['name']), 'model_digest': identity(ident['digest']),
            'status': 'finished', 'kind': 'embedding' if embedding else 'chat',
            'created': r['attempt_started'], 'context': num(r.get('effective_context')),
            'configured_context': num(r.get('configured_context')),
            'engine': session.get('engine', 'ollama') if embedding else identity(session['engine']),
            'runtime_version': None, 'runner': identity(r['live_readback']['runner']),
            'thinking': request.get('thinking') if request.get('thinking') in ('on', 'off') else None,
            'thinking_effective': (r.get('plan', {}).get('thinking') or {}).get('effective'),
            'native_parameters': controls,
            'reported_quantization': identity(ident['details']['quantization_level']),
            'quantization_evidence': tensors,
            'quantization_note': 'Model tag and coarse metadata are not a verified tensor quantization label. Raw tensor type IDs retained; projector kept separate.',
            'provenance': {k: identity(provenance[k]) for k in ('code_version', 'battery_version', 'fixture_version') if provenance.get(k)},
            'source_report_sha256': digest(path),
            'source_raw_manifest_sha256': hashlib.sha256('\n'.join(sorted(hashes)).encode()).hexdigest(),
            'raw_record_count': len(records), 'metrics': metrics, 'cache_cells': cache,
            'cache_verified': r.get('cache_verified'), 'coverage_ok': r.get('coverage_ok'),
            'cache_skipped_context_sizes': r.get('cache_skipped_context_sizes', []),
            'foreign_resident_requests': num(r.get('foreign_resident_requests')),
            'contention_event_count': len(r.get('contention_events') or []),
            'starting_resident_count': None,
            'hardware_evidence': {'cpu': (sensors.get('cpu') or {}).get('model'),
                                  'os_memory_mib': num((sensors.get('memory') or {}).get('total_mb'))},
            'resources': {k: {stat: num(fields[k].get(stat)) for stat in ('min', 'max', 'mean', 'count')} for k in resource_fields if k in fields},
            'resource_note': 'Whole-system telemetry, not isolated allocation. PPT is package power, not CPU plus GPU or wall power. GTT overlaps RAM; aperture is not dedicated VRAM.',
            'embedding_measurements': embed,
            'embedding_latency_s': {str(batch): med(x['elapsed_s'] for x in embed if x['batch_size'] == batch and not x['error'] and x['finite_vectors']) for batch in (1, 8)} if embedding else {},
            'mtp_acceptance': 'unmeasured',
            'caveat': 'Speed only; no answer-quality ranking. >=256 output tokens (including thinking); tiny/calibration requests excluded. Cache-invalid cells are disclosed, not ranked. Runtime version not recorded.'}


def campaign_export(directory):
    root = Path(directory).resolve()
    ledger = root / 'results/campaign.json'
    d = load(ledger)
    name = identity(root.name)
    runs = []
    selected = set()
    for key, model in sorted(d['models'].items(), key=lambda kv: int(kv[0])):
        if model['status'] != 'finished':
            continue
        path = selected_path(model['report'], root)
        selected.add(path.parent)
        run = export_report(path, name)
        run['starting_resident_count'] = len(d.get('starting_residents') or [])
        runs.append(run)
    attempts = sorted(p for p in (root / 'results').glob('*/attempt-*') if p.is_dir() and p not in selected)
    meta = {'id': name, 'source_ledger_sha256': digest(ledger), 'fingerprint': identity(d['fingerprint']), 'complete': d['complete'],
            'cleanup_ok': d['cleanup_ok'], 'selected_finished_reports': len(runs),
            'unselected_attempts': [identity(p.name) for p in attempts],
            'historical_stop_recorded': bool(d.get('stop_error')),
            'historical_stop_category': 'memory-headroom-guard' if 'MemAvailable below' in (d.get('stop_error') or '') else ('recorded-unspecified' if d.get('stop_error') else None),
            'note': 'Only ledger-selected finished reports ranked. Unselected attempts excluded; historical stop is not the final state. Strict complete and per-cell cache validity preserved.'}
    return meta, runs


def append(snapshot, directories):
    out = copy.deepcopy(snapshot)
    extension = out.setdefault('dyno_campaigns', {'schema_version': 1, 'method': METHOD,
        'hardware': {'id': PLATFORM, 'label': 'AMD Strix Halo · Ryzen AI Max+ 395 · Framework Desktop · 128 GB unified memory',
                     'evidence': 'Platform/product and installed memory supplied by operator; source CPU and OS-visible memory retained per run. No dedicated VRAM claim.'},
        'campaigns': [], 'runs': []})
    for directory in directories:
        meta, runs = campaign_export(directory)
        for target, records in [('campaigns', [meta]), ('runs', runs)]:
            existing = {x['id']: x for x in extension[target]}
            for record in records:
                if record['id'] in existing:
                    if existing[record['id']] != record:
                        raise ValueError('Append-only identity conflict: ' + record['id'])
                else:
                    extension[target].append(record)
                    existing[record['id']] = record
    # Hard invariant: every pre-existing key/value and record remains unchanged.
    for key, value in snapshot.items():
        if key != 'dyno_campaigns' and out[key] != value:
            raise AssertionError('Legacy snapshot changed: ' + key)
    text = json.dumps(extension, allow_nan=False)
    for pattern in (r'/home/', r'/usr/', r'/sys/', r'/proc/', r'https?://', r'localhost', r'127\.0\.0\.1',
                    r'"(?:payload|content|thinking_text|template|modelfile|api_key|journal|response|prompt)"\s*:', r'github_pat_', r'gh[pousr]_[A-Za-z0-9]{20,}'):
        if re.search(pattern, text, re.I):
            raise ValueError('Privacy scan failed')
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', default='data/snapshot.json')
    parser.add_argument('--campaign', action='append', required=True)
    parser.add_argument('--out', default='data/snapshot.json')
    args = parser.parse_args()
    result = append(load(args.snapshot), args.campaign)
    Path(args.out).write_text(json.dumps(result, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    ext = result['dyno_campaigns']
    print(json.dumps({'campaigns': len(ext['campaigns']), 'runs': len(ext['runs']),
                      'chat': sum(x['kind'] == 'chat' for x in ext['runs']),
                      'embedding': sum(x['kind'] == 'embedding' for x in ext['runs']),
                      'legacy_counts_unchanged': result['counts']}))
