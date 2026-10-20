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


ENABLED = object()  # speculative probe must be present and positively enabled (value is still pinned by the manifest probe)
FULL, TEXT_ONLY = 'full-practical-v1', 'text-only'
NEW_FIELDS = ('speculative_mode', 'quantization', 'weights_total_bytes', 'plan_coverage')
_CTK = {'chat_template_kwargs': {'enable_thinking': True}}

# Explicit approved-engine table. Anything not listed fails closed.
ENGINES = {
    'halogen': dict(version='0.18.4', image_id=None, session_engines=('openai-compat',), legacy=True,
                    thinking_check='halogen-health', extras=[{'enable_thinking': True}]),
    'strata': dict(version='0.1.44.1', image_id=None, session_engines=('openai-compat',), legacy=True,
                   thinking_check='strata-props', extras=[_CTK]),
    'gufo': dict(version='0.18.0', session_engines=('openai-compat',), legacy=False, thinking_check=None,
                 image_id='sha256:4d784ef0043efe8ca07b8e7d519903a14345b068be2b4762c4896eb449704e81',
                 extras=[_CTK, {'enable_thinking': True}]),
    'ollama': dict(version='0.40.5', image_id=None, session_engines=('openai-compat', 'ollama'), legacy=False,
                   thinking_check=None, attached=True,
                   extras=[{'think': True}, _CTK, {'reasoning_effort': 'medium'}]),
}
VERSIONS = {k: v['version'] for k, v in ENGINES.items()}
# Explicit approved-model table: engine x model identity x quantization x speculative mode.
# vision 'verified' needs a True native probe; 'unsupported' needs a manifest declaration with evidence and is
# the ONLY way a text-only plan is accepted. quants=None accepts any safe label (legacy Halogen/Strata).
MODELS = [
    dict(engine='halogen', label='Flash-Next', quants=None, spec='mtp', spec_claim='mtp', vision='verified', coverage=FULL),
    dict(engine='strata', label='Flash-Next', quants=None, spec='mtp', spec_claim=5, vision='verified', coverage=FULL),
    dict(engine='gufo', label='Flash-Next', quants=('UD-Q4_K_XL',), spec='mtp', spec_claim=ENABLED, vision='verified', coverage=FULL,
         served_ids=('gufo-qwen3.8-flash-next-ud-q4_k_xl',)),
    dict(engine='gufo', label='Qwen3.8-27B', quants=('UD-Q4_K_XL',), spec='dflash2', spec_claim=ENABLED, vision='verified', coverage=FULL,
         served_ids=('gufo-qwen3.8-27b-ud-q4_k_xl',)),
    dict(engine='gufo', label='DeepSeek V4 Flash', quants=('IQ2XXS', 'IQ2_XXS'), canonical_quant='IQ2XXS', spec='dspark',
         spec_claim=ENABLED, vision='unsupported', coverage=TEXT_ONLY),
    dict(engine='ollama', label='Qwen3.8-27B', quants=('UD-Q4_K_XL',), spec='mtp', spec_claim=ENABLED, vision='verified',
         coverage=FULL, served_ids=('qwen3.8-27b:ud-q4_k_xl-mmproj-f16-mtp-q4_0-128k',)),
]
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


def readback(manifest_row, evidence, entry):
    if not ENGINES[manifest_row['key']]['legacy']:
        return readback_native(manifest_row, evidence, entry)
    return readback_legacy(manifest_row, evidence, entry)


