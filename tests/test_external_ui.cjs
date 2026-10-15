// EXPLICITLY SYNTHETIC in-memory UI fixtures only. Never written to snapshot.json.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ui = require('../ui.js');
const baseline = JSON.parse(fs.readFileSync('data/snapshot.json', 'utf8'));
delete baseline.external_dyno; // fixtures test the empty case; real published runs are checked separately
const synthetic = {synthetic: true, id: 'SYNTHETIC-ui-only', campaign: 'SYNTHETIC-only',
  model: '<img src=x onerror=alert(1)>', engine: 'halogen', runtime_version: '0.18.4',
  platform: 'amd-strix-halo', placement: 'unified-memory', context: 131072, thinking: 'on',
  battery_version: 'practical-v1', status: 'finished',
  metrics: {sustained_decode_tps: 150, sustained_n: 2, native_prefill_tps: null, mtp_acceptance: null},
  quality: {mean_score: 0.5, scored_rows: 1, total_rows: 2, by_category: {input: {mean_score: 0.5}}},
  resources: {metrics: {ram_used_bytes: {max: 1024 ** 3}, 'card0.package_power_w': {mean: 80}}},
  coverage: {strict_evidence_complete: false},
  items: [{task_id: 'input-4096', category: 'input', score: 0.5, cache_evidence: 'unknown', cached_prompt_tokens: null}]};
assert.equal(ui.externalRows(baseline).length, 0);
assert.equal(ui.filterRows([synthetic], {search: 'halogen', platform: 'amd-strix-halo', context: '131072', placement: 'unified-memory'}).length, 1);
assert.equal(ui.filterRows([synthetic], {platform: 'legacy-snapshot'}).length, 0);
assert.equal(ui.filterRows([synthetic], {placement: '5090'}).length, 0);
const html = ui.externalRowHTML(synthetic, 0);
assert.ok(html.includes('&lt;img'));
assert.ok(!html.includes('<img'));
assert.ok(html.includes('Shared') || html.includes('shared package power'));
assert.ok(html.includes('Host-wide RAM peak'));
assert.ok(html.includes('Strict evidence incomplete'));
assert.ok(ui.externalRowHTML(synthetic, 0, true).includes('50%'));
assert.ok(ui.externalRowHTML({...synthetic, quality: {...synthetic.quality, mean_score: null}}, 0, true).includes('—'));

async function exercise(snapshot, hasExternal) {
  const elements = new Map();
  function elem(id) {
    if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', textContent: '', hidden: false, style: {},
      classList: {toggle() {}}, addEventListener() {}, setAttribute() {}, showModal() {this.open = true;}, close() {this.open = false;}});
    return elements.get(id);
  }
  elem('resource-mode').value = 'dyno';
  const sandbox = {BenchmarkUI: ui, document: {getElementById: elem, querySelectorAll: () => [], querySelector: elem},
    window: {addEventListener() {}}, location: {hash: ''},
    fetch: async () => ({ok: true, json: async () => structuredClone(snapshot)}), console};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync('app.js', 'utf8'), sandbox);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(!elem('snapshot').textContent.includes('Could not load'), elem('snapshot').textContent);
  for (const view of ['arena','campaign','speed','prefill','resources','dyno','quality','external','practical']) {
    vm.runInContext(`setView('${view}')`, sandbox);
    assert.ok(elem('thead').innerHTML.includes('<th'), view);
    if (['external','practical'].includes(view)) {
      assert.ok(elem('tbody').innerHTML.includes(hasExternal ? 'SYNTHETIC-ui-only' : 'No matching results'), view);
      if (hasExternal) {
        assert.equal((elem('thead').innerHTML.match(/<th scope=/g) || []).length, 7);
        assert.equal((elem('tbody').innerHTML.match(/<td>/g) || []).length, 7);
        vm.runInContext('detail(current[0])', sandbox);
        assert.ok(elem('detail-body').innerHTML.includes('SYNTHETIC-only'));
        assert.ok(elem('detail-body').innerHTML.includes('unavailable'));
      }
    } else {
      assert.ok(!elem('tbody').innerHTML.includes('SYNTHETIC-ui-only'), 'External must not leak into old views');
    }
  }
  vm.runInContext("setView('external')", sandbox);
  elem('platform').value = 'legacy-snapshot';
  vm.runInContext('render()', sandbox);
  assert.ok(elem('tbody').innerHTML.includes('No matching results'));
}
(async () => {
  await exercise(baseline, false);
  const added = structuredClone(baseline);
  added.external_dyno = {campaigns: [{id: 'SYNTHETIC-only'}], runs: [synthetic]};
  await exercise(added, true);
  console.log('External UI/filter/escaping/detail integration and all 9 old/new views passed (synthetic only)');
})().catch(e => {console.error(e); process.exitCode = 1;});
