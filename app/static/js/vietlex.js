(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = () => $('#chat-form input[name="csrf_token"]')?.value || '';
  const toast = message => { const node=$('#toast'); if(!node)return; node.textContent=message; node.hidden=false; clearTimeout(node._timer); node._timer=setTimeout(()=>node.hidden=true,2200); };

  function appendSafeFormattedText(text, parent) {
    const normalized = String(text || '').replace(/\\([*`_#-])/g, '$1');
    const pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)/g;
    let last = 0;
    for (const match of normalized.matchAll(pattern)) {
      const plain = normalized.slice(last, match.index).replace(/\*\*/g, '');
      if (plain) parent.append(document.createTextNode(plain));
      const token = match[0];
      const tag = token.startsWith('**') ? 'strong' : token.startsWith('`') ? 'code' : 'em';
      const node = document.createElement(tag);
      node.textContent = token.startsWith('**') ? token.slice(2, -2) : token.slice(1, -1);
      parent.append(node);
      last = match.index + token.length;
    }
    const tail = normalized.slice(last).replace(/\*\*/g, '');
    if (tail) parent.append(document.createTextNode(tail));
  }

  function renderInlineMarkdown(text, parent) {
    const linkPattern = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+|\/[^\s)]+)\)/g;
    let last = 0;
    for (const match of String(text || '').matchAll(linkPattern)) {
      appendSafeFormattedText(text.slice(last, match.index), parent);
      const anchor = document.createElement('a');
      anchor.href = match[2];
      if (match[2].startsWith('http')) {
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
      }
      appendSafeFormattedText(match[1], anchor);
      parent.append(anchor);
      last = match.index + match[0].length;
    }
    appendSafeFormattedText(String(text || '').slice(last), parent);
  }

  function renderMarkdownTarget(target) {
    const source=target.previousElementSibling?.textContent||''; target.replaceChildren();
    const lines=source.replace(/\r/g,'').split('\n'); let index=0;
    while(index<lines.length){
      const line=lines[index].trim(); if(!line){index++;continue;}
      if(/^---+$/.test(line)){target.append(document.createElement('hr'));index++;continue;}
      if(/^>\s?/.test(line)){const quote=document.createElement('blockquote');const parts=[];while(index<lines.length&&/^\s*>\s?/.test(lines[index])){parts.push(lines[index].replace(/^\s*>\s?/,'').trim());index++;}const p=document.createElement('p');renderInlineMarkdown(parts.join(' '),p);quote.append(p);target.append(quote);continue;}
      const heading=line.match(/^(#{1,3})\s+(.+)$/);
      if(heading){const node=document.createElement(`h${heading[1].length}`);renderInlineMarkdown(heading[2],node);target.append(node);index++;continue;}
      if(/^[-*]\s+/.test(line)){const list=document.createElement('ul');while(index<lines.length&&/^\s*[-*]\s+/.test(lines[index])){const li=document.createElement('li');renderInlineMarkdown(lines[index].replace(/^\s*[-*]\s+/,''),li);list.append(li);index++;}target.append(list);continue;}
      if(/^\d+\.\s+/.test(line)){const list=document.createElement('ol');list.className='ordered-list';while(index<lines.length&&/^\s*\d+\.\s+/.test(lines[index])){const li=document.createElement('li');renderInlineMarkdown(lines[index].replace(/^\s*\d+\.\s+/,''),li);list.append(li);index++;}target.append(list);continue;}
      const parts=[];while(index<lines.length&&lines[index].trim()&&!/^(#{1,3})\s+|^\s*[-*]\s+|^\s*\d+\.\s+|^\s*>\s?|^---+$/.test(lines[index])){parts.push(lines[index].trim());index++;}
      const paragraph=document.createElement('p');renderInlineMarkdown(parts.join(' '),paragraph);target.append(paragraph);
    }
    target.dataset.rendered='true';
  }

  function renderMarkdown(root=document){$$('[data-markdown]:not([data-rendered])',root).forEach(renderMarkdownTarget);}

  async function streamAnswer(target,isCurrent=()=>true){
    if(!isCurrent())return;
    if(target)renderMarkdownTarget(target);
  }

  async function loadSessions(search=''){const list=$('#sidebar-sessions-list');if(!list)return;try{const response=await fetch(`/sessions?search=${encodeURIComponent(search)}`,{credentials:'same-origin'});list.innerHTML=await response.text();}catch{list.textContent='Không thể tải lịch sử.';}}

  async function installPartial(html,mode='append',stream=false,isCurrent=()=>true){
    if(!isCurrent())return;
    const history=$('#chat-history');const wrapper=document.createElement('div');wrapper.innerHTML=html;const sessionInput=wrapper.querySelector('#session-id-input');
    if(sessionInput){$('#session-id-input').value=sessionInput.value;sessionInput.remove();}
    const nodes=[...wrapper.childNodes];if(mode==='replace')history.replaceChildren(...nodes);else history.append(...nodes);
    if(stream){const target=[...nodes].reverse().map(node=>node.querySelector?.('[data-markdown]')).find(Boolean);await streamAnswer(target,isCurrent);}else renderMarkdown(history);
    if(!isCurrent())return;
    history.scrollTop=history.scrollHeight;
  }

  let chatNavigationRevision = 0;
  let chatNavigationPending = false;
  async function navigateChat(url,options={credentials:'same-origin'}){
    const revision=++chatNavigationRevision;
    chatNavigationPending=true;
    const isCurrent=()=>revision===chatNavigationRevision;
    try{
      const response=await fetch(url,options);
      const html=await response.text();
      if(!isCurrent())return;
      if(!response.ok)throw new Error('session_unavailable');
      await installPartial(html,'replace',false,isCurrent);
    }catch{if(isCurrent())toast('Không thể mở hội thoại. Vui lòng thử lại.');}
    finally{if(isCurrent())chatNavigationPending=false;}
  }

  function startProgress(requestId){
    const label=$('#pipeline-progress');const elapsed=$('#pipeline-elapsed');let stopped=false;
    const progressTransport=document.body.dataset.progressTransport||'sse';
    if(progressTransport==='polling'){
      const poll=async()=>{if(stopped)return;try{const response=await fetch(`/api/progress/${encodeURIComponent(requestId)}`,{credentials:'same-origin'});if(response.ok){const data=await response.json();label.textContent=data.label;elapsed.textContent=`${Number(data.elapsed_seconds||0).toFixed(1)}s`;if(data.complete){stopped=true;return;}}}catch{}if(!stopped)setTimeout(poll,1000);};poll();
      return()=>{stopped=true;};
    }
    const source=new EventSource(`/api/progress/${encodeURIComponent(requestId)}/stream`);
    source.onmessage=event=>{if(stopped)return;try{const data=JSON.parse(event.data);label.textContent=data.label||label.textContent;elapsed.textContent=`${Number(data.elapsed_seconds||0).toFixed(1)}s`;if(data.complete){stopped=true;source.close();}}catch{}};
    source.addEventListener('timeout',()=>{stopped=true;source.close();});
    source.onerror=()=>{source.close();};
    return()=>{stopped=true;source.close();};
  }

  async function submitChat(form){
    const loading=$('#chat-loading');const status=$('#chat-status');const submit=form.querySelector('[type="submit"]');const stopBtn=$('#chat-stop');if(submit.disabled||chatNavigationPending)return;
    const llmPicker=$('#chat-form [data-llm-target]');if(llmPicker){const [prov,mod]=String(llmPicker.value||'auto|').split('|');const pIn=$('#chat-form input[name="llm_provider"]');const mIn=$('#chat-form input[name="llm_model"]');if(pIn)pIn.value=prov||'auto';if(mIn)mIn.value=mod||'';}
    const revision=chatNavigationRevision;const isCurrent=()=>revision===chatNavigationRevision;const submittedMessage=form.querySelector('[name="message"]').value;const data=new FormData(form);const requestId=crypto.randomUUID?.()||`${Date.now()}-${Math.random()}`;data.set('request_id',requestId);
    const endpoint=form.dataset?.streamUrl||'/chat';
    const controller=typeof AbortController==='function'?new AbortController():null;
    activeChatController=controller;
    let completed=false;let aborted=false;const previewNodes=[];
    const clearPreviews=()=>{while(previewNodes.length){const n=previewNodes.pop();n?.remove?.();}};
    loading.hidden=false;submit.disabled=true;if(stopBtn)stopBtn.hidden=false;status.textContent='Đang xử lý câu hỏi';$('#pipeline-progress').textContent='Đang tiếp nhận câu hỏi';$('#pipeline-elapsed').textContent='0.0s';$('#welcome-container')?.remove();
    const stopProgress=endpoint==='/chat'?startProgress(requestId):()=>{};
    const startedAt=Date.now();
    const timer=endpoint!=='/chat'?setInterval(()=>{const el=$('#pipeline-elapsed');if(el)el.textContent=`${((Date.now()-startedAt)/1000).toFixed(1)}s`;},200):null;
    try{
      const reqOpts={method:'POST',body:data,credentials:'same-origin',...(controller?{signal:controller.signal}:{})};
      let response=await fetch(endpoint,reqOpts);
      if(endpoint!=='/chat'&&(response.status===404||response.status===405))response=await fetch('/chat',reqOpts);
      const isStream=response.ok&&response.body&&typeof response.body.getReader==='function'&&(endpoint==='/chat/stream'||String(response.headers?.get?.('content-type')||'').includes('application/x-ndjson'));
      if(isStream){
        const history=$('#chat-history');
        let userPreview=null,assistantPreview=null,sourceEl=null,markdownEl=null,accumulated='';
        const ensurePreview=()=>{
          if(assistantPreview||!isCurrent())return;
          userPreview=document.createElement('article');userPreview.className='message-row user streaming-preview';
          const uCard=document.createElement('div');uCard.className='message-card';uCard.textContent=submittedMessage;
          const uAv=document.createElement('div');uAv.className='avatar';uAv.setAttribute?.('aria-hidden','true');uAv.textContent='Bạn';
          userPreview.append?.(uCard,uAv);
          assistantPreview=document.createElement('article');assistantPreview.className='message-row assistant streaming-preview';
          const aAv=document.createElement('div');aAv.className='avatar';aAv.setAttribute?.('aria-hidden','true');aAv.textContent='VL';
          const aCard=document.createElement('div');aCard.className='message-card';
          sourceEl=document.createElement('div');sourceEl.className='answer-source sr-only';
          markdownEl=document.createElement('div');markdownEl.className='answer-text';markdownEl.dataset&&(markdownEl.dataset.markdown='');
          aCard.append?.(sourceEl,markdownEl);assistantPreview.append?.(aAv,aCard);
          history.append(userPreview,assistantPreview);
          previewNodes.push(userPreview,assistantPreview);
        };
        const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
        let streamErrored=false;
        const processLine=async rawLine=>{
          const trimmed=rawLine.trim();if(!trimmed||!isCurrent())return;
          let evt;try{evt=JSON.parse(trimmed);}catch{return;}
          if(evt.type==='stage'){if(evt.session_id){const sIn=$('#session-id-input');if(sIn)sIn.value=evt.session_id;}if(evt.label)$('#pipeline-progress').textContent=evt.label;}
          else if(evt.type==='delta'&&typeof evt.text==='string'){
            ensurePreview();accumulated+=evt.text;
            if(sourceEl)sourceEl.textContent=accumulated;
            if(markdownEl){delete markdownEl.dataset?.rendered;if(typeof renderMarkdownTarget==='function')renderMarkdownTarget(markdownEl);else markdownEl.textContent=accumulated;}
            history.scrollTop=history.scrollHeight;
          }else if(evt.type==='complete'&&typeof evt.html==='string'){
            clearPreviews();
            if(evt.session_id){$('#session-id-input').value=evt.session_id;}
            await installPartial(evt.html,'append',false,isCurrent);if(!isCurrent())return;
            completed=true;
            if(form.querySelector('[name="message"]').value===submittedMessage)form.querySelector('[name="message"]').value='';
            await loadSessions($('#session-search')?.value||'');
          }else if(evt.type==='error'){
            streamErrored=true;clearPreviews();
            appendChatErrorCard(evt.status||503,evt.message||'',null);
          }
        };
        while(true){
          const {value,done}=await reader.read();
          buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});
          const lines=buffer.split('\n');buffer=lines.pop()||'';
          for(const line of lines){await processLine(line);}
          if(done||streamErrored)break;
        }
        if(!streamErrored&&buffer.trim())await processLine(buffer);
      }else{
        const body=await response.text();if(!isCurrent())return;
        if(response.ok){
          await installPartial(body,'append',true,isCurrent);if(!isCurrent())return;
          completed=true;
          if(form.querySelector('[name="message"]').value===submittedMessage)form.querySelector('[name="message"]').value='';
          await loadSessions($('#session-search')?.value||'');
        }else{
          appendChatErrorCard(response.status,body,response.headers);
        }
      }
    }catch(error){
      if(error?.name==='AbortError'){aborted=true;clearPreviews();if(isCurrent())toast('Đã dừng tạo câu trả lời.');}
      else{clearPreviews();if(isCurrent())toast('Không thể kết nối tới VietLex.');}
    }
    finally{if(timer)clearInterval(timer);stopProgress();if(activeChatController===controller)activeChatController=null;loading.hidden=true;submit.disabled=false;if(stopBtn)stopBtn.hidden=true;if(isCurrent())status.textContent=completed?'Đã xử lý xong':aborted?'Đã dừng câu trả lời':'Chưa hoàn tất câu hỏi';}
  }
  var activeChatController=null;
  function stopActiveChat(){if(activeChatController){activeChatController.abort();activeChatController=null;}const stopBtn=$('#chat-stop');if(stopBtn)stopBtn.hidden=true;}
  function extractServerErrorMessage(rawText){
    const text=String(rawText||'').trim();if(!text)return '';
    try{const parsed=JSON.parse(text);const msg=parsed.message||parsed.detail;if(typeof msg==='string'&&msg.trim()&&!/^[a-z0-9_]+$/.test(msg.trim()))return msg.trim();}catch{}
    const ansMatch=text.match(/class="answer-source[^"]*"[^>]*>([\s\S]*?)<\/div>/i);
    if(ansMatch&&ansMatch[1].trim())return ansMatch[1].replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
    const stripped=text.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
    return stripped.length<=280?stripped:'';
  }
  function appendChatErrorCard(statusCode,rawBody,headers){
    const card=document.createElement('article');card.className='message-card error-message';
    if(statusCode===401){
      const serverMsg=extractServerErrorMessage(rawBody)||'Phiên dùng thử yêu cầu đăng nhập tài khoản đã xác minh.';
      card.textContent=`${serverMsg} `;
      if(typeof card.append==='function'){const link=document.createElement('a');link.href='/login';link.textContent='Đăng nhập ngay';card.append(link);}
      toast(serverMsg);
    }else if(statusCode===429){
      const seconds=Number(headers?.get?.('Retry-After'));
      const wait=Number.isFinite(seconds)&&seconds>0&&seconds<=86400
        ? `Thử lại sau khoảng ${seconds<60?`${Math.ceil(seconds)} giây`:`${Math.ceil(seconds/60)} phút`}.`
        : 'Vui lòng thử lại sau.';
      card.textContent=`Đã chạm giới hạn lượt dùng. ${wait} Câu hỏi vẫn được giữ.`;
      toast(card.textContent);
    }else{
      const serverMsg=extractServerErrorMessage(rawBody);
      card.textContent=serverMsg||'Yêu cầu chưa hoàn tất. Vui lòng thử lại sau.';
      toast(card.textContent);
    }
    $('#chat-history')?.append(card);
  }

  function openSource(button){const source=document.getElementById(button.dataset.sourceTarget);const drawer=$('#evidence-drawer');const content=$('#evidence-drawer-content');content.replaceChildren(source?.content?.cloneNode(true)||document.createTextNode('Không có nội dung nguồn.'));drawer.inert=false;drawer.classList.add('open');drawer.setAttribute('aria-hidden','false');$('#drawer-backdrop').hidden=false;drawer._returnFocus=button;drawer.querySelector('[data-action="close-drawer"]')?.focus();}
  function closeSource(){const drawer=$('#evidence-drawer');const returnFocus=drawer._returnFocus;const target=returnFocus?.isConnected?returnFocus:$('#chat-input');target?.focus();drawer.inert=true;drawer.classList.remove('open');drawer.setAttribute('aria-hidden','true');$('#drawer-backdrop').hidden=true;drawer._returnFocus=null;}
  const make=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
  function metricCard(label,value,note){const card=make('div',undefined,'metric-card');card.append(make('strong',`${label}: ${value??'N/A'}`),make('small',note));return card;}
  function scoreText(value){return typeof value==='number'?value.toFixed(3):'Chưa có điểm';}

  function renderCodeEvaluation(panel,evaluation){
    panel.append(make('h3','Kiểm tra tự động của lượt trả lời','evaluation-title'));
    const table=make('table',undefined,'evaluation-table');const body=document.createElement('tbody');
    (evaluation.checks||[]).forEach(check=>{const row=document.createElement('tr');const badge=make('span',check.status==='pass'?'Đạt kiểm tra':'Không đạt',`check-badge ${check.status}`);const state=document.createElement('td');state.append(badge);row.append(make('th',check.label),state,make('td',String(check.value??'N/A')),make('td',check.meaning));body.append(row);});table.append(body);panel.append(table);
    if(evaluation.timings?.length){panel.append(make('h4','Thời gian quan sát'));const timing=make('table',undefined,'evaluation-table timing-table');const timingBody=document.createElement('tbody');evaluation.timings.forEach(item=>{const row=document.createElement('tr');row.append(make('th',item.label),make('td',`${Number(item.seconds).toFixed(4)}s`));timingBody.append(row);});timing.append(timingBody);panel.append(timing);}
    panel.append(make('p',evaluation.limitations?.[0]||'','muted'));
  }

  function renderRagas(panel,result){
    const ragas=result.ragas||{};panel.append(make('h3','Đánh giá tham khảo bằng AI (Ragas)','evaluation-title'));
    if(ragas.status==='ok'){const grid=make('div',undefined,'metric-grid');grid.append(metricCard('Faithfulness',scoreText(ragas.faithfulness),'Mức bám sát đoạn nguồn, thang 0–1; không xác nhận hiệu lực hoặc độ đúng của nguồn.'),metricCard('Answer Relevance',scoreText(ragas.answer_relevance),'Mức trả lời đúng trọng tâm, thang 0–1; không phải xác nhận kết luận đúng luật.'));panel.append(grid);}
    else{panel.append(make('p','Không có điểm Ragas','ragas-empty'));const reason=ragas.error?.message||({disabled:'Deployment chưa bật Ragas.',quota_exceeded:'Đã hết quota Ragas hôm nay.',skipped_no_context:'Không có context để đánh giá.'}[ragas.status])||`Trạng thái: ${ragas.status||'unavailable'}`;panel.append(make('p',reason,'muted'));}
    const catalog=make('div',undefined,'metric-explainer');(result.ragas_metrics||[]).forEach(metric=>{const value=metric.applicable?scoreText(ragas[metric.key]):(metric.display_value||'N/A');const card=metricCard(metric.label,value,metric.meaning||'');if(!metric.applicable)card.append(make('small',metric.reason_not_applicable||''));card.append(make('small',`Giới hạn: ${metric.limitation||'Không có mô tả.'}`));catalog.append(card);});panel.append(catalog);
  }

  async function evaluateAnswer(button,runRagas=false){
    const panel=button.closest('.message-card').querySelector('.evaluation-panel');panel.hidden=false;panel.textContent=runRagas?'Đang chạy Ragas…':'Đang đọc số liệu request…';const data=new FormData();data.set('csrf_token',csrf());data.set('run_ragas',String(runRagas));
    try{const response=await fetch(`/api/evaluation/${encodeURIComponent(button.dataset.traceId)}`,{method:'POST',body:data,credentials:'same-origin'});const result=await response.json();if(!result.code_evaluation){panel.textContent=response.status===429?'Đã đạt giới hạn đánh giá. Vui lòng thử lại sau.':'Không thể chạy đánh giá lúc này.';return;}panel.replaceChildren();renderCodeEvaluation(panel,result.code_evaluation);if(runRagas)renderRagas(panel,result);else{const ragas=make('button','Nhờ AI đánh giá mức bám nguồn (tùy chọn)','button button-quiet');ragas.type='button';ragas.addEventListener('click',()=>evaluateAnswer(button,true));panel.append(ragas);}}catch{panel.textContent='Không thể kết nối dịch vụ đánh giá.';}
  }

  function renderRetrievalTrace(panel,trace){
    panel.replaceChildren();panel.hidden=false;panel.append(make('h3','Retrieval inspector','evaluation-title'));
    if(trace.status!=='available')panel.append(make('p','Trace chi tiết chưa được ghi cho interaction này; dưới đây là các trường còn lưu.','muted'));
    if(trace.query)panel.append(make('h4','Truy vấn gốc'),make('p',trace.query));
    if(trace.rewritten_query)panel.append(make('h4','Truy vấn viết lại đã ghi'),make('p',trace.rewritten_query));
    const overview=make('dl',undefined,'trace-overview');
    const guard=trace.guardrail_state||{};const safety=value=>value===true?'Đạt':value===false?'Không đạt':'Chưa đánh giá';
    [['Trạng thái',trace.request_status],['Runtime',trace.runtime_mode||'Không ghi nhận'],['Backend',trace.backend||'Không ghi nhận'],['Collection',trace.collection||'Không ghi nhận'],['Ranking',trace.ranking||'Không ghi nhận'],['Provider / model',`${trace.observed_provider||'unobserved'} / ${trace.observed_model||'unobserved'}`],['Cache',trace.cached?'Hit':'Miss'],['Evidence cuối',trace.final_evidence_count??'Không ghi nhận'],['Context budget',trace.context_budget_tokens?`${trace.context_budget_tokens} tokens`:'Không ghi nhận'],['Guardrails chế độ / trạng thái',`${guard.mode||'unobserved'} / ${guard.status||'unobserved'}`],['Guardrails yêu cầu / thực thi',`${guard.requested??'Không ghi nhận'} / ${guard.executed??'Không ghi nhận'}`],['Guardrails input/output',`${safety(guard.input_safe)} / ${safety(guard.output_safe)}`],...Object.entries(guard.stages||{}).map(([stage,state])=>[`Guardrails ${stage}`,`${state.status||'not_run'}: ${safety(state.safe)}${state.error?' ('+state.error.reason+')':''}`])].forEach(([label,value])=>{overview.append(make('dt',label),make('dd',String(value??'N/A')));});panel.append(overview);
    const counts=Object.entries(trace.candidate_counts||{});if(counts.length){panel.append(make('h4','Candidate counts đã ghi'));const table=make('table',undefined,'evaluation-table');const body=document.createElement('tbody');counts.forEach(([stage,count])=>{const row=document.createElement('tr');row.append(make('th',stage),make('td',String(count)));body.append(row);});table.append(body);panel.append(table);}
    const timings=Object.entries(trace.latency||{});if(timings.length){panel.append(make('h4','Latency'));const table=make('table',undefined,'evaluation-table');const body=document.createElement('tbody');timings.forEach(([stage,seconds])=>{const row=document.createElement('tr');row.append(make('th',stage),make('td',`${Number(seconds).toFixed(4)}s`));body.append(row);});table.append(body);panel.append(table);}
    if(trace.evidence?.length){panel.append(make('h4','Context được chọn'));const list=make('ol');trace.evidence.forEach(item=>{const row=make('li');const button=make('button',item.citation||('Bằng chứng '+item.rank));button.type='button';button.dataset.action='open-source';button.dataset.sourceTarget='source-'+panel.closest('[data-trace-id]').dataset.traceId+'-'+item.rank;row.append(button);list.append(row);});panel.append(list);}
    if(trace.diagnostics){panel.append(make('h4','Diagnostics đã làm sạch'));Object.entries(trace.diagnostics).forEach(([key,value])=>panel.append(make('p',key+': '+String(value))));}
    panel.append(make('p','Chỉ hiển thị giá trị runtime đã ghi; không suy đoán score hoặc confidence.','muted'));
  }

  async function inspectRetrieval(button){
    const panel=button.closest('.message-card').querySelector('.retrieval-panel');panel.hidden=false;panel.textContent='Đang đọc retrieval trace…';
    try{const response=await fetch(`/api/interactions/${encodeURIComponent(button.dataset.traceId)}/retrieval`,{credentials:'same-origin'});if(!response.ok){panel.textContent='Không thể mở retrieval trace.';return;}renderRetrievalTrace(panel,await response.json());}catch{panel.textContent='Không thể kết nối retrieval inspector.';}
  }

  async function openPinEvidence(button){
    const dialog=$('#pin-evidence-dialog');const form=$('#pin-evidence-form');const select=form.querySelector('[name="workspace_id"]');const empty=$('#pin-evidence-empty');select.replaceChildren();form.querySelector('[name="trace_id"]').value=button.dataset.traceId;form.querySelector('[name="evidence_index"]').value=button.dataset.evidenceIndex;
    try{const response=await fetch('/api/workspaces',{credentials:'same-origin'});if(!response.ok)throw new Error('workspace_unavailable');const payload=await response.json();form.querySelector('[name="note"]').value='';(payload.workspaces||[]).forEach(item=>{const option=document.createElement('option');option.value=item.workspace_id;option.textContent=item.title;select.append(option);});empty.hidden=select.options.length>0;form.querySelector('[type="submit"]').disabled=select.options.length===0;dialog.showModal();}catch{toast('Không thể tải workspace.');}
  }

  document.addEventListener('change',event=>{const target=event.target;if(target?.matches?.('[data-llm-target]')){const [prov,mod]=String(target.value||'auto|').split('|');const pIn=$('#chat-form input[name="llm_provider"]');const mIn=$('#chat-form input[name="llm_model"]');if(pIn)pIn.value=prov||'auto';if(mIn)mIn.value=mod||'';}});
  document.addEventListener('submit',async event=>{const form=event.target;if(form.id==='pin-evidence-form'){event.preventDefault();const submit=form.querySelector('[type="submit"]');if(submit.disabled)return;submit.disabled=true;try{const workspaceId=form.querySelector('[name="workspace_id"]').value;const response=await fetch(`/workspaces/${encodeURIComponent(workspaceId)}/evidence`,{method:'POST',body:new FormData(form),credentials:'same-origin'});if(response.ok){$('#pin-evidence-dialog').close();toast('Đã ghim bằng chứng vào workspace.');}else toast(response.status===409?'Bằng chứng đã ghim hoặc workspace đã đạt giới hạn.':'Không thể ghim bằng chứng.');}catch{toast('Không thể kết nối workspace.');}finally{submit.disabled=false;}return;}if(form.id==='chat-form'){event.preventDefault();await submitChat(form);}if(form.matches('[data-feedback-form]')){event.preventDefault();const response=await fetch('/api/feedback',{method:'POST',body:new FormData(form),credentials:'same-origin'});if(response.ok){const actions=form.closest('.message-actions');const state=make('span',form.querySelector('[name="rating"]').value==='up'?'✓ Hữu ích':'✓ Đã ghi nhận');actions.querySelectorAll('[data-feedback-form]').forEach(node=>node.remove());actions.append(state);}else toast('Không thể ghi nhận phản hồi.');}});
  document.addEventListener('click',async event=>{const target=event.target.closest('button,a');if(!target)return;if(target.dataset.prompt){$('#chat-input').value=target.dataset.prompt;$('#chat-form').requestSubmit();}const action=target.dataset.action;if(action==='stop-chat'){stopActiveChat();return;}if(action==='toggle-tech-details'){const bar=target.closest('.message-meta')?.querySelector('.tech-details-bar');if(bar){bar.hidden=!bar.hidden;target.setAttribute('aria-expanded',String(!bar.hidden));}return;}if(action==='new-session'){stopActiveChat();const data=new FormData();data.set('csrf_token',csrf());await navigateChat('/sessions',{method:'POST',body:data,credentials:'same-origin'});loadSessions();}if(action==='select-session'){stopActiveChat();await navigateChat(`/sessions/${encodeURIComponent(target.dataset.sessionId)}`);}if(action==='delete-session'&&confirm('Xóa hội thoại này?')){await fetch(`/sessions/${target.dataset.sessionId}`,{method:'DELETE',headers:{'X-CSRF-Token':csrf()},credentials:'same-origin'});loadSessions();}if(action==='rename-session'){const name=prompt('Tên mới cho hội thoại:',target.dataset.title||'');if(name){await fetch(`/sessions/${target.dataset.sessionId}/rename`,{method:'POST',headers:{'HX-Prompt':name},body:new URLSearchParams({csrf_token:csrf()}),credentials:'same-origin'});loadSessions();}}if(action==='open-source')openSource(target);if(action==='close-drawer')closeSource();if(action==='pin-evidence')await openPinEvidence(target);if(action==='close-pin-dialog')$('#pin-evidence-dialog').close();if(action==='copy-answer'){await navigator.clipboard.writeText(target.closest('.message-card').querySelector('.answer-source').textContent);toast('Đã sao chép câu trả lời');}if(action==='retry'){$('#chat-input').value=target.dataset.query||'';$('#chat-form').requestSubmit();}if(action==='inspect-retrieval')await inspectRetrieval(target);if(action==='evaluate')await evaluateAnswer(target,false);});
  $('#drawer-backdrop')?.addEventListener('click',closeSource);document.addEventListener('keydown',event=>{if(event.key==='Escape'&&$('#evidence-drawer')?.classList.contains('open'))closeSource();});$('#chat-form')?.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();event.currentTarget.requestSubmit();}});let searchTimer;$('#session-search')?.addEventListener('input',event=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadSessions(event.target.value),180);});const savedTheme=localStorage.getItem('vietlex-theme');if(savedTheme)document.documentElement.dataset.theme=savedTheme;$('#theme-toggle')?.addEventListener('click',()=>{const next=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=next;localStorage.setItem('vietlex-theme',next);});fetch('/readyz').then(async r=>({ok:r.ok,data:await r.json()})).then(({ok})=>{const node=$('#system-readiness');if(!node)return;node.textContent=ok?'Hệ thống sẵn sàng':'Hệ thống chưa sẵn sàng';node.classList.add(ok?'ready':'not-ready');}).catch(()=>{const node=$('#system-readiness');if(node)node.textContent='Không đọc được trạng thái';});loadSessions();renderMarkdown();
  const initialSession=new URLSearchParams(location.search).get('session');
  if(initialSession&&/^[A-Za-z0-9-]{1,100}$/.test(initialSession))void navigateChat('/sessions/'+encodeURIComponent(initialSession));
})();
