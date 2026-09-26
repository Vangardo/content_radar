/* Shared list navigation. Catalog reads use saved data, never YouTube requests. */
labels.posts='Посты';
const listStates={},postSorts=[['observed_vph','Прирост / час'],['views','Просмотры'],['likes','Лайки'],['comments','Комментарии'],['views_per_subscriber','Просмотры / подписчики'],['published_at','Дата публикации'],['fetched_at','Последний замер'],['title','Название']];
let postRequest=0,postSearchTimer;
function listState(key){
 if(!listStates[key]){
  const p=key===state.view?new URLSearchParams(location.search):new URLSearchParams();
  const size=Number(p.get('per_page')),page=Number(p.get('page'));
  listStates[key]={page:Number.isSafeInteger(page)&&page>0?page:1,per_page:[20,50,100].includes(size)?size:20,q:p.get('q')||'',sort:p.get('sort')||({posts:'observed_vph',channels:'subs',history:'date'}[key]||''),order:p.get('order')==='asc'?'asc':'desc',scope:p.get('scope')||((p.get('favorites')==='1'||p.get('filter')==='favorites')?'favorites':'all'),format:p.get('format')||'all',research:p.get('research')||''};
 }
 return listStates[key];
}
function saveListURL(key){if(key!==state.view)return;const p=new URLSearchParams();for(const [k,v] of Object.entries(listState(key)))if(v!==''&&v!=='all')p.set(k,v);history.replaceState(null,'',location.pathname+'?'+p);}
function paginateRows(key,rows){const s=listState(key);s.page=Math.max(1,Math.min(s.page,Math.ceil(rows.length/s.per_page)||1));return rows.slice((s.page-1)*s.per_page,s.page*s.per_page);}
function pagerSlot(key,position){return `<div id="${key}-pager-${position}" data-pager="${key}" data-position="${position}"></div>`;}
function pager(key,total){
 const s=listState(key),pages=Math.max(1,Math.ceil(total/s.per_page)),start=total?(s.page-1)*s.per_page+1:0,end=Math.min(s.page*s.per_page,total);
 const nums=pages<=7?Array.from({length:pages},(_,i)=>i+1):[...new Set([1,s.page-1,s.page,s.page+1,pages])].filter(n=>n>0&&n<=pages).sort((a,b)=>a-b);
 const pageButton=(n,text,disabled=false,current=false)=>`<button class="page-button" data-page-key="${key}" data-page="${n}" aria-label="${typeof text==='number'?'Страница '+n:text}" ${disabled?'disabled':''} ${current?'aria-current="page"':''}>${text}</button>`;
 return `<nav class="pagination" aria-label="Страницы списка"><div class="page-summary" role="status"><strong>${number(start)}–${number(end)}</strong> из ${number(total)}<small>Страница ${s.page} из ${pages}</small></div><div class="page-buttons">${pageButton(s.page-1,'← Назад',s.page===1)}${nums.map((n,i)=>(i&&n-nums[i-1]>1?'<span class="page-gap" aria-hidden="true">…</span>':'')+pageButton(n,n,false,n===s.page)).join('')}${pageButton(s.page+1,'Далее →',s.page>=pages)}</div><label class="page-size">На странице<select data-page-size="${key}" aria-label="Количество на странице">${[20,50,100].map(n=>`<option ${n===s.per_page?'selected':''}>${n}</option>`).join('')}</select></label></nav>`;
}
function renderPagers(key,total){document.querySelectorAll(`[data-pager="${key}"]`).forEach(el=>el.innerHTML=pager(key,total));}
function directionLabel(order){return order==='asc'?'↑ По возрастанию':'↓ По убыванию';}
function sortControls(key,options){const s=listState(key);if(!options.some(([v])=>v===s.sort))s.sort=options[0][0];return `<label class="list-control">Сортировать<select data-list-key="${key}" data-list-field="sort">${options.map(([k,l])=>`<option value="${k}" ${s.sort===k?'selected':''}>${l}</option>`).join('')}</select></label><button class="button sort-direction" data-direction="${key}" aria-label="Изменить направление сортировки">${directionLabel(s.order)}</button>`;}
function listSelect(key,field,label,options){const s=listState(key);if(!options.some(([v])=>v===s[field]))s[field]=options[0][0];return `<label class="list-control">${label}<select data-list-key="${key}" data-list-field="${field}">${options.map(([k,l])=>`<option value="${esc(k)}" ${s[field]===k?'selected':''}>${esc(l)}</option>`).join('')}</select></label>`;}
function listSearch(key,placeholder){return `<label class="list-control list-search">Поиск<input type="search" maxlength="300" data-list-key="${key}" data-list-field="q" placeholder="${placeholder}" value="${esc(listState(key).q)}"></label>`;}
function resetButton(key){return `<button class="button subtle" data-list-reset="${key}">Сбросить фильтры</button>`;}
function sortRows(rows,get,order){const compare=(a,b)=>typeof a==='string'?a.localeCompare(b,'ru',{numeric:true}):a-b;return rows.sort((a,b)=>{const av=get(a),bv=get(b);return av==null?bv==null?0:1:bv==null?-1:(order==='asc'?1:-1)*compare(av,bv);});}
function videoTableHead(key){return `<thead><tr>${[['title','ВИДЕО / КАНАЛ'],['views','ПРОСМОТРЫ'],['views_per_subscriber','ПРОСМОТРОВ / ПОДПИСЧИК'],['observed_vph','ПРИРОСТ / ЧАС']].map(([field,label])=>`<th data-sort-header="${key}" data-sort-field="${field}" aria-sort="none">${key==='results'&&field==='title'?label:`<button data-table-key="${key}" data-table-sort="${field}">${label} <span aria-hidden="true">↕</span></button>`}</th>`).join('')}<th><span class="sr-only">Действия</span></th></tr></thead>`;}
function syncTableSort(key,sort,order){document.querySelectorAll(`[data-sort-header="${key}"]`).forEach(el=>{const selected=el.dataset.sortField===sort;el.setAttribute('aria-sort',selected?(order==='asc'?'ascending':'descending'):'none');const arrow=$('span',el);if(arrow)arrow.textContent=selected?(order==='asc'?'↑':'↓'):'↕';});}

