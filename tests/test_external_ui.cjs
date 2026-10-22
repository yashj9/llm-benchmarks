// EXPLICITLY SYNTHETIC in-memory UI fixtures only. Never written to snapshot.json.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ui = require('../ui.js');
const baseline = JSON.parse(fs.readFileSync('data/snapshot.json', 'utf8'));
delete baseline.external_dyno; // fixtures test the empty case; real published runs are checked separately
const synthetic = {synthetic: true, id: 'SYNTHETIC-ui-only', evidence_notes: {thinking: ['canary-backed'], speculative: ['configured-not-observed']}, campaign: 'SYNTHETIC-only',
  model: '<img src=x onerror=alert(1)>', engine: 'halogen', runtime_version: '0.18.4',
  platform: 'amd-strix-halo', placement: 'unified-memory', context: 131072, thinking: 'on',
  battery_version: 'practical-v1', status: 'finished',
  metrics: {sustained_decode_tps: 150, sustained_n: 2, native_prefill_tps: null, mtp_acceptance: null},
  quality: {mean_score: 0.5, scored_rows: 1, total_rows: 2, by_category: {input: {mean_score: 0.5}}},
  resources: {metrics: {ram_used_bytes: {max: 1024 ** 3}, 'card0.package_power_w': {mean: 80}}},
  coverage: {strict_evidence_complete: false},
  items: [{task_id: 'input-4096', category: 'input', score: 0.5, cache_evidence: 'unknown', cached_prompt_tokens: null}]};
const mk = (over, q = 0.5) => ({...synthetic, ...over, quality: {...synthetic.quality, mean_score: q}});
const legacy = mk({id: 'SYNTHETIC-legacy-halogen', model: 'halogen-qwen3.8-flash-next'}, 0.4);  // no new-contract fields
const gufoFlash = mk({id: 'SYNTHETIC-gufo-flash', engine: 'gufo', runtime_version: '0.18.0', model: 'gufo-x', model_label: 'Flash-Next',
  quantization: 'UD-Q4_K_XL', speculative_mode: 'mtp', plan_coverage: 'full-practical-v1', vision: 'verified'}, 0.6);
const gufoText = mk({id: 'SYNTHETIC-gufo-deepseek', engine: 'gufo', runtime_version: '0.18.0', model: 'gufo-ds', model_label: 'DeepSeek V4 Flash',
  quantization: 'IQ2XXS', speculative_mode: 'dspark', plan_coverage: 'text-only', vision: 'unsupported-declared'}, 0.99);
const ollama = mk({id: 'SYNTHETIC-ollama-27b', engine: 'ollama', runtime_version: '0.40.5', model: 'qwen3.8-27b:ud-q4_k_xl-mmproj-f16-mtp-q4_0-128k',
  model_label: 'Qwen3.8-27B', quantization: 'UD-Q4_K_XL', speculative_mode: 'mtp', plan_coverage: 'full-practical-v1', vision: 'verified'}, 0.7);
const gufo27 = mk({id: 'SYNTHETIC-gufo-27b', engine: 'gufo', runtime_version: '0.18.0', model: 'gufo-27', model_label: 'Qwen3.8-27B',
  quantization: 'UD-Q4_K_XL', speculative_mode: 'dflash2', plan_coverage: 'full-practical-v1', vision: 'verified'}, 0.8);
const allRows = [legacy, gufoFlash, gufoText, ollama, gufo27, synthetic];

