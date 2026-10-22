globalThis.BenchmarkUI = {
  escape(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); },
  externalRows(data) { return data.external_dyno?.runs || []; },
  // Records published before the engine-generalised contract (campaign-003) carry no model/quantization/spec fields.
  // Defaults are derived only for facts that contract proved (verified MTP probes, full plan, verified vision);
  // quantization stays unrecorded rather than inferred.
  externalMeta(r) {
    const legacy = r.speculative_mode == null;
    const known = {'halogen-qwen3.8-flash-next': 'Flash-Next', 'qwen3.8-flash-next-unsloth-ud-iq4_xs': 'Flash-Next'};
    return {engine: r.engine ?? 'unknown', label: r.model_label ?? (legacy ? known[r.model] : null) ?? r.model ?? 'unknown',
      quantization: r.quantization ?? null, spec: r.speculative_mode ?? (legacy && ['halogen', 'strata'].includes(r.engine) ? 'mtp' : null),
      coverage: r.plan_coverage ?? (legacy ? 'full-practical-v1' : null),
      vision: r.vision ?? (legacy ? 'verified' : null), legacy};
  },
  engineBadge(engine) {
    const known = ['halogen', 'strata', 'gufo', 'ollama'].includes(engine) ? engine : 'unknown';  // class names never come from data
    return `<span class="tag engine engine-${known}">${this.escape(engine)}</span>`;
  },
  coverageBadge(meta) {
    return meta.coverage === 'text-only'
      ? '<span class="tag warn coverage-text-only">TEXT-ONLY · no image tasks · not comparable to full-coverage scores</span>'
      : meta.coverage === 'full-practical-v1' ? '<span class="tag good coverage-full">Full practical-v1 (text + image)</span>'
      : '<span class="tag neutral">Coverage unrecorded</span>';
  },
  externalRowHTML(r, i, quality = false) {
    const e = this.escape;
    const meta = this.externalMeta(r);
    const n = v => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: 2});
    const stats = r.resources?.metrics || {};
    const ram = stats.ram_used_bytes?.max;
    const ppt = Object.entries(stats).filter(([k]) => k.endsWith('.package_power_w')).map(([k,v]) => `${e(k.split('.')[0])}: ${n(v.mean)} W`).join('<br>') || '—';
    const q = r.quality;
    const metric = quality ? `${n(q.mean_score == null ? null : q.mean_score * 100)}${q.mean_score == null ? '' : '%'}<span class="sub">${n(q.scored_rows)} / ${n(q.total_rows)} scored rows${meta.coverage === 'text-only' ? ' · text-only task set' : ''}</span>` : `${n(r.metrics.sustained_decode_tps)}<span class="sub">${n(r.metrics.sustained_n)} requests ≥256 output tokens</span>`;
    const extra = quality ? Object.entries(q.by_category).map(([k,v]) => `${e(k)}: ${n(v.mean_score == null ? null : v.mean_score * 100)}${v.mean_score == null ? '' : '%'}`).join('<br>') + (meta.coverage === 'text-only' ? '<br><span class="sub">image: not run (text-only)</span>' : '') : '— / —<span class="sub">Native prefill / MTP acceptance unmeasured</span>';
    const vision = meta.vision === 'unsupported-declared' ? 'Vision: unsupported (declared)' : meta.vision === 'verified' ? 'Vision verified' : 'Vision unrecorded';
    const cells = [`<span class="model">${e(meta.label)}</span><span class="sub">${e(r.model)}<br>${e(r.id)}</span>${this.coverageBadge(meta)}`,
      `${this.engineBadge(meta.engine)} ${e(r.runtime_version)}<span class="sub">AMD Strix Halo · unified memory<br>${n(r.context)} configured tokens · thinking ${e(r.thinking)}<br>${e(vision)}</span>`,
      e(meta.quantization ?? 'not recorded'),
      meta.spec ? e(meta.spec) : 'not recorded',
      metric, extra,
      `${n(ram == null ? null : ram / 1024 ** 3)} GiB<span class="sub">Host-wide RAM peak; not RAM + GTT</span>`,
      `${ppt}<span class="sub">Host-wide shared package power; not wall power</span>`,
      `${e(r.status)}<span class="sub">Strict evidence ${r.coverage.strict_evidence_complete ? 'complete' : 'incomplete'} · cache / near-window occupancy unverified</span><button class="details" data-detail="${i}">Details ↗</button>`];
    return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
  },
  // Group rows by model label (same model across engines). Rows keep their index in `rows` for Details.
  externalTableHTML(rows, quality, group) {
    const e = this.escape;
    let last = null, out = '';
    rows.forEach((r, i) => {
      const meta = this.externalMeta(r);
      if (group && meta.label !== last) {
        const same = rows.filter(x => this.externalMeta(x).label === meta.label);
        const engines = [...new Set(same.map(x => this.externalMeta(x).engine))];
        out += `<tr class="group"><th scope="rowgroup" colspan="9">Model: ${e(meta.label)} · ${same.length} run${same.length === 1 ? '' : 's'} on ${engines.map(x => e(x)).join(', ')} · compare only rows with identical quantization, speculative mode and coverage</th></tr>`;
        last = meta.label;
      }
      out += this.externalRowHTML(r, i, quality);
    });
    return out;
  },
  // ---- model families (same GGUF on several engines) and engine labels, loaded from data/model_families.json
  families: {byId: {}, byModel: {}, engines: {}},
  setFamilies(doc) {
    const f = {byId: {}, byModel: {}, engines: doc?.engines || {}};
    for (const fam of doc?.families || []) {
      f.byId[fam.id] = fam;
      for (const [engine, ids] of Object.entries(fam.ids || {})) for (const id of ids) f.byModel[`${engine}|${id}`] = fam;
    }
    this.families = f;
  },
  familyOf(r) { return r.family_id ? this.families.byId[r.family_id] : this.families.byModel[`${r.engine}|${r.model}`] || null; },
  modelKey(r) { return this.familyOf(r)?.id ?? this.externalMeta(r).label; },
  modelLabel(key) { return this.families.byId[key]?.label ?? key; },
  engineLabel(e) { return this.families.engines[e]?.label ?? e ?? 'unknown'; },
  modelFacets(rowSets) {
    const keys = new Set();
    for (const rows of rowSets) for (const r of rows) keys.add(this.modelKey(r));
    return [...keys].filter(Boolean).sort((a, b) => this.modelLabel(a).localeCompare(this.modelLabel(b)));
  },
  engineFacets(rowSets) {
    const keys = new Set();
    for (const rows of rowSets) for (const r of rows) if (r.engine) keys.add(r.engine);
    return [...keys].sort((a, b) => this.engineLabel(a).localeCompare(this.engineLabel(b)));
  },
  // ---- engine comparison: one row per (model family, context, thinking, GPU setup) with a cell per engine
  ENGINE_ORDER: ['lmstudio', 'ollama', 'unsloth', 'vllm', 'openai-compat'],
  PLACEMENT_ORDER: ['5090', 'both-5090first', 'both', 'both-auto', '5060ti', 'unknown'],
  PLACEMENT_LABEL: {'5090': '5090 only', 'both-5090first': 'Split · 5090 first', both: 'Split · 5060 Ti first', 'both-auto': "Both GPUs · engine's own split", '5060ti': '5060 Ti only', unknown: 'Unknown placement'},
  compareRows(setups) {
    const groups = new Map();
    for (const s of setups || []) {
      const fam = this.familyOf(s);
      if (!fam || s.decode_short_tps == null) continue;
      const key = [fam.id, s.context, s.thinking, s.placement].join('|');
      const g = groups.get(key) || {id: key, family_id: fam.id, model: fam.label, context: s.context, thinking: s.thinking, placement: s.placement, cells: {}};
      const prev = g.cells[s.engine];
      if (!prev || (s.sessions_in_group ?? 0) > (prev.sessions_in_group ?? 0)) g.cells[s.engine] = s;
      groups.set(key, g);
    }
    const order = p => { const i = this.PLACEMENT_ORDER.indexOf(p); return i < 0 ? 9 : i; };
    return [...groups.values()].filter(g => Object.keys(g.cells).length >= 2)
      .sort((a, b) => a.model.localeCompare(b.model) || order(a.placement) - order(b.placement) || (b.context ?? 0) - (a.context ?? 0));
  },
  compareRowHTML(g, i, button) {
    const e = this.escape, n = (v, d = 1) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
    const engines = this.ENGINE_ORDER.filter(x => g.cells[x]);
    const speeds = engines.map(x => g.cells[x].decode_short_tps);
    const best = Math.max(...speeds);
    const place = this.PLACEMENT_LABEL[g.placement] || g.placement;
    const ctx = g.context == null ? 'unknown' : `${n(g.context / 1024, 0)}K`;
    const cell = x => {
      const s = g.cells[x];
      if (!s) return '<span class="sub">not run</span>';
      const win = s.decode_short_tps === best;
      const gap = win ? '' : ` <span class="tag neutral">−${n((1 - s.decode_short_tps / best) * 100, 0)}%</span>`;
      return `<span class="num">${n(s.decode_short_tps, 0)} tok/s</span>${win && engines.length > 1 ? ' <span class="tag good">fastest</span>' : gap}` +
        `<span class="sub">long ${n(s.decode_long_tps, 0)} · TTFT ${n(s.ttft_short_s, 2)} s${s.draft_acceptance != null ? ` · MTP ${n(s.draft_acceptance * 100, 0)}%` : ''}<br>` +
        `reliability ${s.reliability == null ? '—' : n(s.reliability * 100, 0) + '%'} · VRAM ${s.peak_vram_mib == null ? '—' : n(s.peak_vram_mib / 1024, 1) + ' GiB'} · ${s.sessions_in_group} run${s.sessions_in_group === 1 ? '' : 's'}</span>`;
    };
    const winner = engines.find(x => g.cells[x].decode_short_tps === best);
    const second = Math.max(...speeds.filter(v => v !== best), 0);
    return '<tr>' + [`<span class="model">${e(g.model)}</span><span class="sub">${e(place)} · ${ctx} context · thinking ${e(g.thinking)}</span>`,
      ...['lmstudio', 'ollama', 'unsloth', 'vllm', 'openai-compat'].filter(x => engines.includes(x) || ['lmstudio', 'ollama', 'unsloth'].includes(x)).map(cell),
      `${e(this.engineLabel(winner))}<span class="sub">${second ? `+${n((best / second - 1) * 100, 0)}% over next best` : ''}</span>${button}`].map((c, j) => `<td${j === 0 ? ' class="model"' : ''}>${c}</td>`).join('') + '</tr>';
  },
  compareHeads(rows) {
    const used = new Set(rows.flatMap(g => Object.keys(g.cells)));
    const cols = ['lmstudio', 'ollama', 'unsloth', 'vllm', 'openai-compat'].filter(x => used.has(x) || ['lmstudio', 'ollama', 'unsloth'].includes(x));
    return ['Model / GPU setup / context', ...cols.map(x => this.engineLabel(x) + ' · short-prompt decode'), 'Fastest'];
  },

  // ---- hardware views: "what can my GPU run?" and "compare GPUs for one model"
  gpuMemGiB(s) {
    const r = s.resources || {};
    const per = s.placement === '5090' ? r.gpu0_vram_peak_gib : s.placement === '5060ti' ? r.gpu1_vram_peak_gib : null;
    if (per != null) return per;
    return s.peak_vram_mib == null ? null : s.peak_vram_mib / 1024;
  },
  finderRows(setups, o = {}) {
    const best = new Map();
    for (const s of setups || []) {
      const fam = this.familyOf(s);
      if (!fam || s.decode_short_tps == null || (o.engine && s.engine !== o.engine)) continue;
      const key = fam.id + '|' + s.placement;
      const g = best.get(key) || {id: key, family_id: fam.id, model: fam.label, family: fam, placement: s.placement, options: []};
      g.options.push(s); best.set(key, g);
    }
    const budget = o.vram ? Number(o.vram) : null;
    const rows = [...best.values()].map(g => {
      g.options.sort((a, b) => b.decode_short_tps - a.decode_short_tps);
      const top = g.options[0];
      return {...g, best: top, engine: top.engine, context: top.context, mem: this.gpuMemGiB(top)};
    }).filter(g => budget == null || (g.mem != null && g.mem <= budget));
    return rows.sort((a, b) => b.best.decode_short_tps - a.best.decode_short_tps);
  },
  finderHeads() { return ['Model', 'Measured on', 'Decode speed (short prompt)', 'Fastest engine / alternatives', 'GPU memory / RAM at peak', 'Quality · reliability']; },
  finderRowHTML(g) {
    const e = this.escape, n = (v, d = 1) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
    const s = g.best, fam = g.family || {};
    const place = this.PLACEMENT_LABEL[g.placement] || g.placement;
    const others = g.options.slice(1).map(o => `${e(this.engineLabel(o.engine))} ${n(o.decode_short_tps, 0)}`).join(' · ');
    const tags = [fam.params, fam.vision ? 'vision' : null, fam.mtp ? 'MTP' : null].filter(Boolean).map(t => `<span class="tag neutral">${e(t)}</span>`).join(' ');
    const mem = g.mem == null ? '—' : `${n(g.mem, 1)} GiB`;
    return '<tr>' + [
      `<span class="model">${e(g.model)}</span><span class="sub">${tags}</span>`,
      `${e(place)}<span class="sub">${n((g.context ?? 0) / 1024, 0)}K context · thinking ${e(s.thinking ?? '—')}</span>`,
      `<span class="num">${n(s.decode_short_tps, 0)} tok/s</span><span class="sub">long prompts ${n(s.decode_long_tps, 0)} · first token ${n(s.ttft_short_s, 2)} s${s.prefill_long_tps ? ` · prefill ${n(s.prefill_long_tps, 0)} tok/s` : ''}</span>`,
      `${e(this.engineLabel(s.engine))}<span class="sub">${others ? 'also: ' + others : 'only engine measured'}</span>`,
      `${mem}<span class="sub">RAM ${s.peak_ram_mb == null ? '—' : n(s.peak_ram_mb / 1024, 0) + ' GiB'} · whole-system peak</span>`,
      `${s.mean_score == null ? '—' : n(s.mean_score * 100, 0) + '%'}<span class="sub">reliability ${s.reliability == null ? '—' : n(s.reliability * 100, 0) + '%'}</span>`,
    ].map((c, j) => `<td${j === 0 ? ' class="model"' : ''}>${c}</td>`).join('') + '</tr>';
  },
  gpuRows(setups, o = {}) {
    const fams = new Map();
    for (const s of setups || []) {
      const fam = this.familyOf(s);
      if (!fam || s.decode_short_tps == null || (o.engine && s.engine !== o.engine)) continue;
      const cls = s.placement.startsWith('both') ? 'both' : s.placement;
      if (!['5090', '5060ti', 'both'].includes(cls)) continue;
      const g = fams.get(fam.id) || {id: fam.id, family_id: fam.id, model: fam.label, family: fam, cells: {}};
      const cur = g.cells[cls];
      if (!cur || s.decode_short_tps > cur.decode_short_tps) g.cells[cls] = s;
      fams.set(fam.id, g);
    }
    return [...fams.values()].filter(g => Object.keys(g.cells).length >= 2).sort((a, b) => a.model.localeCompare(b.model));
  },
  gpuHeads() { return ['Model', 'RTX 5060 Ti only (16 GB)', 'RTX 5090 only (32 GB)', 'Both GPUs (fastest split measured)', 'What the 5090 adds']; },
  gpuRowHTML(g) {
    const e = this.escape, n = (v, d = 1) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
    const cell = (s) => !s ? '<span class="sub">not measured (model does not fit, or not run)</span>' :
      `<span class="num">${n(s.decode_short_tps, 0)} tok/s</span><span class="sub">${e(this.engineLabel(s.engine))} · ${e(this.PLACEMENT_LABEL[s.placement] || s.placement)} · first token ${n(s.ttft_short_s, 2)} s<br>GPU memory ${n(this.gpuMemGiB(s), 1)} GiB · ${n((s.context ?? 0) / 1024, 0)}K context</span>`;
    const c = g.cells, small = c['5060ti'], big = c['5090'];
    const add = small && big ? `<span class="num">${n(big.decode_short_tps / small.decode_short_tps, 1)}× faster</span><span class="sub">than the 5060 Ti${big.ttft_short_s && small.ttft_short_s ? ` · first token ${n(small.ttft_short_s / big.ttft_short_s, 1)}× sooner` : ''}</span>` :
      big && !small ? '<span class="sub">needs more than 16 GB: only runs on the 5090 or split</span>' : '<span class="sub">—</span>';
    return '<tr>' + [`<span class="model">${e(g.model)}</span><span class="sub">${e(g.family.params || '')}</span>`, cell(c['5060ti']), cell(c['5090']), cell(c.both), add]
      .map((x, j) => `<td${j === 0 ? ' class="model"' : ''}>${x}</td>`).join('') + '</tr>';
  },
  // ---- concurrency: one row per (run, input size)
  concurrencyRows(doc) {
    const out = [];
    for (const run of doc?.runs || []) {
      const sizes = [...new Set(run.windows.map(w => w.input_tokens))].sort((a, b) => a - b);
      for (const size of sizes) {
        const by = {};
        for (const w of run.windows) if (w.input_tokens === size) by[w.concurrency] = w;
        out.push({id: `${run.id}|${size}`, engine: run.engine, model: run.model, family_id: run.family_id, placement: run.placement, context: run.context, input_tokens: size, run, by});
      }
    }
    return out.sort((a, b) => String(a.model).localeCompare(String(b.model)) || a.engine.localeCompare(b.engine) || a.input_tokens - b.input_tokens);
  },
  concurrencyRowHTML(r, i, button) {
    const e = this.escape, n = (v, d = 1) => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: d});
    const cell = c => { const w = r.by[c]; return w ? `<span class="num">${n(w.agg_output_tps, 0)} tok/s total</span><span class="sub">${n(w.per_request_decode_tps, 0)} tok/s per request · TTFT ${n(w.ttft_median_s, 2)} s${w.draft_accept_rate != null ? ` · MTP ${n(w.draft_accept_rate * 100, 0)}%` : ''}</span>` : '—'; };
    const one = r.by[1], top = r.by[8] || r.by[4];
    const scale = one && top && one.agg_output_tps ? `×${n(top.agg_output_tps / one.agg_output_tps, 2)}<span class="sub">${top.concurrency} users vs 1; per-request speed ${n(top.per_request_decode_tps / one.per_request_decode_tps * 100, 0)}% of single-user</span>` : '—';
    const rs = top?.resources || {};
    const res = rs.gpu0_util_pct != null ? `GPU ${n(rs.gpu0_util_pct, 0)}% / ${n(rs.gpu1_util_pct, 0)}%<span class="sub">VRAM ${n(rs.gpu0_vram_gib, 1)} / ${n(rs.gpu1_vram_gib, 1)} GiB · ${n(rs.gpu0_power_w, 0)} / ${n(rs.gpu1_power_w, 0)} W · RAM ${n(rs.ram_peak_gib, 1)} GiB</span>` : `VRAM peak ${n(rs.vram_peak_gib_all_gpus, 1)} GiB (all GPUs)<span class="sub">RAM peak ${n(rs.ram_peak_gib, 1)} GiB · per-GPU split not recorded</span>`;
    const place = this.PLACEMENT_LABEL[r.placement] || r.placement;
    return '<tr>' + [`<span class="model">${e(this.modelLabel(this.modelKey(r)))}</span><span class="sub">${e(this.engineLabel(r.engine))}${r.run.engine_version ? ' ' + e(r.run.engine_version) : ''} · ${e(place)} · ${n(r.context / 1024, 0)}K context<br>${e(r.run.model_format || '')}</span>`,
      `${n(r.input_tokens, 0)} tokens`, cell(1), cell(4), cell(8), scale, res + button].map((c, j) => `<td${j === 0 ? ' class="model"' : ''}>${c}</td>`).join('') + '</tr>';
  },
  externalFacets(rows) {
    const metas = rows.map(r => this.externalMeta(r));
    return {engines: [...new Set(metas.map(m => m.engine))].sort(), models: [...new Set(metas.map(m => m.label))].sort()};
  },
  filterRows(rows, f = {}) {
    return rows.filter(r => (!f.search || JSON.stringify([r.model,r.name,r.id,r.suite,r.engine,r.runtime_version,r.config,r.context,r.thinking,r.model_label,r.quantization,r.speculative_mode]).toLowerCase().includes(f.search.toLowerCase())) &&
      (!f.platform || (r.platform ?? 'legacy-snapshot') === f.platform) &&
      (!f.placement || (r.placement ?? r.headline?.placement ?? 'unknown') === f.placement) &&
      (!f.context || String(r.context ?? r.headline?.context ?? 'unknown') === f.context) &&
      (!f.engine || r.engine === f.engine) &&
      (!f.model || globalThis.BenchmarkUI.modelKey(r) === f.model) &&
      (!f.coverage || globalThis.BenchmarkUI.externalMeta(r).coverage === f.coverage) &&
      (!f.status || (f.status === 'archived' ? r.archived === true : r.status === f.status)));
  }
};
if (typeof module !== 'undefined') module.exports = globalThis.BenchmarkUI;
