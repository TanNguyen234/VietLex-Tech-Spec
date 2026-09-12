(() => {
  document.querySelectorAll('[data-reader-workspaces]').forEach(select => select.addEventListener('focus', async () => {
    if (select.dataset.loaded || select.dataset.loading) return;
    select.dataset.loading = 'true';
    const status = select.closest('form').querySelector('[role="status"]');
    try {
      const response = await fetch('/api/workspaces', {credentials: 'same-origin'});
      if (!response.ok) throw new Error('workspace_options_unavailable');
      const data = await response.json();
      for (const item of data.workspaces) {
        const option = document.createElement('option');
        option.value = item.workspace_id; option.textContent = item.title;
        select.append(option);
      }
      select.dataset.loaded = 'true';
      status.textContent = data.workspaces.length ? '' : 'Chưa có hồ sơ. Tạo hồ sơ rồi tải lại trang.';
    } catch { status.textContent = 'Không tải được hồ sơ. Chọn lại để thử lại.'; }
    finally { delete select.dataset.loading; }
  }));
  document.querySelectorAll('[data-print-report]').forEach(button => button.addEventListener('click', () => window.print()));
  const views = [...document.querySelectorAll('[data-workspace-view]')];
  if (views.length) {
    const showView = () => {
      const hash = location.hash.slice(1);
      const view = views.some(link => link.dataset.workspaceView === hash) ? hash : hash.startsWith('evidence-') ? 'sources' : 'overview';
      document.querySelectorAll('[data-workspace-panel]').forEach(panel => {
        panel.hidden = !panel.dataset.workspacePanel.split(' ').includes(view);
      });
      document.body.dataset.workspaceView = view;
      views.forEach(link => {
        if (link.dataset.workspaceView === view) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
    };
    addEventListener('hashchange', showView);
    showView();
  }
  document.querySelectorAll('[data-copy-section]').forEach(button => button.addEventListener('click', async () => {
    const section = button.closest('.legal-section');
    const url = new URL(location.href); url.hash = section.id;
    const text = button.dataset.copySection === 'text' ? section.querySelector('pre').textContent : button.dataset.copySection === 'citation' ? button.dataset.citation + '\n' + url.href : url.href;
    const status = section.querySelector('[role="status"]');
    try { await navigator.clipboard.writeText(text); status.textContent = 'Đã sao chép.'; }
    catch { status.textContent = 'Không truy cập được clipboard. Hãy chọn và sao chép nội dung trực tiếp.'; }
  }));
  try {
    const theme = localStorage.getItem('vietlex-theme');
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  } catch { /* Browser storage may be unavailable; forms must still work. */ }
  document.querySelectorAll('[data-theme-switch]').forEach(button => button.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('vietlex-theme', next); } catch { /* Keep this page usable. */ }
  }));
  document.addEventListener('submit', async event => {
    const form = event.target;
    if (!form.matches('[data-product-form]')) return;
    event.preventDefault();
    if (form.dataset.busy) return;
    if (form.dataset.confirm && !confirm(form.dataset.confirm)) return;
    let message = form.querySelector('[role="status"]');
    if (!message) { message = document.createElement('p'); message.setAttribute('role', 'status'); form.append(message); }
    const buttons = form.querySelectorAll('button');
    form.dataset.busy = 'true'; buttons.forEach(button => button.disabled = true);
    message.textContent = 'Đang xử lý…';
    try {
      const method = (form.method || 'get').toUpperCase();
      const data = new FormData(form);
      if (method === 'GET') for (const [key, value] of [...data.entries()]) if (value === '') data.delete(key);
      const url = new URL(form.action);
      if (method === 'GET') url.search = new URLSearchParams(data).toString();
      const response = await fetch(url, {method, body: method === 'GET' ? undefined : data, credentials: 'same-origin'});
      if (!response.ok) {
        message.textContent = response.status === 403 ? 'Phiên làm việc đã thay đổi. Tải lại trang rồi thử lại.' : response.status === 409 ? 'Dữ liệu đã thay đổi hoặc chạm giới hạn lưu trữ. Sao chép nội dung đang sửa, tải lại trang rồi thử lại.' : response.status === 429 ? 'Bạn thao tác quá nhanh. Vui lòng đợi một lát.' : 'Không thể hoàn tất. Vui lòng thử lại sau.';
        return;
      }
      if (form.dataset.target) {
        const target = document.querySelector(form.dataset.target);
        // Only same-origin server-rendered, Jinja-escaped fragments are inserted.
        target.innerHTML = await response.text(); message.textContent = 'Đã cập nhật kết quả.';
      } else if (response.redirected) { form.dataset.saved = 'true'; location.assign(response.url); }
      else { message.textContent = 'Đã lưu thay đổi.'; }
    } catch { message.textContent = 'Mất kết nối. Kiểm tra mạng và thử lại.'; }
    finally { delete form.dataset.busy; buttons.forEach(button => button.disabled = false); }
  });
})();