function researchChoices(){const seen=new Set();return [['','Все исследования'],...state.boot.runs.filter(r=>{const id=r.collection_id||r.id;if(seen.has(id))return false;seen.add(id);return true;}).map(r=>[r.collection_id||r.id,r.config.name])];}
async function renderPosts(){
 $('#main').innerHTML=title('ОБЩАЯ ВЫБОРКА YOUTUBE','Посты','Все найденные видео и Shorts без дублей. Последние сохранённые замеры из ваших исследований.')+
 `<div class="list-toolbar">${listSearch('posts','Название, описание, канал или тег')}${listSelect('posts','scope','Показать',[['all','Все авторы'],['small','До 10 000 подписчиков'],['favorites','Избранное']])}${listSelect('posts','format','Формат',[['all','Все форматы'],['shorts','Shorts и кандидаты'],['video','Обычные видео'],['unknown','Формат неизвестен']])}${listSelect('posts','research','Исследование',researchChoices())}${sortControls('posts',postSorts)}${resetButton('posts')}</div>
 <div class="export-bar"><span class="field-help">Клик по заголовку столбца меняет сортировку.</span><button class="button small" data-copy-posts disabled>${icon('copy')}Копировать страницу</button></div>
 <p id="posts-message" class="field-help" role="status"></p>${pagerSlot('posts','top')}<section class="panel table-wrap" id="posts-panel"><table class="results-table">${videoTableHead('posts')}<tbody id="posts-body"></tbody></table><div id="posts-empty" hidden></div></section>${pagerSlot('posts','bottom')}
 <p class="field-help below-table">Shorts определяются по доступным признакам API; кандидаты не подтверждены. Измеренный прирост требует двух замеров от 30 минут. Данные хранятся 28 дней; здесь остаются и видео из удалённых исследований. Скрытые счётчики показаны как «—».</p>`;
 await renderPostList();
}
async function renderPostList(){
 const ticket=++postRequest,s=listState('posts'),params=new URLSearchParams(s);clearTimeout(postSearchTimer);
 $('#posts-panel').setAttribute('aria-busy','true');$('#posts-message').textContent='Обновляем список…';$('[data-copy-posts]').disabled=true;
 try{
  const result=await api('/api/posts?'+params);if(ticket!==postRequest||state.view!=='posts')return;
  state.postRows=result.items;s.page=result.page;
  $('#posts-body').innerHTML=result.items.map(videoRow).join('');
  $('#posts-empty').hidden=!!result.total;$('#posts-empty').innerHTML=result.total?'':empty('Нет подходящих постов','Измените фильтры или запустите исследование.','search',false);
  renderPagers('posts',result.total);syncTableSort('posts',s.sort,s.order);saveListURL('posts');
  $('#posts-message').textContent=`Найдено ${number(result.total)} видео · просмотр списка не расходует квоту`;
  $('[data-copy-posts]').disabled=!result.items.length;
 }catch(e){if(ticket===postRequest){$('#posts-message').textContent=e.message;toast(e.message,true);}}
 finally{if(ticket===postRequest)$('#posts-panel')?.setAttribute('aria-busy','false');}
}

