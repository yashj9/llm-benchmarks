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


def public_row(row):
    fields = ('id', 'task_id', 'category', 'tier', 'size', 'rep', 'turn', 'sub', 'score', 'passed',
              'prompt_tokens', 'cached_prompt_tokens', 'completion_tokens', 'reasoning_tokens',
              'ttft_s', 'answer_start_s', 'e2e_s', 'decode_tps', 'prompt_tps', 'finish_reason',
              'target_prompt_tokens', 'draft_tokens', 'accepted_draft_tokens')
    out = {k: row.get(k) for k in fields if k in row}
    out['error'] = bool(row.get('error'))
    out['hit_token_limit'] = bool((row.get('extra') or {}).get('hit_token_limit')) or (row.get('extra') or {}).get('finish_reason') == 'length'
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
            sources[sid] = {'meta': meta, 'rows': lines(p.parent / 'results.jsonl'), 'archived': 'archive' in p.parts}
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
    result = {'schema_version': 1, 'generated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'hardware': 'RTX 5090 32 GB + RTX 5060 Ti 16 GB; 64 GB system RAM',
              'counts': {'dyno_runs': len(runs), 'quality_runs': len(qruns), 'archived_dyno': sum(r['archived'] for r in runs),
                         'excluded_reference_or_synthetic_quality': excluded},
              'dyno_setups': setups, 'dyno_runs': runs, 'quality_runs': qruns, 'arenas': arenas}
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
