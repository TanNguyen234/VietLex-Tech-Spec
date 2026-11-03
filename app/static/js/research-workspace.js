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
    invalid_evidence_id: 'Mã bằng chứng không hợp lệ.',
    evidence_linked: 'Đã liên kết căn cứ · cần kiểm chứng nội dung'
  };
  const sourceErrors = {
    source_transport_error: 'Nguồn phản hồi chậm hoặc mất kết nối. Có thể thử lại.',
    source_body_too_large: 'Tệp nguồn vượt giới hạn đọc trực tuyến. Hãy mở bản gốc.',
    source_page_out_of_range: 'Trang yêu cầu không nằm trong văn bản.',
    source_page_window_text_limit: 'Nhóm trang có quá nhiều chữ. Hãy chọn ít trang hơn.',
    source_malformed_pdf: 'Chưa đọc được cấu trúc PDF này. Hãy đối chiếu bản gốc.',
    source_encrypted_pdf: 'PDF được bảo vệ; không thể trích xuất nội dung.',
    ocr_file_limit: 'Nhóm trang quá lớn để OCR. Hãy chọn một trang.',
    ocr_timeout: 'OCR chưa hoàn tất trong thời gian cho phép. Hãy thử nhóm nhỏ hơn.',
    ocr_incomplete: 'OCR chưa trả đủ nội dung. Hãy thử từng trang.',
    ocr_provider_error: 'Dịch vụ OCR chưa khả dụng. Nội dung không được suy đoán.',
    source_http_403: 'Cổng nguồn đang từ chối truy cập. Hãy mở bản gốc.',
    source_http_404: 'Không tìm thấy tệp tại địa chỉ nguồn.'
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
    target.append(element('p', 'Tìm thấy tiêu đề chưa đủ để trả lời. Đọc nguồn, ghim đoạn căn cứ rồi chọn Phân tích; hiệu lực vẫn chưa xác minh.'));
    const seen = new Set();
    (dossier.steps || []).forEach(step => {
      const card = element('article', undefined, 'research-step-result');
      card.append(element('h3', step.title), element('p', step.query, 'muted'));
      const searchStates = {
        results_found: 'Có kết quả tìm kiếm',
        partial_results: 'Có kết quả · một nguồn gặp lỗi',
        no_results: 'Chưa tìm thấy với truy vấn này',
        provider_error: 'Chưa truy cập được nguồn tìm kiếm'
      };
      card.append(element('span', searchStates[step.status] || 'Chưa xác định trạng thái', 'support-state ' + step.status));
      if (step.status === 'provider_error' || step.status === 'partial_results') {
        card.append(element('p', 'Một hoặc nhiều cổng nguồn chưa trả kết quả thành công. Bạn có thể thử lại; lỗi này không có nghĩa là không tồn tại quy định.', 'legal-warning'));
        if (step.error_kind) {
          const detail = element('details');
          detail.append(element('summary', 'Chi tiết lỗi kết nối'), element('p', step.error_kind));
          card.append(detail);
        }
      } else if (!(step.sources || []).length) card.append(element('p', 'Hãy thử cụm từ cụ thể hơn hoặc số hiệu văn bản. Không tìm thấy với truy vấn này chưa chứng minh không có quy định.', 'muted'));
      const sources = element('ul', undefined, 'official-source-list');
      (step.sources || []).forEach(source => {
        if (seen.has(source.url)) return;
        seen.add(source.url);
        const item = element('li'), link = element('a', source.title || source.domain);
        link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        const metadata = [source.document_number, source.issued_date, source.domain].filter(Boolean).join(' · ');
        item.append(link, document.createTextNode(' · ' + metadata));
        if (source.snippet && source.snippet !== source.title) item.append(element('p', source.snippet));
        const read = element('button', 'Đọc toàn văn / bản gốc', 'button button-quiet');
        read.type = 'button';
        const reader = element('div'); reader.setAttribute('aria-live', 'polite');
        read.addEventListener('click', async () => {
          read.disabled = true;
          try { await readOfficial(source.url, reader); } finally { read.disabled = false; }
        });
        item.append(read, reader);
        sources.append(item);
      });
      if (sources.children.length) card.append(sources);
      else if ((step.sources || []).length) card.append(element('p', 'Các nguồn của bước này đã được hiển thị ở bước trước.', 'muted'));
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
    if (plan.query_method === 'fallback') form.append(element('p', 'Chưa tạo được từ khóa bằng AI. Hãy sửa các cụm tìm kiếm bên dưới trước khi chạy.', 'legal-warning'));
    plan.steps.forEach((step, index) => {
      const label = element('label', (index + 1) + '. ' + step.title);
      const input = element('textarea'); input.maxLength = 500; input.required = true; input.value = step.query; input.dataset.stepIndex = String(index);
      label.append(input); form.append(label);
    });
    const note = element('p', 'AI chỉ đề xuất từ khóa khi tạo kế hoạch, không xác nhận luật. Bước tìm kiếm gửi 5 truy vấn bạn duyệt tới cổng nguồn đã cấu hình; bước OCR hoặc phân tích sau đó có thể dùng AI.', 'muted');
    const button = element('button', 'Bắt đầu nghiên cứu', 'button button-primary'); button.type = 'submit';
    form.append(note, button); form._researchPlan = plan; researchPlan.append(form);
  }
  function renderContractReview(payload, target) {
    target.replaceChildren();
    if (payload.status && !['ok', 'insufficient_evidence'].includes(payload.status)) {
      target.append(element('p', labels[payload.status] || payload.status, 'legal-warning'));
      return;
    }
    const findings = payload.result?.findings || [];
    if (!findings.length) { target.append(element('p', 'Chưa có finding trong phạm vi điều khoản đã chọn.')); return; }
    const clauses = new Map((payload.selected_clauses || []).map(item => [item.clause_id, item]));
    const headings = ['Điều khoản', 'Mức rà soát', 'Vấn đề', 'Căn cứ luật', 'Trạng thái hỗ trợ', 'Đề xuất'];
    const table = element('table', undefined, 'evaluation-table analysis-table contract-review-table');
    const head = element('thead'), header = element('tr'), body = element('tbody');
    headings.forEach(value => { const th = element('th', value); th.scope = 'col'; header.append(th); }); head.append(header);
    findings.forEach(finding => {
      const clause = clauses.get(finding.clause_id) || {};
      const row = element('tr');
      const values = [clause.title || finding.clause_id, finding.risk_level, finding.issue];
      values.forEach((value, index) => { const cell = element('td', value || '—'); cell.dataset.label = headings[index]; if (index === 1) cell.className = 'contract-risk-' + finding.risk_level; row.append(cell); });
      const law = evidenceLinks(finding.legal_evidence_ids || [], payload); law.dataset.label = headings[3]; if (!(finding.legal_evidence_ids || []).length) law.textContent = 'Chưa có căn cứ luật được chọn'; row.append(law);
      [labels[finding.support_state] || finding.support_state, finding.recommendation].forEach((value, index) => { const cell = element('td', value || '—'); cell.dataset.label = headings[index + 4]; row.append(cell); });
      body.append(row);
    });
    table.append(head, body); target.append(table);
  }
  function operationError(payload, status) {
    if (status === 429) return JSON.stringify(payload).includes('daily_quota') ? 'Đã hết lượt hôm nay (UTC). Nguồn và kết quả đã lưu vẫn đọc được.' : 'Đã chạm giới hạn lượt/phút. Hãy đợi rồi thử lại; nội dung nhập vẫn còn.';
    if (status === 401 || status === 403) return 'Phiên đăng nhập đã thay đổi. Sao chép nội dung đang nhập rồi tải lại trang.';
    return labels[payload.detail] || labels[payload.status] || 'Chưa hoàn tất được yêu cầu. Nội dung nhập vẫn còn để bạn thử lại.';
  }
  function sourceLinks(ids, payload) {
    const group = element('div', undefined, 'analysis-source-links');
    const cell = evidenceLinks(ids, payload); group.append(...cell.childNodes); return group;
  }
  function renderTimeline(payload, target) {
    target.replaceChildren();
    target.append(element('p', 'Các ngày được trích từ nguồn; chưa xác minh hiệu lực hoặc tính đúng đắn của thời hạn pháp lý.', 'legal-warning'));
    const timeline = payload.result || {};
    (timeline.events || []).forEach(event => {
      const card = element('article');
      card.append(element('h3', event.date), element('p', event.context), element('blockquote', event.quote));
      card.append(sourceLinks([event.evidence_id], payload)); target.append(card);
    });
    (timeline.unresolved || []).forEach(event => {
      const card = element('article');
      card.append(element('p', event.reason === 'invalid_calendar_date' ? 'Ngày không hợp lệ' : 'Cần xác định ngày bắt đầu'), element('blockquote', event.quote), sourceLinks([event.evidence_id], payload)); target.append(card);
    });
    const coverage = timeline.coverage || {};
    target.append(element('p', `${coverage.sources_with_dates || 0}/${coverage.sources_total || 0} nguồn có ngày hợp lệ; ${coverage.events || 0} mốc, ${coverage.unresolved || 0} mục cần làm rõ.`, 'muted'));
  }
  function renderClaims(payload, target) {
    target.replaceChildren();
    target.append(element('p', 'Đánh giá của mô hình trong phạm vi nguồn đã chọn; không chứng nhận tính đúng đắn pháp lý.', 'legal-warning'));
    if (payload.status !== 'ok') target.append(element('p', labels[payload.status] || 'Chưa kiểm chứng được các khẳng định.', 'legal-warning'));
    const verification = payload.result || {};
    const verdicts = {supported: 'Nguồn hỗ trợ', contradicted: 'Nguồn mâu thuẫn', insufficient: 'Chưa đủ bằng chứng'};
    (verification.claims || []).forEach(claim => {
      const card = element('article'); card.append(element('h3', claim.text), element('p', verdicts[claim.verdict] || claim.verdict));
      (claim.quotes || []).forEach(quote => card.append(element('blockquote', quote.quote), sourceLinks([quote.evidence_id], payload)));
      target.append(card);
    });
    const coverage = verification.coverage || {};
    target.append(element('p', `${coverage.assessed_claims || 0}/${coverage.total_claims || 0} khẳng định đã đánh giá; ${coverage.insufficient_claims || 0} chưa đủ bằng chứng; ${coverage.skipped_claims || 0} chưa đánh giá.`, 'muted'));
  }
  function renderRedline(payload, target) {
    target.replaceChildren();
    target.append(element('p', 'So sánh văn bản, chưa đánh giá ý nghĩa hoặc rủi ro pháp lý.', 'legal-warning'));
    const redline = payload.result || {};
    const groups = {added: 'Thêm', removed: 'Xóa', changed: 'Thay đổi', same: 'Nội dung giữ nguyên'};
    Object.entries(groups).forEach(([key, title]) => {
      const section = element('details'); section.open = key !== 'same';
      section.append(element('summary', `${title}: ${(redline[key] || []).length}`));
      (redline[key] || []).forEach(row => {
        const card = element('article');
        card.append(element('h3', (row.before?.title || row.after?.title || 'Điều khoản')));
        ['before', 'after'].forEach(side => { if (row[side]) card.append(element('p', `${side === 'before' ? 'Trước' : 'Sau'}: ${row[side].clause_id} · thứ tự ${row[side].order || '—'}`, 'muted')); });
        if (row.comparison_mode === 'bounded_coarse_span') card.append(element('p', 'Vùng thay đổi lớn; hiển thị trích đoạn thay vì diff từng ký tự.', 'muted'));
        const changes = row.changes || [{before: row.before_quote, after: row.after_quote}];
        changes.forEach(change => {
          if (change.before?.quote) card.append(element(key === 'same' ? 'blockquote' : 'del', change.before.quote));
          if (change.after?.quote && key !== 'same') card.append(element('ins', change.after.quote));
        });
        section.append(card);
      }); target.append(section);
    });
    const coverage = redline.coverage?.clauses || {};
    target.append(element('p', `${coverage.numerator || 0}/${coverage.denominator || 0} điều khoản được đối chiếu.`, 'muted'));
  }
  function renderReport(payload, target) {
    target.replaceChildren();
    if (payload.analysis_id) {
      const link = element('a', 'Mở, sửa hoặc xuất báo cáo');
      link.href = '/workspaces/' + encodeURIComponent(workspaceId) + '/reports/' + encodeURIComponent(payload.analysis_id);
      target.append(link);
    }
    const bundle = payload.result || payload, report = bundle.report;
    if (payload.status === 'citation_mismatch') target.append(element('p', 'Có khẳng định dẫn nguồn không khớp với nguồn mô hình dùng để kiểm chứng. Cần rà soát lại.', 'legal-warning'));
    target.append(element('p', 'Báo cáo giới hạn trong nguồn đã chọn. Kiểm chứng bằng mô hình; chưa được chuyên gia xác nhận.', 'legal-warning'));
    if (!report) { target.append(element('p', labels[payload.status] || 'Chưa lập được báo cáo.')); return; }
    target.append(element('h3', report.issue));
    Object.entries({analysis: 'Phân tích', exceptions: 'Ngoại lệ', checklist: 'Checklist'}).forEach(([key,title]) => {
      const section = element('section'); section.append(element('h3', title));
      (report[key] || []).forEach(claim => { const row = element('article'); row.append(element('p', claim.text), sourceLinks(claim.evidence_ids || [], payload)); section.append(row); });
      target.append(section);
    });
    (report.unknown || []).forEach(text => target.append(element('p', text, 'legal-warning')));
    const assessment = element('details'), view = element('div'); assessment.append(element('summary', 'Kiểm chứng khẳng định'), view);
    renderClaims({...bundle.model_assessment, evidence_snapshot: payload.evidence_snapshot}, view); target.append(assessment);
  }
  async function readOfficial(url, target, pageStart = 1, useOcr = false, pageLimit = 5) {
    target.replaceChildren(element('p', useOcr ? 'Đang đọc ảnh quét; cần đối chiếu lại bản gốc…' : 'Đang tải nội dung từ nguồn chính thức…'));
    target.setAttribute('aria-busy', 'true');
    const data = new FormData(); data.set('csrf_token', csrf); data.set('urls', url);
    data.set('page_start', String(pageStart)); data.set('use_ocr', String(useOcr));
    data.set('page_limit', String(pageLimit));
    try {
      const response = await fetch('/workspaces/' + workspaceId + '/analyses/sources', {method:'POST', body:data, credentials:'same-origin'});
      const payload = await response.json();
      if (!response.ok && !payload.result) {
        const daily = JSON.stringify(payload).includes('daily_quota');
        target.textContent = response.status === 429 ? (daily ? 'Đã hết quota hôm nay (UTC). Nguồn đã lưu vẫn đọc được; thử lại sau khi quota đặt lại.' : 'Đã chạm giới hạn lượt/phút. Vui lòng đợi rồi thử lại.') : 'Không đọc được nguồn. Kiểm tra phiên đăng nhập và thử lại.';
      } else {
        renderSources(payload, target);
        if (payload.analysis_id && document.querySelector('#workspace-source-library')) {
          const readback = await refreshWorkspaceState({analysisId: payload.analysis_id});
          if (readback.status === 'failed') showWorkspaceReadbackFailure(target, {analysisId: payload.analysis_id});
        }
        if (document.body.dataset.sourceReader && payload.analysis_id && payload.result?.sources?.length) {
          history.replaceState(null, '', '/workspaces/' + workspaceId + '/sources/' + payload.analysis_id);
        }
        if (payload.result?.errors?.length && pageLimit > 1) {
          const retry = element('button', 'Thử đọc 1 trang', 'button button-quiet'); retry.type = 'button';
          retry.addEventListener('click', () => readOfficial(url, target, pageStart, useOcr, 1)); target.append(retry);
        }
      }
    } catch { target.textContent = 'Không đọc được nguồn do lỗi kết nối. Không có nội dung nào được suy đoán.'; }
    finally { target.setAttribute('aria-busy', 'false'); }
  }
  function renderSources(payload, target) {
    target.replaceChildren();
    const freeResearch = payload.research_mode === 'free_web_research';
    const researchResult = payload.result || {};
    if (freeResearch) {
      const terminal = researchResult.terminal || payload.terminal || {};
      const status = terminal.status || payload.status || researchResult.status || 'interrupted';
      const messages = {
        complete: 'Đã hoàn tất lượt tìm và đọc giới hạn. Điều này không xác nhận đã trả lời câu hỏi hoặc bao phủ đầy đủ pháp luật.',
        partial: 'Đã lưu kết quả một phần. Việc hoàn tất lượt tìm và đọc không xác nhận câu trả lời hoặc độ bao phủ pháp luật.',
        failed: 'Lượt tìm và đọc chưa hoàn tất. Các nguồn đã lưu vẫn có thể xem bên dưới.',
        cancelled: 'Lượt đọc đã bị hủy. Các nguồn đã lưu vẫn có thể xem bên dưới.',
        interrupted: 'Lượt đọc bị gián đoạn. Các nguồn đã lưu vẫn có thể xem bên dưới.'
      };
      target.append(element('p', messages[status] || messages.interrupted, status === 'complete' ? 'muted' : 'legal-warning'));
      target.append(element('p', 'Không dùng lượt AI/OCR; thông tin kết quả tìm kiếm chưa phải nội dung văn bản.', 'muted'));
      (researchResult.source_errors || []).forEach(error => {
        const label = error.url ? `${error.url} · ` : '';
        target.append(element('p', `${label}${error.error_kind || error.kind || 'Không đọc được nguồn chính thức.'}`, 'legal-warning'));
      });
    } else {
      target.append(element('p', 'Nội dung trích xuất từ nguồn; chưa xác minh hiệu lực. OCR có thể đọc sai: đối chiếu bản gốc trước khi sử dụng.', 'legal-warning'));
    }
    (payload.result?.sources || []).forEach((source,index) => {
      const card = element('details'), link = element('a', source.url);
      card.id = 'stored-source-' + index;
      link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      card.open = true;
      card.append(element('summary', source.title || source.url), link);
      if (source.attachment_url) {
        const original = element('a', 'Mở PDF gốc'); original.href = source.attachment_url; original.target = '_blank'; original.rel = 'noopener noreferrer'; card.append(original);
      }
      if (freeResearch) {
        const readAt = source.snapshot_timestamp || source.retrieved_at;
        if (readAt) card.append(element('p', `${source.snapshot_reused ? 'Bản đọc đã lưu' : 'Đọc lúc'} · ${readAt}`, 'muted'));
      }
      (source.attachments || []).filter(url => url !== source.attachment_url).slice(0,10).forEach(url => {
        const attachment = element('button', 'Đọc tệp đính kèm: ' + url.split('/').pop(), 'button button-quiet'); attachment.type = 'button';
        attachment.addEventListener('click', () => readOfficial(url, target)); card.append(attachment);
      });
      if (source.page_count) card.append(element('p', `Đang đọc trang ${source.page_start}–${source.page_end}/${source.page_count}. Đây là phạm vi trang, không phải phần trăm đúng luật.`));
      if (payload.analysis_id && !document.body.dataset.sourceReader) {
        const reopen = element('a', 'Mở trong màn hình đọc nguồn');
        reopen.href = '/workspaces/' + workspaceId + '/sources/' + payload.analysis_id + '#stored-source-' + index; card.append(reopen);
      }
      if (source.reported_effective_from) card.append(element('p', `Ngày hiệu lực nguồn ghi: ${source.reported_effective_from}. Chưa kiểm tra văn bản sửa đổi hoặc tình trạng hiện hành.`, 'legal-warning'));
      if (source.parser_recovered) card.append(element('p', 'PDF có lỗi cấu trúc đã được trình đọc khôi phục. Hãy đối chiếu nội dung với bản gốc.', 'legal-warning'));
      const text = element('pre', source.text || 'Chưa đọc được nội dung điều khoản.', 'source-excerpt'); card.append(text);
      text.tabIndex = 0; text.setAttribute('aria-label', 'Nội dung nguồn; chọn đoạn để ghim');
      if (source.page_count && !freeResearch) {
        const controls = element('div', undefined, 'source-window-controls');
        const startLabel = element('label', 'Đọc từ trang'), start = element('input'); start.type = 'number'; start.min = '1'; start.max = String(source.page_count); start.value = String(source.page_start || 1); startLabel.append(start);
        const limitLabel = element('label', 'Số trang mỗi lượt'), limit = element('select');
        [1,2,3,5].forEach(n => { const option = element('option', String(n)); option.value = String(n); option.selected = n === 2; limit.append(option); }); limitLabel.append(limit);
        const modeLabel = element('label', 'Cách đọc'), mode = element('select');
        [['false','Trích xuất chữ'],['true','OCR ảnh quét (dùng AI)']].forEach(([value,label]) => { const option = element('option', label); option.value=value; option.selected = value === String(source.method === 'vertex_ocr' || source.requires_ocr); mode.append(option); }); modeLabel.append(mode);
        const go = element('button', 'Đọc nhóm trang', 'button button-quiet'); go.type = 'button';
        go.addEventListener('click', () => { if (start.reportValidity() && Number.isInteger(Number(start.value))) readOfficial(source.url, target, Number(start.value), mode.value === 'true', Number(limit.value)); });
        controls.append(startLabel, limitLabel, modeLabel, go); card.append(controls);
      }
      if (source.requires_ocr && !freeResearch) {
        const ocr = element('button', 'Đọc ảnh quét bằng OCR (tối đa 5 trang)', 'button button-primary'); ocr.type = 'button';
        ocr.addEventListener('click', () => readOfficial(source.url, target, source.page_start || 1, true)); card.append(ocr);
      }
      if (source.next_page_start) {
        const next = element('button', 'Đọc nhóm trang tiếp theo', 'button button-quiet'); next.type = 'button';
        next.addEventListener('click', () => readOfficial(source.url, target, source.next_page_start, source.method === 'vertex_ocr')); card.append(next);
      }
      if (source.truncated && !source.page_count) card.append(element('p', `Chỉ lưu ${source.stored_characters}/${source.extracted_characters} ký tự.`, 'legal-warning'));
      // Pin only exact server-stored excerpts; requests include no replacement source body.
      const form = element('form'), quote = element('textarea'), button = element('button', 'Ghim trích đoạn', 'button button-quiet');
      const useSelection = element('button', 'Dùng đoạn đang bôi chọn', 'button button-quiet'); useSelection.type = 'button';
      const selectionStatus = element('p', '', 'muted'); selectionStatus.setAttribute('role', 'status');
      useSelection.addEventListener('click', () => {
        const selection = window.getSelection();
        const chosen = selection?.toString() || '';
        if (!selection?.rangeCount || !text.contains(selection.anchorNode) || !text.contains(selection.focusNode) || !chosen.trim()) { selectionStatus.textContent = 'Bôi chọn một đoạn trong khung nội dung nguồn phía trên.'; return; }
        if (chosen.length > 3000) { selectionStatus.textContent = 'Trích đoạn vượt 3.000 ký tự. Hãy chọn đoạn ngắn hơn.'; return; }
        quote.value = chosen; selectionStatus.textContent = `Đã chọn ${chosen.length}/3.000 ký tự. Kiểm tra rồi ghim.`;
      });
      quote.name = 'quote'; quote.maxLength = 3000; quote.required = true; quote.placeholder = 'Dán nguyên văn trích đoạn từ nội dung phía trên';
      const label = element('label', 'Trích đoạn cần ghim'); label.append(quote); form.append(useSelection, label, selectionStatus, button);
      form.addEventListener('submit', async event => {
        event.preventDefault(); button.disabled = true;
        const data = new FormData(form); data.set('csrf_token', csrf); data.set('analysis_id', payload.analysis_id); data.set('source_index', String(index));
        try { const response = await fetch('/workspaces/' + workspaceId + '/sources/pin', {method:'POST',body:data}); if (!response.ok) throw new Error(); if (location.pathname === '/workspaces/' + workspaceId) { location.hash = 'sources'; location.reload(); } else location.assign('/workspaces/' + workspaceId + '#sources'); }
        catch { button.textContent = 'Chưa ghim được; kiểm tra trích đoạn rồi thử lại'; }
        finally { button.disabled = false; }
      });
      if (payload.analysis_id && source.text?.trim()) {
        card.append(form);
        const ask = element('form');
        ask.method = 'post'; ask.action = '/workspaces/' + encodeURIComponent(workspaceId) + '/analyses/retained-source';
        [['csrf_token', csrf], ['analysis_id', payload.analysis_id], ['source_index', String(index)], ['scope', 'relevant']].forEach(([name, value]) => {
          const hidden = element('input'); hidden.type = 'hidden'; hidden.name = name; hidden.value = value; ask.append(hidden);
        });
        const questionLabel = element('label', 'Câu hỏi và mốc thời gian'), question = element('textarea');
        question.name = 'question'; question.required = true; question.maxLength = 2000;
        question.value = document.querySelector('[data-research-plan] textarea[name="question"]')?.value || '';
        questionLabel.append(question);
        ask.append(questionLabel, element('button', 'Trả lời từ các đoạn liên quan', 'button button-primary'));
        card.append(ask);
      }
      target.append(card);
    });
    (payload.result?.errors || []).forEach(error => {
      target.append(element('p', sourceErrors[error.kind] || 'Chưa đọc được nguồn. Mở bản gốc hoặc thử nhóm trang nhỏ hơn.', 'legal-warning'));
      const details = element('details'); details.append(element('summary', 'Thông tin lỗi nguồn'), element('p', error.url + ' · ' + error.kind)); target.append(details);
    });
    (payload.result?.duplicates || []).forEach(group => target.append(element('p', 'Nội dung trùng: ' + group.urls.join(' · '), 'muted')));
  }
  function renderModels(payload, target) {
    target.replaceChildren();
    target.append(element('p', 'Đối chiếu văn bản trả lời; chưa đánh giá model nào đúng pháp luật.', 'legal-warning'));
    (payload.result?.responses || []).forEach(response => {
      const card = element('article'); card.append(element('h3', response.requested?.provider + ' · ' + response.requested?.model), element('p', response.status), element('p', response.text || 'Không có câu trả lời.'));
      card.append(element('p', 'Model phản hồi: ' + (response.observed?.model && response.observed.model !== 'unobserved' ? response.observed.model : 'Provider chưa báo mã model'), 'muted'));
      const usage = response.usage || {}; card.append(element('p', 'Token thực đo: ' + (usage.total_token_count ?? 'Chưa có số liệu'), 'muted')); target.append(card);
    });
    const comparison = payload.result?.textual_comparison || {};
    target.append(element('p', {same:'Hai câu trả lời giống nhau sau chuẩn hóa khoảng trắng.', different:'Hai câu trả lời khác nhau về văn bản.', not_available:'Chưa đủ kết quả để đối chiếu.'}[comparison.status] || '', 'muted'));
  }
  function renderFullReviewPlan(plan, target) {
    const aggregate = plan.aggregate || {}, coverage = aggregate.coverage || plan.coverage || {};
    target.append(element('h3', 'Kế hoạch rà soát theo lô'), element('p', `${coverage.reviewed_clauses || 0}/${coverage.total_clauses || 0} điều khoản đã rà soát; ${coverage.skipped_clauses || 0} chưa thể xếp lô.`, 'muted'));
    (plan.skipped || []).forEach(item => target.append(element('p', item.clause_id + ' · ' + item.reason, 'legal-warning')));
    const pendingIds = aggregate.pending_batch_ids || (plan.batches || []).map(batch => batch.batch_id);
    (plan.batches || []).filter(batch => pendingIds.includes(batch.batch_id)).forEach(batch => {
      const form = element('form'), button = element('button', 'Rà soát ' + batch.batch_id + ' (' + batch.clause_ids.length + ' điều khoản)', 'button button-quiet');
      form.append(button);
      form.addEventListener('submit', async event => {
        event.preventDefault(); if (pending) return; pending = true; button.disabled = true;
        const data = new FormData(); Object.entries({csrf_token:csrf,document_id:plan.document_id,batch_id:batch.batch_id,input_sha256:plan.input_sha256,legal_evidence_ids:plan.legal_evidence_ids.join(',')}).forEach(([key,value]) => data.set(key,value));
        try { const response = await fetch('/workspaces/' + workspaceId + '/analyses/full-review',{method:'POST',body:data}); const payload = await response.json(); renderAnalysis(payload); }
        catch { result.textContent = 'Chưa rà soát được lô này. Tải lại kế hoạch để kiểm tra trạng thái.'; }
        finally { pending = false; button.disabled = false; }
      }); target.append(form);
    });
    if (coverage.complete) target.append(element('p', 'Đã rà soát toàn bộ phạm vi của kế hoạch này. Kết quả vẫn cần chuyên gia kiểm tra.'));
  }
  document.querySelectorAll('[data-full-review-plan]').forEach(button => button.addEventListener('click', async () => {
    if (pending) return; pending = true; button.disabled = true;
    const lawIds = [...document.querySelectorAll('[name="selected_evidence"]:checked')].filter(node => node.closest('[data-source-kind]')?.dataset.sourceKind !== 'user_document').map(node => node.value);
    const data = new FormData(); data.set('csrf_token',csrf); data.set('legal_evidence_ids',lawIds.join(','));
    try { const response = await fetch('/workspaces/' + workspaceId + '/documents/' + button.dataset.documentId + '/analyses/full-review/plan',{method:'POST',body:data}); const plan = await response.json(); if (!response.ok) throw new Error(); result.replaceChildren(); renderFullReviewPlan(plan,result); }
    catch { result.textContent = 'Chưa lập được kế hoạch; kiểm tra tài liệu và phạm vi bằng chứng.'; }
    finally { pending = false; button.disabled = false; }
  }));
  function renderLegalEffect(payload, target) {
    target.replaceChildren(); const effect = payload.result || payload;
    target.append(element('p', 'Tình trạng theo các sự kiện đã được quản trị viên đối chiếu trong hồ sơ này; chưa chứng nhận tính đầy đủ của lịch sử pháp luật.', 'legal-warning'));
    (effect.effects || []).forEach(row => target.append(element('p', row.target_document_number + ' · ' + row.as_of + ' · ' + ({effective:'Có hiệu lực theo hồ sơ',amended:'Đã sửa đổi theo hồ sơ',partially_effective:'Hết hiệu lực một phần theo hồ sơ',repealed:'Đã bãi bỏ theo hồ sơ',replaced:'Đã thay thế theo hồ sơ',expired:'Hết thời hạn hiệu lực theo hồ sơ',unknown:'Chưa xác định'}[row.status] || row.status))));
    (effect.assertions || []).forEach(row => { const card = element('article'); card.append(element('h3', row.effective_date + ' · ' + row.event_kind), element('blockquote', row.exact_quote), sourceLinks([row.evidence_id], payload)); target.append(card); });
    (effect.reasons || []).forEach(reason => target.append(element('p', reason, 'muted')));
  }
  function renderAnalysis(payload, target = result) {
    if (target === result && ['contract_review', 'full_document_review'].includes(payload.kind)) location.hash = 'review';
    if (payload.kind === 'legal_effect_review') { renderLegalEffect(payload, target); return; }
    if (payload.kind === 'full_document_review') { renderContractReview(payload,target); if (payload.plan) renderFullReviewPlan({...payload.plan,aggregate:payload.aggregate},target); return; }
    if (payload.kind === 'model_comparison') { renderModels(payload, target); return; }
    if (payload.kind === 'trusted_sources') { renderSources(payload, target); return; }
    if (payload.kind === 'research_report') { renderReport(payload, target); return; }
    if (payload.kind === 'document_redline') { renderRedline(payload, target); return; }
    if (payload.kind === 'claim_verification') { renderClaims(payload, target); return; }
    if (payload.kind === 'legal_timeline') { renderTimeline(payload, target); return; }
    if (payload.kind === 'deep_research' || payload.result?.steps) { renderResearch(payload, target); return; }
    if (payload.kind === 'contract_review') { renderContractReview(payload, target); return; }
    target.replaceChildren();
    if (payload.status && payload.status !== 'ok') target.append(element('p', labels[payload.status] || payload.status, 'legal-warning'));
      if (payload.provider || payload.model) {
        const technical = element('details');
        technical.append(element('summary', 'Thông tin kỹ thuật'), element('p', (payload.provider || '—') + ' · ' + (payload.model || '—'), 'muted'));
        target.append(technical);
      }
    if (payload.unanswered_parts?.length) {
      const missing = element('section', undefined, 'legal-warning');
      missing.append(element('h3', 'Phần chưa đủ căn cứ để trả lời'));
      const list = element('ul');
      payload.unanswered_parts.forEach(part => list.append(element('li', part)));
      missing.append(list); target.append(missing);
    }
    if (payload.text) target.append(element('p', payload.text));
    if (payload.kind === 'selected_evidence' && payload.evidence_ids?.length) target.append(sourceLinks(payload.evidence_ids, payload));
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
  let freeResearchController = null;
  let freeResearchPending = false;
  let freeResearchCancelRecorded = false;
  function renderFreeSource(source, analysisId, index, target) {
    const card = element('article', undefined, 'free-research-source');
    const title = element('h3', source.title || source.document_number || source.url);
    const link = element('a', source.url);
    link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    const state = source.snapshot_reused ? 'Bản đọc đã lưu trong 15 phút gần đây.' : 'Đã tải và trích xuất nội dung mới.';
    card.append(title, element('p', state + ' · Đọc lúc ' + (source.retrieved_at || source.snapshot_timestamp || 'không rõ'), 'muted'));
    card.append(element('p', [source.document_number, source.issued_date, source.domain].filter(Boolean).join(' · '), 'muted'));
    card.append(element('p', 'Nội dung nguồn đã đọc; tình trạng hiệu lực chưa xác minh.', 'legal-warning'));
    if (source.page_count) card.append(element('p', `Đọc các trang ${source.page_start}–${source.page_end}/${source.page_count}; đã kiểm tra ${source.inspected_page_count ?? 'không rõ'} trang.`));
    card.append(element('pre', source.text || (source.pages || []).map(page => page.text || '').join('\n\n') || 'Không có nội dung đọc được.', 'source-excerpt'));
    if (source.discovery_snippet) {
      const metadata = element('details');
      metadata.append(element('summary', 'Thông tin từ kết quả tìm kiếm (chưa phải nội dung văn bản)'), element('p', source.discovery_snippet));
      card.append(metadata);
    }
    if (analysisId) {
      const reopen = element('a', 'Mở bản đọc để ghim trích đoạn');
      reopen.href = '/workspaces/' + encodeURIComponent(workspaceId) + '/sources/' + encodeURIComponent(analysisId) + '#stored-source-' + index;
      card.append(reopen);
    }
    target.append(card);
  }
  function renderFreeResearchEvent(event, target, analysisId) {
    if (event.type === 'started') {
      target.replaceChildren(element('p', 'Đang tìm trên Cổng Chính phủ và Công báo; không dùng lượt AI/OCR.', 'muted'));
    } else if (event.type === 'query') {
      const state = {results_found:'Có kết quả tìm kiếm',partial_results:'Có kết quả, một nguồn tìm kiếm gặp lỗi',no_results:'Không tìm thấy với truy vấn này',provider_error:'Nguồn tìm kiếm chưa phản hồi'}[event.status] || event.status;
      const row = element('p', `${event.query} · ${state}`);
      target.append(row);
    } else if (event.type === 'source' && event.status === 'readable') {
      const index = target.querySelectorAll('.free-research-source').length;
      renderFreeSource(event.source || {}, analysisId, index, target);
    } else if (event.type === 'source') {
      let text = `Chưa đọc được ${event.url}: ${event.error_kind || 'source_unreadable'}.`;
      if (Array.isArray(event.inspected_pages)) text += ` Đã xét ${event.inspected_page_count ?? event.inspected_pages.length} trang.`;
      target.append(element('p', text, 'legal-warning'));
    } else if (event.type === 'terminal') {
      const messages = {
        complete: 'Đã đọc xong các nguồn được chọn. Đây không phải kết luận pháp lý.',
        partial: 'Đã lưu kết quả một phần. Hãy kiểm tra lỗi và mở bản nguồn.',
        failed: 'Không đọc được nguồn chính thức nào. Kết quả này không chứng minh không có quy định.',
        cancelled: 'Yêu cầu đã dừng trước khi đọc được nguồn; trạng thái đã lưu.',
        interrupted: 'Phiên chạy bị gián đoạn; trạng thái đã lưu có thể mở lại.'
      };
      const counts = `Đọc mới: ${event.fetched_count ?? 0} · Dùng lại bản lưu: ${event.reused_count ?? 0} · Nguồn có chữ: ${event.source_count ?? 0}.`;
      target.append(element('p', messages[event.status] || 'Phiên tra cứu đã kết thúc.', 'legal-warning'), element('p', counts, 'muted'));
      refreshAfterResearch(analysisId, target);
    }
  }
  let workspaceReadbackSequence = 0;
  const workspaceReadbackRuns = new Set();
  function preserveWorkspaceFragmentState(currentNode, nextNode) {
    const currentControls = [...currentNode.querySelectorAll('[data-readback-preserve]')];
    const currentDetails = [...currentNode.querySelectorAll('details[data-readback-key]')];
    const focusedControl = currentControls.find(control => control === document.activeElement);
    const controlsByKey = new Map(
      [...nextNode.querySelectorAll('[data-readback-preserve]')]
        .map(control => [control.dataset.readbackPreserve, control])
    );
    currentControls.forEach(control => {
      const replacement = controlsByKey.get(control.dataset.readbackPreserve);
      if (!replacement) return;
      if ('value' in control) replacement.value = control.value;
      if ('checked' in control) replacement.checked = control.checked;
      if (Number.isInteger(control.selectionStart) && Number.isInteger(control.selectionEnd)) {
        try { replacement.setSelectionRange(control.selectionStart, control.selectionEnd); }
        catch { /* Select/number controls do not support text selection. */ }
      }
    });
    const detailsByKey = new Map(
      [...nextNode.querySelectorAll('details[data-readback-key]')]
        .map(detail => [detail.dataset.readbackKey, detail])
    );
    currentDetails.forEach(detail => {
      const replacement = detailsByKey.get(detail.dataset.readbackKey);
      if (replacement) replacement.open = detail.open;
    });
    return {
      activeKey: focusedControl?.dataset.readbackPreserve,
      selectionStart: focusedControl?.selectionStart,
      selectionEnd: focusedControl?.selectionEnd,
      scrollX: window.scrollX,
      scrollY: window.scrollY
    };
  }
  function restoreWorkspaceFragmentFocus(node, state) {
    if (state.activeKey) {
      const control = [...node.querySelectorAll('[data-readback-preserve]')]
        .find(candidate => candidate.dataset.readbackPreserve === state.activeKey);
      if (control) {
        control.focus({preventScroll: true});
        if (Number.isInteger(state.selectionStart) && Number.isInteger(state.selectionEnd)) {
          control.setSelectionRange(state.selectionStart, state.selectionEnd);
        }
      }
    }
    window.scrollTo(state.scrollX, state.scrollY);
  }
  function dedupeWorkspaceItems(root, selector, key) {
    const seen = new Set();
    [...root.querySelectorAll(selector)].forEach(node => {
      const value = node.dataset[key];
      if (!value || seen.has(value)) node.remove();
      else seen.add(value);
    });
  }
  async function refreshWorkspaceState({runId, analysisId} = {}) {
    const sequence = ++workspaceReadbackSequence;
    const isCurrent = () => sequence === workspaceReadbackSequence && (
      !runId || freeResearchForm?.querySelector('[name="run_id"]')?.value === runId
    );
    try {
      const response = await fetch('/workspaces/' + encodeURIComponent(workspaceId), {
        method: 'GET', credentials: 'same-origin', cache: 'no-store',
        headers: {Accept: 'text/html'}
      });
      if (!isCurrent()) return {status: 'stale'};
      if (!response.ok) return {status: 'failed'};
      const html = await response.text();
      if (!isCurrent()) return {status: 'stale'};
      const latest = new DOMParser().parseFromString(html, 'text/html');
      if (latest.body?.dataset.workspaceId !== workspaceId) return {status: 'failed'};
      const revision = latest.body.dataset.workspaceRevision || '';
      const currentRevision = document.body.dataset.workspaceRevision || '';
      if (revision && currentRevision && Date.parse(revision) < Date.parse(currentRevision)) {
        return {status: 'stale'};
      }
      if (analysisId && ![...latest.querySelectorAll('[data-analysis-id]')]
        .some(node => node.dataset.analysisId === analysisId)) return {status: 'failed'};
      const selectors = [
        '#workspace-source-library [data-source-library-count]',
        '#workspace-source-library .source-library-grid',
        '#workspace-reports',
        '#activity',
        '#overview'
      ];
      const current = selectors.map(selector => document.querySelector(selector));
      const incoming = selectors.map(selector => latest.querySelector(selector));
      if (current.some(node => !node) || incoming.some(node => !node)) return {status: 'failed'};
      const [currentCount, currentGrid, currentReports, currentHistory, currentOverview] = current;
      const [latestCount, latestGrid, latestReports, latestHistory, latestOverview] = incoming;
      const nextGrid = latestGrid.cloneNode(true);
      const state = preserveWorkspaceFragmentState(currentGrid, nextGrid);
      const nextReports = latestReports.cloneNode(true);
      const nextHistory = latestHistory.cloneNode(true);
      const nextOverview = latestOverview.cloneNode(true);
      nextReports.hidden = currentReports.hidden;
      nextHistory.hidden = currentHistory.hidden;
      nextOverview.hidden = currentOverview.hidden;
      dedupeWorkspaceItems(nextGrid, '[data-source-library-key]', 'sourceLibraryKey');
      dedupeWorkspaceItems(nextReports, '[data-report-id]', 'reportId');
      dedupeWorkspaceItems(nextHistory, '[data-analysis-id]', 'analysisId');
      currentCount.textContent = latestCount.textContent;
      currentGrid.replaceWith(nextGrid);
      currentReports.replaceWith(nextReports);
      currentHistory.replaceWith(nextHistory);
      currentOverview.replaceWith(nextOverview);
      nextHistory.querySelectorAll('[data-saved-analysis]').forEach(node => {
        try { renderAnalysis(JSON.parse(node.textContent), node.parentElement.querySelector('[data-analysis-view]')); }
        catch { /* Keep the server-rendered legacy details readable. */ }
      });
      restoreWorkspaceFragmentFocus(nextGrid, state);
      if (revision) document.body.dataset.workspaceRevision = revision;
      return {status: 'updated'};
    } catch {
      return isCurrent() ? {status: 'failed'} : {status: 'stale'};
    }
  }
  function showWorkspaceReadbackFailure(target, options = {}) {
    if (!target) return;
    const notice = element('p', 'Đã ghi nhận kết quả, nhưng chưa cập nhật được thư viện và danh sách đã lưu.', 'legal-warning');
    notice.setAttribute('role', 'status');
    const retry = element('button', 'Cập nhật danh sách', 'button button-quiet');
    retry.type = 'button';
    retry.addEventListener('click', async () => {
      retry.disabled = true;
      const result = await refreshWorkspaceState(options);
      if (result.status === 'updated') {
        notice.replaceWith(element('p', 'Danh sách đã được cập nhật từ hồ sơ.', 'muted'));
      } else if (result.status === 'failed') {
        retry.disabled = false;
      }
    });
    target.append(notice, retry);
  }
  function refreshAfterResearch(runId, target) {
    if (!runId || workspaceReadbackRuns.has(runId)) return;
    workspaceReadbackRuns.add(runId);
    void refreshWorkspaceState({runId}).then(result => {
      if (result.status === 'failed' && freeResearchForm?.querySelector('[name="run_id"]')?.value === runId) {
        showWorkspaceReadbackFailure(target, {runId});
      }
    });
  }
  const freeResearchForm = document.querySelector('[data-free-web-research]');
  const freeResearchResult = document.querySelector('#free-web-research-result');
  const freeCancelButton = freeResearchForm?.querySelector('[data-cancel-free-research]');
  freeCancelButton?.addEventListener('click', async () => {
    const controller = freeResearchController;
    const runId = freeResearchForm?.querySelector('[name="run_id"]')?.value;
    if (!controller || !runId || freeCancelButton.disabled) return;
    const isCurrentCancel = () => freeResearchController === controller && freeResearchForm?.querySelector('[name="run_id"]')?.value === runId;
    freeCancelButton.disabled = true;
    try {
      const cancelData = new FormData();
      cancelData.set('csrf_token', csrf);
      const cancelPath = '/workspaces/' + encodeURIComponent(workspaceId) + '/research/runs/' + encodeURIComponent(runId) + '/cancel';
      const response = await fetch(cancelPath, {
        method: 'POST', body: cancelData, credentials: 'same-origin'
      });
      if (!isCurrentCancel()) return;
      let payload = {};
      try { payload = await response.json(); } catch { /* Keep the typed HTTP status. */ }
      if (!isCurrentCancel()) return;
      if (!response.ok) {
        if (response.status === 409 && payload.detail?.code === 'research_run_not_running') {
          freeResearchResult?.append(element('p', 'Phiên đã kết thúc với trạng thái ' + (payload.detail.status || 'đã lưu') + '. Kết quả hiện có vẫn được giữ nguyên.', 'muted'));
          return;
        }
        throw new Error(operationError(payload, response.status));
      }
      if (payload.outcome !== 'cancelled' || !['partial', 'cancelled'].includes(payload.status)) {
        throw new Error('cancel_ack_invalid');
      }
      if (!isCurrentCancel()) return;
      freeResearchCancelRecorded = true;
      const savedCount = Number.isInteger(payload.source_count) ? payload.source_count : 0;
      const savedStatus = payload.status === 'partial' ? `${savedCount} nguồn đã lưu` : 'chưa có nguồn nào được lưu';
      freeResearchResult?.append(element('p', `Đã ghi nhận hủy phiên; ${savedStatus} tại thời điểm hủy. Kết quả đã lưu được giữ lại.`, 'muted'));
      if (!isCurrentCancel()) return;
      refreshAfterResearch(runId, freeResearchResult);
      controller.abort();
    } catch (error) {
      if (!isCurrentCancel()) return;
      freeResearchResult?.append(element('p', `Chưa xác nhận được hủy (${error.message || 'lỗi kết nối'}). Luồng vẫn mở; có thể thử lại.`, 'legal-warning'));
      if (freeResearchController === controller) freeCancelButton.disabled = false;
    }
  });
  freeResearchForm?.addEventListener('submit', async event => {
    event.preventDefault();
    if (freeResearchPending) return;
    freeResearchPending = true;
    freeResearchController = new AbortController();
    freeResearchCancelRecorded = false;
    const button = freeResearchForm.querySelector('button[type="submit"]');
    const data = new FormData(freeResearchForm);
    const runId = crypto.randomUUID();
    data.set('csrf_token', csrf);
    data.set('run_id', runId);
    if (!data.has('refresh')) data.set('refresh', 'false');
    freeResearchForm.querySelector('[name="run_id"]').value = runId;
    button.disabled = true;
    if (freeCancelButton) { freeCancelButton.hidden = false; freeCancelButton.disabled = true; }
    freeResearchResult?.setAttribute('aria-busy', 'true');
    freeResearchResult?.replaceChildren(element('p', 'Đang chuẩn bị phiên tra cứu…', 'muted'));
    try {
      const response = await fetch(freeResearchForm.action, {
        method: 'POST', body: data, credentials: 'same-origin', signal: freeResearchController.signal
      });
      if (!response.ok) {
        let payload = {};
        try { payload = await response.json(); } catch { /* Typed status remains useful without JSON. */ }
        throw new Error(operationError(payload, response.status));
      }
      const reader = response.body?.getReader();
      if (!reader) throw new Error('Trình duyệt không hỗ trợ luồng kết quả này.');
      const decoder = new TextDecoder();
      let buffer = '';
      const consume = line => {
        if (!line.trim()) return;
        try {
          const parsed = JSON.parse(line);
          renderFreeResearchEvent(parsed, freeResearchResult, runId);
          if (parsed.type === 'started' && freeCancelButton) freeCancelButton.disabled = false;
          if (parsed.type === 'terminal' && freeCancelButton) freeCancelButton.disabled = true;
        }
        catch { freeResearchResult.append(element('p', 'Bỏ qua một sự kiện kết quả không đọc được.', 'legal-warning')); }
      };
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
        const lines = buffer.split('\n'); buffer = lines.pop() || '';
        lines.forEach(consume);
        if (done) break;
      }
      consume(buffer);
    } catch (error) {
      if (error.name === 'AbortError') {
        if (!freeResearchCancelRecorded) freeResearchResult?.append(element('p', 'Đã hủy kết nối. Các sự kiện đã nhận được lưu trong hồ sơ; tải lại để xem trạng thái.', 'legal-warning'));
      } else freeResearchResult?.append(element('p', error.message || 'Không thể kết nối tới nguồn tìm kiếm.', 'legal-warning'));
    } finally {
      freeResearchPending = false;
      freeResearchController = null;
      button.disabled = false;
      if (freeCancelButton) { freeCancelButton.hidden = true; freeCancelButton.disabled = false; }
      freeResearchResult?.setAttribute('aria-busy', 'false');
    }
  });
  document.querySelectorAll('[data-saved-analysis]').forEach(node => {
    try { renderAnalysis(JSON.parse(node.textContent), node.parentElement.querySelector('[data-analysis-view]')); }
    catch { /* The server-rendered record remains readable for older schemas. */ }
  });
  document.addEventListener('change', showScope);
  document.addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.action === 'pin-document-clause') {
      button.disabled = true;
      try {
        const path = '/workspaces/' + workspaceId + '/documents/' + button.dataset.documentId + '/clauses/' + button.dataset.clauseId + '/pin';
        const response = await fetch(path, {method: 'POST', headers: {'X-CSRF-Token': csrf}});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || payload.reason || 'pin_failed');
        location.reload();
      } catch { if (result) result.textContent = 'Không thể ghim điều khoản. Điều khoản có thể đã được ghim hoặc bảng bằng chứng đã đầy.'; }
      finally { button.disabled = false; }
      return;
    }
    if (!['delete-workspace', 'unpin-evidence', 'delete-document'].includes(button.dataset.action)) return;
    const removeWorkspace = button.dataset.action === 'delete-workspace';
    const removeDocument = button.dataset.action === 'delete-document';
    const prompt = removeWorkspace ? 'Xóa hồ sơ, ghi chú, bằng chứng và phân tích đã lưu? Không thể hoàn tác.' : removeDocument ? 'Xóa tài liệu và mọi điều khoản đã ghim từ tài liệu này?' : 'Bỏ ghim bằng chứng này?';
    if (!confirm(prompt)) return;
    button.disabled = true;
    try {
      const path = '/workspaces/' + workspaceId + (removeWorkspace ? '' : removeDocument ? '/documents/' + button.dataset.documentId : '/evidence/' + button.dataset.evidenceId);
      const response = await fetch(path, {method: 'DELETE', headers: {'X-CSRF-Token': csrf}});
      if (!response.ok) throw new Error('delete_failed');
      if (removeWorkspace) location.href = '/workspaces'; else location.reload();
    } catch { result.textContent = 'Không thể lưu thay đổi. Vui lòng thử lại.'; }
    finally { button.disabled = false; }
  });
  document.addEventListener('submit', async event => {
    const uploadForm = event.target.closest('[data-document-upload]');
    if (uploadForm) {
      event.preventDefault();
      if (pending) return;
      pending = true; const button = uploadForm.querySelector('button'); button.disabled = true;
      if (result) result.textContent = 'Đang trích xuất tài liệu…';
      try {
        const response = await fetch(uploadForm.action, {method: 'POST', body: new FormData(uploadForm)});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || 'upload_failed');
        location.reload();
      } catch (error) {
        const uploadErrors = {
          ocr_incomplete: 'OCR chưa đọc đầy đủ tài liệu; chưa lưu kết quả. Thử tách PDF thành ít trang hơn.',
          ocr_invalid_response: 'Kết quả OCR không đủ hoặc sai thứ tự trang; chưa lưu tài liệu.',
          ocr_page_limit: 'OCR chỉ hỗ trợ tối đa 5 trang mỗi tài liệu.',
          ocr_file_limit: 'OCR chỉ hỗ trợ PDF tối đa 3,7 MB.',
          ocr_pdf_only: 'Chỉ chọn OCR khi tải file PDF.',
          ocr_timeout: 'OCR vượt thời gian xử lý. Không tự thử lại.',
          duplicate_document: 'Tài liệu này đã có trong hồ sơ.',
          demo_daily_quota: 'Đã hết lượt AI hôm nay.',
          workspace_changed: 'Hồ sơ đã thay đổi hoặc chạm giới hạn tổng dung lượng 12 MB; chưa lưu tài liệu.'
        };
        if (result) result.textContent = uploadErrors[error.message] || 'Không thể tải tài liệu. Kiểm tra định dạng, dung lượng hoặc thử lại sau.';
      }
      finally { pending = false; button.disabled = false; }
      return;
    }
    const contractForm = event.target.closest('[data-contract-review]');
    if (contractForm) {
      event.preventDefault();
      if (pending) return;
      const card = contractForm.closest('[data-workspace-document]');
      const clauseIds = [...card.querySelectorAll('[data-document-clause]:checked')].map(node => node.value);
      if (!clauseIds.length || clauseIds.length > 10) { if (result) result.textContent = 'Chọn từ 1 đến 10 điều khoản để rà soát.'; return; }
      const lawIds = [...document.querySelectorAll('[name="selected_evidence"]:checked')].filter(node => node.closest('[data-source-kind]')?.dataset.sourceKind !== 'user_document').map(node => node.value);
      const data = new FormData(contractForm); data.set('clause_ids', clauseIds.join(',')); data.set('legal_evidence_ids', lawIds.join(','));
      pending = true; const button = contractForm.querySelector('button'); button.disabled = true;
      if (result) { result.setAttribute('aria-busy', 'true'); result.textContent = 'Đang rà soát các điều khoản đã chọn…'; }
      try {
        const response = await fetch(contractForm.action, {method: 'POST', body: data});
        const payload = await response.json(); if (!response.ok && !payload.analysis_id) { result.textContent = operationError(payload, response.status); return; } renderAnalysis(payload);
        if (!response.ok) throw new Error(payload.detail || payload.status || 'review_failed');
      } catch { if (result && !result.children.length) result.textContent = 'Không thể hoàn tất rà soát lúc này.'; }
      finally { pending = false; button.disabled = false; result?.setAttribute('aria-busy', 'false'); }
      return;
    }
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
        if (!response.ok) throw new Error(operationError(payload, response.status));
        renderPlan(payload);
      } catch (error) { if (researchPlan) researchPlan.textContent = error.message || 'Không thể tạo kế hoạch lúc này.'; }
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
        if (!response.ok) throw new Error(operationError(payload, response.status));
        renderResearch(payload);
      } catch (error) { if (researchResult) researchResult.textContent = error.message || 'Không thể hoàn tất nghiên cứu lúc này.'; }
      finally { pending = false; runForm.querySelector('button').disabled = false; researchResult?.setAttribute('aria-busy', 'false'); }
      return;
    }
    const form = event.target.closest('[data-analysis]');
    if (!form) return;
    event.preventDefault();
    if (pending) return;
    const data = new FormData(form);
    if (form.dataset.analysis === 'legal-effect') {
      const event = {}; ['event_kind','effective_date','document_number','target_document_number','exact_quote'].forEach(key => event[key] = data.get(key)); event.evidence_id = data.get('event_evidence_id'); event.scope = data.get('event_scope'); if (data.get('effective_until')) event.effective_until = data.get('effective_until'); data.set('events',JSON.stringify([event])); data.set('evidence_ids',event.evidence_id);
    } else if (form.dataset.analysis === 'compare') {
      const a = group('a'), b = group('b');
      if (!a.length || !b.length) { result.textContent = 'Chọn bằng chứng cho cả nhóm A và nhóm B.'; return; }
      data.set('evidence_a', a.join(',')); data.set('evidence_b', b.join(','));
    } else if (form.dataset.analysis === 'sources') {
      // URL reads do not use the evidence selection.
    } else if (form.dataset.analysis === 'redline') {
      if (data.get('document_a_id') === data.get('document_b_id')) { result.textContent = 'Chọn hai tài liệu khác nhau.'; return; }
    } else {
      if (!selected().length || selected().length > 10) { result.textContent = 'Chọn từ 1 đến 10 bằng chứng. Vào tab Nguồn để điều chỉnh phạm vi.'; return; }
      data.set('evidence_ids', selected().join(','));
    }
    pending = true;
    document.querySelectorAll('[data-analysis] button').forEach(button => { button.disabled = true; });
    result.setAttribute('aria-busy', 'true'); result.textContent = 'Đang phân tích trong phạm vi bằng chứng đã chọn…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: data});
      const payload = await response.json(); if (!response.ok && !payload.analysis_id) { result.textContent = operationError(payload, response.status); return; } renderAnalysis(payload);
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
        const readback = await refreshWorkspaceState({analysisId: payload.analysis_id});
        if (readback.status === 'failed') showWorkspaceReadbackFailure(result, {analysisId: payload.analysis_id});
      }
    } catch { result.textContent = 'Không thể hoàn tất phân tích lúc này.'; }
    finally {
      pending = false; result.setAttribute('aria-busy', 'false');
      document.querySelectorAll('[data-analysis] button').forEach(button => { button.disabled = false; });
    }
  });
  try { const theme = localStorage.getItem('vietlex-theme'); if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme; } catch { /* Selection and forms still work without browser storage. */ }
  showScope();
})();
