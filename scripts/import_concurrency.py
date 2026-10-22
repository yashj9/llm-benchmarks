"""Build data/concurrency.json: concurrent-request (1/4/8) speed and resource records. Standard library only; reads saved result files, never runs inference.
Sources: vLLM matrix (tools/vllm-bench/results/conc-matrix-*/summary.json) and Dyno concurrency sessions (dyno/data/concurrency/ses-*/, concurrency-v1 battery).
Privacy: scores/numbers only, no paths, prompts or endpoints."""
import argparse, json, statistics, sys
from pathlib import Path


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 3) if xs else None


def vllm_runs(base: Path):
    runs = []
    for summary in sorted(base.glob('conc-matrix-*/summary.json')):
        data = json.loads(summary.read_text(encoding='utf-8'))
        for placement, labels in data.items():
            for label, res in labels.items():
                if not res.get('started') or len(res.get('windows') or []) < 6:
                    continue  # interrupted attempts (fewer than the 2 inputs x 3 levels) are not published
                windows = []
                for w in res['windows']:
                    rows = w.get('rows') or []
                    t = w.get('telemetry') or {}
                    g0, g1 = t.get('gpu0') or {}, t.get('gpu1') or {}
                    windows.append({
                        'input_tokens': w['input_tokens'], 'concurrency': w['concurrency'], 'rounds': len(rows),
                        'agg_output_tps': mean(r.get('agg_output_tps') for r in rows), 'per_request_decode_tps': mean(r.get('per_req_decode_median_tps') for r in rows),
                        'per_request_decode_min_tps': mean(r.get('per_req_decode_min_tps') for r in rows),
                        'ttft_median_s': mean(r.get('ttft_median_s') for r in rows), 'ttft_max_s': mean(r.get('ttft_max_s') for r in rows),
                        'draft_accept_rate': mean(r.get('draft_accept_rate') for r in rows), 'errors': sum(len(r.get('errors') or []) for r in rows),
                        'resources': {'gpu0_util_pct': g0.get('util_avg'), 'gpu1_util_pct': g1.get('util_avg'), 'gpu0_vram_gib': round(g0['vram_max_mib'] / 1024, 2) if g0.get('vram_max_mib') else None,
                                      'gpu1_vram_gib': round(g1['vram_max_mib'] / 1024, 2) if g1.get('vram_max_mib') else None, 'gpu0_power_w': g0.get('power_avg_w'), 'gpu1_power_w': g1.get('power_avg_w'),
                                      'cpu_pct': t.get('cpu_avg'), 'ram_peak_gib': t.get('ram_max_gib')}})
                runs.append({'id': f"vllm-{summary.parent.name}-{label}", 'engine': 'vllm', 'engine_version': '0.32.0', 'model': 'qwen3.8-27b-nvfp4',
                             'model_format': 'NVFP4 (native compressed-tensors safetensors, MTP head)', 'placement': 'both', 'context': 131072, 'thinking': 'n/a (raw completions)',
                             'speculative': 'MTP, 1 draft token', 'configuration': label, 'startup_s': res.get('load_s'), 'output_tokens': 256, 'windows': windows,
                             'notes': ['Pipeline split 58/6 layers across RTX 5090 and RTX 5060 Ti; 128K context; FP8 KV cache; CUDA graphs.',
                                       'Single-GPU placements do not fit this 27.6 GB checkpoint: 5060 Ti alone (16 GB) cannot hold it; 5090 alone has no room for KV cache at 128K (tried CPU offload up to 11 GB).']})
    return runs


