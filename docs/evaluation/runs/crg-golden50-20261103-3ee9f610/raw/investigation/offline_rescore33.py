from pathlib import Path
from datetime import datetime,timezone
import sys,json,hashlib,copy,uuid,subprocess,time,ast
sys.path.insert(0,str(Path.cwd()))
from app.evaluation.answer_metrics import calculate_case_answer_metrics,aggregate_answer_metrics,ANSWER_METRIC_VERSION
from app.evaluation.case_selection import build_cases
from app.evaluation.retrieval_metrics import aggregate_retrieval_metrics,calculate_stage_survival_rates
from app.evaluation.latency_metrics import calculate_stage_latency_summary
from app.evaluation.retrieval_gate import evaluate_retrieval_gate
from app.evaluation.schemas import AnswerCaseResult,EvaluationRunManifest
from app.evaluation.reporting import write_run_report
from app.evaluation.run_manifest import atomic_write_json,collect_artifact_files,calculate_configuration_fingerprint
from app.evaluation.provenance import collect_git_provenance
r=Path.cwd();w=Path(__file__).parent;parent='answer-golden50-production-timeout20-20261103-f93a41fe';p=r/'docs/evaluation/runs'/parent
def load(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
assert ANSWER_METRIC_VERSION=='3.3.0'
start=time.monotonic();original=load(p/'answer_results.json');answers=copy.deepcopy(original);cases={c.case_id:c for c in build_cases(load(r/'docs/evaluation/golden50-v3/cases.json'),{})}
command=load(w/'benchmark-timeout-command.json');base=load(w/'benchmark-full-command.json')
for name,key in [('cases.json','dataset_sha256'),('labels.json','sidecar_sha256')]:assert sha(r/'docs/evaluation/golden50-v3'/name)==command[key]==base[key]
allowed={'answer_metric_version','citation_precision','invalid_citation_rate','citation_recall','citation_coverage','metric_skip_reasons'};paired=[]
assert len(answers)==50 and {x['case_id'] for x in answers}==set(cases)
for old,x in zip(original,answers):
 c=cases[x['case_id']];contexts=x['prompt_contexts'];assert [hashlib.sha256(t.encode()).hexdigest() for t in contexts]==[v['sha256'] for v in x['prompt_evidence']]
 new=calculate_case_answer_metrics(x['final_response'],c.reference_answer,c.question_type,contexts,c.expected_numbers,c.expected_dates,c.expected_entities,status=x['status'])
 assert all(old['metrics'][k]==new[k] for k in new if k not in allowed)
 x['metrics']=new;assert {k:v for k,v in old.items() if k!='metrics'}=={k:v for k,v in x.items() if k!='metrics'}
 paired.append({'case_id':x['case_id'],'answer_sha256':hashlib.sha256(x['final_response'].encode()).hexdigest(),'prompt_hashes_unchanged':True,'old_citation_precision':old['metrics']['citation_precision'],'new_citation_precision':new['citation_precision'],'old_invalid_rate':old['metrics']['invalid_citation_rate'],'new_invalid_rate':new['invalid_citation_rate']})
retrieval=load(p/'retrieval_results.json');ret=aggregate_retrieval_metrics(retrieval);gate=evaluate_retrieval_gate(ret,k=3);oldsummary=aggregate_answer_metrics(original);summary=aggregate_answer_metrics(answers)
summary_record={'mode':'offline same-answer full50 rescore; zero provider/database calls','parent_live_run':parent,'parent_answer_results_sha256':sha(p/'answer_results.json'),'old_metric_version':'3.2.0','new_metric_version':ANSWER_METRIC_VERSION,'cases':50,'input_safe_count':sum(x['input_safe'] is True for x in answers),'output_safe_count':sum(x['output_safe'] is True for x in answers),'technical_error_cases':sum(bool(x['technical_errors']) for x in answers),'generation_observed_in_parent':sum(x['generation_metadata'].get('observed') is True for x in answers),'old_answer_summary':oldsummary,'answer_summary':summary,'retrieval_summary':ret,'retrieval_gate':gate,'paired_cases':paired,'unchanged_non_citation_metrics':True,'original_answers_contexts_metadata_unchanged':True}
if '--draft' in sys.argv:
 atomic_write_json(w/'metric33-draft-summary.json',summary_record);print(json.dumps({'draft':True,'cases':50,'old_citation_precision':oldsummary['citation_precision'],'new_citation_precision':summary['citation_precision'],'new_invalid_rate':summary['invalid_citation_rate']}));sys.exit(0)
cycle=r/'.tmp-finish-real-20261030/cycle27';assert load(cycle/'full-result.json')['status']=='PASS';snapshot=load(cycle/'source-before-full.json');assert all(sha(r/f)==h for f,h in snapshot.items())
# Only the offline metric module changes in app; its online helpers are AST-identical.
before=load(r/'.tmp-finish-real-20261030/cycle26/source-before-full.json');changed_app=[f for f,h in before.items() if f.startswith('app/') and sha(r/f)!=h];assert changed_app==['app/evaluation/answer_metrics.py']
oldast=ast.parse((w/'answer_metrics-before33.py').read_text(encoding='utf-8'));newast=ast.parse((r/'app/evaluation/answer_metrics.py').read_text(encoding='utf-8'));oldf={n.name:ast.dump(n,include_attributes=False) for n in oldast.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))};newf={n.name:ast.dump(n,include_attributes=False) for n in newast.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))};assert all(newf[n]==v for n,v in oldf.items() if n!='calculate_case_answer_metrics')
run='answer-golden50-offline-metrics33-20261103-'+uuid.uuid4().hex[:8];out=r/'docs/evaluation/runs'/run;out.mkdir(exist_ok=False)
parent_manifest=load(p/'manifest.json');config=copy.deepcopy(parent_manifest['configuration']);config['answer_metric_version']=ANSWER_METRIC_VERSION;config['rescore']={'mode':'offline_only','parent_live_run':parent,'parent_answer_results_sha256':sha(p/'answer_results.json'),'provider_calls_this_run':0,'database_calls_this_run':0,'online_observations_and_latencies':'inherited unchanged from parent; not new calls or new latency observations','changed_app_files':changed_app,'unchanged_online_helper_AST':True}
prov=collect_git_provenance(r);current={k:getattr(prov,k) for k in parent_manifest if hasattr(prov,k)};current.update({'provenance_status':prov.status,'provenance_error':prov.error})
manifest=EvaluationRunManifest.model_validate({**parent_manifest,**current,'run_id':run,'utc_timestamp':datetime.now(timezone.utc).isoformat(),'answer_metric_version':ANSWER_METRIC_VERSION,'configuration':config,'configuration_fingerprint':calculate_configuration_fingerprint(config),'command':subprocess.list2cmdline([sys.executable,'-X','utf8',str(Path(__file__).relative_to(r))]),'artifact_files':[]})
atomic_write_json(out/'manifest.json',manifest.model_dump(mode='json'));atomic_write_json(out/'configuration.json',config);atomic_write_json(out/'answer_results.json',answers)
for name in ['retrieval_results.json','evaluation_case_set.json']:(out/name).write_bytes((p/name).read_bytes())
stage=calculate_stage_survival_rates([AnswerCaseResult.model_validate(x).retrieval_result.stage_trace for x in answers]);latency=calculate_stage_latency_summary([x['latency'] for x in answers])
report=write_run_report(out,manifest,ret,stage,latency,summary,answers)
prefix='# OFFLINE FULL-METRIC RESCORE — no new provider/database calls\n\nAll answers, prompt contexts, retrieval results, generation/guard observations and latencies come unchanged from live parent `'+parent+'` (source26). Only deterministic citation metrics are recomputed using3.3 on source27. This is not a new live50 run on deployment27. Source/dependency proof and paired old/new metrics are in rescore-proof.json and paired-metrics.json.\n\n'
report.write_text(prefix+report.read_text(encoding='utf-8'),encoding='utf-8')
diff=subprocess.run(['git','diff','--binary','HEAD'],capture_output=True,check=True).stdout
proof={'parent_run':parent,'parent_files_sha256':{f.name:sha(f) for f in p.iterdir() if f.is_file()},'source_snapshot_sha256':snapshot,'git_dirty':True,'git_diff_sha256':hashlib.sha256(diff).hexdigest(),'git_diff_hash_contract':'literal tracked git diff --binary HEAD; canonical whole-workingtree provenance retains redacted policy','changed_app_files':changed_app,'unchanged_online_helpers_AST':True,'answers_contexts_provider_metadata_unchanged':True,'non_citation_metrics_unchanged':True,'dataset_raw_sha256':command['dataset_sha256'],'labels_raw_sha256':command['sidecar_sha256'],'provider_calls':0,'database_calls':0,'elapsed_offline_seconds':time.monotonic()-start}
atomic_write_json(out/'rescore-proof.json',proof);atomic_write_json(out/'paired-metrics.json',paired);atomic_write_json(out/'full-metric-summary.json',{'retrieval':ret,'stage_survival':stage,'answer':summary,'latency_inherited_from_parent':latency,'retrieval_gate':gate})
manifest=manifest.model_copy(update={'artifact_files':collect_artifact_files(out)});atomic_write_json(out/'manifest.json',manifest.model_dump(mode='json'))
summary_record['run_id']=run;summary_record['latency']=latency;atomic_write_json(w/'metric33-final-summary.json',summary_record);(w/'metric33-run-path.txt').write_text(str(out),encoding='utf-8')
assert all(sha(r/f)==h for f,h in snapshot.items());print(json.dumps({'run_id':run,'cases':50,'old_citation_precision':oldsummary['citation_precision'],'new_citation_precision':summary['citation_precision'],'new_invalid_rate':summary['invalid_citation_rate'],'provider_calls':0,'database_calls':0,'report':str(report)}))
