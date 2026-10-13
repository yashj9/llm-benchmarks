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
const names = {arena:'Combined leaderboard',speed:'Speed by setup',dyno:'Dyno run history',quality:'Quality run history'};
const explanations = {
 arena:'Comparable Quality scores + representative Dyno speed. Quality and speed are separate runs; their runtime settings may differ. Inspect details before comparing.',
 speed:'One row per model / engine / context / thinking / GPU placement. Medians across all active finished sessions in each setup; archives excluded.',
 dyno:'Every preserved real Dyno session, including archived and failed attempts. Reliability is a Dyno task score, not the Quality benchmark score.',
 quality:'Every preserved real Quality run. Historical benchmarks, non-standard protocols and partial runs are included here, not silently ranked.'
};
function setView(v){view=names[v]?v:'arena';location.hash=view;for(const b of document.querySelectorAll('[data-view]')){b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-pressed',b.dataset.view===view)}$('status-label').hidden=!['dyno','quality'].includes(view);$('protocol-label').hidden=view!=='arena';$('status').value='';render()}
function render(){
 const arena=data.arenas[Number($('protocol').value)||0];
 let rows = view==='arena' ? arena.models.map(m=>({...m,model:m.key,placement:m.headline?.placement})) : view==='speed'?data.dyno_setups:view==='dyno'?data.dyno_runs:data.quality_runs;
 rows=filterRows(rows,{search:$('search').value,placement:$('placement').value,status:$('status').value});
 const metric = r => view==='arena'?r.balance:view==='speed'?r.decode_short_tps:view==='dyno'?r.metrics.decode_short_tps:r.summary.weighted_score??r.summary.score;
 const sort=$('sort').value;
 rows.sort((a,b)=>sort==='model'?String(a.model).localeCompare(String(b.model)):sort==='date'?String(b.created||b.created_at||'').localeCompare(String(a.created||a.created_at||'')):(metric(a)==null)-(metric(b)==null)||((metric(b)??0)-(metric(a)??0)));
 current=rows;$('heading').textContent=names[view];$('explanation').textContent=explanations[view];$('count').textContent=`${rows.length} ${view==='arena'?'models':view==='speed'?'setups':'runs'} shown · click Details to inspect settings, metrics and per-test scores`;
 const heads = view==='arena'?['Model','Quality / 90% interval','Short / long tok/s','Dyno reliability','Balanced','Evidence']:view==='speed'?['Model / engine','Setup / context / thinking','Short / long tok/s','Reliability','Sessions / caps / errors','Evidence']:view==='dyno'?['Model / run','Status','Setup / context / thinking','Short / long tok/s','Reliability / caps','Evidence']:['Model / suite / run','Status','Thinking / max tokens','Pass / total','Weighted quality','Evidence'];
 $('thead').innerHTML='<tr>'+heads.map(h=>`<th scope="col">${E(h)}</th>`).join('')+'</tr>';
 $('tbody').innerHTML=rows.length?rows.map((r,i)=>rowHTML(r,i)).join(''):`<tr><td class="empty" colspan="6">No matching results. Reset the filters to see all runs.</td></tr>`;
 for(const b of document.querySelectorAll('[data-detail]'))b.onclick=()=>detail(current[Number(b.dataset.detail)]);
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
 }else if(view==='dyno'){
  cells=[`<span class="model">${E(r.model)}</span><span class="sub">${E(r.id)}<br>${E(stamp(r.created))}</span>`,`${badge(r.status,r.status==='finished'?'good':'warn')}${r.archived?'<br>'+badge('archived'):''}`,`${badge(placement(r.placement))}<span class="sub">${E(r.engine)} · ${context(r.context)} · thinking ${E(r.thinking)}</span>`,`<span class="num">${number(r.metrics.decode_short_tps)} / ${number(r.metrics.decode_long_tps)}</span>`,`${scoreCell(r.metrics.reliability)}<span class="sub">${r.metrics.token_limit_hits} caps · ${r.metrics.errors} errors</span>`,button];
 }else{
  cells=[`<span class="model">${E(r.name||r.model)}</span><span class="sub">${E(r.suite)} · ${E(r.id)}<br>${E(stamp(r.created))}</span>`,`${badge(r.status,r.status==='finished'?'good':'warn')}<span class="sub">${r.comparable_candidate?'Protocol recorded':'Historical / unverified protocol'}</span>`,`${E(r.thinking??'unknown')} / ${number(r.max_tokens,0)}<span class="sub">${E(placement(r.placement))} · ${E(r.engine)}</span>`,`<span class="num">${number(r.summary.passed,0)} / ${number(r.summary.n_total??r.summary.n,0)}</span>`,scoreCell(r.summary.weighted_score??null),button];
 }
 return '<tr>'+cells.map((c,j)=>`<td${j===0?' class="model"':''}>${c}</td>`).join('')+'</tr>';
}
function detail(r){
 let summary=r,items=r.items||[],related=[];
 if(r.key && r.setups){related=[...r.setups.map(s=>({label:`${placement(s.placement)} · ${context(s.context)} · thinking ${s.thinking}`,ids:s.session_ids})),...Object.entries(r.quality?.by_suite||{}).map(([suite,q])=>({label:suite,ids:[q.run]}))];
 }else if(r.session_ids){related=[{label:'Contributing Dyno sessions',ids:r.session_ids}]}
 const compact={...summary};delete compact.items;
 let html=`<p class="model">${E(r.name||r.model)}</p><p class="muted">Recorded settings only. Unknown does not mean disabled. No raw prompts or answers are published.</p><pre>${E(JSON.stringify(compact,null,2))}</pre>`;
 for(const group of related){html+=`<h3>${E(group.label)}</h3>`;for(const id of group.ids){const run=data.dyno_runs.find(x=>x.id===id)||data.quality_runs.find(x=>x.id===id);html+=`<button class="details" data-related="${E(id)}">${E(id)}</button> `;}}
 if(items.length){html+='<h3>Per-test metrics</h3><div class="table-wrap"><table><thead><tr><th>Test / category</th><th>Score</th><th>Tokens in / out</th><th>Decode tok/s</th><th>Outcome</th></tr></thead><tbody>'+items.map(x=>`<tr><td>${E(x.id||x.task_id||x.category)}<span class="sub">${E(x.category||'')} ${E(x.tier||'')}</span></td><td>${percent(x.score)}</td><td>${number(x.prompt_tokens,0)} / ${number(x.completion_tokens,0)}</td><td>${number(x.decode_tps)}</td><td>${x.error?'error':x.hit_token_limit||x.finish_reason==='length'?'token cap':x.passed===true?'passed':x.passed===false?'miss':'unscored'}</td></tr>`).join('')+'</tbody></table></div>'}
 $('detail-body').innerHTML=html;for(const b of document.querySelectorAll('[data-related]'))b.onclick=()=>detail(data.dyno_runs.find(r=>r.id===b.dataset.related)||data.quality_runs.find(r=>r.id===b.dataset.related));if(!$('detail').open)$('detail').showModal();
}
$('close').onclick=()=>$('detail').close();
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>setView(b.dataset.view);
for(const id of ['search','placement','protocol','status','sort'])$(id).addEventListener(id==='search'?'input':'change',()=>data&&render());
$('reset').onclick=()=>{for(const id of ['search','placement','status'])$(id).value='';$('sort').value='score';render()};
window.addEventListener('hashchange',()=>{if(location.hash.slice(1)!==view)setView(location.hash.slice(1))});
fetch('data/snapshot.json').then(r=>{if(!r.ok)throw new Error(`Snapshot HTTP ${r.status}`);return r.json()}).then(d=>{
 data=d;if(!data.arenas.length)throw new Error('No recorded quality protocols');
 $('snapshot').textContent=`${data.hardware} · snapshot ${stamp(data.generated_at)}`;
 const standard=data.arenas[0],quality=standard.models.filter(m=>m.quality?.score!=null).sort((a,b)=>b.quality.score-a.quality.score)[0],fastest=data.dyno_setups.filter(s=>s.decode_short_tps!=null).sort((a,b)=>b.decode_short_tps-a.decode_short_tps)[0];
 $('cards').innerHTML=[['Dyno sessions',data.counts.dyno_runs,`${data.counts.archived_dyno} archived · all attempts preserved`],['Quality runs',data.counts.quality_runs,'Suites, protocols and previous attempts'],['Highest quality',percent(quality?.quality.score),quality?.name||'No comparable results'],['Fastest setup',`${number(fastest?.decode_short_tps)} tok/s`,`${fastest?.model??'—'} · ${placement(fastest?.placement)}`]].map(([title,value,sub])=>`<article class="card"><span>${E(title)}</span><strong>${E(value)}</strong><small>${E(sub)}</small></article>`).join('');
 $('protocol').innerHTML=data.arenas.map((a,i)=>`<option value="${i}">${E(a.protocol.id)}${a.protocol.standard?' · standard':''}</option>`).join('');setView(location.hash.slice(1)||'arena');
}).catch(e=>{$('snapshot').textContent='Could not load scores: '+e.message;$('snapshot').style.color='#b42318'});
