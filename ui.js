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
      (!f.model || globalThis.BenchmarkUI.externalMeta(r).label === f.model) &&
      (!f.coverage || globalThis.BenchmarkUI.externalMeta(r).coverage === f.coverage) &&
      (!f.status || (f.status === 'archived' ? r.archived === true : r.status === f.status)));
  }
};
if (typeof module !== 'undefined') module.exports = globalThis.BenchmarkUI;