def dyno_runs(base: Path, include_smoke: bool):
    runs = []
    for folder in sorted(base.glob('ses-*')):
        meta_path = folder / 'session.json'
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        plan = meta.get('concurrency_plan') or {}
        if meta.get('status') != 'finished' or not plan or (not include_smoke and max(plan.get('inputs') or [0]) < 16384):
            continue
        by = {}
        for line in (folder / 'results.jsonl').read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            if r.get('kind') == 'concurrency-window':
                by.setdefault((r['input_target'], r['concurrency']), []).append(r)
        windows = []
        for (inp, conc), rows in sorted(by.items()):
            res = [r.get('resources') or {} for r in rows]
            windows.append({'input_tokens': inp, 'concurrency': conc, 'rounds': len(rows),
                            'agg_output_tps': mean(r.get('agg_output_tps') for r in rows), 'per_request_decode_tps': mean(r.get('per_req_decode_median_tps') for r in rows),
                            'per_request_decode_min_tps': mean(r.get('per_req_decode_min_tps') for r in rows), 'ttft_median_s': mean(r.get('ttft_median_s') for r in rows),
                            'ttft_max_s': mean(r.get('ttft_max_s') for r in rows), 'draft_accept_rate': mean(r.get('draft_accept_rate') for r in rows),
                            'errors': sum(len(r.get('errors') or []) for r in rows),
                            'resources': {'vram_peak_gib_all_gpus': round(max((x.get('vram_peak_mib') or 0 for x in res), default=0) / 1024, 2) or None, 'ram_peak_gib': round(max((x.get('ram_peak_mb') or 0 for x in res), default=0) / 1024, 2) or None}})
        applied = meta.get('applied_settings') or {}
        notes = [n for n in meta.get('notes', []) if 'capped' in n or 'Skipped' in n]
        notes.append(f"Saved context raised to {applied.get('context_length')} tokens total for this test so every one of the {applied.get('parallel')} slots holds the 16K input ({plan.get('slot_context')} per slot); the engine shares the context across slots.")
        notes.append('VRAM is the peak of all GPUs combined (Dyno sampler); per-GPU utilisation and power were not split for these runs.')
        runs.append({'id': meta['id'], 'engine': meta.get('engine'), 'model': meta.get('model'), 'model_format': 'GGUF from the shared library (no copy)', 'placement': 'unknown',
                     'context': applied.get('context_length'), 'parallel_slots': applied.get('parallel'), 'slot_context': plan.get('slot_context'), 'output_tokens': plan.get('max_tokens'),
                     'thinking': 'on', 'speculative': 'MTP as saved in the engine', 'configuration': f"parallel {applied.get('parallel')}, {applied.get('context_length')} total context", 'windows': windows, 'notes': notes})
    return runs


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--vllm', default='C:/Users/YashJ/AIWorkSpace/tools/vllm-bench/results')
    ap.add_argument('--dyno-concurrency', default='C:/Users/YashJ/AIWorkSpace/dyno/data/concurrency')
    ap.add_argument('--ledger', help='JSON file {session_id: placement} for Dyno concurrency sessions')
    ap.add_argument('--out', default='data/concurrency.json')
    ap.add_argument('--include-smoke', action='store_true')
    a = ap.parse_args()
    runs = vllm_runs(Path(a.vllm)) + (dyno_runs(Path(a.dyno_concurrency), a.include_smoke) if Path(a.dyno_concurrency).exists() else [])
    placements = {}
    for pj in sorted(Path(a.dyno_concurrency).parents[2].glob('tools/lmstudio-matrix/batch-*concurrency*/progress.json')):
        for m in json.loads(pj.read_text(encoding='utf-8')).get('models', []):
            for r in m.get('rounds', []):
                if r.get('session') and r.get('status') == 'finished': placements[r['session']] = r.get('mode') or m.get('mode')
    if a.ledger:
        placements.update(json.loads(Path(a.ledger).read_text()))
    if placements:
        for r in runs:
            r['placement'] = placements.get(r['id'], r['placement'])
    for r in runs:
        peak = max(((w.get('resources') or {}).get('vram_peak_gib_all_gpus') or 0 for w in r['windows']), default=0)
        if r['engine'] == 'lmstudio' and r['placement'] == '5090' and peak >= 30:
            r.setdefault('notes', []).append(f'VRAM peaked at {peak:.1f} GiB of the 32 GiB on the 5090 at this context and 8 slots; the driver may have spilled part of the load to system memory, so treat absolute numbers as conservative.')
    doc = {'schema_version': 1, 'battery_version': 'concurrency-v1',
           'method': 'N simultaneous streaming chat requests (1, 4, 8) at 1K and 16K input tokens, 256 output tokens, 2 rounds per cell after an unrecorded warm-up. Unique prompts per request, so no prefix sharing. Total tok/s = all output tokens / window wall time. Speed only; no quality scoring.',
           'runs': runs}
    text = json.dumps(doc, separators=(',', ':'), allow_nan=False)
    for bad in ('C:\\', 'C:/Users', '127.0.0.1', 'localhost'):
        assert bad not in text, 'privacy scan: ' + bad
    Path(a.out).write_text(text, encoding='utf-8')
    print(len(runs), 'runs written to', a.out)
