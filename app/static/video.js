/* Details use escaped text only. YouTube's embedHtml is data, never executable UI. */
const formatLabels={all:'Все форматы',shorts:'Shorts',videos:'Обычные видео'};
function formatLabel(v){return v.video_format==='shorts'?'Shorts · оценка':v.video_format==='video'?'Обычное видео':v.shorts_candidate?'Возможный Shorts':'Формат неизвестен';}
function signedCount(n){return n==null?'—':(n>0?'+':'')+number(n);}
function formatFilter(){return `<select id="result-format" aria-label="Формат видео">${[['','Все форматы'],['shorts','Shorts · оценка'],['video','Обычные видео'],['unknown','Формат неизвестен']].map(([k,l])=>`<option value="${k}" ${(state.format||'')===k?'selected':''}>${l}</option>`).join('')}</select>`;}
function videoDetails(v){
 const chips=values=>values?.length?`<div class="metadata-tags">${values.map(x=>`<span>${esc(x)}</span>`).join('')}</div>`:'<p>Не указаны в ответе YouTube.</p>';
 return `<div class="video-facts"><span class="source-pill">${esc(formatLabel(v))} · ${duration(v.duration_s)}</span><a class="text-link" href="/channels/${encodeURIComponent(v.channel_id||'')}">${esc(v.channel_title||'Канал')}</a><span>Публикация: ${date(Date.parse(v.published_at)/1000)}</span><span>Язык: ${esc(v.lang||'не указан')}</span></div><p class="field-help">${esc(v.format_reason||'Обновите рост, чтобы получить метаданные формата.')} YouTube API не подтверждает принадлежность к Shorts.</p>
 <div class="results-metrics entity-metrics">${metricCard(v,'views','Просмотры')}${metricCard(v,'likes','Лайки')}${metricCard(v,'comments','Комментарии')}</div>
 <p>${changeCaption(v.last_change)} Скорость — разница, делённая на фактический интервал. «—» означает отсутствие данных; отрицательное значение может быть корректировкой YouTube.</p>
 <section class="metadata-section"><h3>Описание</h3>${v.metadata_version?`<div class="video-description">${esc(v.description||'Описание не указано.')}</div><h3>Хэштеги из названия и описания</h3>${chips(v.hashtags)}<details><summary>Теги автора · ${v.tags?.length||0}</summary>${chips(v.tags)}</details>`:'<p>В этом старом замере описание и теги не сохранены. Нажмите «Обновить рост» в актуальном исследовании, чтобы получить их новым замером.</p>'}</section>
 ${v.youtube?`<details class="metadata-raw"><summary>Все публичные поля YouTube · JSON</summary><pre tabindex="0" aria-label="Публичные поля видео">${esc(JSON.stringify(v.youtube,null,2))}</pre><p>Сохранён полный полученный ответ. Закрытые данные владельца и тексты комментариев не запрашиваются.</p></details>`:''}`;
}
