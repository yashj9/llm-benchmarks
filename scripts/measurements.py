"""Numeric, scores-only measurement summaries."""
import math
import statistics


def valid(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def median(values):
    values = [v for v in values if valid(v)]
    return round(statistics.median(values), 3) if values else None


def prefill(rows):
    cold = [r for r in rows if r.get('label') == 'fresh_prefix' and not r.get('error') and valid(r.get('prompt_tps')) and r['prompt_tps'] > 0]
    hot = [r for r in rows if r.get('label') == 'repeat_same_prefix' and not r.get('error') and valid(r.get('prompt_tps')) and r['prompt_tps'] > 0]
    return {'cold_tps': median([r['prompt_tps'] for r in cold]), 'hot_tps': median([r['prompt_tps'] for r in hot]),
            'cold_ttft_s': median([r.get('ttft_s') for r in cold]), 'hot_ttft_s': median([r.get('ttft_s') for r in hot]),
            'prompt_tokens': median([r.get('prompt_tokens') for r in cold + hot]),
            'cold_n': len(cold), 'hot_n': len(hot), 'hot_cache_verified': bool(hot) and all(r.get('cache_verified') for r in hot),
            'method': 'client prompt tokens / TTFT; fresh-prefix then identical-prefix repeat',
            'scope': 'paired 260-record probe; not model-load cold start'}


def normalize(row):
    """Normalize known telemetry layouts, never retaining process lists or identifiers."""
    out = {'t': row.get('timestamp', row.get('time', row.get('t')))}
    if 'timestamp' in row:
        out['ram_used_gib'] = row.get('windows_ram_used_mb') / 1024 if valid(row.get('windows_ram_used_mb')) else None
        cpu = (row.get('lhm') or {}).get('cpu') or {}
        out.update(cpu_w=cpu.get('package_power_w'), cpu_pct=cpu.get('utilization_pct'), cpu_temp_c=cpu.get('temperature_c'))
        for i, name in enumerate(('5090', '5060')):
            g = next((g for g in (row.get('lhm') or {}).get('gpus', []) if name in g.get('name', '')), {})
            memory = (row.get('gpu_used_mib') or [])
            out.update({f'gpu{i}_vram_gib': memory[i] / 1024 if len(memory) > i and valid(memory[i]) else None,
                        f'gpu{i}_w': g.get('power_w'), f'gpu{i}_pct': g.get('utilization_pct'), f'gpu{i}_temp_c': g.get('temperature_c')})
    elif 'gpu_csv' in row:
        for key, source in [('ram_used_gib', 'ram_used_bytes'), ('ram_avail_gib', 'ram_available_bytes')]:
            out[key] = row[source] / 2**30 if valid(row.get(source)) else None
        out['cpu_pct'] = row.get('cpu_pct')
        for key, source in [('disk_read_mbs', 'disk_read_bytes_s'), ('disk_write_mbs', 'disk_write_bytes_s')]:
            out[key] = row[source] / 2**20 if valid(row.get(source)) else None
        for line in row['gpu_csv'].splitlines():
            values = [s.strip() for s in line.split(',')]
            if len(values) != 6 or values[0] not in ('0', '1'):
                continue
            i = values[0]
            for index, key, divisor in [(1, 'vram_gib', 1024), (3, 'pct', 1), (4, 'w', 1), (5, 'temp_c', 1)]:
                try:
                    out[f'gpu{i}_{key}'] = float(values[index]) / divisor
                except ValueError:
                    out[f'gpu{i}_{key}'] = None
    else:
        for key in ('ram_used_gib', 'ram_avail_gib', 'swap_used_gib', 'cpu_pct', 'disk_read_mbs', 'disk_write_mbs'):
            out[key] = row.get(key)
        out.update(cpu_w=row.get('cpu_Powers_Package'), cpu_temp_c=row.get('cpu_Temperatures_Core_(Tctl_Tdie)'))
        for i in (0, 1):
            g = row.get(f'gpu{i}') or {}
            out.update({f'gpu{i}_vram_gib': g['vram_mib'] / 1024 if valid(g.get('vram_mib')) else None,
                        f'gpu{i}_w': g.get('power_w'), f'gpu{i}_pct': g.get('util'), f'gpu{i}_temp_c': g.get('temp_c')})
    powers = [out.get(k) for k in ('cpu_w', 'gpu0_w', 'gpu1_w')]
    out['cpu_gpu_w'] = sum(powers) if all(valid(v) for v in powers) else None
    return out


def resources(rows, start=None, end=None, ram_total_gib=None):
    rows = [normalize(r) for r in rows]
    rows = [r for r in rows if valid(r['t']) and (start is None or r['t'] >= start) and (end is None or r['t'] <= end)]
    if ram_total_gib is not None:
        for r in rows:
            if r.get('ram_avail_gib') is None and valid(r.get('ram_used_gib')):
                r['ram_avail_gib'] = ram_total_gib - r['ram_used_gib']
    fields = {'ram_mean_gib': ('ram_used_gib', 'mean'), 'ram_peak_gib': ('ram_used_gib', 'max'),
              'ram_available_min_gib': ('ram_avail_gib', 'min'), 'swap_peak_gib': ('swap_used_gib', 'max'),
              'cpu_mean_pct': ('cpu_pct', 'mean'), 'cpu_mean_w': ('cpu_w', 'mean'),
              'cpu_temp_peak_c': ('cpu_temp_c', 'max'), 'cpu_gpu_mean_w': ('cpu_gpu_w', 'mean'),
              'disk_read_mean_mbs': ('disk_read_mbs', 'mean'), 'disk_write_mean_mbs': ('disk_write_mbs', 'mean')}
    for i in (0, 1):
        fields.update({f'gpu{i}_vram_peak_gib': (f'gpu{i}_vram_gib', 'max'), f'gpu{i}_mean_w': (f'gpu{i}_w', 'mean'),
                       f'gpu{i}_mean_pct': (f'gpu{i}_pct', 'mean'), f'gpu{i}_temp_peak_c': (f'gpu{i}_temp_c', 'max')})
    out = {'samples': len(rows), 'duration_s': round(rows[-1]['t'] - rows[0]['t'], 1) if rows else None,
           'scope': 'whole-system samples; includes background activity; not isolated model power or wall power'}
    for target, (source, operation) in fields.items():
        values = [r[source] for r in rows if valid(r.get(source))]
        f = statistics.mean if operation == 'mean' else max if operation == 'max' else min
        out[target] = round(f(values), 3) if values else None
    return out


def pool(summaries):
    """Maximum observed peaks, minimum headroom, medians of session means; never pool unequal workloads as samples."""
    out = {'sessions': len(summaries), 'measured_sessions': sum(bool(r.get('samples')) for r in summaries),
           'samples': sum(r.get('samples') or 0 for r in summaries),
           'scope': 'whole-system; maximum peaks/minimum headroom; median of session means; compare equal workloads only'}
    keys = {k for r in summaries for k in r if k not in out and k not in ('duration_s', 'scope')}
    for key in keys:
        values = [r.get(key) for r in summaries if valid(r.get(key))]
        operation = max if '_peak_' in key else min if '_min_' in key else statistics.median
        out[key] = round(operation(values), 3) if values else None
    return out
