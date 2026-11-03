from pathlib import Path
from dataclasses import asdict
import sys,json
sys.path.insert(0,str(Path.cwd()))
from app.evaluation.answer_metrics import _parsed_citation_set,_evidence_citations,_citation_satisfies
w=Path(__file__).parent
a=json.loads((Path('docs/evaluation/runs/answer-golden50-production-timeout20-20261103-f93a41fe/answer_results.json')).read_text(encoding='utf-8'))
rows=[]
for x in a:
 if not x['metrics'].get('invalid_citation_rate'):continue
 pred=_parsed_citation_set(x['final_response']);evidence=set().union(*[_evidence_citations(t) for t in x['prompt_contexts']]);bad=[c for c in pred if not any(_citation_satisfies(e,c) for e in evidence)]
 rows.append({'case_id':x['case_id'],'macro_invalid':x['metrics']['invalid_citation_rate'],'unsupported_locators':[asdict(t) for t in bad],'same_article_or_clause_evidence':sorted([asdict(t) for t in evidence if any(t.article==b.article and bool(t.article) for b in bad)],key=lambda t:json.dumps(t)),'indexed_response_paragraphs':[p for p in x['final_response'].split('\n\n') if '#' in p][:8]})
(w/'citation-audit.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(rows,ensure_ascii=False,indent=2))
