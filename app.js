/* Static snapshot only; untrusted labels are escaped before rendering. */
'use strict';
const {escape:E, filterRows} = globalThis.BenchmarkUI;
const $ = id => document.getElementById(id);
const number = (v,d=1) => v == null ? '—' : Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const percent = v => v == null ? '—' : `${number(v*100)}%`;
const context = v => v == null ? 'unknown' : `${number(v/1024,0)}K`;
const placement = v => ({'5090':'5090 only',both:'Both GPUs','5060ti':'5060 Ti only',unknown:'Unknown'})[v] || 'Unknown';
const stamp = v => v == null ? 'unknown' : new Date(v).toLocaleString();
const badge = (s,cl='neutral') => `<span class="tag ${cl}">${E(s)}</span>`;
const scoreCell = v => `<span class="num">${percent(v)}</span>${v == null?'':`<div class="bar"><i style="width:${Math.max(0,Math.min(100,v*100))}%"></i></div>`}`;
let data,view='arena',current=[];
const names = {arena:'Combined leaderboard',speed:'Speed by setup',prefill:'Cold / hot prefill',resources:'System resource comparisons',dyno:'Dyno run history',quality:'Quality run history'};
const explanations = {
 arena:'Comparable Quality scores + representative Dyno speed. Quality and speed are separate runs; their runtime settings may differ. Inspect details before comparing.',
 speed:'One row per model / engine / context / thinking / GPU placement. Medians across all active finished sessions in each setup; archives excluded.',
 prefill:'Cold = fresh-prefix request; hot = identical-prefix repeat. Rates are client-observed prompt tokens / TTFT, not native engine compute rates. Cache-hit reporting was unavailable: repeated-prefix observations are NOT verified cache speeds. Same 260-record probe; tokenized prompt lengths differ by model.',
 resources:'Observed whole-system RAM, per-GPU VRAM, CPU load/power, GPU power and temperatures. Includes background activity—not isolated model consumption or wall power. Compare the same context and workload. Dyno and Quality resource captures are kept separate.',
 dyno:'Every preserved real Dyno session, including archived and failed attempts. Reliability is a Dyno task score, not the Quality benchmark score.',
 quality:'Every preserved real Quality run. Historical benchmarks, non-standard protocols and partial runs are included here, not silently ranked.'
};
function setView(v){view=names[v]?v:'arena';location.hash=view;for(const b of document.querySelectorAll('[data-view]')){b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-pressed',b.dataset.view===view)}$('status-label').hidden=!['dyno','quality'].includes(view);$('protocol-label').hidden=view!=='arena';$('resource-mode-label').hidden=view!=='resources';$('status').value='';render()}
function render(){
 const arena=data.arenas[Number($('protocol').value)||0];
 let rows = view==='arena' ? arena.models.map(m=>({...m,model:m.key,placement:m.headline?.placement})) : ['speed','prefill'].includes(view)?data.dyno_setups:view==='resources'?($('resource-mode').value==='quality'?data.quality_resource_jobs:data.resource_comparisons):view==='dyno'?data.dyno_runs:data.quality_runs;
 rows=filterRows(rows,{search:$('search').value,placement:$('placement').value,context:$('context').value,status:$('status').value});
 const sort=$('sort').value;
 const metric = r => {
   const pp=r.prefill??r.headline?.prefill,rs=r.resources??r.headline?.resources;
   if(sort==='cold')return pp?.cold_tps;
   if(sort==='hot')return pp?.hot_tps;
   if(sort==='ram')return rs?.ram_peak_gib;
   if(sort==='power')return rs?.cpu_gpu_mean_w;
   return view==='arena'?r.balance:['speed','resources'].includes(view)?r.decode_short_tps:view==='prefill'?r.prefill?.cold_tps:view==='dyno'?r.metrics.decode_short_tps:r.summary.weighted_score??r.summary.score;
 };
 const direction=['ram','power'].includes(sort)?1:-1;
 rows.sort((a,b)=>sort==='model'?String(a.model).localeCompare(String(b.model)):sort==='date'?String(b.created||b.created_at||'').localeCompare(String(a.created||a.created_at||'')):(metric(a)==null)-(metric(b)==null)||direction*((metric(a)??0)-(metric(b)??0)));
 current=rows;$('heading').textContent=names[view];$('explanation').textContent=explanations[view];$('count').textContent=`${rows.length} ${view==='arena'?'models':['speed','prefill'].includes(view)?'setups':view==='resources'?'comparisons':'runs'} shown · click Details for source measurements${view==='resources'?` · ${rows.filter(r=>r.resources?.samples>0).length} with telemetry`:''}`;
 const heads = view==='arena'?['Model','Quality / 90% interval','Short / long tok/s','Cold / hot prefill tok/s*','Dyno reliability','Balanced','Evidence']:view==='speed'?['Model / engine','Setup / context / thinking','Short / long tok/s','Cold / hot prefill tok/s*','Long prefill tok/s*','Reliability','Sessions / caps / errors','Evidence']:view==='prefill'?['Model / setup','Cold / fresh tok/s*','Hot / repeat tok/s*','Cold / hot TTFT s','Probe tokens','Long prefill tok/s*','Cache evidence']:view==='resources'?['Model / setup','RAM mean / peak GiB','RAM free min / swap peak GiB','VRAM peaks GiB (5090 / 5060 Ti)','CPU mean % / W','GPU mean W (5090 / 5060 Ti)','GPU mean % (5090 / 5060 Ti)','CPU + GPUs mean W','Peak °C (CPU / 5090 / 5060 Ti)','Evidence']:view==='dyno'?['Model / run','Status','Setup / context / thinking','Short / long tok/s','Reliability / caps','Evidence']:['Model / suite / run','Status','Thinking / max tokens','Pass / total','Weighted quality','Evidence'];
 $('thead').innerHTML='<tr>'+heads.map(h=>`<th scope="col">${E(h)}</th>`).join('')+'</tr>';
 $('tbody').innerHTML=rows.length?rows.map((r,i)=>rowHTML(r,i)).join(''):`<tr><td class="empty" colspan="${heads.length}">No matching results. Reset the filters to see all runs.</td></tr>`;
 document.querySelector('.table-wrap').scrollLeft=0;
 document.querySelector('.table-wrap table').classList.toggle('resource-table',view==='resources');
 for(const b of document.querySelectorAll('[data-detail]'))b.onclick=()=>detail(current[Number(b.dataset.detail)]);
}
function prefillCell(p){
 return `<span class="num">${number(p?.cold_tps,0)} / ${number(p?.hot_tps,0)}</span><span class="sub">${p?.hot_n?(p.hot_cache_verified?'Cache verified':'Repeated prefix · cache unverified'):'Pair not recorded'}</span>`;
}
function rowHTML(r,i){
 const button=`<button class="details" data-detail="${i}">Details ↗</button>`;
 let cells;
 if(view==='arena'){
  const q=r.quality,h=r.headline,ci=q?.ci?.map(percent).join('–'),gaps=[...(r.gaps||[])];
  if(h?.token_limit_hits)gaps.push(`${h.token_limit_hits} Dyno token-cap hits`);
  cells=[`<span class="model">${E(r.name)}</span><span class="sub">${E(r.key)}</span>`,`${scoreCell(q?.score)}<span class="sub">${E(ci||'Not comparable / missing')} · ${q?.n??0} tests</span>`,`<span class="num">${number(h?.decode_short_tps)} / ${number(h?.decode_long_tps)}</span><span class="sub">${E(placement(h?.placement))} · ${context(h?.context)} · thinking ${E(h?.thinking??'unknown')}</span>`,scoreCell(h?.reliability),`${scoreCell(r.balance)}<span class="sub">70% quality / 30% speed</span>`,`${button}<span class="sub">${gaps.length?E(gaps.join(' · ')):'Standard comparable evidence'}</span>`];
 }else if(view==='speed'){
  cells=[`<span class="model">${E(r.model)}</span><span class="sub">${E(r.engine)}</span>`,`${badge(placement(r.placement))}<span class="sub">${context(r.context)} · thinking ${E(r.thinking)}</span>`,`<span class="num">${number(r.decode_short_tps)} / ${number(r.decode_long_tps)}</span><span class="sub">Short spread ${number(r.decode_short_tps_min)}–${number(r.decode_short_tps_max)}</span>`,scoreCell(r.reliability),`${r.sessions_in_group} sessions<span class="sub">${r.token_limit_hits} caps · ${r.errors} errors</span>`,button];
 }else if(view==='prefill'){
  const p=r.prefill;
  cells=[`<span class="model">${E(r.model)}</span><span class="sub">${E(r.engine)} · ${placement(r.placement)} · ${context(r.context)} · thinking ${E(r.thinking)}</span>`,number(p.cold_tps,0),number(p.hot_tps,0),`${number(p.cold_ttft_s,3)} / ${number(p.hot_ttft_s,3)}`,`${number(p.prompt_tokens,0)}<span class="sub">${p.cold_n} fresh / ${p.hot_n} repeat measurements</span>`,`${number(r.prefill_long_tps,0)}<span class="sub">Battery prompts ≥64K · cache state mixed</span>`,`${button}<br>${badge(p.hot_n?(p.hot_cache_verified?'Cache verified':'cache unverified'):'Pair not recorded',p.hot_n&&!p.hot_cache_verified?'warn':'neutral')}`];
 }else if(view==='resources'){
  const rs=r.resources;
  const ramBar=rs.ram_peak_gib==null?'':`<div class="bar"><i style="width:${Math.max(0,Math.min(100,rs.ram_peak_gib/64*100))}%"></i></div>`;
  cells=[`<span class="model">${E(r.name||r.model)}</span><span class="sub">${E(r.kind)} · ${E(r.engine)} · ${placement(r.placement)} · ${context(r.context)}<br>thinking ${E(r.thinking??'unknown')}${r.max_tokens?` · ${number(r.max_tokens,0)} output cap`:''}${r.decode_short_tps?`<br>${number(r.decode_short_tps)} decode tok/s`:''}</span>`,`${number(rs.ram_mean_gib)} / ${number(rs.ram_peak_gib)}${ramBar}<span class="sub">Loaded-idle ${number(rs.loaded_idle_ram_gib)} GiB</span>`,`${number(rs.ram_available_min_gib)} / ${number(rs.swap_peak_gib)}<span class="sub">Free / swap (where recorded)</span>`,`${number(rs.gpu0_vram_peak_gib)} / ${number(rs.gpu1_vram_peak_gib)}`,`${number(rs.cpu_mean_pct)}% / ${number(rs.cpu_mean_w)}`,`${number(rs.gpu0_mean_w)} / ${number(rs.gpu1_mean_w)}`,`${number(rs.gpu0_mean_pct)} / ${number(rs.gpu1_mean_pct)}`,`${number(rs.cpu_gpu_mean_w)}<span class="sub">Not wall power</span>`,`${number(rs.cpu_temp_peak_c)} / ${number(rs.gpu0_temp_peak_c)} / ${number(rs.gpu1_temp_peak_c)}`,`${button}<span class="sub">${rs.samples?`${number(rs.samples,0)} samples${rs.measured_sessions!=null?` · ${rs.measured_sessions}/${rs.sessions} sessions`:''}`:'Not recorded'}${r.kind==='Quality job'?'<br>Whole job: load/run/unload':'<br>Post-load Dyno workload'}</span>`];
 }else if(view==='dyno'){
  cells=[`<span class="model">${E(r.model)}</span><span class="sub">${E(r.id)}<br>${E(stamp(r.created))}</span>`,`${badge(r.status,r.status==='finished'?'good':'warn')}${r.archived?'<br>'+badge('archived'):''}`,`${badge(placement(r.placement))}<span class="sub">${E(r.engine)} · ${context(r.context)} · thinking ${E(r.thinking)}</span>`,`<span class="num">${number(r.metrics.decode_short_tps)} / ${number(r.metrics.decode_long_tps)}</span>`,`${scoreCell(r.metrics.reliability)}<span class="sub">${r.metrics.token_limit_hits} caps · ${r.metrics.errors} errors</span>`,button];
 }else{
  cells=[`<span class="model">${E(r.name||r.model)}</span><span class="sub">${E(r.suite)} · ${E(r.id)}<br>${E(stamp(r.created))}</span>`,`${badge(r.status,r.status==='finished'?'good':'warn')}<span class="sub">${r.comparable_candidate?'Protocol recorded':'Historical / unverified protocol'}</span>`,`${E(r.thinking??'unknown')} / ${number(r.max_tokens,0)}<span class="sub">${E(placement(r.placement))} · ${E(r.engine)}</span>`,`<span class="num">${number(r.summary.passed,0)} / ${number(r.summary.n_total??r.summary.n,0)}</span>`,scoreCell(r.summary.weighted_score??null),button];
 }
 if(view==='arena')cells.splice(3,0,prefillCell(r.headline?.prefill));
 if(view==='speed')cells.splice(3,0,prefillCell(r.prefill),`${number(r.prefill_long_tps,0)}<span class="sub">Prompts ≥64K · mixed cache</span>`);
 return '<tr>'+cells.map((c,j)=>`<td${j===0?' class="model"':''}>${c}</td>`).join('')+'</tr>';
}
function detail(r){
 let summary=r,items=r.items||[],related=[];
 if(r.key && r.setups){related=[...r.setups.map(s=>({label:`${placement(s.placement)} · ${context(s.context)} · thinking ${s.thinking}`,ids:s.session_ids})),...Object.entries(r.quality?.by_suite||{}).map(([suite,q])=>({label:suite,ids:[q.run]}))];
 }else if(r.session_ids){related=[{label:'Contributing Dyno sessions',ids:r.session_ids}]}
 const compact={...summary};delete compact.items;
 let html=`<p class="model">${E(r.name||r.model)}</p><p class="muted">Recorded settings only. Unknown does not mean disabled. No raw prompts or answers are published.</p><pre>${E(JSON.stringify(compact,null,2))}</pre>`;
 for(const group of related){html+=`<h3>${E(group.label)}</h3>`;for(const id of group.ids){const run=data.dyno_runs.find(x=>x.id===id)||data.quality_runs.find(x=>x.id===id);html+=`<button class="details" data-related="${E(id)}">${E(id)}</button> `;}}
 if(r.source_ids?.length){html+='<h3>Upstream source credits</h3>'+r.source_ids.map(id=>{const s=data.sources.find(s=>s.id===id);return s?`<p><a href="${E(s.url)}" target="_blank" rel="noopener">${E(s.name)}</a> — ${E(s.creator)}<br><span class="muted">${E(s.license)} · ${E(s.status)} · asset redistribution ${E(s.unrestricted_asset_redistribution)}</span></p>`:''}).join('')}
 if(r.resource_job_id){const job=data.quality_resource_jobs.find(j=>j.id===r.resource_job_id);if(job)html+=`<h3>Quality job resources</h3><p class="muted">Shared job capture, not per-suite isolation.</p><pre>${E(JSON.stringify(job.resources,null,2))}</pre>`}
 if(items.length){html+='<h3>Per-test metrics</h3><div class="table-wrap"><table><thead><tr><th>Test / category</th><th>Score</th><th>Tokens in / out</th><th>Prefill tok/s*</th><th>Decode tok/s</th><th>Cached tokens</th><th>Outcome</th></tr></thead><tbody>'+items.map(x=>`<tr><td>${E(x.id||x.task_id||x.category)}<span class="sub">${E(x.category||'')} ${E(x.tier||'')}</span></td><td>${percent(x.score)}</td><td>${number(x.prompt_tokens,0)} / ${number(x.completion_tokens,0)}</td><td>${number(x.prompt_tps,0)}</td><td>${number(x.decode_tps)}</td><td>${x.cache_evidence==='present'?number(x.cached_prompt_tokens,0):'unavailable'}</td><td>${x.error?'error':x.hit_token_limit||x.finish_reason==='length'?'token cap':x.passed===true?'passed':x.passed===false?'miss':'unscored'}</td></tr>`).join('')+'</tbody></table></div>'}
 $('detail-body').innerHTML=html;for(const b of document.querySelectorAll('[data-related]'))b.onclick=()=>detail(data.dyno_runs.find(r=>r.id===b.dataset.related)||data.quality_runs.find(r=>r.id===b.dataset.related));if(!$('detail').open)$('detail').showModal();
}
$('close').onclick=()=>$('detail').close();
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>setView(b.dataset.view);
for(const id of ['search','placement','context','resource-mode','protocol','status','sort'])$(id).addEventListener(id==='search'?'input':'change',()=>data&&render());
$('reset').onclick=()=>{for(const id of ['search','placement','context','status'])$(id).value='';$('sort').value='score';render()};
window.addEventListener('hashchange',()=>{if(location.hash.slice(1)!==view)setView(location.hash.slice(1))});
fetch('data/snapshot.json?v=3').then(r=>{if(!r.ok)throw new Error(`Snapshot HTTP ${r.status}`);return r.json()}).then(d=>{
 data=d;if(!data.arenas.length)throw new Error('No recorded quality protocols');
 $('snapshot').textContent=`${data.hardware} · snapshot ${stamp(data.generated_at)}`;
 $('source-list').innerHTML=data.sources.map(s=>`<article><h3><a href="${E(s.url)}" target="_blank" rel="noopener">${E(s.name)}</a></h3><p>${E(s.creator)}</p><p><strong>${E(s.license)}</strong></p><p>${E(s.use)}</p><p>${badge(s.status.replaceAll('-',' '),s.unrestricted_asset_redistribution==='not-cleared'?'warn':'good')}<br><span class="sub">Asset redistribution: ${E(s.unrestricted_asset_redistribution)}</span></p></article>`).join('');
 const standard=data.arenas[0],quality=standard.models.filter(m=>m.quality?.score!=null).sort((a,b)=>b.quality.score-a.quality.score)[0],fastest=data.dyno_setups.filter(s=>s.decode_short_tps!=null).sort((a,b)=>b.decode_short_tps-a.decode_short_tps)[0];
 $('cards').innerHTML=[['Dyno sessions',data.counts.dyno_runs,`${data.counts.archived_dyno} archived · all attempts preserved`],['Quality runs',data.counts.quality_runs,'Suites, protocols and previous attempts'],['Highest quality',percent(quality?.quality.score),quality?.name||'No comparable results'],['Fastest setup',`${number(fastest?.decode_short_tps)} tok/s`,`${fastest?.model??'—'} · ${placement(fastest?.placement)}`]].map(([title,value,sub])=>`<article class="card"><span>${E(title)}</span><strong>${E(value)}</strong><small>${E(sub)}</small></article>`).join('');
 $('protocol').innerHTML=data.arenas.map((a,i)=>`<option value="${i}">${E(a.protocol.id)}${a.protocol.standard?' · standard':''}</option>`).join('');setView(location.hash.slice(1)||'arena');
}).catch(e=>{$('snapshot').textContent='Could not load scores: '+e.message;$('snapshot').style.color='#b42318'});
