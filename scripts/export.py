"""Export a read-only, allowlisted snapshot. No raw prompts, answers, paths or endpoints are copied."""
import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measurements import prefill, resources, pool, median, valid


def public_row(row):
    fields = ('id', 'task_id', 'category', 'tier', 'size', 'rep', 'turn', 'sub', 'score', 'passed',
              'prompt_tokens', 'cached_prompt_tokens', 'completion_tokens', 'reasoning_tokens',
              'ttft_s', 'answer_start_s', 'e2e_s', 'decode_tps', 'prompt_tps', 'finish_reason',
              'target_prompt_tokens', 'draft_tokens', 'accepted_draft_tokens')
    out = {k: row.get(k) for k in fields if k in row}
    out['error'] = bool(row.get('error'))
    out['hit_token_limit'] = bool((row.get('extra') or {}).get('hit_token_limit')) or (row.get('extra') or {}).get('finish_reason') == 'length'
    evidence = (row.get('extra') or {}).get('cache_evidence')
    out['cache_evidence'] = evidence if evidence in ('present', 'unavailable') else 'unavailable'
    return out


def load(path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()] if path.exists() else []


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def numeric_tree(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: numeric_tree(v) for k, v in value.items() if isinstance(v, (dict, int, float, bool)) or v is None}
    return None


def real(model, engine=None, settings=None):
    return bool(model) and engine != 'fake' and not (settings or {}).get('reference') and not re.match(r'^(reference|fake|smoke|test|synthetic)(-|$)', model, re.I)


def date(value):
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat()
    return value


