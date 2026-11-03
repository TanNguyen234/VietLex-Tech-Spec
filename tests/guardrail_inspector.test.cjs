const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/js/vietlex.js'), 'utf8');
const render = source.slice(source.indexOf('  function renderRetrievalTrace('), source.indexOf('  async function inspectRetrieval('));
function node(text = '') { return {text, children: [], append(...values) {this.children.push(...values);}, replaceChildren() {this.children=[];}}; }
test('inspector renders explicit mode, execution and stage errors without calling unknown safe', () => {
  const panel=node();
  new Function('make', render+'; return renderRetrievalTrace;')((tag,text)=>node(text))(panel, {
    status:'available', guardrail_state:{mode:'enforce', requested:true, executed:true, status:'error',
      input_safe:null, output_safe:null, stages:{input:{status:'error',safe:null},output:{status:'not_run',safe:null}}},
  });
  const texts = value => [value.text,...value.children.flatMap(texts)].join(' ');
  const output=texts(panel);
  assert.match(output, /enforce/);
  assert.match(output, /error/);
  assert.match(output, /not_run/);
  assert.match(output, /Chưa đánh giá/);
});
