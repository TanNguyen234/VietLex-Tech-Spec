(() => {
  const rows = [...document.querySelectorAll('.evidence-board .evidence-row')];
  const search = document.querySelector('[data-evidence-search]');
  const filter = document.querySelector('[data-evidence-filter]');
  const checked = () => rows.filter(row => row.querySelector('[name="selected_evidence"]')?.checked);
  const storageKey = 'vietlex-selection-' + (document.body.dataset.workspaceId || '');
  const normalize = value => value.toLocaleLowerCase('vi').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g, 'd');
  function update() {
    const needle = normalize(search?.value || ''), status = filter?.value || 'all';
    rows.forEach(row => {
      row.hidden = !normalize(row.querySelector('.evidence-content')?.textContent || '').includes(needle) || (status !== 'all' && row.dataset.reviewStatus !== status);
    });
    const visible = rows.filter(row => !row.hidden).length;
    const note = document.querySelector('[data-evidence-filter-count]');
    if (note) note.textContent = `${visible}/${rows.length} căn cứ đang hiển thị. Lọc không bỏ các nguồn đã chọn.`;
    const selection = checked();
    document.querySelectorAll('[data-selection-summary]').forEach(node => {
      node.textContent = selection.length ? `${selection.length} căn cứ đã chọn · ${selection.filter(row => row.hidden).length} đang ẩn bởi bộ lọc` : 'Chọn căn cứ bằng ô đánh dấu để phân tích hoặc lập báo cáo.';
    });
    let scope = document.querySelector('[data-selected-source-list]');
    if (!scope && document.querySelector('#evidence-scope')) {
      scope = document.createElement('ul'); scope.dataset.selectedSourceList = ''; scope.className = 'selected-source-list';
      document.querySelector('#evidence-scope').after(scope);
    }
    if (scope) {
      scope.replaceChildren();
      selection.forEach(row => { const item = document.createElement('li'), link = document.createElement('a'); link.href = '#' + row.id; link.textContent = row.querySelector('.citation').textContent; item.append(link); scope.append(item); });
    }
    try { if (rows.length) sessionStorage.setItem(storageKey, JSON.stringify(selection.map(row => row.querySelector('[name="selected_evidence"]').value))); } catch { /* In-memory selection remains usable. */ }
  }
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || '[]');
    if (Array.isArray(saved)) rows.forEach(row => { const input = row.querySelector('[name="selected_evidence"]'); if (saved.includes(input.value)) input.checked = true; });
  } catch { /* Private browsing may block storage. */ }
  search?.addEventListener('input', update); filter?.addEventListener('change', update);
  document.addEventListener('change', update);
  document.querySelector('[data-clear-selection]')?.addEventListener('click', () => {
    rows.forEach(row => row.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; }));
    document.dispatchEvent(new Event('change'));
  });
  if (rows.length) document.dispatchEvent(new Event('change'));
  update();
  document.querySelectorAll('[data-finding-filter]').forEach(select => select.addEventListener('change', () => {
    const findings = [...document.querySelectorAll('[data-finding-status]')];
    findings.forEach(row => { row.hidden = select.value !== 'all' && row.dataset.findingStatus !== select.value; });
    const count = document.querySelector('[data-finding-count]');
    if (count) count.textContent = `${findings.filter(row => !row.hidden).length}/${findings.length} phát hiện đang hiển thị`;
  }));
  const edit = document.querySelector('[data-unsaved-form]');
  if (edit) {
    const textarea = edit.querySelector('textarea'), initial = textarea.value;
    edit.addEventListener('input', () => { delete edit.dataset.saved; edit.querySelector('[data-edit-status]').textContent = textarea.value === initial ? 'Chưa có thay đổi.' : 'Có thay đổi chưa lưu. Bản in/xuất vẫn dùng phiên bản đã lưu.'; });
    addEventListener('beforeunload', event => { if (textarea.value !== initial && !edit.dataset.saved) { event.preventDefault(); event.returnValue = ''; } });
  }
  function openAnchor() { if (location.hash === '#report-edit') document.querySelector('#report-edit')?.setAttribute('open', ''); }
  addEventListener('hashchange', openAnchor); openAnchor();
})();
