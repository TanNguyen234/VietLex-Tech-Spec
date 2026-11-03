'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'static', 'js', 'research-workspace.js'),
  'utf8',
);
const handlerStart = source.indexOf("  freeCancelButton?.addEventListener('click', async () => {");
const handlerEnd = source.indexOf("  freeResearchForm?.addEventListener('submit', async event => {", handlerStart);
assert.ok(handlerStart >= 0 && handlerEnd > handlerStart, 'cancellation handler is present');
const handlerSource = source.slice(handlerStart, handlerEnd);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

function harness(fetchImpl) {
  const oldController = {aborts: 0, abort() { this.aborts += 1; }};
  const sandbox = {
    controller: oldController,
    runId: 'old-run',
    fetchImpl,
    messages: [],
    jsonCalled: false,
  };
  const executeHandler = new Function('sandbox', `
    let freeResearchController = sandbox.controller;
    let freeResearchCancelRecorded = false;
    const csrf = 'csrf-token';
    const workspaceId = 'workspace-1';
    const freeResearchForm = {querySelector: () => ({value: sandbox.runId})};
    const freeCancelButton = {
      disabled: false,
      addEventListener(_name, listener) { sandbox.cancel = listener; },
    };
    const freeResearchResult = {
      append(node) { sandbox.messages.push(node.text); },
    };
    class FormData { set() {} }
    const fetch = (...args) => sandbox.fetchImpl(...args);
    const element = (_tag, text) => ({text});
    const operationError = (_payload, status) => 'HTTP ' + status;
    ${handlerSource}
    return {
      setCurrent(controller, runId) {
        freeResearchController = controller;
        sandbox.controller = controller;
        sandbox.runId = runId;
      },
      isCancelRecorded() { return freeResearchCancelRecorded; },
      button: freeCancelButton,
    };
  `);
  sandbox.oldController = oldController;
  sandbox.handler = executeHandler(sandbox);
  return sandbox;
}

function startNewRun(sandbox) {
  sandbox.handler.setCurrent({aborts: 0, abort() { this.aborts += 1; }}, 'new-run');
  sandbox.messages.splice(0, sandbox.messages.length, 'new-run output');
  sandbox.handler.button.disabled = false;
}

function assertStaleRequestHadNoEffects(sandbox) {
  assert.equal(sandbox.oldController.aborts, 0);
  assert.equal(sandbox.handler.isCancelRecorded(), false);
  assert.deepEqual(sandbox.messages, ['new-run output']);
  assert.equal(sandbox.handler.button.disabled, false);
}

test('late fetch response cannot abort or alter a newer run', async () => {
  const request = deferred();
  const sandbox = harness(() => request.promise);
  const pending = sandbox.cancel();
  assert.equal(sandbox.handler.button.disabled, true);

  startNewRun(sandbox);
  request.resolve({
    ok: true,
    json: async () => {
      sandbox.jsonCalled = true;
      return {outcome: 'cancelled', status: 'partial', source_count: 1};
    },
  });
  await pending;

  assert.equal(sandbox.jsonCalled, false);
  assertStaleRequestHadNoEffects(sandbox);
});

test('late JSON acknowledgement cannot abort or alter a newer run', async () => {
  const body = deferred();
  const sandbox = harness(async () => ({
    ok: true,
    json: () => {
      sandbox.jsonCalled = true;
      return body.promise;
    },
  }));
  const pending = sandbox.cancel();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sandbox.jsonCalled, true);

  startNewRun(sandbox);
  body.resolve({outcome: 'cancelled', status: 'partial', source_count: 1});
  await pending;

  assertStaleRequestHadNoEffects(sandbox);
});

test('late fetch failure cannot add an error to a newer run', async () => {
  const request = deferred();
  const sandbox = harness(() => request.promise);
  const pending = sandbox.cancel();

  startNewRun(sandbox);
  request.reject(new Error('delayed network failure'));
  await pending;

  assertStaleRequestHadNoEffects(sandbox);
});