async function renderChannels(){
 channelRows=(await api('/api/entities/channels')).channels;
 $('#main').innerHTML=title('АВТОРЫ В ВАШЕЙ ВЫБОРКЕ','Каналы','Показатели всего канала: подписчики, просмотры и публикации.')+
 `<div class="list-toolbar">${listSearch('channels','Название или адрес канала')}${listSelect('channels','scope','Показать',[['all','Все каналы'],['small','До 10 000 подписчиков'],['favorites','Избранные']])}${sortControls('channels',[['subs','Подписчики'],['views','Просмотры'],['subs-rate','Рост подписчиков / час'],['views-rate','Рост просмотров / час'],['video_count','Количество видео'],['fetched_at','Последний замер'],['title','Название']])}${resetButton('channels')}</div>
 <div class="entity-toolbar">${refreshKey()}<button class="button" data-entity="refresh-favorites" data-kind="channels">${icon('refresh')}Обновить избранные каналы</button></div><p class="field-help">${channelRows.length} каналов из исследований. Обновление — до 50 каналов за 1 общую единицу API, без поиска. Число подписчиков округляется YouTube.</p>
 ${pagerSlot('channels','top')}<div id="channel-list" class="channel-grid"></div>${pagerSlot('channels','bottom')}`;
 renderChannelList();
}
function renderChannelList(){
 const s=listState('channels'),q=s.q.trim().toLocaleLowerCase();
 const rows=channelRows.filter(c=>(s.scope!=='favorites'||c.favorite)&&(s.scope!=='small'||c.subs!=null&&c.subs<=10000)&&[c.title,c.custom_url].join(' ').toLocaleLowerCase().includes(q));
 sortRows(rows,c=>s.sort.endsWith('-rate')?c.last_change?.metrics?.[s.sort.split('-')[0]]?.per_hour:c[s.sort],s.order);
 $('#channel-list').innerHTML=rows.length?paginateRows('channels',rows).map(channelCard).join(''):empty('Нет подходящих каналов','Попробуйте изменить фильтры или запустите исследование.','chart',false);
 paginateRows('channels',rows);renderPagers('channels',rows.length);saveListURL('channels');
 $('[data-entity="refresh-favorites"][data-kind="channels"]').disabled=!channelRows.some(c=>c.favorite);
}

function renderHistory(){
 $('#main').innerHTML=title('ВАШ ИССЛЕДОВАТЕЛЬСКИЙ ЖУРНАЛ','Мои исследования','Исследования и их последние операции. Откройте исследование, чтобы увидеть всю историю замеров.',`<div class="button-row"><a class="button" href="/trash">${icon('trash')}Удалённые</a><a class="button primary" href="/new">${icon('radar')}Новое исследование</a></div>`)+
 `<div class="list-toolbar">${listSearch('history','Название или поисковый запрос')}${listSelect('history','scope','Показать',[['all','Все исследования'],['monitor','Мониторинг включён'],['once','Без активного мониторинга']])}${sortControls('history',[['date','Последняя операция'],['name','Название'],['videos','Количество видео']])}${resetButton('history')}</div>${pagerSlot('history','top')}<div id="research-list" class="history-list"></div>${pagerSlot('history','bottom')}`;
 renderResearchList();
}
function renderResearchList(){
 const s=listState('history'),q=s.q.trim().toLocaleLowerCase(),collections=new Map();
 for(const r of state.boot.runs){const id=r.collection_id||r.id;if(!collections.has(id))collections.set(id,[]);collections.get(id).push(r);}
 const scheduled=id=>state.boot.schedules?.find(x=>x.collection_id===id)?.enabled;
 const rows=[...collections.values()].filter(items=>{const r=items[0],on=scheduled(r.collection_id||r.id);return (s.scope!=='monitor'||on)&&(s.scope!=='once'||!on)&&[r.config.name,...r.config.seeds].join(' ').toLocaleLowerCase().includes(q);});
 sortRows(rows,items=>s.sort==='name'?items[0].config.name:s.sort==='videos'?items[0].stats.videos:items[0].created_at,s.order);
 $('#research-list').innerHTML=rows.length?paginateRows('history',rows).map(items=>{const r=items[0];return `<article class="collection-card"><a class="history-card" href="/runs/${r.id}"><div class="history-main"><span class="history-symbol">${icon('folder')}</span><div><h3>${esc(r.config.name)}</h3><p>${date(r.created_at)} · ${esc(operationLabels[r.kind]||r.kind)}${scheduled(r.collection_id||r.id)?' · Мониторинг включён':''}</p></div></div><div class="history-meta"><div class="stat-mini">${number(r.stats.videos)}<small>видео в списке</small></div>${badge(r)}${icon('arrow')}</div></a><div class="collection-actions">${deleteResearchButton(r.collection_id||r.id)}</div>${items.length>1?`<details class="history-operations"><summary>Последние операции · ${items.length}</summary>${items.map(x=>`<a href="/runs/${x.id}">${date(x.created_at)} · ${esc(operationLabels[x.kind]||x.kind)} ${badge(x)}</a>`).join('')}</details>`:''}</article>`;}).join(''):empty('Нет подходящих исследований','Измените фильтры или создайте новое исследование.','folder');
 paginateRows('history',rows);renderPagers('history',rows.length);saveListURL('history');
}

