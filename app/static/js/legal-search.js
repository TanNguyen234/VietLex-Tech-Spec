// Trang tìm văn bản: sao chép trích dẫn và lưu tìm kiếm gần đây (chỉ trên máy người dùng).
// Tách ra file riêng vì CSP của VietLex chặn script inline (script-src 'self').
(function () {
  'use strict';

  var RECENT_KEY = 'vietlex.recentSearches';
  var RECENT_LIMIT = 8;

  function copyCitation(button) {
    var text = button.getAttribute('data-citation') || '';
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { button.textContent = 'Đã sao chép'; },
        function () { button.textContent = 'Không sao chép được'; }
      );
    } else {
      button.textContent = 'Trình duyệt chặn sao chép';
    }
  }

  function loadRecent() {
    try {
      var value = JSON.parse(window.localStorage.getItem(RECENT_KEY) || '[]');
      return Array.isArray(value) ? value.filter(function (item) { return typeof item === 'string'; }) : [];
    } catch (error) {
      return [];
    }
  }

  function saveRecent(list) {
    try {
      window.localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_LIMIT)));
    } catch (error) {
      // Trình duyệt chặn bộ nhớ cục bộ: bỏ qua, trang vẫn tìm kiếm bình thường.
    }
  }

  function renderRecent(box) {
    var list = loadRecent();
    box.textContent = '';
    if (!list.length) {
      box.hidden = true;
      return;
    }
    var label = document.createElement('span');
    label.textContent = 'Tìm gần đây: ';
    box.appendChild(label);
    list.forEach(function (query) {
      var link = document.createElement('a');
      link.href = '/search?q=' + encodeURIComponent(query);
      link.textContent = query;
      link.style.marginRight = '0.6rem';
      box.appendChild(link);
    });
    box.hidden = false;
  }

  document.addEventListener('click', function (event) {
    var target = event.target;
    var button = target && target.closest ? target.closest('button[data-citation]') : null;
    if (button) {
      copyCitation(button);
    }
  });

  document.addEventListener('DOMContentLoaded', function () {
    var box = document.getElementById('recent-searches');
    var form = document.querySelector('form[action="/search"]');
    if (box) {
      renderRecent(box);
    }
    if (form) {
      form.addEventListener('submit', function () {
        var field = form.querySelector('input[name=q]');
        var query = field ? field.value.trim() : '';
        if (!query) {
          return;
        }
        var list = loadRecent().filter(function (item) { return item !== query; });
        list.unshift(query);
        saveRecent(list);
      });
    }
  });
})();