assert.equal(ui.externalRows(baseline).length, 0);
assert.equal(ui.filterRows([synthetic], {search: 'halogen', platform: 'amd-strix-halo', context: '131072', placement: 'unified-memory'}).length, 1);
assert.equal(ui.filterRows([synthetic], {platform: 'legacy-snapshot'}).length, 0);
assert.equal(ui.filterRows([synthetic], {placement: '5090'}).length, 0);
// engine / model / coverage / search-by-new-field filters
assert.deepEqual(ui.filterRows(allRows, {engine: 'gufo'}).map(r => r.id), ['SYNTHETIC-gufo-flash', 'SYNTHETIC-gufo-deepseek', 'SYNTHETIC-gufo-27b']);
assert.deepEqual(ui.filterRows(allRows, {model: 'Qwen3.8-27B'}).map(r => r.id), ['SYNTHETIC-ollama-27b', 'SYNTHETIC-gufo-27b']);
assert.deepEqual(ui.filterRows(allRows, {coverage: 'text-only'}).map(r => r.id), ['SYNTHETIC-gufo-deepseek']);
assert.equal(ui.filterRows(allRows, {coverage: 'full-practical-v1'}).length, 5);  // legacy derives full coverage
assert.equal(ui.filterRows(allRows, {search: 'dflash2'}).length, 1);
assert.equal(ui.filterRows(allRows, {engine: 'ollama', model: 'Flash-Next'}).length, 0);
assert.equal(ui.filterRows(baseline.dyno_runs, {}).length, baseline.dyno_runs.length, 'old rows unaffected by new filter keys');
// legacy rows: derived defaults, never invented quantization
const lm = ui.externalMeta(legacy);
assert.deepEqual([lm.label, lm.quantization, lm.spec, lm.coverage, lm.vision], ['Flash-Next', null, 'mtp', 'full-practical-v1', 'verified']);
assert.deepEqual(ui.externalFacets(allRows).engines, ['gufo', 'halogen', 'ollama']);
// escaping, badges and columns
const html = ui.externalRowHTML(synthetic, 0);
assert.ok(html.includes('&lt;img'));
assert.ok(!html.includes('<img'));
assert.ok(html.includes('Shared') || html.includes('shared package power'));
assert.ok(html.includes('Host-wide RAM peak'));
assert.ok(html.includes('Strict evidence incomplete'));
assert.equal((html.match(/<td>/g) || []).length, 9);
assert.ok(html.includes('engine-halogen') && html.includes('not recorded'));
const evil = ui.externalRowHTML(mk({engine: '"><script>alert(1)</script>', model_label: '<b>x</b>', quantization: '<i>q</i>', speculative_mode: '<u>s</u>',
  plan_coverage: 'full-practical-v1', vision: '<svg>'}), 0);
assert.ok(!/<(script|b|i|u|svg)[ >]/.test(evil), evil);
assert.ok(evil.includes('engine-unknown'));
const textHtml = ui.externalRowHTML(gufoText, 0, true);
assert.ok(textHtml.includes('TEXT-ONLY') && textHtml.includes('not comparable') && textHtml.includes('IQ2XXS') && textHtml.includes('dspark'));
assert.ok(textHtml.includes('Vision: unsupported (declared)') && textHtml.includes('image: not run'));
assert.ok(ui.externalRowHTML(gufoFlash, 0).includes('Full practical-v1') && ui.externalRowHTML(gufoFlash, 0).includes('engine-gufo'));
assert.ok(!ui.externalRowHTML(gufoFlash, 0, true).includes('TEXT-ONLY'));
assert.ok(ui.externalRowHTML(synthetic, 0, true).includes('50%'));
assert.ok(ui.externalRowHTML({...synthetic, quality: {...synthetic.quality, mean_score: null}}, 0, true).includes('—'));
// grouping by model keeps Details indices and labels the comparison conditions
const grouped = ui.externalTableHTML([ollama, gufo27, gufoFlash], true, true);
assert.equal((grouped.match(/class="group"/g) || []).length, 2);
assert.ok(grouped.includes('Model: Qwen3.8-27B · 2 runs on ollama, gufo') || grouped.includes('Model: Qwen3.8-27B · 2 runs on gufo, ollama'));
assert.ok(grouped.includes('data-detail="2"') && !grouped.includes('data-detail="3"'));
assert.ok(!ui.externalTableHTML([ollama], true, false).includes('class="group"'));