def readback_legacy(manifest_row, evidence, entry):
    require(not evidence.get('synthetic'), 'Synthetic runtime readback')
    probes = manifest_row['probes']
    needed = {'version', 'identity', 'context', 'thinking', 'mtp'} | ({'vision'} if entry['vision'] == 'verified' else set())
    require(len(probes) == len(needed) and {p['claim'] for p in probes} == needed, 'Missing native probes')
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
    if entry['vision'] == 'verified':
        require(claims['vision'] is True and not manifest_row.get('vision'), 'Vision enablement unproven')
    else:
        declared = manifest_row.get('vision')
        require(isinstance(declared, dict) and declared.get('status') == 'unsupported' and declared.get('evidence')
                and claims.get('vision') is not True, 'Text-only requires a declared unsupported-vision manifest with evidence')
    claim = claims['mtp']
    if entry['spec_claim'] is ENABLED:
        require(claim not in (None, False, 0, '', 'none', 'off'), 'Speculative mode enablement unproven')
    else:
        require(type(claim) is type(entry['spec_claim']) and claim == entry['spec_claim'], 'Speculative mode enablement unproven')
    contract = manifest_row.get('thinking_contract') or {}
    extras = manifest_row.get('request_extras')
    require(extras in ENGINES[manifest_row['key']]['extras'], 'Unapproved thinking request extras')
    expected_contract = {'mode': 'explicit-native-request', 'template_sha256': contract.get('template_sha256'),
                         'request_extras': extras, 'default_enablement': 'not asserted'}
    require(contract.get('mode') == 'explicit-native-request' and
            re.fullmatch(r'[0-9a-f]{64}', contract.get('template_sha256', '')) and
            manifest_row.get('request_extras') == extras and claims['thinking'] == contract['template_sha256']
            and evidence.get('thinking_request_contract') == expected_contract, 'Thinking request contract unproven')
    check = ENGINES[manifest_row['key']]['thinking_check']
    if check == 'halogen-health':
        template = evidence['raw']['/health']['chat_template']
        require(template.get('thinking_control') is True and template.get('probe') == 'passed',
                'Native thinking control unproven')
    elif check == 'strata-props':
        require('enable_thinking' in evidence['raw']['/props']['chat_template'], 'Native thinking control unproven')
    # Raw template/native values are verified, never copied to public output.
    return claims


def _walk(value, path):
    require(isinstance(path, list) and path, 'Missing probe selector')
    for part in path:
        if isinstance(part, dict):
            hits = [x for x in value if isinstance(x, dict) and all(x.get(k) == v for k, v in part['where'].items())] \
                if isinstance(value, list) else []
            require(len(hits) == 1, 'Probe selector must match exactly one item')
            value = hits[0]
        else:
            value = value[part]
    return value


def _compare(value, probe):
    mode, expected = probe.get('compare', 'equals'), probe['expected']
    if mode == 'equals':
        return type(value) is type(expected) and value == expected
    if mode == 'contains':
        return isinstance(value, (list, str)) and expected in value
    if mode == 'regex':
        return isinstance(value, str) and re.search(expected, value, re.M) is not None
    raise ValueError('Unknown probe comparison')


STATIC_KINDS = ('container-args', 'container-log', 'container-exec')
NOTE_TOKENS = ('observed', 'launch-or-log-evidence', 'container-backed', 'canary-backed',
               'configured-not-observed', 'declared-unsupported')
CLAIMS = {'version', 'identity', 'context', 'thinking', 'speculative', 'vision'}


