/* Scheduling is attached to the persistent collection, never to a browser timer. */
function monitoringPanel(){
  const m=state.result.monitoring;if(!m)return '';
  const c=state.result.run.config, daily=Math.ceil(24/m.full_hours)*c.seeds.length*Math.ceil(c.max_results/50);
  return `<section class="panel monitoring-panel"><div class="panel-head"><div><div class="eyebrow">НЕПРЕРЫВНОЕ НАБЛЮДЕНИЕ</div><h2>Радар вашей темы</h2><p>Полный список — периодически. Лидеры среди небольших каналов и новые малые кандидаты — чаще.</p></div><span class="source-pill">${m.enabled?'Включено':'На паузе'}</span></div><form id="schedule-form" class="panel-body">
  <div class="schedule-fields">${selectField('full_hours','Полный поиск и пересмотр',[[4,'Каждые 4 часа'],[6,'Каждые 6 часов'],[12,'Каждые 12 часов'],[24,'Раз в сутки']],m.full_hours)}${selectField('monitor_minutes','Замер лидеров',[[30,'Каждые 30 минут'],[60,'Каждый час'],[120,'Каждые 2 часа']],m.monitor_minutes)}${selectField('top_limit','Активный список',[[50,'Топ-50 + новые'],[100,'Топ-100 + новые']],m.top_limit)}</div>
  <div class="schedule-status"><div><small>Следующий широкий цикл</small><strong>${m.enabled?date(m.next_full):'—'}</strong></div><div><small>Следующий замер</small><strong>${m.enabled?date(m.next_monitor):'—'}</strong></div><div><small>Ожидают первого прироста</small><strong>${m.candidate_count} видео</strong></div></div>
  <p class="field-help" id="schedule-estimate">План поиска: до ${daily} вызовов/сутки для этого исследования. Частый замер топа: ${Math.ceil(m.top_limit/50)} ед. + новые кандидаты; без search.list.</p>
  <p class="field-help">${esc(m.last_message||'Расписание сохранено')}. Работает при запущенном приложении, даже если браузер закрыт.</p>
  <div class="button-row"><button class="button primary" type="submit">${m.enabled?'Сохранить расписание':'Включить мониторинг'}</button>${m.enabled?'<button class="button" type="button" data-action="pause-schedule">Поставить на паузу</button>':''}</div><div class="inline-error" role="alert"></div>
  <details class="ranking-guide"><summary>Как выбирается активный топ</summary><p>У каждого нового видео небольшого канала сначала проверяем рост повторным замером, даже если просмотров пока мало. После этого чаще обновляем топ малых каналов: по одному сильнейшему видео на канал, с учётом фильтров исследования. Неизвестные и крупные каналы остаются в широком пересмотре. При широком цикле обновляем все сохранённые ID: поздний рост может вернуть видео в топ.</p><p>Рейтинг = max(0, Δпросмотров − 2 × √Δпросмотров) / часы между замерами × 1 000 / max(подписчики, 1 000). Это поправка на шум малых чисел, не прогноз. Минимальный интервал — 30 минут; рядом остаются исходный прирост и длительность замера. Длинный интервал сглаживает краткие всплески. Отрицательная коррекция просмотров исключается из рейтинга.</p></details></form></section>`;
}
document.addEventListener('submit',async e=>{
  if(e.target.id!=='schedule-form')return;e.preventDefault();
  const form=e.target, button=form.querySelector('button[type=submit]');button.disabled=true;
  try{const f=new FormData(form);await api(`/api/runs/${state.runId}/schedule`,{method:'PUT',body:{enabled:true,full_hours:Number(f.get('full_hours')),monitor_minutes:Number(f.get('monitor_minutes')),top_limit:Number(f.get('top_limit'))}});toast('Мониторинг включён. Расписание сохранено.');await loadRun();}
  catch(error){form.querySelector('.inline-error').textContent=error.message;button.disabled=false;}
});
document.addEventListener('change',e=>{
  if(!e.target.closest('#schedule-form'))return;
  const f=new FormData($('#schedule-form')), c=state.result.run.config;
  const daily=Math.ceil(24/Number(f.get('full_hours')))*c.seeds.length*Math.ceil(c.max_results/50);
  $('#schedule-estimate').textContent=`План поиска: до ${daily} вызовов/сутки. Частый замер топа: ${Math.ceil(Number(f.get('top_limit'))/50)} ед. + новые кандидаты. ${daily>state.result.quota.search_limit?'План превышает дневной бюджет: увеличьте интервал или уменьшите глубину поиска.':''}`;
});
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-action="pause-schedule"]');if(!b)return;b.disabled=true;
  try{const m=state.result.monitoring;await api(`/api/runs/${state.runId}/schedule`,{method:'PUT',body:{enabled:false,full_hours:m.full_hours,monitor_minutes:m.monitor_minutes,top_limit:m.top_limit}});toast('Мониторинг на паузе. Текущая операция завершится.');await loadRun();}
  catch(error){toast(error.message,true);b.disabled=false;}
});
