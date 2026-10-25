const assert = require('node:assert/strict');
const ui = require('../ui.js');
const fs = require('node:fs');
const snapshot = JSON.parse(fs.readFileSync('data/snapshot.json','utf8'));
assert.equal(typeof ui.filterRows, 'function', 'filters not implemented');
assert.equal(ui.filterRows(snapshot.dyno_runs, {search:'qwen3.8-flash-next-iq2_xs', placement:'5090', status:'finished'}).length, 1);
assert.equal(ui.filterRows(snapshot.quality_runs, {}).length, 128);
assert.equal(ui.filterRows(snapshot.dyno_runs, {status:'archived'}).length, 36);
assert.equal(ui.filterRows(snapshot.dyno_runs, {status:'failed'}).length, 18);
assert.equal(ui.filterRows(snapshot.dyno_runs, {search:'NO_MATCH'}).length, 0);
assert.equal(ui.escape('<img src=x onerror=alert(1)>'), '&lt;img src=x onerror=alert(1)&gt;');
assert.equal(ui.filterRows(snapshot.dyno_setups, {context:'32768'}).length, 1, 'Context filter must not combine different workloads');
const campaigns = snapshot.dyno_campaigns.runs;
assert.equal(ui.filterRows(campaigns, {platform:'amd-strix-halo'}).length, 13);
assert.equal(ui.filterRows(campaigns, {platform:'legacy-snapshot'}).length, 0);
assert.equal(ui.filterRows(snapshot.dyno_runs, {platform:'amd-strix-halo'}).length, 0);
assert.equal(ui.filterRows(snapshot.dyno_runs, {platform:'legacy-snapshot'}).length, 111);
assert.equal(ui.filterRows(campaigns, {platform:'amd-strix-halo',search:'nail-',context:'131072',placement:'unified-memory'}).length, 2);
assert.equal(ui.filterRows(campaigns, {platform:'amd-strix-halo',context:'24576'}).length, 1);
assert.equal(ui.filterRows(campaigns, {platform:'amd-strix-halo',context:'40960'}).length, 1);
assert.equal(ui.filterRows(campaigns, {platform:'amd-strix-halo',context:'32768'}).length, 1);
assert.equal(ui.filterRows(campaigns, {platform:'amd-strix-halo',placement:'5090'}).length, 0);
console.log('Original filter/escaping assertions + 9 campaign/platform assertions passed');

// ---- engine comparison / concurrency / model families (added with the Ollama, Unsloth Studio and concurrency data)
const families = JSON.parse(fs.readFileSync('data/model_families.json', 'utf8'));
const concurrency = JSON.parse(fs.readFileSync('data/concurrency.json', 'utf8'));
ui.setFamilies(families);
const groups = ui.compareRows(snapshot.dyno_setups);
assert.ok(groups.length >= 15, 'engine comparison must hold the cross-engine setups');
assert.ok(groups.every(g => Object.keys(g.cells).length >= 2), 'every comparison row has at least two engines');
assert.ok(groups.some(g => ['lmstudio', 'ollama', 'unsloth'].every(e => g.cells[e])), 'at least one row compares all three engines');
assert.equal(ui.filterRows(groups, {model: 'qwen3.8-27b-ud'}).every(g => g.family_id === 'qwen3.8-27b-ud'), true);
assert.equal(ui.engineLabel('unsloth'), 'Unsloth Studio');
assert.equal(ui.familyOf({engine: 'ollama', model: 'lmstudio/qwen3.8-27b:ud-q4_k_m-native'}).id, 'qwen3.8-27b-ud');
const crows = ui.concurrencyRows(concurrency);
assert.equal(crows.length, concurrency.runs.length * 2, 'two input sizes per concurrency run');
assert.ok(crows.some(r => r.engine === 'vllm') && crows.some(r => r.engine === 'lmstudio'));
assert.equal(ui.filterRows(crows, {engine: 'vllm'}).length, 2);
assert.ok(ui.concurrencyRowHTML(crows[0], 0, '').includes('tok/s total'));
assert.ok(ui.compareRowHTML(groups[0], 0, '').includes('tok/s'));
{ const text = JSON.stringify(concurrency); assert.ok(!text.includes('127.0.0.1') && !text.includes('localhost') && !/[A-Za-z]:[\/]+Users/.test(text), 'concurrency data must carry no local paths or endpoints'); }
console.log('Engine comparison, family mapping and concurrency assertions passed');

// ---- hardware views
{
  const all = ui.finderRows(snapshot.dyno_setups, {});
  assert.ok(all.length >= 15, 'finder holds model x GPU setup rows');
  assert.ok(all.every((g, i) => i === 0 || all[i - 1].best.decode_short_tps >= g.best.decode_short_tps), 'finder is sorted fastest first');
  const small = ui.finderRows(snapshot.dyno_setups, {vram: 16});
  assert.ok(small.length > 0 && small.length < all.length, 'a 16 GiB budget hides larger setups');
  assert.ok(small.every(g => g.mem != null && g.mem <= 16), 'budget filter respects memory');
  assert.ok(ui.finderRows(snapshot.dyno_setups, {engine: 'ollama'}).every(g => g.engine === 'ollama'));
  assert.ok(ui.finderRowHTML(all[0]).includes('tok/s') && ui.finderHeads().length === 6);
  const gp = ui.gpuRows(snapshot.dyno_setups, {});
  assert.ok(gp.length >= 5 && gp.every(g => Object.keys(g.cells).length >= 2), 'gpu comparison needs two GPU setups');
  assert.ok(gp.some(g => g.cells['5090'] && g.cells['5060ti']) && ui.gpuRowHTML(gp.find(g => g.cells['5090'] && g.cells['5060ti'])).includes('faster'));
  assert.ok(ui.gpuHeads().length === 5);
  assert.equal(ui.PLACEMENT_LABEL['both-5090first'], 'Split · 5090 first');
  console.log('Hardware finder and GPU comparison assertions passed');
}