def readback_native(manifest_row, evidence, entry):
    """Gufo/Ollama: every manifest probe needs a matching, passing recorded evidence item (same order).

    Returns {claim: [evidence strengths]} for the public evidence_notes; nothing raw or local is returned.
    """
    require(not evidence.get('synthetic') and not manifest_row.get('synthetic'), 'Synthetic runtime readback')
    key, approved = manifest_row['key'], ENGINES[manifest_row['key']]
    probes, recorded = manifest_row['probes'], evidence['evidence']
    require(isinstance(probes, list) and {p['claim'] for p in probes} == CLAIMS, 'Missing native probes')
    require(isinstance(recorded, list) and len(recorded) == len(probes), 'Missing or extra recorded evidence')
    raw = evidence.get('raw') or {}
    canary_pin = manifest_row.get('canary_evidence') or {}
    by_claim, notes = {}, {}
    for probe, item in zip(probes, recorded):
        kind = probe.get('evidence_type', 'endpoint')
        require(item.get('claim') == probe['claim'] and item.get('evidence_type') == kind,
                'Recorded evidence differs from probe')
        strength = item.get('strength')
        require(strength in NOTE_TOKENS, 'Unknown evidence strength')
        if kind == 'endpoint':
            require(item.get('source') == probe['endpoint'] and probe['endpoint'] in raw, 'Endpoint evidence source mismatch')
            value = _walk(raw[probe['endpoint']], probe['path'])
            if probe.get('transform') == 'sha256':
                value = hashlib.sha256(value.encode('utf-8')).hexdigest()
            else:
                require(probe.get('transform') is None, 'Unknown readback transform')
            require(_compare(value, probe) and item.get('observed') == value
                    and type(item.get('observed')) is type(value), 'Unproven native runtime claim')
            require(strength == probe.get('evidence_strength', 'observed'), 'Evidence strength mismatch')
            observed = value
        elif kind == 'declared':
            vision = manifest_row.get('vision') or {}
            require(probe['claim'] == 'vision' and entry['vision'] == 'unsupported' and probe.get('expected') is False
                    and vision.get('supported') is False and vision.get('basis') and item.get('observed') is False
                    and strength == 'declared-unsupported', 'Text-only requires a declared unsupported-vision manifest')
            observed = False
        elif kind == 'unverifiable-by-endpoint':
            backing = probe.get('backing') or {}
            if backing.get('type') == 'canary':
                # Thinking must be proven by a fresh canary that produced reasoning under the reviewed extras.
                require(probe['claim'] == 'thinking' and strength == 'canary-backed' and item.get('observed') is True
                        and re.fullmatch(r'[0-9a-f]{64}', str(item.get('canary_sha256', '')))
                        and item.get('canary_sha256') == canary_pin.get('sha256')
                        and type(item.get('reasoning_chars')) is int and item['reasoning_chars'] > 0,
                        'Thinking canary evidence missing or unpinned')
                observed = True
            else:
                require(probe['claim'] == 'version' and key == 'gufo' and backing.get('type') == 'container-exec'
                        and backing.get('argv') == ['gufo', '--version'] and strength == 'container-backed'
                        and item.get('source') == 'backing:container-exec', 'Unapproved unverifiable-by-endpoint backing')
                observed = item.get('observed')
        elif kind in STATIC_KINDS:
            require(strength == 'launch-or-log-evidence' and item.get('source') == 'owned container',
                    'Container evidence mismatch')
            observed = item.get('observed')
            if kind == 'container-args':
                require(isinstance(observed, list) and observed == probe['expected'], 'Container argument evidence mismatch')
            else:
                require(kind == 'container-log' and probe.get('compare') == 'regex' and _compare(observed, probe),
                        'Container log evidence mismatch')
        else:
            raise ValueError('Unknown evidence type')
        by_claim.setdefault(probe['claim'], []).append((kind, observed))
        notes.setdefault(probe['claim'], set()).add(strength)

    def of(claim, kind):
        return [o for k, o in by_claim.get(claim, []) if k == kind]

    # Claim semantics are checked against the importer's own approvals, never only against the manifest.
    require(manifest_row['version'] == approved['version'], 'Runtime version does not match the approved version')
    if key == 'gufo':
        found = of('version', 'unverifiable-by-endpoint')
        require(len(found) == 1 and isinstance(found[0], str) and re.fullmatch(
            r'gufo version ' + re.escape(approved['version']) + r' \([0-9a-f]{7,40}\)', found[0]),
            'Runtime version does not match the approved version')
    else:
        require(of('version', 'endpoint') == [approved['version']], 'Runtime version does not match the approved version')
    ident = of('identity', 'endpoint')
    ctx = of('context', 'endpoint')
    require(len(ident) == 1 and len(ctx) == 1 and ctx == [manifest_row['context']] and ctx[0] == 131072,
            'Runtime identity/context mismatch')
    if key == 'gufo':
        require(ident == [manifest_row['model']]
                and [x['id'] for x in (evidence.get('models') or {}).get('data', [])] == [manifest_row['model']],
                'Runtime identity mismatch')
        require(len(of('identity', 'container-args')) == 1
                and ['--served-model-name', manifest_row['model']] in of('identity', 'container-args')[0],
                'Identity launch evidence missing')
        require(len(of('context', 'container-args')) == 1 and ['--context', '131072'] in of('context', 'container-args')[0],
                'Context launch evidence missing')
    else:
        require(re.fullmatch(r'[0-9a-f]{64}', str(manifest_row.get('digest'))) and ident == [manifest_row['digest']],
                'Runtime identity mismatch')
    stated = evidence.get('claims') or {}
    require(stated.get('identity', ident[0]) == ident[0] and stated.get('context', ctx[0]) == ctx[0],
            'Recorded claims disagree with evidence')
    # thinking
    extras = manifest_row.get('request_extras')
    require(extras in approved['extras'], 'Unapproved thinking request extras')
    contract, seen = manifest_row.get('thinking_contract') or {}, evidence.get('thinking_request_contract') or {}
    require(contract.get('mode') == 'explicit-native-request' and seen.get('mode') == 'explicit-native-request'
            and seen.get('request_extras') == extras and seen.get('template_sha256') == contract.get('template_sha256')
            and seen.get('default_enablement') == 'not asserted', 'Thinking request contract unproven')
    require(len(of('thinking', 'unverifiable-by-endpoint')) == 1, 'Thinking canary evidence missing or unpinned')
    if key == 'ollama':
        template, values = contract.get('template_sha256'), of('thinking', 'endpoint')
        require(re.fullmatch(r'[0-9a-f]{64}', template or '') and template in values
                and any(isinstance(v, list) and 'thinking' in v for v in values), 'Native thinking template unproven')
    else:
        require(contract.get('template_sha256') is None, 'Unexpected template pin for a compiled-in formatter')
    # speculative: the recorded evidence must name the approved mode
    mode = entry['spec']
    if key == 'gufo':
        args, logs = of('speculative', 'container-args'), of('speculative', 'container-log')
        require(args and logs, 'Speculative launch and startup-log evidence required')
        flagged = {seq[1] for o in args for seq in o if len(seq) == 2 and seq[0] == '--speculative'}
        named = {m for o in logs for m in re.findall(r'speculative=([A-Za-z0-9_]+)', o)}
        require(flagged == {mode} and named == {mode}, 'Speculative evidence does not name the approved mode')
    else:
        texts = of('speculative', 'endpoint')
        require(mode == 'mtp' and manifest_row.get('draft_num_predict') == 4
                and re.fullmatch(r'[0-9a-f]{64}', str(manifest_row.get('draft_blob_sha256')))
                and len(texts) == 2 and any(re.search(r'^draft_num_predict\s+4$', t, re.M) for t in texts)
                and any(re.search(r'^DRAFT .*sha256-' + manifest_row['draft_blob_sha256'] + r'$', t, re.M) for t in texts)
                and notes['speculative'] == {'configured-not-observed'}, 'Draft model configuration unproven')
    # vision
    if entry['vision'] == 'verified':
        require(not (manifest_row.get('vision') or {}).get('supported') is False and not of('vision', 'declared'),
                'Vision enablement unproven')
        values = of('vision', 'endpoint')
        if key == 'gufo':
            require(values == [['text', 'image']] and of('vision', 'container-args') and of('vision', 'container-log'),
                    'Vision enablement unproven')
        else:
            require(len(values) == 1 and 'vision' in values[0], 'Vision enablement unproven')
    else:
        require(len(of('vision', 'declared')) == 1 and not any(
            isinstance(v, list) and ('image' in v or 'vision' in v) for v in of('vision', 'endpoint')),
            'Text-only requires a declared unsupported-vision manifest')
    return {claim: sorted(v) for claim, v in notes.items()}


