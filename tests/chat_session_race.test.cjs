'use strict';
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {test} = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app/static/js/vietlex.js'), 'utf8');
function deferred() { let resolve; const promise = new Promise(r => resolve = r); return {promise, resolve}; }
function response(session) { return {ok: true, text: async () => session}; }
function harness(fetch) {
  const nodes = {};
  for (const id of ['chat-loading','chat-status','pipeline-progress','pipeline-elapsed','session-search','session-id-input']) nodes[id] = {value:'',textContent:'',hidden:true};
  nodes['session-id-input'].value='A';
  const history={items:['history-A'],append(...values){this.items.push(...values);},replaceChildren(...values){this.items=[...values];},scrollHeight:0};nodes['chat-history']=history;
  const button={disabled:false},message={value:'Question A'};
  const form={querySelector(selector){return selector==='[type="submit"]'?button:message;}};
  let click;
  const document={addEventListener(type,handler){if(type==='click') click=handler;},createElement(){return {set innerHTML(session){this.session=session;this.childNodes=['reply-'+session];},querySelector(){return {value:this.session,remove(){}};}};}};
  class FormData { constructor(){this.values=new Map([['message',message.value],['session_id',nodes['session-id-input'].value]]);}set(k,v){this.values.set(k,v);}get(k){return this.values.get(k);} }
  const install=source.slice(source.indexOf('  async function installPartial('),source.indexOf('  function startProgress('));
  const submit=source.slice(source.indexOf('  async function submitChat('),source.indexOf('  function openSource('));
  const handler=source.split('\n').find(line=>line.includes("document.addEventListener('click',async event=>"));
  const api=new Function('$','document','fetch','FormData','crypto','startProgress','streamAnswer','renderMarkdown','loadSessions','toast','csrf',install+submit+handler+';return {submitChat};')(s=>nodes[s.slice(1)]||null,document,fetch,FormData,{randomUUID:()=> 'request'},()=>()=>{},async()=>{},()=>{},async()=>{},()=>{},()=> 'csrf');
  return {nodes,history,message,button,submit:()=>api.submitChat(form),navigate:session=>click({target:{closest:()=>({dataset:{action:'select-session',sessionId:session}})}})};
}
test('late chat response cannot replace another session or erase its draft',async()=>{
  const chat=deferred();const h=harness(url=>url==='/chat'?chat.promise:Promise.resolve(response('B')));
  const pending=h.submit(); await h.navigate('B');h.message.value='Draft B';chat.resolve(response('A'));await pending;
  assert.equal(h.nodes['session-id-input'].value,'B');assert.deepEqual(h.history.items,['reply-B']);assert.equal(h.message.value,'Draft B');
});
test('a draft edited during the current request survives its successful reply',async()=>{
  const chat=deferred();const h=harness(()=>chat.promise);const pending=h.submit();h.message.value='Next question';chat.resolve(response('A'));await pending;
  assert.equal(h.message.value,'Next question');assert.deepEqual(h.history.items,['history-A','reply-A']);
});
test('history responses arriving out of order keep the latest requested session',async()=>{
  const b=deferred(),c=deferred();const h=harness(url=>url.endsWith('/B')?b.promise:c.promise);
  const old=h.navigate('B'),latest=h.navigate('C');c.resolve(response('C'));await latest;b.resolve(response('B'));await old;
  assert.equal(h.nodes['session-id-input'].value,'C');assert.deepEqual(h.history.items,['reply-C']);
});
test('duplicate submit while active sends only one request and normal success clears submitted text',async()=>{
  const chat=deferred();let calls=0;const h=harness(()=>{calls++;return chat.promise;});const a=h.submit(),b=h.submit();chat.resolve(response('A'));await Promise.all([a,b]);
  assert.equal(calls,1);assert.equal(h.message.value,'');assert.equal(h.button.disabled,false);
});
test('submit is held until requested navigation has installed the correct session',async()=>{
  const nav=deferred();let chats=0;
  const h=harness(url=>{if(url==='/chat'){chats++;return Promise.resolve(response('A'));}return nav.promise;});
  const navigation=h.navigate('B');await h.submit();nav.resolve(response('B'));await navigation;
  assert.equal(chats,0);assert.equal(h.nodes['session-id-input'].value,'B');
});

test('rate limit response uses the server wait interval and preserves the draft',async()=>{
  for (const [seconds, expected] of [['3600', /60 phút/], ['30', /30 giây/], [null, /thử lại sau/]]) {
    const h=harness(async()=>({ok:false,status:429,headers:{get:()=>seconds},text:async()=>'{"detail":"demo_daily_quota"}'}));
    await h.submit();
    assert.match(h.history.items.at(-1).textContent, expected);
    assert.doesNotMatch(h.history.items.at(-1).textContent, /chờ một phút/);
    assert.equal(h.message.value,'Question A');
    assert.equal(h.button.disabled,false);
  }
});

test('backend failure does not announce that the question was processed',async()=>{
  const h=harness(async()=>({ok:false,status:503,text:async()=>''}));
  await h.submit();
  assert.doesNotMatch(h.nodes['chat-status'].textContent,/Đã xử lý xong/);
  assert.equal(h.message.value,'Question A');
});