async function exercise(snapshot, hasExternal) {
  const elements = new Map();
  function elem(id) {
    if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', textContent: '', hidden: false, style: {},
      classList: {toggle() {}}, addEventListener() {}, setAttribute() {}, showModal() {this.open = true;}, close() {this.open = false;}});
    return elements.get(id);
  }
  elem('resource-mode').value = 'dyno';
  elem('sort').value = 'score';  // default option in the real page
  const sandbox = {BenchmarkUI: ui, document: {getElementById: elem, querySelectorAll: () => [], querySelector: elem},
    window: {addEventListener() {}}, location: {hash: ''}, history: {replaceState() {}}, URLSearchParams,
    fetch: async () => ({ok: true, json: async () => structuredClone(snapshot)}), console};
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync('app.js', 'utf8'), sandbox);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(!elem('snapshot').textContent.includes('Could not load'), elem('snapshot').textContent);
  for (const view of ['arena','compare','concurrency','campaign','speed','prefill','resources','dyno','quality','external','practical']) {
    vm.runInContext(`setView('${view}')`, sandbox);
    assert.ok(elem('thead').innerHTML.includes('<th'), view);
    if (['external','practical'].includes(view)) {
      assert.ok(elem('tbody').innerHTML.includes(hasExternal ? 'SYNTHETIC-ui-only' : 'No matching results'), view);
      if (hasExternal) {
        assert.equal((elem('thead').innerHTML.match(/<th scope=/g) || []).length, 9);
        assert.equal((elem('tbody').innerHTML.match(/<td>/g) || []).length, 9 * snapshot.external_dyno.runs.length);
        vm.runInContext('detail(current[0])', sandbox);
        assert.ok(elem('detail-body').innerHTML.includes('SYNTHETIC-only'));
        assert.ok(elem('detail-body').innerHTML.includes('unavailable'));
        if (vm.runInContext('!!current[0].evidence_notes', sandbox)) assert.ok(elem('detail-body').innerHTML.includes('Runtime evidence strength'));
        assert.equal(elem('engine-label').hidden, false);
        assert.ok(elem('engine').innerHTML.includes('ollama'));
        if (snapshot.external_dyno.runs.length > 3) assert.ok(elem('model-filter').innerHTML.includes('DeepSeek V4 Flash'));
      } else {
        assert.equal(elem('group-label').hidden, false);
      }
    } else {
      assert.equal(elem('engine-label').hidden, !['speed','prefill','resources','dyno','concurrency'].includes(view), view);  // engine/model filters now serve every speed/resource view
      assert.ok(!elem('tbody').innerHTML.includes('SYNTHETIC-ui-only'), 'External must not leak into old views');
    }
  }
  vm.runInContext("setView('external')", sandbox);
  elem('platform').value = 'legacy-snapshot';
  vm.runInContext('render()', sandbox);
  assert.ok(elem('tbody').innerHTML.includes('No matching results'));
  elem('platform').value = '';
  if (hasExternal && snapshot.external_dyno.runs.length > 3) {
    // practical view: text-only (99%) must never be ranked above full-coverage rows by score
    vm.runInContext("setView('practical')", sandbox);
    const tb = elem('tbody').innerHTML;
    assert.ok(tb.indexOf('SYNTHETIC-gufo-deepseek') > tb.indexOf('SYNTHETIC-ollama-27b'));
    assert.ok(tb.indexOf('SYNTHETIC-gufo-deepseek') > tb.indexOf('SYNTHETIC-ui-only'));
    assert.ok(tb.includes('TEXT-ONLY'));
    elem('group').value = 'model';
    vm.runInContext('render()', sandbox);
    assert.ok(elem('tbody').innerHTML.includes('Model: Qwen3.8-27B'));
    assert.equal((elem('tbody').innerHTML.match(/<td>/g) || []).length, 9 * snapshot.external_dyno.runs.length);
    vm.runInContext('detail(current[0])', sandbox);  // Details index maps to rows, not header rows
    elem('group').value = '';
    elem('engine').value = 'ollama';
    vm.runInContext('render()', sandbox);
    assert.equal((elem('tbody').innerHTML.match(/<td>/g) || []).length, 9);
    elem('engine').value = '';
    elem('coverage').value = 'text-only';
    vm.runInContext('render()', sandbox);
    assert.ok(elem('tbody').innerHTML.includes('SYNTHETIC-gufo-deepseek') && !elem('tbody').innerHTML.includes('SYNTHETIC-gufo-flash'));
    elem('coverage').value = ''; elem('model-filter').value = 'Nonexistent';
    vm.runInContext('render()', sandbox);
    assert.ok(elem('tbody').innerHTML.includes('No matching results'));
    // stale external filters must not leak into old views
    vm.runInContext("setView('dyno')", sandbox);
    assert.equal(elem('model-filter').value, '');
    assert.ok(!elem('tbody').innerHTML.includes('No matching results'));
  }
}
const published = JSON.parse(fs.readFileSync('data/snapshot.json', 'utf8')).external_dyno.runs;  // real published rows, read-only
assert.equal(published.length, 5);
const counts = {};
for (const r of published) counts[r.engine] = (counts[r.engine] || 0) + 1;
assert.deepEqual(counts, {halogen: 1, strata: 1, gufo: 2, ollama: 1});
for (const r of published.slice(0, 2)) {
  const row = ui.externalRowHTML(r, 0, true);
  assert.ok(row.includes('Flash-Next') && row.includes('Full practical-v1') && row.includes('not recorded') && row.includes('mtp'));
  assert.ok(!('speculative_mode' in r), 'published legacy rows are not rewritten');
}
assert.deepEqual(ui.filterRows(published, {engine: 'strata'}).map(r => r.engine), ['strata']);

(async () => {
  await exercise(baseline, false);
  const added = structuredClone(baseline);
  added.external_dyno = {campaigns: [{id: 'SYNTHETIC-only'}], runs: [synthetic]};
  await exercise(added, true);
  const multi = structuredClone(baseline);
  multi.external_dyno = {campaigns: [{id: 'SYNTHETIC-only'}], runs: structuredClone(allRows)};
  await exercise(multi, true);
  console.log('External UI/filter/escaping/detail integration and all 9 old/new views passed (synthetic only)');
})().catch(e => {console.error(e); process.exitCode = 1;});
