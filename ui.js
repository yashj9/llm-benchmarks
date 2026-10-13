globalThis.BenchmarkUI = {
  escape(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); },
  filterRows(rows, f = {}) {
    return rows.filter(r => (!f.search || JSON.stringify([r.model,r.name,r.id,r.suite,r.engine,r.config,r.context,r.thinking]).toLowerCase().includes(f.search.toLowerCase())) &&
      (!f.placement || (r.placement ?? r.headline?.placement ?? 'unknown') === f.placement) &&
      (!f.context || String(r.context ?? r.headline?.context ?? 'unknown') === f.context) &&
      (!f.status || (f.status === 'archived' ? r.archived === true : r.status === f.status)));
  }
};
if (typeof module !== 'undefined') module.exports = globalThis.BenchmarkUI;
