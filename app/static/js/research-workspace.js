(() => {
  const csrf = document.body.dataset.csrfToken || '';
  const workspaceId = document.body.dataset.workspaceId || '';
  const result = document.querySelector('#analysis-result');
  const researchPlan = document.querySelector('#research-plan');
  const researchResult = document.querySelector('#deep-research-result');
  const selected = () => [...document.querySelectorAll('[name="selected_evidence"]:checked')].map(node => node.value);
  const group = name => [...document.querySelectorAll('[data-evidence-group="' + name + '"]:checked')].map(node => node.value);
  let pending = false;
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function showScope() {
    const node = document.querySelector('#evidence-scope');
    if (node) node.textContent = 'Phạm vi bằng chứng: ' + selected().length + ' mục · Nhóm A: ' + group('a').length + ' · Nhóm B: ' + group('b').length;
  }
  document.querySelectorAll('.evidence-board .evidence-row').forEach(row => {
    const source = row.querySelector('[name="selected_evidence"]');
    if (!source) return;
    const groups = element('fieldset', undefined, 'evidence-groups');
    groups.append(element('legend', 'Nhóm so sánh'));
    ['a', 'b'].forEach(name => {
      const label = element('label'), input = element('input');
      input.type = 'checkbox'; input.dataset.evidenceGroup = name; input.value = source.value;
      label.append(input, document.createTextNode(' ' + name.toUpperCase())); groups.append(label);
    });
    const controls = element('div', undefined, 'evidence-controls');
    const originalLabel = source.closest('label');
    originalLabel.replaceWith(controls);
    controls.append(originalLabel, groups);
  });
  document.querySelectorAll('[data-analysis="compare"] input[name="evidence_a"],[data-analysis="compare"] input[name="evidence_b"]').forEach(input => {
      input.required = false;
      const label = input.closest('label');
      if (label) label.hidden = true;
  });
  const labels = {
    directly_supported: 'Có dẫn chiếu · cần kiểm chứng nội dung',
    partially_supported: 'Liên kết một phần · cần kiểm chứng',
    unsupported: 'Chưa có hỗ trợ', needs_verification: 'Cần kiểm chứng',
    all: 'Tất cả', difference: 'Khác biệt', addition: 'Bổ sung', removal: 'Loại bỏ',
    potential_conflict: 'Xung đột tiềm năng', same: 'Tương đồng',
    required: 'Bắt buộc', permitted: 'Được phép', prohibited: 'Bị cấm', conditional: 'Có điều kiện',
    insufficient_evidence: 'Không đủ bằng chứng', degraded: 'Dịch vụ phân tích chưa khả dụng',
      provider_error: 'Chưa thể hoàn tất phân tích. Bạn có thể thử lại sau.',
      invalid_structured_response: 'Chưa thể xác minh kết quả phân tích. Vui lòng thử lại hoặc chọn bằng chứng khác.',
      evidence_scope_too_large: 'Phạm vi quá lớn. Vui lòng chọn ít bằng chứng hơn.',
    workspace_changed: 'Hồ sơ đã thay đổi; kết quả chưa được lưu.',
    invalid_evidence_id: 'Mã bằng chứng không hợp lệ.'
  };
  function evidenceLinks(ids, payload) {
    const cell = element('td');
    ids.forEach(id => {
      const source = document.getElementById('evidence-' + id);
      if (!source) {
        const saved = (payload.evidence_snapshot || []).find(item => item.evidence_id === id);
        if (saved) {
          const detail = element('details');
          detail.append(element('summary', saved.citation || id), element('p', saved.excerpt || saved.original));
          if (Number.isInteger(saved.document_id) && saved.document_id > 0) {
            const link = element('a', 'Mở văn bản'); link.href = '/documents/' + saved.document_id; detail.append(link);
          }
          cell.append(detail);
        } else cell.append(element('p', id + ' · bằng chứng đã bỏ ghim'));
        return;
      }
      const link = element('a', source.querySelector('.citation')?.textContent || id);
      link.href = '#evidence-' + id; cell.append(link, element('br'));
    });
    return cell;
  }
  function renderResearch(payload, target = researchResult) {
    if (!target) return;
    target.replaceChildren();
    const dossier = payload.result || payload;
    const summary = dossier.status === 'complete' ? 'Cả 5 bước đều có kết quả metadata từ nguồn chính thức.' : dossier.status === 'failed' ? 'Không bước nào có kết quả metadata từ nguồn chính thức.' : 'Kết quả tìm kiếm một phần; xem trạng thái từng bước.';
    target.append(element('p', summary, 'legal-warning'));
    (dossier.steps || []).forEach(step => {
      const card = element('article', undefined, 'research-step-result');
      card.append(element('h3', step.title), element('p', step.query, 'muted'));
      card.append(element('span', step.status, 'support-state ' + step.status));
      if (!(step.sources || []).length) card.append(element('p', 'Chưa có kết quả metadata từ nguồn chính thức.', 'muted'));
      const sources = element('ul', undefined, 'official-source-list');
      (step.sources || []).forEach(source => {
        const item = element('li'), link = element('a', source.title || source.domain);
        link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        const metadata = [source.document_number, source.issued_date, source.domain].filter(Boolean).join(' · ');
        item.append(link, document.createTextNode(' · ' + metadata));
        if (source.snippet && source.snippet !== source.title) item.append(element('p', source.snippet));
        sources.append(item);
      });
      if (sources.children.length) card.append(sources);
      target.append(card);
    });
    if (payload.provider || dossier.provider || payload.model || dossier.model) {
      const technical = element('details');
      technical.append(element('summary', 'Thông tin kỹ thuật'), element('p', (payload.provider || dossier.provider || '—') + ' · ' + (payload.model || dossier.model || '—'), 'muted'));
      target.append(technical);
    }
  }
  function renderPlan(plan) {
    if (!researchPlan) return;
    researchPlan.replaceChildren();
    const form = element('form', undefined, 'research-plan-editor');
    form.dataset.deepResearch = 'true';
    form.action = '/workspaces/' + workspaceId + '/research/run';
    form.method = 'post';
    form.append(element('h3', 'Kế hoạch đề xuất'));
    plan.steps.forEach((step, index) => {
      const label = element('label', (index + 1) + '. ' + step.title);
      const input = element('textarea'); input.maxLength = 500; input.required = true; input.value = step.query; input.dataset.stepIndex = String(index);
      label.append(input); form.append(label);
    });
    const note = element('p', 'Việc chạy kế hoạch gửi 5 truy vấn tới Hệ thống văn bản của Cổng Chính phủ. Không gọi LLM và không tiêu thụ token.', 'muted');
    const button = element('button', 'Bắt đầu nghiên cứu', 'button button-primary'); button.type = 'submit';
    form.append(note, button); form._researchPlan = plan; researchPlan.append(form);
  }
  function renderAnalysis(payload, target = result) {
    if (payload.kind === 'deep_research' || payload.result?.steps) { renderResearch(payload, target); return; }
    target.replaceChildren();
    if (payload.status && payload.status !== 'ok') target.append(element('p', labels[payload.status] || payload.status, 'legal-warning'));
      if (payload.provider || payload.model) {
        const technical = element('details');
        technical.append(element('summary', 'Thông tin kỹ thuật'), element('p', (payload.provider || '—') + ' · ' + (payload.model || '—'), 'muted'));
        target.append(technical);
      }
    if (payload.text) target.append(element('p', payload.text));
    const rows = payload.result?.findings || payload.result?.rows;
    if (!rows) {
      if (!payload.text) target.append(element('p', labels[payload.detail] || 'Không thể hoàn tất phân tích. Vui lòng thử lại.'));
      return;
    }
    if (!rows.length) { target.append(element('p', 'Không tìm được kết quả từ bằng chứng đã chọn.')); return; }
    const isCompare = Boolean(payload.result.findings);
    const filter = element('select'); filter.setAttribute('aria-label', 'Lọc kết quả phân tích');
    const options = isCompare ? ['all', 'difference', 'addition', 'removal', 'potential_conflict', 'same'] : ['all', 'required', 'permitted', 'prohibited', 'conditional'];
    options.forEach(value => { const option = element('option', labels[value]); option.value = value; filter.append(option); });
    const table = element('table', undefined, 'evaluation-table analysis-table');
      const headings = isCompare ? ['Khía cạnh', 'Nhóm A', 'Nhóm B', 'Diễn giải', 'Trạng thái hỗ trợ', 'Bằng chứng'] : ['Chủ thể', 'Nghĩa vụ / quyền', 'Tính chất', 'Điều kiện / thời hạn / ngoại lệ', 'Trạng thái hỗ trợ', 'Bằng chứng'];
    const head = element('thead'), header = element('tr');
    headings.forEach(text => { const th = element('th', text); th.scope = 'col'; header.append(th); }); head.append(header);
    const body = element('tbody');
    rows.forEach(item => {
      const row = element('tr'); row.dataset.kind = isCompare ? item.change_type : item.modality;
      const values = isCompare ? [item.topic, item.document_a_finding, item.document_b_finding, item.interpretation] : [item.subject, item.action, labels[item.modality], [item.condition, item.deadline, item.exception].filter(Boolean).join(' · ')];
      values.push(labels[item.support_state] || item.support_state);
      values.forEach((value, index) => { const td = element('td', value || '—'); td.dataset.label = headings[index]; row.append(td); });
      const links = evidenceLinks(isCompare ? [...item.evidence_a, ...item.evidence_b] : item.evidence_ids, payload);
      links.dataset.label = 'Bằng chứng'; row.append(links); body.append(row);
    });
    table.append(head, body);
    filter.addEventListener('change', () => [...body.rows].forEach(row => { row.hidden = filter.value !== 'all' && row.dataset.kind !== filter.value; }));
    target.append(filter, table);
  }
  document.querySelectorAll('[data-saved-analysis]').forEach(node => {
    try { renderAnalysis(JSON.parse(node.textContent), node.parentElement.querySelector('[data-analysis-view]')); }
    catch { /* The server-rendered record remains readable for older schemas. */ }
  });
  document.addEventListener('change', showScope);
  document.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button || !['delete-workspace', 'unpin-evidence'].includes(button.dataset.action)) return;
    const removeWorkspace = button.dataset.action === 'delete-workspace';
    if (!confirm(removeWorkspace ? 'Xóa hồ sơ, ghi chú, bằng chứng và phân tích đã lưu? Không thể hoàn tác.' : 'Bỏ ghim bằng chứng này?')) return;
    button.disabled = true;
    try {
      const path = '/workspaces/' + workspaceId + (removeWorkspace ? '' : '/evidence/' + button.dataset.evidenceId);
      const response = await fetch(path, {method: 'DELETE', headers: {'X-CSRF-Token': csrf}});
      if (!response.ok) throw new Error('delete_failed');
      if (removeWorkspace) location.href = '/workspaces'; else location.reload();
    } catch { result.textContent = 'Không thể lưu thay đổi. Vui lòng thử lại.'; }
    finally { button.disabled = false; }
  });
  document.addEventListener('submit', async event => {
    const planForm = event.target.closest('[data-research-plan]');
    if (planForm) {
      event.preventDefault();
      if (pending) return;
      pending = true;
      const button = planForm.querySelector('button'); button.disabled = true;
      if (researchPlan) researchPlan.textContent = 'Đang tạo kế hoạch…';
      try {
        const response = await fetch(planForm.action, {method: 'POST', body: new FormData(planForm)});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'plan_failed');
        renderPlan(payload);
      } catch { if (researchPlan) researchPlan.textContent = 'Không thể tạo kế hoạch lúc này.'; }
      finally { pending = false; button.disabled = false; }
      return;
    }
    const runForm = event.target.closest('[data-deep-research]');
    if (runForm) {
      event.preventDefault();
      if (pending) return;
      const plan = structuredClone(runForm._researchPlan);
      runForm.querySelectorAll('[data-step-index]').forEach(input => { plan.steps[Number(input.dataset.stepIndex)].query = input.value; });
      const data = new FormData(); data.set('csrf_token', csrf); data.set('plan', JSON.stringify(plan));
      pending = true;
      runForm.querySelector('button').disabled = true;
      if (researchResult) { researchResult.setAttribute('aria-busy', 'true'); researchResult.textContent = 'Đang đối chiếu 5 bước với nguồn chính thức…'; }
      try {
        const response = await fetch(runForm.action, {method: 'POST', body: data});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'research_failed');
        renderResearch(payload);
      } catch { if (researchResult) researchResult.textContent = 'Không thể hoàn tất nghiên cứu lúc này.'; }
      finally { pending = false; runForm.querySelector('button').disabled = false; researchResult?.setAttribute('aria-busy', 'false'); }
      return;
    }
    const form = event.target.closest('[data-analysis]');
    if (!form) return;
    event.preventDefault();
    if (pending) return;
    const data = new FormData(form);
    if (form.dataset.analysis === 'compare') {
      const a = group('a'), b = group('b');
      if (!a.length || !b.length) { result.textContent = 'Chọn bằng chứng cho cả nhóm A và nhóm B.'; return; }
      data.set('evidence_a', a.join(',')); data.set('evidence_b', b.join(','));
    } else {
      if (!selected().length) { result.textContent = 'Chọn ít nhất một bằng chứng.'; return; }
      data.set('evidence_ids', selected().join(','));
    }
    pending = true;
    document.querySelectorAll('[data-analysis] button').forEach(button => { button.disabled = true; });
    result.setAttribute('aria-busy', 'true'); result.textContent = 'Đang phân tích trong phạm vi bằng chứng đã chọn…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: data});
      const payload = await response.json(); renderAnalysis(payload);
      if (payload.analysis_id) {
          const names = { selected_evidence: 'Phân tích bằng chứng', comparison: 'So sánh văn bản', obligation_matrix: 'Nghĩa vụ và quyền' };
          const entry = element('article'); entry.append(element('strong', names[payload.kind] || 'Kết quả phân tích'));
        const view = element('div', undefined, 'analysis-result'); renderAnalysis(payload, view); entry.append(view);
        document.querySelector('.analysis-history .muted')?.remove();
        document.querySelector('.analysis-history .section-rule')?.after(entry);
        const entries = [...document.querySelectorAll('.analysis-history>article')];
        entries.slice(50).forEach(node => node.remove());
        const count = document.querySelector('.analysis-history .section-rule>span');
        if (count) count.textContent = Math.min(entries.length, 50) + ' lần chạy';
      }
    } catch { result.textContent = 'Không thể hoàn tất phân tích lúc này.'; }
    finally {
      pending = false; result.setAttribute('aria-busy', 'false');
      document.querySelectorAll('[data-analysis] button').forEach(button => { button.disabled = false; });
    }
  });
  const theme = localStorage.getItem('vietlex-theme');
  if (theme) document.documentElement.dataset.theme = theme;
  showScope();
})();
