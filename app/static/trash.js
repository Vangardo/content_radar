/* Reversible research removal; shared video/channel history remains intact. */
labels.trash='Удалённые исследования';
paths.trash='<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/>';
function deleteResearchButton(id){return `<button class="button small danger" data-trash="delete" data-id="${esc(id)}">${icon('trash')}Удалить исследование</button>`;}
const renderWithEntities=render;
render=async function(){if(state.view==='trash'){decorate();await renderTrash();}else await renderWithEntities();};
async function renderTrash(){
 const rows=(await api('/api/research/trash')).research;
 $('#main').innerHTML=title('УПРАВЛЕНИЕ СПИСКОМ','Удалённые исследования','Здесь можно восстановить исследование. Мониторинг останется на паузе.',`<a class="button" href="/history">К истории ${icon('arrow')}</a>`)+
 (rows.length?`<div class="history-list">${rows.map(r=>`<article class="panel trash-row"><div><h2>${esc(r.name)}</h2><p>${r.language.toUpperCase()} · удалено ${date(r.deleted_at)}</p></div><button class="button" data-trash="restore" data-id="${esc(r.id)}">${icon('refresh')}Восстановить</button></article>`).join('')}</div>`:empty('Корзина пуста','Удалённые исследования будут здесь.','trash',false))+
 '<p class="field-help below-table">Удаление скрывает исследование и останавливает расписание. Избранное и общая история видео/каналов сохраняются. Для API-данных действует прежний срок хранения — 28 дней.</p>';
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-trash]');if(!b||b.disabled)return;
 const dialog=$('#research-delete-dialog');
 if(b.dataset.trash==='delete'){dialog.dataset.id=b.dataset.id;$('.inline-error',dialog).textContent='';dialog.showModal();return;}
 if(b.dataset.trash==='cancel'){dialog.close();return;}
 b.disabled=true;
 try{
  const remove=b.dataset.trash==='confirm';
  await api(`/api/research/${remove?dialog.dataset.id:b.dataset.id}${remove?'':'/restore'}`,{method:remove?'DELETE':'POST'});
  if(remove)dialog.close();
  if(state.view==='run'){location.href='/history';return;}
  state.boot=await api('/api/bootstrap');await render();
  toast(remove?'Исследование удалено. Восстановление доступно в истории → Удалённые.':'Исследование восстановлено. Мониторинг на паузе.');
 }catch(error){if(dialog.open)$('.inline-error',dialog).textContent=error.message;else toast(error.message,true);}finally{b.disabled=false;}
});
