'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'app', 'static', 'js', 'research-workspace.js'),
  'utf8',
);
const helperStart = source.indexOf('  let workspaceReadbackSequence = 0;');
const helperEnd = source.indexOf('  const freeResearchForm =', helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'workspace readback helpers are present');
const helperSource = source.slice(helperStart, helperEnd);

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return {promise, resolve, reject};
}

let fakeDocument;

function fragment(name, values = {}) {
  return {
    name,
    textContent: values.textContent || '',
    items: values.items || [],
    controls: values.controls || [],
    details: values.details || [],
    cloneNode() {
      const clonedControls = this.controls.map(control => ({
        ...control,
        focus(options) { this.focused = options; fakeDocument.activeElement = this; },
        setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
      }));
      return fragment(name, {
        textContent: this.textContent,
        items: [...this.items],
        controls: clonedControls,
        details: this.details.map(detail => ({...detail})),
      });
    },
    querySelectorAll(selector) {
      if (selector === '[data-readback-preserve]') return this.controls;
      if (selector === 'details[data-readback-key]') return this.details;
      return [];
    },
  };
}

function harness(fetchImpl, snapshotByText = {}) {
  const current = {
    '#workspace-source-library [data-source-library-count]': fragment('count', {textContent: '0 bản nguồn'}),
    '#workspace-source-library .source-library-grid': fragment('grid', {items: ['old-source']}),
    '#workspace-reports': fragment('reports', {items: ['empty-report-state']}),
    '#activity': fragment('history', {items: ['old-analysis']}),
    '#overview': fragment('overview', {items: ['old-summary']}),
  };
  const initialGrid = current['#workspace-source-library .source-library-grid'];
  const question = {
    dataset: {readbackPreserve: 'retained-question'},
    value: 'chưa lưu',
    selectionStart: 3,
    selectionEnd: 6,
    focus(options) { this.focused = options; fakeDocument.activeElement = this; },
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
  };
  initialGrid.controls = [question];
  const detail = {dataset: {readbackKey: 'source-detail'}, open: true};
  initialGrid.details = [detail];
  const document = {
    body: {dataset: {workspaceId: 'workspace-1', workspaceRevision: '2026-10-26T09:00:00Z'}},
    activeElement: question,
    querySelector(selector) { return current[selector] || null; },
  };
  fakeDocument = document;
  Object.entries(current).forEach(([selector, node]) => {
    node.replaceWith = replacement => { current[selector] = replacement; };
  });
  const window = {
    scrollX: 0,
    scrollY: 620,
    scrollTo(x, y) { this.scrollX = x; this.scrollY = y; },
  };
  const snapshotDocument = text => snapshotByText[text];
  class DOMParser {
    parseFromString(text) { return snapshotDocument(text); }
  }
  const freeResearchForm = {querySelector: () => ({value: 'run-1'})};
  const build = new Function(
    'document', 'window', 'fetch', 'DOMParser', 'workspaceId', 'freeResearchForm',
    `${helperSource}; return refreshWorkspaceState;`,
  );
  const refresh = build(document, window, fetchImpl, DOMParser, 'workspace-1', freeResearchForm);
  return {refresh, current, document, window, question, detail, freeResearchForm};
}

function snapshot({revision = '2026-10-26T09:01:00Z', sourceCount = '1 bản nguồn', sourceIds = ['source-1'], reportIds = ['report-1'], analysisIds = ['analysis-1']} = {}) {
  const nodes = {
    '#workspace-source-library [data-source-library-count]': fragment('count', {textContent: sourceCount}),
    '#workspace-source-library .source-library-grid': fragment('grid', {
      items: sourceIds,
      controls: [{dataset: {readbackPreserve: 'retained-question'}, value: 'server default', selectionStart: 0, selectionEnd: 0}],
      details: [{dataset: {readbackKey: 'source-detail'}, open: false}],
    }),
    '#workspace-reports': fragment('reports', {items: reportIds}),
    '#activity': fragment('history', {items: analysisIds}),
    '#overview': fragment('overview', {items: ['current-summary']}),
  };
  return {
    body: {dataset: {workspaceId: 'workspace-1', workspaceRevision: revision}},
    querySelector(selector) { return nodes[selector] || null; },
    querySelectorAll(selector) {
      if (selector === '[data-analysis-id]') return analysisIds.map(analysisId => ({dataset: {analysisId}}));
      return [];
    },
  };
}

function htmlResponse(text, {ok = true} = {}) {
  return {ok, status: ok ? 200 : 503, text: async () => text};
}

test('canonical owner-scoped readback updates library and reports while preserving active edits and focus', async () => {
  const page = snapshot({
    sourceCount: '1 bản nguồn',
    sourceIds: ['source-1'],
    reportIds: ['report-9'],
    analysisIds: ['analysis-9'],
  });
  const app = harness(async url => {
    assert.equal(url, '/workspaces/workspace-1');
    return htmlResponse('canonical', {ok: true});
  }, {canonical: page});

  const result = await app.refresh({analysisId: 'analysis-9'});

  assert.equal(result.status, 'updated');
  assert.equal(app.current['#workspace-source-library [data-source-library-count]'].textContent, '1 bản nguồn');
  assert.deepEqual(app.current['#workspace-source-library .source-library-grid'].items, ['source-1']);
  assert.deepEqual(app.current['#workspace-reports'].items, ['report-9']);
  assert.deepEqual(app.current['#activity'].items, ['analysis-9']);
  assert.deepEqual(app.current['#overview'].items, ['current-summary']);
  const restoredQuestion = app.current['#workspace-source-library .source-library-grid'].controls[0];
  assert.equal(restoredQuestion.value, 'chưa lưu');
  assert.equal(restoredQuestion.selectionStart, 3);
  assert.equal(restoredQuestion.selectionEnd, 6);
  assert.equal(app.document.activeElement, restoredQuestion);
  assert.equal(app.current['#workspace-source-library .source-library-grid'].details[0].open, true);
  assert.equal(app.window.scrollY, 620);
});

test('a late readback from an older run cannot replace the newer canonical state', async () => {
  const earlier = deferred();
  let calls = 0;
  const app = harness(async () => {
    calls += 1;
    return calls === 1 ? earlier.promise : htmlResponse('newer', {ok: true});
  }, {
    newer: snapshot({revision: '2026-10-26T09:03:00Z', sourceIds: ['new-source'], reportIds: ['new-report']}),
    older: snapshot({revision: '2026-10-26T09:02:00Z', sourceIds: ['old-source'], reportIds: ['old-report']}),
  });

  const oldRequest = app.refresh({runId: 'run-1'});
  const newResult = await app.refresh();
  earlier.resolve(htmlResponse('older', {ok: true}));
  const oldResult = await oldRequest;

  assert.equal(newResult.status, 'updated');
  assert.equal(oldResult.status, 'stale');
  assert.deepEqual(app.current['#workspace-source-library .source-library-grid'].items, ['new-source']);
  assert.deepEqual(app.current['#workspace-reports'].items, ['new-report']);
});

test('a failed readback leaves saved UI intact and reports a retryable failure', async () => {
  const app = harness(async () => { throw new Error('network'); });

  const result = await app.refresh();

  assert.equal(result.status, 'failed');
  assert.equal(app.current['#workspace-source-library [data-source-library-count]'].textContent, '0 bản nguồn');
  assert.deepEqual(app.current['#workspace-source-library .source-library-grid'].items, ['old-source']);
});
