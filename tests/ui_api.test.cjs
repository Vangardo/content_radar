const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('app/static/app.js','utf8');
const code=source.slice(source.indexOf('async function api('),source.indexOf('function title('));
function client(response,serverMode=false){
 const context={fetch:async()=>response,$:()=>({content:'synthetic-csrf'}),state:{boot:{server_mode:serverMode}},location:{},Error};
 vm.runInNewContext(code,context);return context;
}
test('plain text 500/HTML 502 produce readable errors without leaking response text',async()=>{
 for(const status of [500,502]){
  const c=client(new Response(status===502?'<html>Bad Gateway private diagnostic</html>':'Internal Server Error private diagnostic',{status}));
  await assert.rejects(c.api('/api/research'),e=>e.message.includes('HTTP '+status)&&!e.message.includes('JSON')&&!e.message.includes('private'));
 }
});
test('JSON API errors retain the actionable message',async()=>{
 const c=client(new Response(JSON.stringify({error:'Хранилище временно недоступно'}),{status:503}));
 await assert.rejects(c.api('/api/research'),/Хранилище временно недоступно/);
});
test('malformed success is reported and valid data is preserved',async()=>{
 await assert.rejects(client(new Response('invalid')).api('/api/posts'),/некорректный ответ/);
 const data=await client(new Response('{"items":[],"total":0}')).api('/api/posts');
 assert.equal(data.total,0);
});
test('session expiration still redirects to login before JSON parsing',async()=>{
 const c=client(new Response('Unauthorized',{status:401}),true);
 await assert.rejects(c.api('/api/posts'),/Войдите заново/);
 assert.equal(c.location.href,'/login');
});
