document.querySelector('#login-form').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.target,button=form.querySelector('button'),error=document.querySelector('#login-error');button.disabled=true;error.textContent='';
  try{const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name=csrf-token]').content},body:JSON.stringify({username:form.elements.username.value,password:form.elements.password.value})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Вход не выполнен');form.elements.password.value='';location.href='/';}catch(e){error.textContent=e.message;button.disabled=false;}
});
