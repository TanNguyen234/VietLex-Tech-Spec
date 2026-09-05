(() => {
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
        message.textContent = response.status === 403 ? 'Phiên làm việc đã thay đổi. Tải lại trang rồi thử lại.' : response.status === 409 ? 'Không thể thực hiện thay đổi này. Kiểm tra trạng thái tài khoản và thử lại.' : response.status === 429 ? 'Bạn thao tác quá nhanh. Vui lòng đợi một lát.' : 'Không thể hoàn tất. Vui lòng thử lại sau.';
        return;
      }
      if (form.dataset.target) {
        const target = document.querySelector(form.dataset.target);
        // Only same-origin server-rendered, Jinja-escaped fragments are inserted.
        target.innerHTML = await response.text(); message.textContent = 'Đã cập nhật kết quả.';
      } else if (response.redirected) location.assign(response.url);
      else { message.textContent = 'Đã lưu thay đổi.'; }
    } catch { message.textContent = 'Mất kết nối. Kiểm tra mạng và thử lại.'; }
    finally { delete form.dataset.busy; buttons.forEach(button => button.disabled = false); }
  });
})();