def enrich_measurements(dyno, quality, matrix, sources, runs, qruns, setups, arenas, strata):
    """Attach numeric evidence; never reinterpret a general prompt rate as verified hot/cold prefill."""
    strata_out = dyno / '.hermes-contracts/strata-matrix/run1'
    accepted = {v.get('session'): mode for mode, v in strata.get('dyno', {}).items()}
    by_id = {r['id']: r for r in runs}
    for r in runs:
        src = sources[r['id']]
        m = src['meta']
        paired = []
        pointer = m.get('matrix_prefill_pair')
        if pointer:
            path = Path(pointer)
            if path.resolve().is_relative_to(matrix.resolve()) and path.exists():
                paired = load(path, [])
        src['prefill_rows'] = paired
        r['prefill'] = prefill(paired)
        startup = m.get('startup') or {}
        idle = startup.get('idle_loaded') or {}
        total_ram = idle.get('windows_ram_total_mb')
        total_ram = total_ram / 1024 if valid(total_ram) else None
        start = idle.get('timestamp') or m.get('created_at')
        end = m.get('finished_at')
        samples = lines(src['folder'] / 'samples.jsonl')
        r['resources'] = resources(samples, start, end, total_ram)
        r['resources']['source'] = 'Dyno samples (post-load, including warm-up)'
        if r['id'] in accepted:
            telemetry = lines(strata_out / f"telemetry-{accepted[r['id']]}-dyno.jsonl")
            r['resources'] = resources(telemetry, m.get('created_at'), end, total_ram)
            r['resources']['source'] = 'Strata sidecar (accepted Dyno session window only)'
        # A loaded-idle snapshot is not an unloaded-system baseline; keep that distinction explicit.
        loaded_ram = idle.get('windows_ram_used_mb')
        loaded_ram = loaded_ram / 1024 if valid(loaded_ram) else None
        r['resources']['loaded_idle_ram_gib'] = round(loaded_ram, 3) if loaded_ram is not None else None
        r['resources']['peak_minus_loaded_idle_ram_gib'] = round(r['resources']['ram_peak_gib'] - loaded_ram, 3) if valid(r['resources']['ram_peak_gib']) and loaded_ram is not None else None
        if not r['resources']['samples']:
            recorded = m.get('resources') or {}
            r['resources']['source'] = 'Dyno recorded summary; sample stream unavailable'
            for target, source, divisor in [('ram_peak_gib', 'ram_peak_mb', 1024), ('cpu_mean_w', 'cpu_power_mean_w', 1)]:
                if valid(recorded.get(source)):
                    r['resources'][target] = recorded[source] / divisor
    comparisons = []
    for setup in setups:
        ids = setup['session_ids']
        setup['prefill'] = prefill([row for sid in ids for row in sources[sid]['prefill_rows']])
        setup['resources'] = pool([by_id[sid]['resources'] for sid in ids])
        comparisons.append({**{k: setup.get(k) for k in ('model', 'engine', 'context', 'thinking', 'placement', 'session_ids', 'sessions_in_group', 'created_at', 'decode_short_tps')},
                            'resources': setup['resources'], 'kind': 'Dyno setup'})
    by_setup = {tuple(s['session_ids']): s for s in setups}
    for arena in arenas:
        for model in arena['models']:
            for setup in model['setups'] + ([model['headline']] if model.get('headline') else []):
                evidence = by_setup.get(tuple(setup['session_ids']))
                if evidence:
                    setup['prefill'], setup['resources'] = evidence['prefill'], evidence['resources']
    # Quality resource captures are associated by the exact managed job ID from the matrix log, not by model-name guessing.
    job_telemetry = {}
    for path in matrix.glob('batch-*/progress.json'):
        ledger = load(path, {})
        for model in ledger.get('models', []):
            log = (model.get('quality') or {}).get('log')
            if not log:
                continue
            log = Path(log)
            if not log.resolve().is_relative_to(matrix.resolve()) or not log.exists():
                continue
            ids = set(re.findall(r'"id"\s*:\s*"(quality-[a-z0-9]+)"', log.read_text(encoding='utf-8')))
            telemetry_path = log.parent / 'resources.jsonl'
            if len(ids) == 1 and telemetry_path.exists():
                job_telemetry[ids.pop()] = (model['key'], lines(telemetry_path))
    groups = {}
    original = {}
    for r in qruns:
        m = load(quality / 'results' / r['id'] / 'meta.json')
        original[r['id']] = m
        groups.setdefault(m.get('job_id') or r['id'], []).append(r)
    quality_jobs = []
    for job_id, group in groups.items():
        first = group[0]
        recorded = original[first['id']]
        rows, origin = [], 'Not recorded'
        linked = job_telemetry.get(job_id)
        if linked and linked[0] == first['model']:
            rows, origin = linked[1], 'Matrix telemetry: Quality job load/run/unload'
        if all((original[r['id']].get('model_evidence') or {}).get('source') == 'strata_matrix' for r in group):
            rows = lines(strata_out / 'telemetry-quality.jsonl')
            # Match the known completed job only; a historical repeat must not borrow this capture.
            expected = {rid for step in (strata.get('quality') or {}).get('runs', []) for rid in step.get('results', [])}
            if not expected or not {r['id'] for r in group}.issubset(expected):
                rows = []
            origin = 'Strata telemetry: Quality job load/run/unload' if rows else 'Not recorded'
        window_start, window_end = None, None
        if origin.startswith('Strata telemetry'):
            created = [datetime.datetime.fromisoformat(r['created']).timestamp() for r in group if r.get('created')]
            finished = [datetime.datetime.fromisoformat(r['finished']).timestamp() for r in group if r.get('finished')]
            window_start = min(created) - (strata.get('quality') or {}).get('load_s', 0) - 5 if created else None
            window_end = max(finished) + 5 if finished else None
        summary = resources(rows, window_start, window_end)
        summary['source'] = origin
        states = {r['status'] for r in group}
        state = 'finished' if states.issubset({'finished', 'needs-review', 'reviewed'}) else 'partial'
        actual = recorded.get('actual_settings') or {}
        job = {'id': job_id, 'model': first['model'], 'name': first['name'], 'kind': 'Quality job', 'status': state,
               'placement': first['placement'], 'engine': first['engine'], 'thinking': first['thinking'], 'max_tokens': first['max_tokens'],
               'context': actual.get('context_length'), 'created': min(r['created'] or '' for r in group),
               'session_ids': [r['id'] for r in group], 'suites': [r['suite'] for r in group], 'resources': summary}
        quality_jobs.append(job)
        for r in group:
            r['resource_job_id'] = job_id
    return comparisons, quality_jobs