const renderBeforeLists=render;
render=async function(){if(state.view==='posts'){decorate();await renderPosts();}else await renderBeforeLists();};
async function redrawList(key){if(key==='posts')await renderPostList();else if(key==='channels')renderChannelList();else if(key==='history')renderResearchList();else if(key==='results')renderTable();}
function syncListControls(key){const s=listState(key);document.querySelectorAll(`[data-list-key="${key}"]`).forEach(el=>el.value=s[el.dataset.listField]);const direction=$(`[data-direction="${key}"]`);if(direction)direction.textContent=directionLabel(s.order);}
document.addEventListener('input',e=>{
 const el=e.target;if(el.dataset.listField!=='q')return;const key=el.dataset.listKey,s=listState(key);s.q=el.value;s.page=1;
 if(key==='posts'){++postRequest;clearTimeout(postSearchTimer);$('[data-copy-posts]').disabled=true;postSearchTimer=setTimeout(()=>redrawList(key),250);}else redrawList(key);
});
document.addEventListener('change',e=>{
 const el=e.target;
 if(el.dataset.pageSize){const key=el.dataset.pageSize;listState(key).per_page=Number(el.value);listState(key).page=1;redrawList(key);}
 if(el.dataset.listField&&el.dataset.listField!=='q'){const key=el.dataset.listKey,s=listState(key);s[el.dataset.listField]=el.value;s.page=1;redrawList(key);}
});
document.addEventListener('click',async e=>{
 const b=e.target.closest('button');if(!b||b.disabled)return;
 if(b.dataset.pageKey){const key=b.dataset.pageKey;listState(key).page=Number(b.dataset.page);await redrawList(key);const top=$(`#${key}-pager-top`);top?.scrollIntoView({block:'nearest'});$('[aria-current="page"]',top)?.focus({preventScroll:true});}
 if(b.dataset.direction){const key=b.dataset.direction,s=listState(key);s.order=s.order==='asc'?'desc':'asc';s.page=1;syncListControls(key);await redrawList(key);}
 if(b.hasAttribute('data-result-direction')){state.sortTouched=true;state.sortOrder=(state.sortOrder||(state.sort==='age_days'?'asc':'desc'))==='asc'?'desc':'asc';listState('results').page=1;renderTable();}
 if(b.dataset.tableKey){const key=b.dataset.tableKey,field=b.dataset.tableSort;
  if(key==='results'){state.sortOrder=state.sort===field&&state.sortOrder!=='asc'?'asc':'desc';state.sort=field;state.sortTouched=true;const select=$('#result-sort');if(![...select.options].some(o=>o.value===field))select.add(new Option('Просмотры / подписчики',field));select.value=field;}
  else{const s=listState(key);s.order=s.sort===field&&s.order==='desc'?'asc':'desc';s.sort=field;syncListControls(key);}
  listState(key).page=1;await redrawList(key);
 }
 if(b.dataset.listReset){const key=b.dataset.listReset,s=listState(key);Object.assign(s,{page:1,q:'',scope:'all',format:'all',research:''});syncListControls(key);await redrawList(key);}
 if(b.hasAttribute('data-copy-posts')){try{await copy(videoText(state.postRows||[]));}catch(err){toast(err.message,true);}}
});
