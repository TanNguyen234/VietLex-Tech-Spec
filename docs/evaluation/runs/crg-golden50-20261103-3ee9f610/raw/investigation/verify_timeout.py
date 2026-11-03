from pathlib import Path
from collections import Counter
import sys,json,hashlib
sys.path.insert(0,str(Path.cwd()))
from app.evaluation.answer_metrics import calculate_case_answer_metrics,aggregate_answer_metrics
from app.evaluation.case_selection import build_cases
from app.evaluation.retrieval_metrics import aggregate_retrieval_metrics
from app.evaluation.retrieval_gate import evaluate_retrieval_gate
from app.evaluation.latency_metrics import calculate_stage_latency_summary
w=Path(__file__).parent;run=json.loads((w/'benchmark-timeout-exit.json').read_text())
assert run['exit_code']==0 and not run['source_mismatches']
command=json.loads((w/'benchmark-timeout-command.json').read_text());baseline=json.loads((w/'benchmark-full-command.json').read_text())
for name,key in [('cases.json','dataset_sha256'),('labels.json','sidecar_sha256')]:
 assert hashlib.sha256((Path('docs/evaluation/golden50-v3')/name).read_bytes()).hexdigest()==command[key]==baseline[key], 'Frozen dataset or labels changed'
p=Path('docs/evaluation/runs')/run['run_id'];a=json.loads((p/'answer_results.json').read_text(encoding='utf-8'));dataset=json.loads(Path('docs/evaluation/golden50-v3/cases.json').read_text(encoding='utf-8'));cases={x.case_id:x for x in build_cases(dataset,{})};rows=[]
assert len(a)==50 and {x['case_id'] for x in a}==set(cases)
for x in a:
 c=cases[x['case_id']];contexts=x['prompt_contexts'];hashes=[hashlib.sha256(t.encode()).hexdigest() for t in contexts];expected=[t['sha256'] for t in x['prompt_evidence']]
 metrics=calculate_case_answer_metrics(pred_response=x['final_response'],ref_answer=c.reference_answer,question_type=c.question_type,retrieved_contexts=contexts,expected_numbers=c.expected_numbers,expected_dates=c.expected_dates,expected_entities=c.expected_entities,status=x['status'])
 row={'id':x['case_id'],'prompt_contexts':len(contexts),'hashes_match':hashes==expected,'metrics_reproduce':metrics==x['metrics'],'input_safe':x['input_safe'],'output_safe':x['output_safe'],'status':x['status']};rows.append(row)
assert all(x['hashes_match'] and x['metrics_reproduce'] for x in rows)
ret=aggregate_retrieval_metrics(json.loads((p/'retrieval_results.json').read_text()));gate=evaluate_retrieval_gate(ret,k=3);answers=aggregate_answer_metrics(a)
result={'run_id':run['run_id'],'evidence':'offline deterministic replay of the actual final live run, zero provider/database calls','cases':rows,'replay_passed_cases':sum(x['metrics_reproduce'] and x['hashes_match'] for x in rows),'input_safe_count':sum(x['input_safe'] is True for x in rows),'output_safe_count':sum(x['output_safe'] is True for x in rows),'statuses':dict(Counter(x['status'] for x in a)),'generation_observed':sum(x['generation_metadata'].get('observed') is True for x in a),'observed_generation_models':dict(Counter(x['generation_metadata'].get('model','unobserved') for x in a if x['generation_metadata'].get('observed'))),'technical_error_cases':sum(bool(x['technical_errors']) for x in a),'ragas_results':sum(x.get('ragas_metrics') is not None for x in a),'retrieval_gate':gate,'retrieval_summary':ret,'answer_summary':answers,'latency':calculate_stage_latency_summary([x['latency'] for x in a])}
(w/'timeout50-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:result[k] for k in ['run_id','replay_passed_cases','input_safe_count','output_safe_count','statuses','generation_observed','technical_error_cases','ragas_results','retrieval_gate']},indent=2))