def snapshot(dyno, quality, matrix):
    dyno, quality, matrix = Path(dyno), Path(quality), Path(matrix)
    os.environ['DYNO_REPO'] = str(dyno)
    os.environ['DYNO_HOME'] = str(dyno / 'data')
    os.environ['DYNO_MATRIX_DIR'] = str(matrix)
    lb = module('public_dyno_leaderboard', dyno / 'dyno/api/leaderboard.py')
    ar = module('public_quality_arena', quality / 'quality-ui/arena.py')
    placements = lb.placement_map(matrix)
    sources = {}
    # Prefer active copies when a historical archive has the same ID.
    for p in sorted((dyno / 'data').rglob('session.json'), key=lambda p: 'archive' not in p.parts):
        meta = load(p)
        if meta and real(meta.get('model'), meta.get('engine')):
            sid = meta.get('id') or p.parent.name
            sources[sid] = {'meta': meta, 'rows': lines(p.parent / 'results.jsonl'), 'archived': 'archive' in p.parts, 'folder': p.parent}
    active = [s for s in sources.values() if not s['archived']]
    setups = lb.build_rows(active, placements)
    # "both" identifies participation, not a guaranteed first-device order (Strata has its own split).
    for s in setups:
        if s['placement'] == 'both':
            s['placement_label'] = 'Both GPUs'
    speed = {'available': True, 'rows': setups, 'failed': lb.failed_sessions(active), 'sessions': len(active)}
    runs = []
    strata_path = dyno / '.hermes-contracts/strata-matrix/run1/results.json'
    strata = load(strata_path, {})
    configs = {d.get('session'): {'name': d.get('config'), 'engine': 'Strata', 'max_context': d.get('max_context')}
               for d in strata.get('dyno', {}).values()}
    config_keys = ('context_length', 'parallel', 'gpu_offload', 'flash_attention', 'use_mmap', 'eval_batch_size', 'kv_cache_quantization')
    for sid, s in sources.items():
        m, rows = s['meta'], s['rows']
        applied = m.get('applied_settings') or {}
        runs.append({'id': sid, 'model': m['model'], 'engine': m.get('engine'), 'status': m.get('status'),
                     'created': date(m.get('created_at')), 'finished': date(m.get('finished_at')), 'archived': s['archived'],
                     'context': (m.get('plan') or {}).get('effective_context') or applied.get('context_length'),
                     'thinking': lb.thinking_of(m), 'placement': placements.get(sid, 'unknown'),
                     'config': configs.get(sid) or {k: applied[k] for k in config_keys if k in applied},
                     'metrics': lb.aggregate(m, rows), 'items': [public_row(r) for r in rows],
                     'has_error': bool(m.get('error'))})
    qruns, excluded = [], 0
    ranked = {r['id'] for r in ar.load_runs(quality / 'results')}
    for p in sorted((quality / 'results').glob('*/meta.json')):
        m = load(p)
        model = m.get('model_key') or m.get('model')
        if not real(model, settings=m.get('settings')):
            excluded += 1
            continue
        g = m.get('generation_controls') or {}
        provenance = m.get('suite_provenance') or {}
        evidence = m.get('model_evidence') or {}
        qruns.append({'id': m.get('id') or p.parent.name, 'model': model,
                      'name': m.get('label') or m.get('display_name') or model, 'suite': m.get('suite'), 'status': m.get('status'),
                      'created': date(m.get('created')), 'finished': date(m.get('finished')),
                      'thinking': g.get('thinking'), 'max_tokens': g.get('max_tokens'),
                      'request_timeout': g.get('request_timeout'), 'wall_seconds': g.get('wall_seconds'),
                      'suite_version': provenance.get('suite_version'), 'selected_ids': m.get('selected_ids'),
                      'comparable_candidate': (m.get('id') or p.parent.name) in ranked,
                      'placement': evidence.get('setup', 'unknown'), 'engine': evidence.get('engine', 'unknown'),
                      'config': evidence.get('config'), 'summary': numeric_tree(m.get('summary') or {}),
                      'items': [public_row(i) for i in lines(p.parent / 'items.jsonl')]})
    arenas = [ar.build(quality / 'results', speed, p['id']) for p in ar.protocols(ar.load_runs(quality / 'results'))]
    resource_comparisons, quality_resource_jobs = enrich_measurements(dyno, quality, matrix, sources, runs, qruns, setups, arenas, strata)
    result = {'schema_version': 2, 'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'hardware': 'RTX 5090 32 GB + RTX 5060 Ti 16 GB; 64 GB system RAM',
              'counts': {'dyno_runs': len(runs), 'quality_runs': len(qruns), 'archived_dyno': sum(r['archived'] for r in runs),
                         'excluded_reference_or_synthetic_quality': excluded},
              'dyno_setups': setups, 'dyno_runs': runs, 'quality_runs': qruns, 'arenas': arenas,
              'resource_comparisons': resource_comparisons, 'quality_resource_jobs': quality_resource_jobs}
    registry = load(Path(__file__).resolve().parents[1] / 'SOURCES.json')
    known_sources = {source['id'] for source in registry['sources']}
    direct = {'coding': ['quality-coding'], 'mcp': ['quality-mcp', 'mcp-sdk'], 'lcb': ['livecodebench-data'],
              'design': ['artifactsbench'], 'screenspot': ['screenspot-v2']}
    for run in qruns:
        ids = list(direct.get(run['suite'], []))
        if run['suite'] == 'benchmarks':
            ids.append('evalscope')
            for item in run['items']:
                identity = item.get('id') or ''
                if identity.startswith('gsm8k'):
                    ids.append('gsm8k')
                elif identity.startswith('simpleqa'):
                    ids.append('simpleqa')
                else:
                    raise ValueError('Unknown benchmark source identity; review source registry before export')
        if not ids or not set(ids).issubset(known_sources):
            raise ValueError('Missing upstream attribution mapping for Quality suite')
        run['source_ids'] = sorted(set(ids))
    result['sources'] = registry['sources']
    result['licensing'] = {'code_spdx': 'MIT', 'original_compilation_spdx': 'CC-BY-4.0', 'copyright': 'Copyright (c) 2026 YashJ',
                           'attribution': 'YashJ, Local LLM Benchmarks (Dyno + Quality), snapshot date in generated_at, https://yashj9.github.io/llm-benchmarks/',
                           'scope': 'Only our original code and original compilation/annotations to the extent applicable rights exist. No relicensing of third-party assets or unprotected facts.',
                           'code_license_url': 'https://github.com/yashj9/llm-benchmarks/blob/main/LICENSE',
                           'data_license_url': 'https://github.com/yashj9/llm-benchmarks/blob/main/data/LICENSE',
                           'sources_url': 'https://github.com/yashj9/llm-benchmarks/blob/main/THIRD_PARTY_NOTICES.md'}
    text = json.dumps(result, allow_nan=False)
    for pattern in (r'[A-Za-z]:[/\\]Users', r'127\.0\.0\.1', r'localhost', r'gh[pousr]_[A-Za-z0-9]{20,}', r'github_pat_', r'"(?:base_url|api_key|authorization|source_hashes)"\s*:', r'"(?:prompt|output)"\s*:\s*"'):
        if re.search(pattern, text, re.I):
            raise ValueError('Privacy scan failed: forbidden pattern ' + pattern)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dyno', required=True)
    parser.add_argument('--quality', required=True)
    parser.add_argument('--matrix', required=True)
    parser.add_argument('--out', default='data/snapshot.json')
    args = parser.parse_args()
    data = snapshot(args.dyno, args.quality, args.matrix)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    print(json.dumps(data['counts']))
