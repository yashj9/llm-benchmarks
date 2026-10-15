globalThis.BenchmarkUI = {
  escape(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); },
  externalRows(data) { return data.external_dyno?.runs || []; },
  externalRowHTML(r, i, quality = false) {
    const e = this.escape;
    const n = v => v == null ? '—' : Number(v).toLocaleString(undefined, {maximumFractionDigits: 2});
    const stats = r.resources?.metrics || {};
    const ram = stats.ram_used_bytes?.max;
    const ppt = Object.entries(stats).filter(([k]) => k.endsWith('.package_power_w')).map(([k,v]) => `${e(k.split('.')[0])}: ${n(v.mean)} W`).join('<br>') || '—';
    const q = r.quality;
    const metric = quality ? `${n(q.mean_score == null ? null : q.mean_score * 100)}${q.mean_score == null ? '' : '%'}<span class="sub">${n(q.scored_rows)} / ${n(q.total_rows)} scored rows</span>` : `${n(r.metrics.sustained_decode_tps)}<span class="sub">${n(r.metrics.sustained_n)} requests ≥256 output tokens</span>`;
    const extra = quality ? Object.entries(q.by_category).map(([k,v]) => `${e(k)}: ${n(v.mean_score == null ? null : v.mean_score * 100)}${v.mean_score == null ? '' : '%'}`).join('<br>') : '— / —<span class="sub">Native prefill / MTP acceptance unmeasured</span>';
    const cells = [`<span class="model">${e(r.model)}</span><span class="sub">${e(r.id)}</span>`, `${e(r.engine)} ${e(r.runtime_version)}<span class="sub">AMD Strix Halo · unified memory<br>${n(r.context)} configured tokens · thinking ${e(r.thinking)}</span>`, metric, extra, `${n(ram == null ? null : ram / 1024 ** 3)} GiB<span class="sub">Host-wide RAM peak; not RAM + GTT</span>`, `${ppt}<span class="sub">Host-wide shared package power; not wall power</span>`, `${e(r.status)}<span class="sub">Strict evidence ${r.coverage.strict_evidence_complete ? 'complete' : 'incomplete'} · cache / near-window occupancy unverified</span><button class="details" data-detail="${i}">Details ↗</button>`];
    return '<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>';
  },
  filterRows(rows, f = {}) {
    return rows.filter(r => (!f.search || JSON.stringify([r.model,r.name,r.id,r.suite,r.engine,r.runtime_version,r.config,r.context,r.thinking]).toLowerCase().includes(f.search.toLowerCase())) &&
      (!f.platform || (r.platform ?? 'legacy-snapshot') === f.platform) &&
      (!f.placement || (r.placement ?? r.headline?.placement ?? 'unknown') === f.placement) &&
      (!f.context || String(r.context ?? r.headline?.context ?? 'unknown') === f.context) &&
      (!f.status || (f.status === 'archived' ? r.archived === true : r.status === f.status)));
  }
};
if (typeof module !== 'undefined') module.exports = globalThis.BenchmarkUI;