def records(native, staged, session, plan, coverage=FULL):
    require(native and len(native) == len(staged), 'Missing or mismatched result records')
    tasks = plan['tasks']
    require(tasks and len({t['id'] for t in tasks}) == len(tasks), 'Invalid task plan')
    # Frozen practical-v1, 128K, thinking-on and verified image support. A
    # truncated plan cannot turn a partial session into a finished score row.
    frozen = {f'{category}-{size}': (category, size, 2 if size <= 16384 else 1)
              for category in ('input', 'retention', 'agentic', 'compaction')
              for size in (4096, 8192, 16384, 32768, 65536, 131072)}
    frozen.update({f'output-{size}': ('output', size, 2) for size in (256, 1024, 4096, 8192)})
    if coverage == FULL:
        frozen.update({f'image-{size}': ('image', size, 2) for size in (512, 1024)})
    else:
        require(coverage == TEXT_ONLY, 'Unknown plan coverage')  # text-only omits ONLY the image category
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


def pinned_weights(engine, config, runtime):
    """Total weight bytes from pinned files (Gufo) or the loaded Ollama blobs; stat only, fail closed."""
    if config.get('files'):
        pinned = {str(Path(f['path'])) for f in config['files']}
        need = {config.get('model_path'), config.get('mmproj_path'), (config.get('speculative') or {}).get('model_path')} - {None}
        require(need <= pinned and all(Path(x).is_file() for x in pinned), 'Pinned weight files missing')
        return sum(Path(x).stat().st_size for x in pinned)
    require(ENGINES[engine].get('attached') and runtime is not None, 'Cannot derive weights_total_bytes')
    text = ''.join(e['observed'] for e in runtime.get('evidence', [])
                   if e.get('claim') == 'speculative' and isinstance(e.get('observed'), str) and e['observed'].startswith('# Modelfile'))
    blobs = re.findall(r'^(?:FROM|DRAFT|PROJECTOR) (/usr/share/ollama/\.ollama/models/blobs/sha256-[0-9a-f]{64})$', text, re.M)
    require(len(blobs) == 3 and len(set(blobs)) == 3 and blobs[1].endswith('sha256-' + str(config.get('draft_blob_sha256')))
            and all(Path(x).is_file() for x in blobs), 'Ollama weight blobs not statable')
    return sum(Path(x).stat().st_size for x in blobs)


