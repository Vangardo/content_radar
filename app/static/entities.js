/* Channel catalog, signed changes and explicit per-entity refreshes. */
labels.channels='Каналы';labels.channel='Карточка канала';
let channelRows=[],channelMetric='subs',entityBusy=false;
function deltaBadge(change,field){
 const m=change?.metrics?.[field],delta=m?.delta;
 if(delta==null)return '<span class="delta delta-empty">Нет сравнения</span>';
 const sign=delta>0?'+':delta<0?'−':'';
 return `<span class="delta ${delta>0?'delta-up':delta<0?'delta-down':'delta-flat'}" title="С предыдущего фактического замера">${sign}${number(Math.abs(delta))}${m.percent==null?'':` <small>(${m.percent>0?'+':''}${number(m.percent,1)}%)</small>`}</span>`;
}
function metricCard(entity,field,label){const m=entity.last_change?.metrics?.[field];return `<div class="metric"><small>${label}</small><strong>${number(entity[field])}</strong>${deltaBadge(entity.last_change,field)}<div class="metric-foot">${m?.per_hour!=null?`${m.per_hour>0?'+':''}${number(m.per_hour,1)} / час`:entity[field]==null?'Нет публичных данных':'Нужны два замера'}</div></div>`;}
function changeCaption(change){return change?.from_at?`С ${preciseDate(change.from_at)} до ${preciseDate(change.to_at)} · интервал ${interval(change.interval_hours)}.${change.short_interval?' Короткий интервал: скорость может сильно колебаться.':''}`:'Пока один замер. Обновите позже, чтобы увидеть изменения.';}
function refreshKey(chosen){const keys=readyKeys();return `<div class="refresh-key">${selectField('entity-key','Ключ для обновления',keys.map(k=>[k.id,k.name]),keys.some(k=>k.id===chosen)?chosen:keys[0]?.id)}</div>`;}
function entityButton(kind,id,label='Обновить сейчас'){return `<button class="button primary" data-entity="refresh" data-kind="${kind}" data-id="${esc(id)}" ${entityBusy?'disabled':''}>${icon('refresh')}${label}</button>`;}
function channelCard(c){return `<article class="panel channel-card"><div class="channel-card-head"><div><span class="source-pill">${c.subs!=null&&c.subs<=10000?'Небольшой канал':c.subs==null?'Размер неизвестен':'Канал YouTube'}</span><h2><a href="/channels/${encodeURIComponent(c.id)}">${esc(c.title)}</a></h2><p>${esc(c.custom_url||c.country||'YouTube')}</p></div><button class="icon-button ${c.favorite?'selected':''}" data-entity="favorite-channel" data-id="${esc(c.id)}" aria-label="${c.favorite?'Убрать канал из избранного':'Добавить канал в избранное'}" aria-pressed="${!!c.favorite}">${icon('bookmark')}</button></div><div class="channel-card-metrics"><div><small>Подписчики</small><strong>${number(c.subs)}</strong>${deltaBadge(c.last_change,'subs')}</div><div><small>Просмотры</small><strong>${compact(c.views)}</strong>${deltaBadge(c.last_change,'views')}</div><div><small>Видео</small><strong>${number(c.video_count)}</strong>${deltaBadge(c.last_change,'video_count')}</div></div><p class="field-help">Замер: ${date(c.fetched_at)}${c.expired?' · данные устарели':''}</p><div class="button-row"><a class="button" href="/channels/${encodeURIComponent(c.id)}">Открыть канал ${icon('arrow')}</a>${entityButton('channels',c.id,'Обновить')}</div></article>`;}
function channelChart(snapshots,field){const points=snapshots.filter(s=>s[field]!=null);if(!points.length)return '<p class="field-help">Пока нет публичных данных этого показателя.</p>';const start=points[0].observed_at,end=points.at(-1).observed_at,min=Math.min(...points.map(s=>s[field])),max=Math.max(...points.map(s=>s[field]));const x=t=>30+(end===start?370:(t-start)/(end-start)*740),y=v=>160-(v-min)/(max-min||1)*130;return `<svg class="channel-chart" viewBox="0 0 800 190" role="img" aria-label="Фактические замеры показателя канала"><line x1="30" y1="160" x2="770" y2="160" class="chart-axis"/><polyline fill="none" points="${points.map(s=>`${x(s.observed_at)},${y(s[field])}`).join(' ')}"/>${points.map(s=>`<circle cx="${x(s.observed_at)}" cy="${y(s[field])}" r="4"><title>${preciseDate(s.observed_at)}: ${number(s[field])}</title></circle>`).join('')}</svg><div class="chart-range"><span>${date(start)}</span><span>${number(min)} → ${number(max)} · диапазон</span><span>${date(end)}</span></div>`;}
function snapshotCells(current,previous,field){const value=current[field],delta=value!=null&&previous?.[field]!=null?value-previous[field]:null;return `<td>${number(value)}${delta==null?'':`<small class="delta ${delta>0?'delta-up':delta<0?'delta-down':'delta-flat'}">${signedCount(delta)}</small>`}</td>`;}
function channelHistory(rows){return `<div class="entity-table-scroll"><table class="snapshot-table"><thead><tr><th>Замер · Варшава</th><th>Подписчики</th><th>Просмотры</th><th>Видео</th></tr></thead><tbody>${rows.map((r,i)=>({r,i})).slice(-30).reverse().map(({r,i})=>`<tr><td>${preciseDate(r.observed_at)}</td>${['subs','views','video_count'].map(f=>snapshotCells(r,rows[i-1],f)).join('')}</tr>`).join('')}</tbody></table></div>`;}
async function renderChannel(){
 state.channelDetail=await api('/api/entities/channels/'+encodeURIComponent(state.runId));const {entity:c,snapshots,videos}=state.channelDetail;state.saved=videos;
 $('#main').innerHTML=`<a class="back-link" href="/channels">← Все каналы</a>`+title('КАНАЛ YOUTUBE',esc(c.title),esc(c.custom_url||'Общий рост канала'),`<div class="button-row">${entityButton('channels',c.id)}<button class="button" data-entity="favorite-channel" data-id="${esc(c.id)}" aria-pressed="${!!c.favorite}">${icon('bookmark')}${c.favorite?'В избранном':'В избранное'}</button><a class="button" href="https://www.youtube.com/channel/${encodeURIComponent(c.id)}" target="_blank" rel="noopener noreferrer">YouTube ${icon('external')}</a></div>`)+
 `${refreshKey(c.credential_id)}<p class="field-help">Последний замер: ${date(c.fetched_at)} · обновление 1 канала — 1 общая единица API, без поиска.</p><div class="results-metrics entity-metrics">${metricCard(c,'subs','Подписчики')}${metricCard(c,'views','Все просмотры канала')}${metricCard(c,'video_count','Публичные видео')}</div><p class="field-help">${changeCaption(c.last_change)} Подписчики округляются YouTube; изменение приблизительное. Отрицательное значение может означать отписки, удаление видео или корректировку счётчика. Показатели канала включают все форматы.</p>
 <section class="panel chart-panel"><div class="panel-head"><div><h2>История канала</h2><p>Реальные значения, полученные из YouTube</p></div>${selectField('channel-metric','Показатель',[['subs','Подписчики'],['views','Просмотры'],['video_count','Количество видео']],channelMetric)}</div><div class="panel-body" id="channel-chart">${channelChart(snapshots,channelMetric)}</div><div class="panel-body"><details><summary>Таблица замеров · ${snapshots.length}</summary>${channelHistory(snapshots)}<p class="field-help">Последние 30 замеров. Копирование включает всю доступную историю за срок хранения.</p></details></div></section>
 <details class="panel research-controls"><summary>Описание и данные канала</summary><div class="panel-body"><div class="video-description">${esc(c.description||'Описание пока не получено. Обновите канал.')}</div><p class="field-help">Создан: ${date(Date.parse(c.published_at)/1000)} · страна: ${esc(c.country||'не указана')}</p><button class="button" data-entity="copy-channel">${icon('copy')}Скопировать канал и историю</button>${c.youtube?`<details class="metadata-raw"><summary>Публичные поля YouTube</summary><pre tabindex="0">${esc(JSON.stringify(c.youtube,null,2))}</pre></details>`:''}</div></details>
 <div class="section-label"><h2>Видео этого канала в нашей выборке</h2><span>${videos.length} видео · не весь канал</span></div>${videoTable(videos)}
 <section class="panel panel-body"><form id="channel-note-form"><div class="field"><label for="channel-note">Заметка о канале</label><textarea id="channel-note" maxlength="5000">${esc(c.note||'')}</textarea></div><button class="button" type="submit">Сохранить заметку</button><div class="inline-error" role="alert"></div></form></section>`;
}
function videoTable(videos){return videos.length?`<section class="panel table-wrap"><table class="results-table"><thead><tr><th>ВИДЕО / КАНАЛ</th><th>ПРОСМОТРЫ</th><th>ПРОСМОТРОВ / ПОДПИСЧИК</th><th>ПРИРОСТ / ЧАС</th><th>Действия</th></tr></thead><tbody>${videos.map(videoRow).join('')}</tbody></table></section>`:empty('Пока нет видео','Добавьте видео в избранное из результатов исследования.','bookmark',false);}
const originalRenderSaved=renderSaved;
renderSaved=function(){
 originalRenderSaved();const heading=$('#main .page-heading');
 if(heading)heading.insertAdjacentHTML('afterend',`<div class="entity-toolbar">${refreshKey()}<button class="button primary" data-entity="refresh-favorites" data-kind="videos" ${state.saved.some(v=>v.favorite)?'':'disabled'}>${icon('refresh')}Обновить избранные видео · ${Math.ceil(state.saved.filter(v=>v.favorite).length/50)} ед.</button><a class="button" href="/channels?filter=favorites">Избранные каналы ${icon('arrow')}</a></div><p class="field-help">Обновляются все видео с закладкой. Отдельное видео можно обновить в его карточке; поиск не расходуется.</p>`);
};
const renderBeforeEntities=render;
render=async function(){if(state.view==='channels'||state.view==='channel'){decorate();if(state.view==='channels'){await renderChannels();}else await renderChannel();}else await renderBeforeEntities();};

