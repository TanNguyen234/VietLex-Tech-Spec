document.addEventListener('submit', event => {
  const form = event.target.closest('[data-source-analysis-form]');
  if (!form) return;
  form.querySelector('button').disabled = true;
  form.querySelector('[role="status"]').textContent = 'Đang phân tích các trang đã lưu và kiểm tra trích dẫn…';
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('[data-source-analysis-form]').forEach(form => {
    form.querySelector('button').disabled = false;
    form.querySelector('[role="status"]').textContent = '';
  });
});
