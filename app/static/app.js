/* Local UI. External titles and user notes always pass through HTML escaping. */
const $ = (s, parent = document) => parent.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  radar:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><path d="m12 12 7-7"/><circle cx="16" cy="8" r="1"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  bookmark:'<path d="M6 4h12v17l-6-4-6 4z"/>',
  settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="currentColor" stroke="none"/><circle cx="16" cy="17" r="3" fill="currentColor" stroke="none"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
  external:'<path d="M14 4h6v6m0-6L10 14M10 4H4v16h16v-6"/>',
  play:'<rect x="3" y="5" width="18" height="14" rx="4"/><path d="m10 9 5 3-5 3z"/>',
  key:'<circle cx="8" cy="9" r="4"/><path d="m11 12 9 9m-5-5 3-3m0 6 3-3"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6z"/><path d="m8 12 3 3 5-6"/>',
  spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
  tech:'<rect x="5" y="5" width="14" height="14" rx="3"/><path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3"/>',
  film:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4m-4 8h4M17 8h4m-4 8h4"/>',
  edit:'<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14z"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  chart:'<path d="M4 4v16h16M8 15l4-6 4 3 4-8"/>',
  copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V3H3v13h5"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
  more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  folder:'<path d="M3 7V4h7l3 3h8v13H3z"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.radar}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