async function waitForEntityJob(id){
 // Continue showing queue progress; a slow request never implies completion.
 for(let i=0;i<120;i++){const job=await api('/api/entities/jobs/'+id);if(!['queued','running'].includes(job.status))return job;await new Promise(r=>setTimeout(r,1000));}
 throw new Error('Обновление ещё в очереди или выполняется. Не запускайте повторно: откройте карточку позже.');
}
async function refreshEntity(kind,ids,favorites=false){
 const key=$('#entity-key')?.value||state.videoDetail?.video?.credential_id;
 const job=await api(`/api/entities/${kind}/refresh`,{method:'POST',body:{ids,favorites,credential_id:key||null,request_id:crypto.randomUUID()}});
 const done=await waitForEntityJob(job.id);if(done.status!=='completed'){throw new Error((done.error||'Не удалось обновить')+` Обновлено: ${done.result.updated||0} из ${done.result.requested||job.requested}.`);}
 toast(`Обновлено: ${done.result.updated}. Расход: ${done.result.general_units} общих единиц, без поиска.`);
}
async function refreshVideoCard(id){
 if(state.view==='run'){
  const requestedAt=Date.now()/1000;
  for(let attempt=0;attempt<2;attempt++){
   const created=await api(`/api/runs/${state.runId}/refresh`,{method:'POST',body:{video_ids:[id],request_id:crypto.randomUUID()}});
   let result;
   for(let i=0;i<120;i++){result=await api('/api/runs/'+created.id);if(!active(result.run))break;await new Promise(r=>setTimeout(r,1000));}
   if(active(result.run))throw new Error('Обновление выполняется. Результат появится в истории исследования.');
   if(result.run.status!=='completed')throw new Error(result.run.error||'Не удалось обновить видео');
   const updated=result.videos.find(v=>v.video_id===id);
   if(updated&&!updated.unavailable&&updated.fetched_at>=requestedAt){
    clearTimeout(pollTimer);state.runId=created.id;state.result=result;state.followLatest=true;history.replaceState(null,'','/runs/'+created.id);renderRun();schedulePoll();await openVideo(id);toast('Обновлено только выбранное видео. Новый снимок сохранён.');return;
   }
   if(result.run.selection?.includes(id))throw new Error('YouTube не вернул видео. Предыдущие данные сохранены.');
  }
  throw new Error('Исследование занято. Повторите после завершения текущей операции.');
 }
 await refreshEntity('videos',[id]);
 if(state.view==='saved'){state.saved=await api('/api/saved');renderSaved();}
 else if(state.view==='channel')await renderChannel();
 else if(state.view==='posts')await renderPostList();
 await openVideo(id);
}
document.addEventListener('click',async event=>{
 const b=event.target.closest('[data-entity]');if(!b||b.disabled||entityBusy)return;const action=b.dataset.entity;
 b.disabled=true;const before=b.innerHTML;
 try{
  if(['refresh','refresh-video','refresh-favorites'].includes(action)){entityBusy=true;b.innerHTML=icon('refresh')+'Обновляем…';}
  if(action==='refresh'){await refreshEntity(b.dataset.kind,[b.dataset.id]);if(state.view==='channels')await renderChannels();else await renderChannel();}
  if(action==='refresh-video')await refreshVideoCard(b.dataset.id);
  if(action==='refresh-favorites'){await refreshEntity(b.dataset.kind,[],true);if(state.view==='channels')await renderChannels();else{state.saved=await api('/api/saved');renderSaved();}}
  if(action==='favorite-channel'){const c=state.view==='channel'?state.channelDetail.entity:channelRows.find(x=>x.id===b.dataset.id);await api(`/api/entities/channels/${encodeURIComponent(c.id)}/note`,{method:'PUT',body:{favorite:!c.favorite,text:c.note||''}});c.favorite=!c.favorite;if(state.view==='channel')await renderChannel();else renderChannelList();toast(c.favorite?'Канал добавлен в избранное':'Канал убран из избранного');}
  if(action==='copy-channel')await copy(JSON.stringify(state.channelDetail,null,2));
 }catch(error){toast(error.message,true);}finally{entityBusy=false;b.disabled=false;b.innerHTML=before;document.querySelectorAll('[data-entity="refresh"]').forEach(el=>el.disabled=false);}
});
document.addEventListener('change',e=>{if(e.target.id==='channel-metric'){channelMetric=e.target.value;$('#channel-chart').innerHTML=channelChart(state.channelDetail.snapshots,channelMetric);}});

document.addEventListener('submit',async e=>{if(e.target.id!=='channel-note-form')return;e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{const c=state.channelDetail.entity;await api(`/api/entities/channels/${encodeURIComponent(c.id)}/note`,{method:'PUT',body:{favorite:c.favorite,text:$('#channel-note').value}});c.note=$('#channel-note').value;toast('Заметка сохранена');}catch(error){$('.inline-error',e.target).textContent=error.message;}finally{b.disabled=false;}});
