(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = () => $('#chat-form input[name="csrf_token"]')?.value || '';
  const toast = message => { const node=$('#toast'); node.textContent=message; node.hidden=false; clearTimeout(node._timer); node._timer=setTimeout(()=>node.hidden=true,2200); };

  function renderInlineMarkdown(text, parent) {
    const normalized=text.replace(/\\([*`_#-])/g,'$1');
    const pattern=/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g; let last=0;
    for (const match of normalized.matchAll(pattern)) {
      parent.append(document.createTextNode(normalized.slice(last,match.index)));
      const token=match[0]; const node=document.createElement(token.startsWith('**')?'strong':token.startsWith('`')?'code':'em');
      node.textContent=token.startsWith('**')?token.slice(2,-2):token.slice(1,-1); parent.append(node); last=match.index+token.length;
    }
    parent.append(document.createTextNode(normalized.slice(last)));
  }

  function renderMarkdownTarget(target) {
    const source=target.previousElementSibling?.textContent||''; target.replaceChildren();
    const lines=source.replace(/\r/g,'').split('\n'); let index=0;
    while(index<lines.length){
      const line=lines[index].trim(); if(!line){index++;continue;}
      if(/^---+$/.test(line)){target.append(document.createElement('hr'));index++;continue;}
      const heading=line.match(/^(#{1,3})\s+(.+)$/);
      if(heading){const node=document.createElement(`h${heading[1].length}`);renderInlineMarkdown(heading[2],node);target.append(node);index++;continue;}
      if(/^[-*]\s+/.test(line)){const list=document.createElement('ul');while(index<lines.length&&/^\s*[-*]\s+/.test(lines[index])){const li=document.createElement('li');renderInlineMarkdown(lines[index].replace(/^\s*[-*]\s+/,''),li);list.append(li);index++;}target.append(list);continue;}
      if(/^\d+\.\s+/.test(line)){const list=document.createElement('ol');list.className='ordered-list';while(index<lines.length&&/^\s*\d+\.\s+/.test(lines[index])){const li=document.createElement('li');renderInlineMarkdown(lines[index].replace(/^\s*\d+\.\s+/,''),li);list.append(li);index++;}target.append(list);continue;}
      const parts=[];while(index<lines.length&&lines[index].trim()&&!/^(#{1,3})\s+|^\s*[-*]\s+|^\s*\d+\.\s+|^---+$/.test(lines[index])){parts.push(lines[index].trim());index++;}
      const paragraph=document.createElement('p');renderInlineMarkdown(parts.join(' '),paragraph);target.append(paragraph);
    }
    target.dataset.rendered='true';
  }

  function renderMarkdown(root=document){$$('[data-markdown]:not([data-rendered])',root).forEach(renderMarkdownTarget);}

  async function streamAnswer(target){
    if(!target||matchMedia('(prefers-reduced-motion: reduce)').matches){renderMarkdownTarget(target);return;}
    const source=target.previousElementSibling?.textContent||'';target.replaceChildren();target.dataset.rendered='streaming';
    const text=document.createTextNode('');const cursor=document.createElement('span');cursor.className='streaming-cursor';cursor.setAttribute('aria-hidden','true');target.append(text,cursor);
    for(let end=0;end<source.length;end+=12){text.data=source.slice(0,end+12);await new Promise(resolve=>requestAnimationFrame(resolve));}
    delete target.dataset.rendered;renderMarkdownTarget(target);
  }

  async function loadSessions(search=''){const list=$('#sidebar-sessions-list');if(!list)return;try{const response=await fetch(`/sessions?search=${encodeURIComponent(search)}`,{credentials:'same-origin'});list.innerHTML=await response.text();}catch{list.textContent='Không thể tải lịch sử.';}}

  async function installPartial(html,mode='append',stream=false){
    const history=$('#chat-history');const wrapper=document.createElement('div');wrapper.innerHTML=html;const sessionInput=wrapper.querySelector('#session-id-input');
    if(sessionInput){$('#session-id-input').value=sessionInput.value;sessionInput.remove();}
    const nodes=[...wrapper.childNodes];if(mode==='replace')history.replaceChildren(...nodes);else history.append(...nodes);
    if(stream){const target=[...nodes].reverse().map(node=>node.querySelector?.('[data-markdown]')).find(Boolean);await streamAnswer(target);}else renderMarkdown(history);
    history.scrollTop=history.scrollHeight;
  }

  function startProgress(requestId){
    const label=$('#pipeline-progress');const elapsed=$('#pipeline-elapsed');let stopped=false;
    const poll=async()=>{if(stopped)return;try{const response=await fetch(`/api/progress/${encodeURIComponent(requestId)}`,{credentials:'same-origin'});if(response.ok){const data=await response.json();label.textContent=data.label;elapsed.textContent=`${Number(data.elapsed_seconds||0).toFixed(1)}s`;if(data.complete){stopped=true;return;}}}catch{}if(!stopped)setTimeout(poll,400);};poll();
    return()=>{stopped=true;};
  }

  async function submitChat(form){
    const loading=$('#chat-loading');const status=$('#chat-status');const submit=form.querySelector('[type="submit"]');const data=new FormData(form);const requestId=crypto.randomUUID?.()||`${Date.now()}-${Math.random()}`;data.set('request_id',requestId);
    loading.hidden=false;submit.disabled=true;status.textContent='Đang xử lý câu hỏi';$('#pipeline-progress').textContent='Đang tiếp nhận câu hỏi';$('#pipeline-elapsed').textContent='0.0s';$('#welcome-container')?.remove();const stopProgress=startProgress(requestId);
    try{const response=await fetch('/chat',{method:'POST',body:data,credentials:'same-origin'});const body=await response.text();if(response.ok){await installPartial(body,'append',true);form.querySelector('[name="message"]').value='';await loadSessions($('#session-search').value);}else{const card=document.createElement('article');card.className='message-card error-message';card.textContent=response.status===429?'Bạn gửi quá nhanh. Vui lòng chờ một phút rồi thử lại.':'Yêu cầu chưa hoàn tất. Vui lòng thử lại sau.';$('#chat-history').append(card);toast(card.textContent);}}catch{toast('Không thể kết nối tới VietLex.');}finally{stopProgress();loading.hidden=true;submit.disabled=false;status.textContent='Đã xử lý xong';}
  }

  function openSource(button){const source=document.getElementById(button.dataset.sourceTarget);const drawer=$('#evidence-drawer');$('#evidence-drawer-content').textContent=source?.content?.textContent||source?.textContent||'Không có nội dung nguồn.';drawer.classList.add('open');drawer.setAttribute('aria-hidden','false');$('#drawer-backdrop').hidden=false;drawer._returnFocus=button;drawer.querySelector('[data-action="close-drawer"]')?.focus();}
  function closeSource(){const drawer=$('#evidence-drawer');drawer.classList.remove('open');drawer.setAttribute('aria-hidden','true');$('#drawer-backdrop').hidden=true;drawer._returnFocus?.focus();}
  const make=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
  function metricCard(label,value,note){const card=make('div',undefined,'metric-card');card.append(make('strong',`${label}: ${value??'N/A'}`),make('small',note));return card;}
  function scoreText(value){return typeof value==='number'?value.toFixed(3):'Chưa có điểm';}

  function renderCodeEvaluation(panel,evaluation){
    panel.append(make('h3','Code evaluation — deterministic','evaluation-title'));
    const table=make('table',undefined,'evaluation-table');const body=document.createElement('tbody');
    (evaluation.checks||[]).forEach(check=>{const row=document.createElement('tr');const badge=make('span',check.status==='pass'?'PASS':'FAIL',`check-badge ${check.status}`);const state=document.createElement('td');state.append(badge);row.append(make('th',check.label),state,make('td',String(check.value??'N/A')),make('td',check.meaning));body.append(row);});table.append(body);panel.append(table);
    if(evaluation.timings?.length){panel.append(make('h4','Thời gian quan sát'));const timing=make('table',undefined,'evaluation-table timing-table');const timingBody=document.createElement('tbody');evaluation.timings.forEach(item=>{const row=document.createElement('tr');row.append(make('th',item.label),make('td',`${Number(item.seconds).toFixed(4)}s`));timingBody.append(row);});timing.append(timingBody);panel.append(timing);}
    panel.append(make('p',evaluation.limitations?.[0]||'','muted'));
  }

  function renderRagas(panel,result){
    const ragas=result.ragas||{};panel.append(make('h3','Ragas — LLM-as-a-judge','evaluation-title'));
    if(ragas.status==='ok'){const grid=make('div',undefined,'metric-grid');grid.append(metricCard('Faithfulness',scoreText(ragas.faithfulness),'Được context hỗ trợ'),metricCard('Answer Relevance',scoreText(ragas.answer_relevance),'Trả lời đúng trọng tâm'));panel.append(grid);}
    else{panel.append(make('p','Không có điểm Ragas','ragas-empty'));const reason=ragas.error?.message||({disabled:'Deployment chưa bật Ragas.',quota_exceeded:'Đã hết quota Ragas hôm nay.',skipped_no_context:'Không có context để đánh giá.'}[ragas.status])||`Trạng thái: ${ragas.status||'unavailable'}`;panel.append(make('p',reason,'muted'));}
    const catalog=make('div',undefined,'metric-explainer');(result.ragas_metrics||[]).forEach(metric=>{const value=metric.applicable?scoreText(ragas[metric.key]):(metric.display_value||'N/A');const card=metricCard(metric.label,value,metric.meaning||'');if(!metric.applicable)card.append(make('small',metric.reason_not_applicable||''));card.append(make('small',`Giới hạn: ${metric.limitation||'Không có mô tả.'}`));catalog.append(card);});panel.append(catalog);
  }

  async function evaluateAnswer(button,runRagas=false){
    const panel=button.closest('.message-card').querySelector('.evaluation-panel');panel.hidden=false;panel.textContent=runRagas?'Đang chạy Ragas…':'Đang đọc số liệu request…';const data=new FormData();data.set('csrf_token',csrf());data.set('run_ragas',String(runRagas));
    try{const response=await fetch(`/api/evaluation/${encodeURIComponent(button.dataset.traceId)}`,{method:'POST',body:data,credentials:'same-origin'});const result=await response.json();if(!result.code_evaluation){panel.textContent=response.status===429?'Đã đạt giới hạn đánh giá. Vui lòng thử lại sau.':'Không thể chạy đánh giá lúc này.';return;}panel.replaceChildren();renderCodeEvaluation(panel,result.code_evaluation);if(runRagas)renderRagas(panel,result);else{const ragas=make('button','Chạy Ragas (tùy chọn)','button button-quiet');ragas.type='button';ragas.addEventListener('click',()=>evaluateAnswer(button,true));panel.append(ragas);}}catch{panel.textContent='Không thể kết nối dịch vụ đánh giá.';}
  }

  document.addEventListener('submit',async event=>{const form=event.target;if(form.id==='chat-form'){event.preventDefault();await submitChat(form);}if(form.matches('[data-feedback-form]')){event.preventDefault();const response=await fetch('/api/feedback',{method:'POST',body:new FormData(form),credentials:'same-origin'});if(response.ok){const actions=form.closest('.message-actions');const state=make('span',form.querySelector('[name="rating"]').value==='up'?'✓ Hữu ích':'✓ Đã ghi nhận');actions.querySelectorAll('[data-feedback-form]').forEach(node=>node.remove());actions.append(state);}else toast('Không thể ghi nhận phản hồi.');}});
  document.addEventListener('click',async event=>{const target=event.target.closest('button,a');if(!target)return;if(target.dataset.prompt){$('#chat-input').value=target.dataset.prompt;$('#chat-form').requestSubmit();}const action=target.dataset.action;if(action==='new-session'){const data=new FormData();data.set('csrf_token',csrf());const r=await fetch('/sessions',{method:'POST',body:data,credentials:'same-origin'});await installPartial(await r.text(),'replace');loadSessions();}if(action==='select-session'){const r=await fetch(`/sessions/${target.dataset.sessionId}`,{credentials:'same-origin'});await installPartial(await r.text(),'replace');}if(action==='delete-session'&&confirm('Xóa hội thoại này?')){await fetch(`/sessions/${target.dataset.sessionId}`,{method:'DELETE',headers:{'X-CSRF-Token':csrf()},credentials:'same-origin'});loadSessions();}if(action==='rename-session'){const name=prompt('Tên mới cho hội thoại:',target.dataset.title||'');if(name){await fetch(`/sessions/${target.dataset.sessionId}/rename`,{method:'POST',headers:{'HX-Prompt':name},body:new URLSearchParams({csrf_token:csrf()}),credentials:'same-origin'});loadSessions();}}if(action==='open-source')openSource(target);if(action==='close-drawer')closeSource();if(action==='copy-answer'){await navigator.clipboard.writeText(target.closest('.message-card').querySelector('.answer-source').textContent);toast('Đã sao chép câu trả lời');}if(action==='retry'){$('#chat-input').value=target.dataset.query||'';$('#chat-form').requestSubmit();}if(action==='evaluate')await evaluateAnswer(target,false);});
  $('#drawer-backdrop')?.addEventListener('click',closeSource);document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('#evidence-drawer')?.classList.contains('open'))closeSource();});$('#chat-form')?.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();event.currentTarget.requestSubmit();}});let searchTimer;$('#session-search')?.addEventListener('input',event=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadSessions(event.target.value),180);});const savedTheme=localStorage.getItem('vietlex-theme');if(savedTheme)document.documentElement.dataset.theme=savedTheme;$('#theme-toggle')?.addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=next;localStorage.setItem('vietlex-theme',next);});fetch('/readyz').then(async r=>({ok:r.ok,data:await r.json()})).then(({ok})=>{const node=$('#system-readiness');if(!node)return;node.textContent=ok?'Hệ thống sẵn sàng':'Hệ thống chưa sẵn sàng';node.classList.add(ok?'ready':'not-ready');}).catch(()=>{const node=$('#system-readiness');if(node)node.textContent='Không đọc được trạng thái';});loadSessions();renderMarkdown();
})();