def resolve_model(engine, config, bundle, runtime=None):
    """Return (approved model entry, new_contract). Fail closed on anything unlisted."""
    bundle = dict(bundle)
    if 'speculative_mode' in bundle and 'plan_coverage' in bundle and not ENGINES[engine]['legacy']:
        bundle.setdefault('quantization', None)
        bundle.setdefault('weights_total_bytes', None)
        # The wrapper emits null quantization/weights and the short coverage token 'full'. Derive them from the
        # approved allowlist (exactly one entry per engine + speculative mode) and from the pinned files' sizes.
        matches = [m for m in MODELS if m['engine'] == engine and m['spec'] == bundle['speculative_mode']
                   and m['quants'] is not None and len(m['quants']) >= 1]
        if bundle['quantization'] is None and len(matches) == 1:
            bundle['quantization'] = matches[0].get('canonical_quant') or matches[0]['quants'][0]
        if bundle['plan_coverage'] == 'full':
            bundle['plan_coverage'] = FULL
        if bundle['weights_total_bytes'] is None:
            bundle['weights_total_bytes'] = pinned_weights(engine, config, runtime)
    present = [k in bundle for k in NEW_FIELDS]
    require(all(present) or not any(present), 'Partial new-contract staging fields')
    candidates = [m for m in MODELS if m['engine'] == engine]
    if not any(present):
        require(ENGINES[engine]['legacy'], 'Engine requires new-contract staging fields')
        entry = candidates[0]
        require(len(candidates) == 1 and entry['spec'] == 'mtp' and entry['coverage'] == FULL
                and entry['vision'] == 'verified', 'Ambiguous legacy model')
        return entry, False, None
    quant, spec = bundle['quantization'], bundle['speculative_mode']
    require(spec in ('mtp', 'dflash2', 'dspark', 'none'), 'Unknown speculative mode')
    token(quant)
    found = [m for m in candidates if m['spec'] == spec and (m['quants'] is None or quant in m['quants'])]
    require(len(found) == 1, 'Unapproved engine/model/quantization/speculative mode')
    entry = found[0]
    path = config.get('model_path')
    require(path is None or any(q in Path(path).name for q in entry['quants'] or ()) or entry['quants'] is None,
            'Model file does not match the approved quantization')
    for source in (bundle, config):
        require('model_label' not in source or source['model_label'] == entry['label'], 'Model label mismatch')
    require('served_ids' not in entry or config['model'] in entry['served_ids'], 'Unapproved served model identity')
    require(bundle['plan_coverage'] == entry['coverage'], 'Plan coverage does not match the approved model')
    weights = bundle['weights_total_bytes']
    require(type(weights) is int and weights > 0, 'Invalid weights_total_bytes')
    return entry, True, weights


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
    require(configured and len(configured) == len(manifest['engines']) and set(configured) <= set(ENGINES),
            'Unexpected or duplicate manifest engine')
    selected = c['models']
    require(len(selected) == len(configured) and {r['engine'] for r in selected} == set(configured),
            'Missing or duplicate selected engine')
    runs = []
    for link in selected:
        engine = link['engine']
        config = configured[engine]
        require(config['version'] == ENGINES[engine]['version'] and link['status'] == 'finished', 'Unapproved engine/version')
        require(ENGINES[engine]['image_id'] is None or config.get('image_id') == ENGINES[engine]['image_id'],
                'Unapproved engine image digest')
        sid = token(link['session_id'])
        require(re.fullmatch(r'ses-[0-9]{8}-[0-9]{6}-[0-9a-f]{6}', sid), 'Invalid selected session ID')
        folder = root / 'sessions' / sid
        staging_path = pointer(link['website_staging'], root, root / ((config.get('row_id') or engine) + '-website-staging.json'))
        bundle = load(staging_path)
        require(bundle.get('schema') == 'dyno-external-website-staging-v1'
                and bundle.get('synthetic') is False and bundle.get('status') == 'finished'
                and not bundle.get('error'), 'Synthetic/unfinished staging bundle')
        require(bundle['engine'] == engine and bundle['version'] == config['version']
                and bundle['model'] == config['model'] and bundle['session_id'] == sid
                and bundle['context'] == 131072 and bundle.get('native_sampling') is True,
                'Staging identity mismatch')
        runtime_path = root / engine / 'runtime-readback.json'
        runtime = load(runtime_path)
        entry, new_contract, weights_total = resolve_model(engine, config, bundle, runtime)
        require(bundle.get('thinking_request_extras', config.get('request_extras')) == config.get('request_extras')
                or not new_contract, 'Staging thinking extras differ from the reviewed manifest')
        sources = bundle['sources']
        paths = {k: pointer(sources[k], root, expected) for k, expected in {
            'session': folder / 'session.json', 'results': folder / 'results.jsonl',
            'native_samples': folder / 'samples.jsonl', 'host_samples': root / engine / 'host-samples.jsonl',
            'host_summary': folder / 'host-resources.json'}.items()}
        require(pointer(link['session'], root) == paths['session'] and
                pointer(link['resource_summary'], root) == paths['host_summary'], 'Ledger link mismatch')
        session = load(paths['session'])
        require(session['id'] == sid and session['model'] == config['model']
                and session.get('engine') in ENGINES[engine]['session_engines'] and session.get('engine_label') == engine
                and session.get('status') == 'finished' and not session.get('error')
                and session.get('cleanup', {}).get('ok') is True
                and not session.get('provenance', {}).get('offline_mock')
                and not session.get('synthetic'), 'Native session unfinished/synthetic/mismatched')
        require(bundle['battery_version'] == 'practical-v1' and session['provenance']['battery_version'] == 'practical-v1'
                and bundle['fixture_version'] == session['provenance']['fixture_version']
                and session['plan']['battery_version'] == 'practical-v1'
                and session['plan']['effective_context'] == 131072, 'Battery/provenance mismatch')
        cleanup_path = root / engine / 'cleanup.json'
        identity_path = root / engine / 'identity.json'
        evidence_notes = readback(config, runtime, entry)
        require(load(cleanup_path).get('ok') is True, 'Runtime cleanup unproven')
        ident = load(identity_path)
        if ENGINES[engine].get('attached') and new_contract and not config['files']:
            # Attached Ollama pins content digests, not host files: model digest + draft blob digest.
            artifacts = sorted([config['digest'], config['draft_blob_sha256']])
            require(not ident.get('synthetic') and ident.get('commands') and ident.get('files') == []
                    and all(re.fullmatch(r'[0-9a-f]{64}', x) for x in artifacts) and len(set(artifacts)) == 2,
                    'Missing identity artifact evidence')
        else:
            require(not ident.get('synthetic') and ident.get('commands') and ident.get('files') == config['files'] and config['files']
                    and all(re.fullmatch(r'[0-9a-f]{64}', x['sha256']) for x in config['files']),
                    'Missing identity artifact evidence')
            artifacts = sorted(x['sha256'] for x in ident['files'])
        native = lines(paths['results'])
        items = records(native, bundle['records'], session, session['plan'], entry['coverage'])
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
                     'artifact_sha256': artifacts,
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
        if new_contract:  # legacy campaign-003 records stay byte-identical; the UI derives their defaults
            runs[-1].update(model_label=entry['label'],
                            quantization=entry.get('canonical_quant') or (entry['quants'][0] if entry['quants'] else bundle['quantization']),
                            speculative_mode=entry['spec'], plan_coverage=entry['coverage'],
                            vision='verified' if entry['vision'] == 'verified' else 'unsupported-declared',
                            weights_total_bytes=weights_total, evidence_notes=evidence_notes)
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
