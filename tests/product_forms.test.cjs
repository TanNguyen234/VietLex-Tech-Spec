const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const script = fs.readFileSync(path.join(__dirname, '../app/static/js/product.js'), 'utf8');

function fixture({confirm = true, fetch} = {}) {
  const events = {}, navigated = [], target = {}, buttons = [{disabled:false}];
  const message = {textContent:'', setAttribute() {}};
  const form = {
    method:'post', action:'http://localhost/workspaces', dataset:{},
    values:[['csrf_token','test-token'], ['title','Test']],
    matches:() => true, querySelector:() => message,
    querySelectorAll:() => buttons, append() {},
  };
  const context = {
    document:{documentElement:{dataset:{}}, querySelectorAll:() => [],
      querySelector:() => target, createElement:() => message,
      addEventListener:(name, handler) => events[name] = handler},
    localStorage:{getItem() {throw Error('unavailable');}},
    confirm:() => confirm, URL, URLSearchParams,
    FormData:class extends Map {constructor(value) {super(value.values);}},
    fetch:fetch || (async () => ({ok:true})),
    location:{assign:value => navigated.push(value)},
  };
  vm.runInNewContext(script, context);
  return {form, buttons, message, target, navigated,
    submit:() => events.submit({target:form, preventDefault() {}})};
}

test('forms still work with browser storage disabled', async () => {
  const f = fixture(); await f.submit();
  assert.equal(f.message.textContent, 'Đã lưu thay đổi.');
  assert.equal(f.buttons[0].disabled, false);
});

test('destructive confirmation cancellation never submits', async () => {
  let calls = 0;
  const f = fixture({confirm:false, fetch:async () => {calls++;}});
  f.form.dataset.confirm = 'Confirm?'; await f.submit();
  assert.equal(calls, 0);
});

test('admin filters omit empty options and replace only their target', async () => {
  const f = fixture({fetch:async (url, options) => {
    assert.equal(url.search, '?search=abc&skip=25');
    assert.equal(options.body, undefined);
    return {ok:true, text:async () => '<p>Escaped server result</p>'};
  }});
  f.form.method = 'get'; f.form.dataset.target = '#admin-log-results';
  f.form.values = [['search','abc'], ['provider',''], ['skip','25']];
  await f.submit(); assert.match(f.target.innerHTML, /Escaped server result/);
});

test('pending submissions are deduplicated and errors restore controls', async () => {
  let complete, calls = 0;
  const f = fixture({fetch:(url, options) => {
    calls++; assert.equal(options.body.get('csrf_token'), 'test-token');
    return new Promise(resolve => complete = resolve);
  }});
  const first = f.submit(); await f.submit();
  assert.equal(calls, 1); assert.equal(f.buttons[0].disabled, true);
  complete({ok:false,status:429}); await first;
  assert.match(f.message.textContent, /quá nhanh/);
  assert.equal(f.buttons[0].disabled, false);
  assert.equal(f.form.dataset.busy, undefined);
});

test('successful redirects navigate to the server-selected page', async () => {
  const f = fixture({fetch:async () => ({ok:true,redirected:true,url:'http://localhost/login'})});
  await f.submit(); assert.deepEqual(f.navigated, ['http://localhost/login']);
});
