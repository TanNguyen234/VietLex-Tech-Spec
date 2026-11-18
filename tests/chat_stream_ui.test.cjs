'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'static', 'js', 'vietlex.js'),
  'utf8',
);

function makeElement(tag = 'div', textContent = '', className = '') {
  return {
    tag,
    textContent,
    className,
    hidden: false,
    disabled: false,
    dataset: {},
    attributes: {},
    children: [],
    childNodes: [],
    href: '',
    isConnected: true,
    set innerHTML(html) {
      this._html = html;
      this.childNodes = [{tag: 'rendered-fragment', html, textContent: html}];
    },
    get innerHTML() {
      return this._html || '';
    },
    setAttribute(k, v) { this.attributes[k] = v; },
    append(...items) {
      this.children.push(...items);
      this.childNodes.push(...items);
    },
    replaceChildren(...items) {
      this.children = [...items];
      this.childNodes = [...items];
    },
    remove() {
      this.removed = true;
      this.isConnected = false;
    },
    querySelector(sel) {
      if (sel === '#session-id-input' && (this._html || '').includes('id="session-id-input"')) {
        const m = this._html.match(/value="([^"]+)"/);
        return {value: m ? m[1] : 'stream-session', remove() {}};
      }
      return null;
    },
  };
}

function createStreamResponse(lines, status = 200) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get(name) {
        if (String(name).toLowerCase() === 'content-type') return 'application/x-ndjson';
        return null;
      },
    },
    body: {
      getReader() {
        return {
          async read() {
            if (index >= lines.length) return {done: true, value: undefined};
            const chunk = encoder.encode(lines[index++] + '\n');
            return {done: false, value: chunk};
          },
        };
      },
    },
    async text() {
      return lines.join('\n');
    },
  };
}