const labels = {scan:'Исследование', history:'История', saved:'Сохранённое', settings:'Настройки', run:'Результаты исследования'};
const statuses = {queued:'В очереди',running:'Выполняется',completed:'Завершено',partial:'Частично',failed:'Ошибка',waiting_quota:'Лимит квоты',cancelled:'Отменено',interrupted:'Прервано'};
const active = r => ['queued','running'].includes(r.status);
const state = {view:document.body.dataset.view, runId:document.body.dataset.runId, boot:null, result:null, saved:[], filter:'small', sort:'candidate_score', query:'', search:'', config:null, group:'', selected:new Set(), actionDepth:null, sortTouched:false};
const number = (v, decimals=0) => v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toLocaleString('ru-RU',{maximumFractionDigits:decimals});
const compact = v => v == null ? '—' : Number(v).toLocaleString('ru-RU',{notation:'compact',maximumFractionDigits:1});
const date = ts => ts ? new Date(ts*1000).toLocaleString('ru-RU',{timeZone:'Europe/Warsaw',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}) : '—';
const preciseDate = ts => new Date(ts*1000).toLocaleString('ru-RU',{timeZone:'Europe/Warsaw',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const age = days => days == null ? 'Возраст неизвестен' : days < 1 ? `${Math.max(1,Math.floor(days*24))} ч назад` : `${Math.floor(days)} дн. назад`;
const interval = hours => hours < 1/60 ? `${Math.max(1,Math.round(hours*3600))} с` : hours < 1 ? `${number(hours*60,1)} мин` : `${number(hours,1)} ч`;
const duration = seconds => seconds == null ? '' : `${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
const badge = r => `<span class="status-pill ${esc(r.status)}">${esc(statuses[r.status] || r.status)}</span>`;
const button = (text,action,ico,extra='') => `<button class="button" type="button" data-action="${action}" ${extra}>${ico?icon(ico):''}${text}</button>`;
const empty = (title,description,ico='folder',cta=true) => `<div class="panel empty-state"><div class="empty-icon">${icon(ico)}</div><h2>${title}</h2><p>${description}</p>${cta?`<a class="button primary" href="/new">Новое исследование ${icon('arrow')}</a>`:''}</div>`;
let toastTimer, pollTimer;
function toast(text, error=false){const el=$('#toast');el.textContent=text;el.className='toast'+(error?' error':'');el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,5000);}
async function api(path,options={}){
  let response;
  try{response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-CSRF-Token':$('meta[name=csrf-token]').content,...options.headers},body:options.body===undefined?undefined:JSON.stringify(options.body)});}catch{throw new Error('Приложение недоступно. Проверьте, что локальный сервер запущен.');}
  if(response.status===401&&state.boot?.server_mode){location.href='/login';throw new Error('Войдите заново');}
  let data;
  try{data=await response.json();}catch{throw new Error(response.ok?'Сервер вернул некорректный ответ. Обновите страницу.':`Сервер временно не может выполнить запрос (HTTP ${response.status}). Попробуйте позже.`);}
  if(!response.ok)throw new Error(data?.error||`Не удалось выполнить действие (HTTP ${response.status}).`);return data;
}
function title(eyebrow,heading,sub,right='') {return `<div class="page-heading"><div><div class="eyebrow">${eyebrow}</div><h1>${heading}</h1><p>${sub}</p></div>${right}</div>`;}
function decorate(){
  let warning=$('#worker-warning');
  const workerError=state.boot.worker_error||(!state.boot.worker_alive?'Фоновый мониторинг остановлен. Требуется проверка сервера.':'');
  if(workerError&&!warning){warning=document.createElement('div');warning.id='worker-warning';warning.className='notice warning';warning.setAttribute('role','status');$('#main').before(warning);}
  if(warning){warning.hidden=!workerError;warning.textContent=workerError;}
  $('#page-label').textContent=labels[state.view];
  document.querySelectorAll('[data-nav]').forEach(el=>{const current=el.dataset.nav===(state.view==='run'?'history':state.view==='channel'?'channels':state.view==='trash'?'history':state.view);el.classList.toggle('active',current);if(current)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  const b=state.boot, key={...b.credential,configured:b.credentials?b.credentials.some(k=>k.configured&&k.enabled):b.credential.configured};
  $('#connection').innerHTML=`<span class="status-dot ${key.configured?'':'off'}"></span>${key.configured?'Ключ API сохранён':'YouTube не подключён'}`;
  const latest=[...new Map([...b.runs].reverse().map(r=>[r.collection_id||r.id,r])).values()].reverse();
  $('#history-count').textContent=latest.length;
  $('#recent-runs').innerHTML=latest.length?latest.slice(0,4).map(r=>`<a href="/runs/${r.id}"><span class="recent-dot"></span><span>${esc(r.config.name)}</span></a>`).join(''):'<p>Здесь появится история исследований.</p>';
}
function defaultConfig(profile='ai', language='en'){
  const p=state.boot.presets[profile];const ru={ai:['ИИ агенты','локальные нейросети','новые ИИ инструменты'],tech:['новые смартфоны','обзор ноутбука','новые гаджеты'],film:['новые трейлеры фильмов','новые сериалы','обзор фильма'],custom:[]};
  return {name:p.name,profile,language,region:'US',seeds:language==='ru'?ru[profile]:p.seeds,days:30,max_results:100,min_views:1000,max_subscribers:10000,min_duration:0,max_duration:0,excluded_words:[],excluded_categories:p.excluded_categories,order:'mixed',extract_phrases:true,force:false};
}
function keyPanel(){
  const key=state.boot.credential;
  return `<div class="panel"><div class="panel-body"><div class="key-symbol">${icon(key.configured?'check':'key')}</div><h3>${key.configured?'YouTube готов к исследованию':'Начните с ключа API'}</h3><p>${key.configured?'Ключ сохранён в защищённом хранилище. Доступ к YouTube проверится при первом сканировании.':'Подключите YouTube Data API, чтобы искать видео и получать их статистику.'}</p>${key.configured?`<div class="rail-caption">${icon('shield')}Fingerprint <span class="mono">${esc(key.fingerprint)}</span></div><a class="hint-link" href="/settings">Управление ключом ${icon('arrow')}</a>`:keyForm()}
  ${key.error?`<div class="error-message">${esc(key.error)}</div>`:''}</div></div>`;
}
function keyForm(){return `<form class="key-form" id="key-form"><label class="field-label" for="api-key">YouTube Data API key</label><input id="api-key" name="api_key" type="password" autocomplete="off" spellcheck="false" placeholder="Вставьте ключ из Google Cloud" minlength="20" maxlength="200" required><button type="submit" class="button primary full">${icon('key')}Сохранить ключ</button><div class="inline-error" role="alert"></div></form><div class="rail-caption">${icon('shield')}${state.boot.server_mode?'Ключ зашифрован на сервере':'Ключ в системном хранилище'}</div><a class="hint-link" href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer">Получить ключ в Google Cloud ${icon('external')}</a>`;}
function inputField(name,label,value,type='number',min=0,max=1000000000){return `<div class="field"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}" ${type==='number'?`min="${min}" max="${max}"`:''}></div>`;}
function selectField(name,label,options,value){return `<div class="field"><label for="${name}">${label}</label><select id="${name}" name="${name}">${options.map(([v,t])=>`<option value="${v}" ${String(v)===String(value)?'selected':''}>${t}</option>`).join('')}</select></div>`;}
function renderScan(){
  const b=state.boot,c=state.config||(state.config=defaultConfig()), running=b.runs.find(active);
  $('#main').innerHTML=title('ОТ СИГНАЛА К ИДЕЕ','Что взлетает у малых каналов?','Ищите идеи в своей теме: небольшая аудитория, заметные просмотры и измеренный рост.',`<span class="source-pill">${icon('play')}YouTube Data API</span>`)+
    `<div class="overview-strip"><div class="overview-item"><span class="overview-icon">${icon('radar')}</span><div><small>Исследований</small><strong>${new Set(b.runs.map(r=>r.collection_id||r.id)).size}<span>в вашей истории</span></strong></div></div><div class="overview-item"><span class="overview-icon">${icon('search')}</span><div><small>Поисковых запросов сегодня</small><strong>${b.quota.search_used}<span>/ ${b.quota.search_limit}</span></strong></div></div><div class="overview-item"><span class="overview-icon">${icon('clock')}</span><div><small>Последний запуск</small><strong class="last-run">${b.runs.length?date(b.runs[0].created_at):'—'}</strong></div></div></div>
    ${running?`<div class="notice">Исследование уже выполняется. <a class="text-link" href="/runs/${running.id}">Открыть прогресс →</a></div>`:''}
    <div class="scan-layout"><section class="panel"><div class="panel-head"><div><h2>Новое исследование</h2><p>Задайте направление — начнём с конкретных видео.</p></div><span class="step-label">01 / ПОИСК</span></div><form id="scan-form" class="panel-body">
      <div class="field"><span class="field-label">Направление</span><div class="profile-tabs" role="group" aria-label="Направление исследования">${[['ai','AI и нейросети','spark'],['tech','Технологии','tech'],['film','Кино и сериалы','film'],['custom','Своё','edit']].map(([id,name,ico])=>`<button type="button" class="profile-tab ${c.profile===id?'selected':''}" data-action="profile" data-value="${id}" aria-pressed="${c.profile===id}">${icon(ico)}${name}</button>`).join('')}</div></div>
      <div class="field"><label for="seeds">Что ищем?</label><textarea id="seeds" name="seeds" required maxlength="1200" placeholder="Например: локальные нейросети\nИИ агенты для работы">${esc(c.seeds.join('\n'))}</textarea><span class="field-help">Один запрос на строку. До 6 запросов на исследование.</span></div>
      <div class="field-row">${selectField('language','Язык контента',[['en','Английский'],['ru','Русский']],c.language)}${selectField('days','Опубликовано за',[[7,'7 дней'],[14,'14 дней'],[30,'30 дней'],[90,'90 дней'],[180,'180 дней'],[365,'Год']],c.days)}${selectField('max_results','Глубина на запрос',[[50,'До 50 · 1 страница'],[100,'До 100 · 2 страницы'],[200,'До 200 · 4 страницы']],Math.max(50,c.max_results))}</div>
      <div class="small-focus">${inputField('max_subscribers','Небольшой канал · до подписчиков',c.max_subscribers||10000,'number',1)}<p class="field-help">По умолчанию до 10 000. Неизвестный размер показываем отдельно. Считаем по текущим данным YouTube.</p></div>
      <details><summary>${icon('settings')}Параметры и фильтры</summary><div class="field-row two">${inputField('name','Название исследования',c.name,'text')}${inputField('region','Регион поиска (код страны)',c.region,'text')}${inputField('min_views','Минимум просмотров',c.min_views)}${inputField('min_duration','Длительность от, секунд',c.min_duration,'number',0,86400)}${inputField('max_duration','Длительность до · 0 = любая',c.max_duration,'number',0,86400)}</div>
      ${selectField('order','Порядок поиска YouTube',[['mixed','Популярные + свежие'],['viewCount','Самые просматриваемые'],['date','Самые новые'],['relevance','Самые релевантные']],c.order)}
      <div class="field"><label for="excluded_words">Исключить слова · через запятую</label><input id="excluded_words" name="excluded_words" value="${esc(c.excluded_words.join(', '))}" placeholder="Например: реклама, стрим"></div>
      <div class="field"><label for="excluded_categories">Исключить категории YouTube · ID через запятую</label><input id="excluded_categories" name="excluded_categories" value="${esc(c.excluded_categories.join(', '))}" placeholder="Например: 10, 17, 20"><span class="field-help">1 — кино, 10 — музыка, 17 — спорт, 20 — игры. Пусто — без исключений.</span></div>
      <label class="check-label"><input type="checkbox" name="extract_phrases" ${c.extract_phrases?'checked':''}>Показать очевидные группы по названиям</label><label class="check-label"><input type="checkbox" name="force" ${c.force?'checked':''}>Запросить поиск и статистику заново, минуя кэш</label><p class="field-help">Язык — предпочтение YouTube, а не строгий фильтр. В режиме «Популярные + свежие» 100 результатов = одна страница популярных и одна свежих, в том же бюджете. При глубине 50 — одна свежая страница. Дубли объединяются.</p></details>
      <div id="scan-error" class="inline-error" role="alert"></div><div class="form-bottom"><div class="form-estimate"><strong id="cost-estimate">До ${new Set(c.seeds).size*Math.ceil(c.max_results/50)} поисковых вызовов</strong>По 50 видео на страницу · кэш экономит вызовы · ошибки могут вызвать повторы</div><button class="button primary" type="submit" ${!b.credential.configured||running?'disabled':''}>${icon('radar')}Сканировать ${icon('arrow')}</button></div></form></section>
    <aside class="rail">${keyPanel()}<div class="guide-panel"><div class="eyebrow">КАК ЧИТАТЬ РЕЗУЛЬТАТЫ</div><h3>Меньше догадок.<br>Больше наблюдений.</h3><ol><li><div><strong>Найдите кандидатов</strong>Видео небольших авторов, заметные относительно размера канала.</div></li><li><div><strong>Откройте доказательства</strong>Исходные видео, каналы и время получения данных.</div></li><li><div><strong>Вернитесь к замеру</strong>Обновите статистику и увидите реальный прирост.</div></li></ol></div><p class="privacy-note">Без LLM и платных источников. Результаты остаются ${state.boot.server_mode?'на вашем сервере':'на вашем компьютере'}. Сервис помогает исследовать, но не обещает вирусность.</p></aside></div>
    ${b.directions.length?`<div class="section-label"><h2>Сохранённые настройки</h2><span>Ваши сохранённые настройки</span></div><div class="button-row">${b.directions.map((d,i)=>`<button class="button" data-action="direction" data-value="${i}">${icon('folder')}${esc(d.name)}<span class="muted">${esc(d.language.toUpperCase())}</span></button>`).join('')}</div>`:''}`;
}
function readConfig(){
  const f=$('#scan-form');if(!f)return state.config;
  const data=new FormData(f), c={...state.config};
  ['name','language','region','order'].forEach(k=>c[k]=String(data.get(k)||''));c.region=c.region.toUpperCase().trim();
  ['days','max_results','min_views','max_subscribers','min_duration','max_duration'].forEach(k=>c[k]=Number(data.get(k)||0));
  c.seeds=String(data.get('seeds')||'').split('\n').map(x=>x.trim()).filter(Boolean);
  ['excluded_words','excluded_categories'].forEach(k=>c[k]=String(data.get(k)||'').split(',').map(x=>x.trim()).filter(Boolean));
  ['extract_phrases','force'].forEach(k=>c[k]=data.has(k));state.config=c;return c;
}
function renderSettings(){const b=state.boot;
  $('#main').innerHTML=title('ВАШЕ РАБОЧЕЕ ПРОСТРАНСТВО','Настройки','Подключение к YouTube, бюджет запросов и хранение данных.')+
    `<div class="settings-layout"><div><section class="panel"><div class="panel-head"><div><h2>Подключение YouTube</h2><p>Нужен API key проекта с включённым YouTube Data API v3.</p></div>${icon('key')}</div><div class="panel-body">${b.credential.configured?`<div class="notice">Ключ сохранён · fingerprint <span class="mono">${esc(b.credential.fingerprint)}</span></div>`:''}${keyForm()}${b.credential.configured?`<div class="button-row security-note"><button class="button danger" data-action="delete-key">Удалить сохранённый ключ</button></div>`:''}<p class="security-note">${b.server_mode?'Секрет хранится на сервере в зашифрованном файле.':'Секрет хранится в системном хранилище учётных данных.'} В базе и экспортах ключа нет. Сохранение ключа не расходует квоту; доступ проверяется при исследовании.</p></div></section>
    <section class="panel"><div class="panel-head"><div><h2>Бюджет проекта</h2><p>Применяется к следующим запускам.</p></div>${icon('chart')}</div><form id="budget-form" class="panel-body"><div class="field-row two">${inputField('search_limit','Поисковых вызовов в сутки',b.quota.search_limit,'number',0,100000)}${inputField('unit_limit','Единиц остальных методов',b.quota.unit_limit,'number',0,1000000)}</div><p class="field-help">Это локальный счётчик приложения. Фактические лимиты и расход других программ смотрите в Google Cloud. Смена ключа не даёт новую квоту.</p><div class="form-bottom"><span class="field-help">Сброс: ${date(b.quota.reset_at)} · Варшава</span><button class="button primary" type="submit">Сохранить бюджет</button></div><div class="inline-error" role="alert"></div></form></section></div>
    <div><section class="panel"><div class="panel-head"><h2>Данные и источники</h2>${icon('shield')}</div><div class="panel-body"><div class="settings-detail"><span class="muted">API</span><strong>YouTube Data API v3</strong></div><div class="settings-detail"><span class="muted">История API-данных</span><strong>28 дней</strong></div><div class="settings-detail"><span class="muted">Поиск / статистика / каналы</span><strong>6 ч / 1 ч / 24 ч</strong></div><div class="settings-detail"><span class="muted">Фоновый исполнитель</span><strong>${b.worker_alive?'Работает':'Остановлен'}</strong></div><p class="security-note">История запусков и ваши заметки сохраняются дольше. Устаревшие названия, метрики и кэш удаляются автоматически. Экспорт формируется при скачивании; загруженные вами копии находятся под вашим управлением.</p><button class="button full" data-action="purge">${icon('refresh')}Очистить просроченные данные</button></div></section><div class="guide-panel"><div class="eyebrow">О ГРАНИЦАХ ИССЛЕДОВАНИЯ</div><p class="security-note">Результат — проверенная выборка, а не весь YouTube. «Просмотры / день» — среднее с публикации. Измеренный рост появляется только после двух свежих ответов с интервалом от 30 минут.</p><p class="security-note">Группы объединяют очевидные совпадения названий на разных каналах. Это подсказки внутри выборки, а не прогноз спроса. Неоднозначные видео остаются отдельно.</p><a class="hint-link" href="https://developers.google.com/youtube/terms/developer-policies" target="_blank" rel="noopener noreferrer">Правила YouTube API ${icon('external')}</a><br><a class="hint-link" href="https://www.youtube.com/t/terms" target="_blank" rel="noopener noreferrer">Условия YouTube ${icon('external')}</a><br><a class="hint-link" href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">Политика Google ${icon('external')}</a></div></div></div>`;
  if(b.server_mode)$('#main').insertAdjacentHTML('beforeend','<div class="server-signout"><button class="button" data-action="logout">Выйти из рабочего пространства</button></div>');
}
function filteredVideos(){
  let videos=[...state.result.videos];
  if(state.filter==='small')videos=videos.filter(v=>v.small_channel&&v.included);
  if(state.filter==='breakout')videos=videos.filter(v=>v.signal_status==='breakout');
  if(state.filter==='unknown')videos=videos.filter(v=>['unknown','stale'].includes(v.channel_class));
  if(state.filter==='included')videos=videos.filter(v=>v.included);
  if(state.filter==='excluded')videos=videos.filter(v=>!v.included);
  if(state.filter==='active')videos=videos.filter(v=>state.result.monitoring?.active_video_ids?.includes(v.video_id));
  if(state.format)videos=videos.filter(v=>v.video_format===state.format);
  if(state.query)videos=videos.filter(v=>v.queries.includes(state.query));
  if(state.group){const g=state.result.groups.find(g=>g.id===state.group);videos=g?videos.filter(v=>g.video_ids.includes(v.video_id)):[];}
  if(state.search){const text=state.search.toLocaleLowerCase();videos=videos.filter(v=>[v.title,v.channel_title,v.description,...(v.tags||[]),...(v.hashtags||[])].join(' ').toLocaleLowerCase().includes(text));}
  videos.sort((a,b)=>{const av=a[state.sort],bv=b[state.sort];if(av==null)return bv==null?0:1;if(bv==null)return -1;return (state.sortOrder||(state.sort==='age_days'?'asc':'desc'))==='asc'?av-bv:bv-av;});return videos;
}
const signalLabels={breakout:'Растёт у малого канала',candidate:'Кандидат · нужен второй замер',measured:'Рост измерен · ниже порога сигнала',large:'Крупнее выбранного порога',unknown:'Размер канала неизвестен',stale:'Нужны свежие данные канала',excluded:'Не проходит фильтры',correction:'Коррекция просмотров',unavailable:'Видео недоступно'};
function videoRow(v){return `<tr class="${v.included===false?'excluded-row':''}"><td><div class="video-cell">${state.view==='run'?`<label class="row-select"><input type="checkbox" data-select-id="${esc(v.video_id)}" aria-label="Выбрать: ${esc(v.title)}" ${state.selected.has(v.video_id)?'checked':''}></label>`:''}<a class="thumb" href="https://www.youtube.com/watch?v=${encodeURIComponent(v.video_id)}" target="_blank" rel="noopener noreferrer" tabindex="-1" aria-hidden="true">${icon('play')}${/^[a-zA-Z0-9_-]{11}$/.test(v.video_id)&&!v.video_id.startsWith('fixture')?`<img src="https://i.ytimg.com/vi/${encodeURIComponent(v.video_id)}/mqdefault.jpg" loading="lazy" alt="">`:''}<span class="duration">${duration(v.duration_s)}</span></a><div class="video-info"><a class="video-title" href="https://www.youtube.com/watch?v=${encodeURIComponent(v.video_id)}" target="_blank" rel="noopener noreferrer">${esc(v.title)}</a><div class="video-meta"><span title="${esc(v.format_reason||'')}">${esc(formatLabel(v))}</span><a href="/channels/${encodeURIComponent(v.channel_id||'')}">${esc(v.channel_title||'YouTube')}</a><span>${age(v.age_days)}</span>${v.subs!=null?`<span>${compact(v.subs)} подписчиков</span>`:''}</div>${state.view==='run'&&state.result.monitoring?.active_video_ids?.includes(v.video_id)?'<div class="number-note">'+(v.observed_vph==null?'Кандидат для повторного замера':'В активном топе')+'</div>':''}${v.signal_status?`<div class="signal-label ${v.signal_status==='breakout'?'signal-hot':''}">${esc(signalLabels[v.signal_status]||'')}</div>`:''}${v.inherited?'<div class="number-note">Из предыдущего запуска · время замера сохранено</div>':''}${v.unavailable?'<div class="excluded-reason">YouTube не вернул видео в последнем запросе</div>':''}${v.reasons?.length?`<div class="excluded-reason">${esc(v.reasons.join(' · '))}</div>`:''}</div></div></td>
  <td class="metric-cell" data-label="ПРОСМОТРЫ"><div class="table-number">${number(v.views)}</div>${deltaBadge(v.last_change,'views')}<div class="number-note">${date(v.fetched_at)}</div><div class="number-note">${compact(v.likes)} лайков · ${compact(v.comments)} комментариев</div></td><td class="metric-cell" data-label="ПРОСМОТРОВ / ПОДПИСЧИК"><div class="table-number">${v.views_per_subscriber==null?'—':number(v.views_per_subscriber,1)+'×'}</div><div class="number-note">${number(v.views_per_day)} / день с публикации</div></td><td class="metric-cell" data-label="ПРИРОСТ / ЧАС"><div class="table-number">${v.correction?'Коррекция':number(v.observed_vph,1)}</div><div class="number-note">${v.trend_score!=null?'рейтинг '+number(v.trend_score,1)+' · ':''}${v.interval_hours!=null?'интервал '+interval(v.interval_hours):(v.growth_status==='needs_interval'?'между замерами меньше 30 минут':'нужен второй замер от 30 мин')}</div></td>
  <td class="table-actions"><button class="icon-button ${v.favorite?'selected':''}" data-action="favorite" data-id="${esc(v.video_id)}" aria-label="${v.favorite?'Убрать из сохранённого':'Сохранить видео'}" aria-pressed="${!!v.favorite}">${icon('bookmark')}</button><button class="icon-button" data-action="video" data-id="${esc(v.video_id)}" aria-label="Подробнее о видео">${icon('more')}</button></td></tr>`;}
function visibleVideos(){return paginateRows('results',filteredVideos());}
function renderTable(){
 const videos=filteredVideos(),visible=paginateRows('results',videos);
 $('#video-table-body').innerHTML=visible.map(videoRow).join('');
 $('#table-count').textContent=`Найдено ${videos.length} из ${state.result.videos.length} видео`;
 $('#no-filter-results').hidden=!!videos.length;
 renderPagers('results',videos.length);
 const direction=$('[data-result-direction]');if(direction)direction.textContent=directionLabel(state.sortOrder||(state.sort==='age_days'?'asc':'desc'));
 syncTableSort('results',state.sort,state.sortOrder||(state.sort==='age_days'?'asc':'desc'));
 updateSelection();
}
function renderSaved(){
  $('#main').innerHTML=title('ОТБОР И ЗАМЕТКИ','Сохранённое','Видео, к которым стоит вернуться. Ваши заметки сохраняются независимо от срока хранения API-данных.')+
    (state.saved.length?`<section class="panel table-wrap"><table class="results-table"><thead><tr><th>ВИДЕО / КАНАЛ</th><th>ПРОСМОТРЫ</th><th>ПРОСМОТРОВ / ПОДПИСЧИК</th><th>ПРИРОСТ / ЧАС</th><th>ДЕЙСТВИЯ</th></tr></thead><tbody>${state.saved.map(videoRow).join('')}</tbody></table></section>`:empty('Соберите свою подборку','Нажмите на закладку рядом с видео в результатах исследования. Добавьте заметку, чтобы сохранить идею.','bookmark'));
}
async function render(){decorate();if(state.view==='scan')renderScan();else if(state.view==='history')renderHistory();else if(state.view==='settings')renderSettings();else if(state.view==='saved'){state.saved=await api('/api/saved');renderSaved();}else if(state.view==='run')await loadRun();}
async function loadRun(){
 clearTimeout(pollTimer);state.result=await api(`/api/runs/${state.runId}`);
 if(state.followLatest===undefined)state.followLatest=state.result.collection.latest_id===state.runId;
 if(!state.actionDepth){state.actionDepth=Math.max(50,state.result.run.config.max_results);state.sort=state.result.videos.some(v=>v.trend_score!=null)?'trend_score':'candidate_score';}
 renderRun();schedulePoll();
}
function schedulePoll(){if(active(state.result.run)||state.result.monitoring?.enabled)pollTimer=setTimeout(pollRun,active(state.result.run)?2200:15000);}
async function pollRun(){
 try{
  state.result=await api(`/api/runs/${state.runId}`);
  const editing=$('#video-dialog').open||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName);
  if(state.followLatest&&!editing&&state.result.collection.latest_id!==state.runId){state.runId=state.result.collection.latest_id;history.replaceState(null,'','/runs/'+state.runId);state.result=await api(`/api/runs/${state.runId}`);}
  if(!state.sortTouched)state.sort=state.result.videos.some(v=>v.trend_score!=null)?'trend_score':'candidate_score';
  if(!editing)renderRun();
  if(!active(state.result.run)){state.boot=await api('/api/bootstrap');decorate();}
  schedulePoll();
 }catch(error){toast(error.message,true);pollTimer=setTimeout(pollRun,5000);}
}
async function copy(text){try{await navigator.clipboard.writeText(text);}catch{const area=document.createElement('textarea');area.className='copy-area';area.value=text;document.body.append(area);area.select();const ok=document.execCommand('copy');area.remove();if(!ok)throw new Error('Копирование недоступно. Используйте экспорт JSON или CSV.');}toast('Скопировано в буфер обмена');}
function findVideo(id){return (state.view==='posts'?state.postRows||[]:state.result?.videos||state.saved).find(v=>v.video_id===id);}
async function openVideo(id){
  let v=findVideo(id);if(!v&&state.view==='run')return;
  let snapshots;
  if(state.view==='run')snapshots=await api(`/api/videos/${encodeURIComponent(id)}/snapshots?run_id=${encodeURIComponent(state.runId)}`);
  else {const detail=await api('/api/entities/videos/'+encodeURIComponent(id));v=detail.entity;snapshots=detail.snapshots;}
  state.videoDetail={video:v,snapshots};
  const known=snapshots.filter(s=>s.views!=null);let chart='';
  if(known.length>1){const max=Math.max(...known.map(s=>s.views)),min=Math.min(...known.map(s=>s.views)),start=known[0].observed_at,end=known.at(-1).observed_at;const pts=known.map(s=>`${10+(s.observed_at-start)/(end-start||1)*580},${100-(s.views-min)/(max-min||1)*80}`).join(' ');chart=`<svg class="snapshot-chart" viewBox="0 0 600 120" role="img" aria-label="История фактических замеров просмотров"><polyline fill="none" points="${pts}"/>${known.map(s=>`<circle cx="${10+(s.observed_at-start)/(end-start||1)*580}" cy="${100-(s.views-min)/(max-min||1)*80}" r="3" fill="currentColor"/>`).join('')}</svg>`;}
  $('#dialog-content').innerHTML=`<div class="dialog-head"><h2 id="dialog-title">${esc(v.title)}</h2><button class="icon-button" data-action="close-dialog" aria-label="Закрыть">${icon('close')}</button></div><div class="dialog-body"><div class="button-row"><button class="button primary" data-entity="refresh-video" data-id="${esc(id)}">${icon('refresh')}Обновить это видео</button><a class="button primary" href="https://www.youtube.com/watch?v=${encodeURIComponent(id)}" target="_blank" rel="noopener noreferrer">Открыть YouTube ${icon('external')}</a><button class="button" data-action="copy-video" data-id="${esc(id)}">${icon('copy')}Скопировать данные</button></div>${videoDetails(v)}<div class="section-label"><h3>История замеров</h3><span>Время Варшавы</span></div>${chart}${snapshots.length?`<div class="entity-table-scroll"><table class="snapshot-table"><thead><tr><th>Получено из YouTube</th><th>Просмотры</th><th>Лайки</th><th>Комментарии</th></tr></thead><tbody>${snapshots.map((s,i)=>({s,i})).slice(-30).reverse().map(({s,i})=>`<tr><td>${preciseDate(s.observed_at)}</td>${['views','likes','comments'].map(f=>snapshotCells(s,snapshots[i-1],f)).join('')}</tr>`).join('')}</tbody></table></div>`:'<p>Свежих снимков нет или срок их хранения истёк.</p>'}<p>${known.length<2?'Нажмите «Обновить это видео» позже, чтобы сравнить показатели. ':''}Показаны последние 30 замеров на момент этого снимка. Копирование карточки включает всю доступную историю. Чтение кэша не добавляет новую точку. Линия соединяет наблюдения и не восстанавливает пропущенные значения.</p><form id="note-form" data-id="${esc(id)}"><div class="field"><label for="note-text">Моя заметка</label><textarea id="note-text" name="text" maxlength="5000" placeholder="Идея, интересный подход, что стоит проверить…">${esc(v.note||'')}</textarea></div><label class="check-label"><input type="checkbox" name="favorite" ${v.favorite?'checked':''}>Сохранить в подборку</label><button class="button primary" type="submit">Сохранить заметку</button></form></div>`;
  if(!$('#video-dialog').open)$('#video-dialog').showModal();
}
document.addEventListener('input',event=>{
  if(event.target.closest('#scan-form')){const c=readConfig();$('#cost-estimate').textContent=`До ${new Set(c.seeds).size*Math.ceil(c.max_results/50)} поисковых вызовов`;}
  if(event.target.id==='result-search'){listState('results').page=1;state.search=event.target.value;renderTable();}
});
document.addEventListener('change',event=>{
  if(['result-group','result-query','result-sort','result-format','result-filter'].includes(event.target.id))listState('results').page=1;
  if(event.target.dataset.selectId){const id=event.target.dataset.selectId;event.target.checked?state.selected.add(id):state.selected.delete(id);updateSelection();}
  if(event.target.id==='select-visible'){for(const v of visibleVideos())event.target.checked?state.selected.add(v.video_id):state.selected.delete(v.video_id);renderTable();}
  if(event.target.id==='result-group'){state.group=event.target.value;renderTable();}
  if(event.target.id==='result-query'){state.query=event.target.value;renderTable();}
  if(event.target.id==='action-depth'){state.actionDepth=Number(event.target.value);updateSelection();}
  if(event.target.id==='result-sort'){state.sortTouched=true;state.sort=event.target.value;state.sortOrder=state.sort==='age_days'?'asc':'desc';renderTable();}
  if(event.target.id==='result-format'){state.format=event.target.value;renderTable();}
  if(event.target.id==='result-filter'){state.filter=event.target.value;renderTable();}
});
document.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target,submit=$('button[type=submit]',form);if(submit)submit.disabled=true;
  const errorBox=$('.inline-error',form);if(errorBox)errorBox.textContent='';
  try{
    if(form.id==='key-form'){readConfig();const data=await api('/api/credential',{method:'PUT',body:{api_key:form.elements.api_key.value}});form.elements.api_key.value='';state.boot.credential=data;decorate();if(state.view==='scan')renderScan();else renderSettings();toast('Ключ сохранён. Теперь можно сканировать.');}
    if(form.id==='scan-form'){const c=readConfig();if(!c.seeds.length||c.seeds.length>6)throw new Error('Введите от 1 до 6 запросов, по одному на строку.');const r=await api('/api/runs',{method:'POST',body:{config:c,request_id:crypto.randomUUID()}});location.href='/runs/'+r.id;}
    if(form.id==='focus-form'){const r=await api(`/api/runs/${state.runId}/focus`,{method:'POST',body:{request_id:crypto.randomUUID(),max_subscribers:Number(new FormData(form).get('focus-limit'))}});location.href='/runs/'+r.id;}
    if(form.id==='budget-form'){const data=new FormData(form);state.boot.quota=await api('/api/budget',{method:'PUT',body:{search_limit:Number(data.get('search_limit')),unit_limit:Number(data.get('unit_limit'))}});toast('Бюджет сохранён');renderSettings();}
    if(form.id==='note-form'){const data=new FormData(form),id=form.dataset.id;await api(`/api/videos/${encodeURIComponent(id)}/note`,{method:'PUT',body:{text:String(data.get('text')),favorite:data.has('favorite')}});$('#video-dialog').close();toast('Заметка сохранена');if(state.view==='run')await loadRun();else await render();}
  }catch(error){if(errorBox)errorBox.textContent=error.message;toast(error.message,true);}finally{if(submit)submit.disabled=false;}
});
document.addEventListener('click',async event=>{
  const el=event.target.closest('[data-action]');if(!el||el.disabled)return;const action=el.dataset.action;
  try{
    if(action==='logout'){await api('/api/logout',{method:'POST'});location.href='/login';}
    else if(action==='reload')location.reload();
    else if(action==='profile'){readConfig();state.config={...state.config,...defaultConfig(el.dataset.value,state.config.language)};renderScan();}
    else if(action==='direction'){state.config={...state.boot.directions[Number(el.dataset.value)],max_results:Math.max(50,state.boot.directions[Number(el.dataset.value)].max_results),force:false};renderScan();window.scrollTo({top:0,behavior:'smooth'});}
    else if(action==='delete-key'){await api('/api/credential',{method:'DELETE'});state.boot.credential={configured:false};decorate();renderSettings();toast('Ключ удалён из хранилища');}
    else if(action==='purge'){const r=await api('/api/purge',{method:'POST'});toast(`Удалено просроченных записей: ${r.deleted}`);}
    else if(['repeat','refresh','append','refresh-selected'].includes(action)){el.disabled=true;const selected=action==='refresh-selected';const r=await api(`/api/runs/${state.runId}/${selected?'refresh':action}`,{method:'POST',body:{request_id:crypto.randomUUID(),max_results:state.actionDepth,...(selected?{video_ids:[...state.selected]}:{})}});location.href='/runs/'+r.id;}
    else if(action==='cancel'){await api(`/api/runs/${state.runId}/cancel`,{method:'POST'});el.disabled=true;el.textContent='Останавливаем…';}
    else if(action==='favorite'){const v=findVideo(el.dataset.id);await api(`/api/videos/${encodeURIComponent(v.video_id)}/note`,{method:'PUT',body:{favorite:!v.favorite,text:v.note||''}});v.favorite=!v.favorite;if(state.view==='run')renderTable();else if(state.view==='channel')await renderChannel();else if(state.view==='posts')await renderPostList();else{state.saved=await api('/api/saved');renderSaved();}toast(v.favorite?'Видео сохранено':'Закладка снята');}
    else if(action==='video')await openVideo(el.dataset.id);
    else if(action==='close-dialog')$('#video-dialog').close();
    else if(action==='copy-video')await copy(JSON.stringify(state.videoDetail?.video.video_id===el.dataset.id?state.videoDetail:{video:findVideo(el.dataset.id)},null,2));
    else if(action==='copy-results')await copy(videoText(visibleVideos()));
    else if(action==='copy-all')await copy(videoText(state.result.videos));
    else if(action==='copy-selected')await copy(videoText(state.result.videos.filter(v=>state.selected.has(v.video_id))));
    else if(action==='copy-group'){const g=state.result.groups.find(g=>g.id===el.dataset.id);await copy(g.title+'\n'+videoText(state.result.videos.filter(v=>g.video_ids.includes(v.video_id))));}
    else if(action==='show-group'){state.group=el.dataset.id;state.filter='all';$('#result-group').value=state.group;$('#result-filter').value='all';state.search='';$('#result-search').value='';renderTable();$('#result-group').focus();}
    else if(action==='clear-selection'){state.selected.clear();renderTable();}
  }catch(error){toast(error.message,true);el.disabled=false;}
});
$('#video-dialog').addEventListener('click',event=>{if(event.target===$('#video-dialog'))$('#video-dialog').close();});
document.addEventListener('error',event=>{if(event.target.tagName==='IMG')event.target.hidden=true;},true);
document.addEventListener('DOMContentLoaded',async()=>{try{state.boot=await api('/api/bootstrap');await render();}catch(error){$('#main').innerHTML=`<div class="error-message" role="alert">${esc(error.message)}</div><button class="button" data-action="reload">Обновить страницу</button>`;}});

setInterval(async()=>{
 if(state.view!=='history'||document.hidden||document.querySelector('details[open]'))return;
 try{state.boot=await api('/api/bootstrap');decorate();renderHistory();}catch(error){toast(error.message,true);}
},15000);
