'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/research-workspace.js'), 'utf8');

function serialize(until) {
  const start = source.indexOf("    if (form.dataset.analysis === 'legal-effect') {");
  const end = source.indexOf("    } else if (form.dataset.analysis === 'compare')", start);
  assert.ok(start >= 0 && end > start);
  const data = new Map(Object.entries({event_kind:'effective', effective_date:'2026-07-01',
    effective_until:until, document_number:'A/2026', target_document_number:'A/2026',
    exact_quote:'exact public source', event_evidence_id:'ev', event_scope:'whole_document'}));
  new Function('form', 'data', source.slice(start, end) + '}')({dataset:{analysis:'legal-effect'}}, data);
  return JSON.parse(data.get('events'))[0];
}

test('admin form carries explicit inclusive bound into reviewed event', () => {
  assert.equal(serialize('2027-02-28').effective_until, '2027-02-28');
});
test('empty bound preserves old event shape', () => {
  assert.equal(Object.hasOwn(serialize(''), 'effective_until'), false);
});
test('workspace replay renders finite expiry in Vietnamese', () => {
  const start = source.indexOf('  function renderLegalEffect(');
  const end = source.indexOf('  function renderAnalysis(', start);
  assert.ok(start >= 0 && end > start);
  const messages = [];
  const target = {replaceChildren(){}, append(node){messages.push(node.text);}};
  const render = new Function('element', 'sourceLinks', source.slice(start,end) + ';return renderLegalEffect;')(
    (_tag,text) => ({text,append(){}}), () => ({}));
  render({result:{effects:[{target_document_number:'A/2026',as_of:'2027-03-01',status:'expired'}]}},target);
  assert.ok(messages.some(text => text.includes('Hết thời hạn hiệu lực theo hồ sơ')));
  assert.ok(messages.some(text => text.includes('chưa chứng nhận')));
});