function buildStreamHarness(fetchImpl) {
  const nodes = {};
  for (const id of [
    'chat-loading',
    'chat-status',
    'pipeline-progress',
    'pipeline-elapsed',
    'session-search',
    'session-id-input',
    'chat-stop',
    'chat-input',
  ]) {
    nodes[id] = makeElement('div');
    nodes[id].value = '';
    nodes[id].hidden = true;
  }
  nodes['session-id-input'].value = 'sess-init';
  nodes['chat-input'].value = 'Câu hỏi thử nghiệm';

  const history = {
    items: [],
    scrollTop: 0,
    scrollHeight: 420,
    append(...values) { this.items.push(...values); },
    replaceChildren(...values) { this.items = [...values]; },
  };
  nodes['chat-history'] = history;

  const submitButton = {disabled: false};
  const messageInput = nodes['chat-input'];
  const form = {
    dataset: {streamUrl: '/chat/stream'},
    querySelector(sel) {
      if (sel === '[type="submit"]') return submitButton;
      if (sel === '[name="message"]') return messageInput;
      return null;
    },
  };
  nodes['chat-form'] = form;

  let clickHandler = null;
  const toasts = [];
  const doc = {
    addEventListener(type, handler) {
      if (type === 'click') clickHandler = handler;
    },
    createElement(tag) {
      return makeElement(tag);
    },
    createTextNode(text) {
      return {textContent: text, data: text};
    },
  };

  class MockFormData {
    constructor() {
      this.values = new Map([
        ['message', messageInput.value],
        ['session_id', nodes['session-id-input'].value],
      ]);
    }
    set(k, v) { this.values.set(k, v); }
    get(k) { return this.values.get(k); }
  }

  const install = source.slice(
    source.indexOf('  async function installPartial('),
    source.indexOf('  function startProgress('),
  );
  const submit = source.slice(
    source.indexOf('  async function submitChat('),
    source.indexOf('  function openSource('),
  );
  const handler = source
    .split('\n')
    .find(line => line.includes("document.addEventListener('click',async event=>"));

  const api = new Function(
    '$',
    'document',
    'fetch',
    'FormData',
    'crypto',
    'startProgress',
    'streamAnswer',
    'renderMarkdown',
    'renderMarkdownTarget',
    'loadSessions',
    'toast',
    'csrf',
    install + submit + handler + ';return {submitChat};',
  )(
    selector => nodes[selector.replace(/^#/, '')] || null,
    doc,
    fetchImpl,
    MockFormData,
    {randomUUID: () => 'req-123'},
    () => () => {},
    async () => { throw new Error('fake typewriter must not run on streamed responses'); },
    () => {},
    () => {},
    async () => {},
    msg => toasts.push(msg),
    () => 'csrf-tok',
  );

  return {
    nodes,
    history,
    messageInput,
    submitButton,
    toasts,
    submit: () => api.submitChat(form),
    clickStop: () =>
      clickHandler({
        target: {
          closest: () => ({dataset: {action: 'stop-chat'}}),
        },
      }),
  };
}

test('submitChat streams NDJSON stages and deltas then swaps in final complete card', async () => {
  const lines = [
    JSON.stringify({type: 'stage', label: 'Đang kiểm tra an toàn đầu vào'}),
    JSON.stringify({type: 'stage', label: 'Đang tổng hợp câu trả lời có dẫn chiếu'}),
    JSON.stringify({type: 'delta', text: 'Theo Điều 25 '}),
    JSON.stringify({type: 'delta', text: 'Bộ luật Lao động 2019.'}),
    JSON.stringify({
      type: 'complete',
      html: '<article class="message-row assistant"><div class="message-card">Verified card</div></article><input type="hidden" id="session-id-input" value="sess-final">',
      session_id: 'sess-final',
      title: 'Câu hỏi thử nghiệm',
      guardrail_adjusted: false,
    }),
  ];
  let requestedUrl = null;
  const h = buildStreamHarness(async url => {
    requestedUrl = url;
    return createStreamResponse(lines);
  });

  await h.submit();

  assert.equal(requestedUrl, '/chat/stream');
  assert.equal(h.nodes['session-id-input'].value, 'sess-final');
  assert.equal(h.messageInput.value, '');
  assert.equal(h.nodes['chat-stop'].hidden, true);
  const activeItems = h.history.items.filter(item => !item.removed);
  assert.equal(activeItems.length, 1);
  assert.match(activeItems[0].html, /Verified card/);
});

test('clicking #chat-stop aborts in-flight stream cleanly and keeps user draft', async () => {
  let abortObserved = false;
  const h = buildStreamHarness((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      abortObserved = true;
      const err = new Error('The operation was aborted.');
      err.name = 'AbortError';
      reject(err);
    });
  }));

  const pending = h.submit();
  assert.equal(h.nodes['chat-stop'].hidden, false);
  await h.clickStop();
  await pending;

  assert.equal(abortObserved, true);
  assert.equal(h.messageInput.value, 'Câu hỏi thử nghiệm');
  assert.equal(h.nodes['chat-stop'].hidden, true);
  assert.equal(h.submitButton.disabled, false);
  assert.ok(!h.toasts.includes('Không thể kết nối tới VietLex.'));
});

test('401 demo login required renders login link and 503 surfaces server message', async () => {
  const h401 = buildStreamHarness(async () => ({
    ok: false,
    status: 401,
    headers: {get: () => 'application/json'},
    text: async () => JSON.stringify({detail: 'demo_login_required', message: 'Đăng nhập tài khoản đã xác minh để dùng chức năng này.'}),
  }));
  await h401.submit();
  const errCard401 = h401.history.items.at(-1);
  const loginAnchor = (errCard401.children || []).find(c => c.tag === 'a');
  assert.ok(loginAnchor, '401 error card includes a login link');
  assert.equal(loginAnchor.href, '/login');
  assert.equal(h401.messageInput.value, 'Câu hỏi thử nghiệm');

  const h503 = buildStreamHarness(async () => ({
    ok: false,
    status: 503,
    headers: {get: () => 'application/json'},
    text: async () => JSON.stringify({message: 'Hệ thống kiểm duyệt an toàn đang bận.'}),
  }));
  await h503.submit();
  assert.match(h503.history.items.at(-1).textContent, /Hệ thống kiểm duyệt an toàn đang bận/);
});
