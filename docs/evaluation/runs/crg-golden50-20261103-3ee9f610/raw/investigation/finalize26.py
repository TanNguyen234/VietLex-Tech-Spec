from pathlib import Path
from datetime import datetime,timezone
import sys,json,hashlib,shutil,subprocess,uuid,re
sys.path.insert(0,str(Path.cwd()))
r=Path.cwd();w=Path(__file__).parent;c=r/'.tmp-finish-real-20261030/cycle26';p=w/'production-final26'
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
snapshot=read(c/'source-before-full.json');assert all(sha(r/f)==h for f,h in snapshot.items())
assert read(c/'full-result.json')['status']=='PASS'
v=read(w/'timeout50-validation.json');assert v['replay_passed_cases']==50 and v['retrieval_gate']['passed'] and v['technical_error_cases']==0 and v['input_safe_count']==50 and v['output_safe_count']==50
assert read(w/'local-guard-timeout20.json')['passed'] and read(w/'local-guard-timeout20.json')['guardrail_timeout_seconds']==20.0
g=read(p/'guardrails-verified.json');assert g['all_pass']
db=read(p/'database-roundtrip.json');assert len(db['cases'])==8 and all(x['contexts_match_prompt'] and x['saved_answer_matches_HTTP'] and x['foreign_owner_count']==0 and x['guardrail_engine']=='direct_self_check' for x in db['cases'])
assert read(p/'control-database.json')['passed']
assert next(x for x in read(p/'ownership.json')['checks'] if x['role']=='USER')['passed']
assert read(p/'admin-policy.json')['mandatory_copy_present']
assert read(w/'frontend-final26/receipt.json')['matches_tested_source']
assert read(w/'log-scan.json')['exit_code']==0
trip=read(p/'source-roundtrip.json');assert len(trip)==8 and all(x['export_hash_sequence_matches_prompt'] and x['replay_source_bodies_equal'] for x in trip)
pdf=read(p/'pdf-g7-original.json');assert pdf['status']=='ok' and pdf['result']['sources'][0]['document_sha256']=='e8a97fb2f060f944a7d87716176de06e9fbd1d8049006797fea8185f253b5a6e'
assert read(p/'pdf-datafiles-control.json')['status']=='metadata_only'
review=read(w/'content-review-final.json');assert len(review['cases'])==8
identity=read(p/'health.json')['identity'];assert identity['public_guardrail_policy']=='enforce'
run='crg-golden50-20261103-'+uuid.uuid4().hex[:8];out=r/'docs/evaluation/runs'/run;out.mkdir();(w/'report-path.txt').write_text(str(out))
shutil.copytree(w,out/'raw/investigation',ignore=shutil.ignore_patterns('__pycache__','report-path.txt'))
shutil.copytree(c,out/'raw/release26',ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(r/'.tmp-finish-real-20261030/cycle25',out/'raw/candidate25-unpromoted',ignore=shutil.ignore_patterns('__pycache__'))
changed=['.codex/config.toml','.code-review-graphignore','app/evaluation/legal_citations.py','app/evaluation/answer_metrics.py','app/evaluation/schemas.py','run_answer_eval.py','app/config.py','tests/services/test_serverless_guardrails.py','tests/evaluation/test_evidence_citation_scope.py','tests/evaluation/test_chat_pipeline_parity.py','tests/evaluation/test_vietnamese_entity_metrics.py']
for f in changed:
 d=out/'source'/f;d.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(r/f,d)
benchmarks={}
for kind,receipt in [('baseline','benchmark-full-command.json'),('citation32_failed','benchmark-fixed-command.json'),('final','benchmark-timeout-command.json')]:
 x=read(w/receipt);bp=r/'docs/evaluation/runs'/x['run_id'];assert bp.is_dir()
 benchmarks[kind]={'run_id':x['run_id'],'files_sha256':{f.relative_to(bp).as_posix():sha(f) for f in bp.rglob('*') if f.is_file()},'command':x['argv'],'git_diff_sha256':x['git_diff_sha256'],'dataset_sha256':x['dataset_sha256'],'sidecar_sha256':x['sidecar_sha256']}
(out/'benchmark-references.json').write_text(json.dumps(benchmarks,indent=2))
(out/'configuration.json').write_text(json.dumps({'production_identity':identity,'metric_version':'3.2.0','pipeline':'chat_service_v1','retrieval':'Vertex/Qdrant v3 rrf-dbsf','guardrails':'enforce input+output; public local/online mandatory','guardrail_timeout_seconds_source_default':20.0,'production_timeout_override_present':False,'production_env_preflight':'raw/investigation/timeout-env-preflight-complete.json','judge':'none; zero Ragas calls','dataset':'unchanged Golden50-v3; 40 verified cases/53 items; 10 no_verified_gold_label retrieval skips','benchmark_execution':'local production service with actual providers, separate from deployed frozen8 HTTP acceptance','model_ids':['gemini-3.5-flash','gemini-embedding-2/1024','vietlex-legal-rag-v3-vertex-1024']},indent=2))
template=(w/'REPORT-template26.md').read_text(encoding='utf-8')
pyresult=next(x.strip('= ') for x in reversed((c/'python-full.log').read_text(encoding='utf-8',errors='replace').splitlines()) if ' passed' in x and ' in ' in x)
for a,b in {'@RUN@':run,'@DEPLOYMENT@':identity['deployment_id'],'@APP_SHA@':identity['app_source_sha256'],'@CONFIG_SHA@':identity['configuration_sha256'],'@PYTHON@':pyresult,'@FINAL_RUN@':v['run_id'],'@CONTENT@':review['summary']}.items():template=template.replace(a,b)
assert not re.search(r'@[A-Z_]+@',template)
metric_rows=[]
for name in ['exact_match','token_precision','token_recall','token_f1','char_f1','citation_precision','invalid_citation_rate','citation_recall','mixed_claim_refusal_rate']:
 m=v['answer_summary']['metric_details'][name];metric_rows.append(f"| {name} | {m['value']} | {m['numerator']}/{m['denominator']} | {m['coverage']} |")
numeric='\n## Final measured answer metrics\n\n| Metric | Value | Numerator/denominator | Coverage |\n| --- | ---: | ---: | ---: |\n'+'\n'.join(metric_rows)+'\n\nRetrieval configured gate: `'+json.dumps(v['retrieval_gate'],ensure_ascii=False)+'`.\n\nObserved generation: '+str(v['generation_observed'])+'/50; input safe '+str(v['input_safe_count'])+'/50; output safe '+str(v['output_safe_count'])+'/50; technical-error cases '+str(v['technical_error_cases'])+'/50. Generation/guard models and latency detail are in timeout50-validation.json.\n'
template+=numeric
canonical=(r/'docs/evaluation/runs'/v['run_id']/'report.md').read_text(encoding='utf-8')
retrieval_rows=[line for line in canonical.splitlines() if any(line.startswith('| '+name+' |') for name in ['Document Recall @ 3','Article Recall @ 3','Clause Recall @ 3','Multi-hop all-required coverage'])]
assert len(retrieval_rows)==4
template+='\n| Retrieval metric | Macro | Micro | Numerator/denominator | Scored/skipped | Skip reasons |\n| --- | ---: | ---: | ---: | ---: | --- |\n'+'\n'.join(retrieval_rows)+'\n'
(out/'REPORT.md').write_text(template,encoding='utf-8')
status=f"CRG/Golden50 follow-up 2026-11-03 (latest): actual CRG stdio MCP repaired and used; citation metrics3.2 and exact prompt-context replay fixed. Fresh {pyresult}; Node22passed. Golden50 `{v['run_id']}` completed50 cases; replay50/50, guards {v['input_safe_count']}/50 input and {v['output_safe_count']}/50 output, retrieval gate {'PASS' if v['retrieval_gate']['passed'] else 'FAIL'}. Live release `{identity['deployment_id']}` frozen8/roles/source/database/guard controls checked. L04 source dossier expanded; complete legal-currentness/human approval remains DEFERRED. This bounded dataset does not demonstrate full-corpus production readiness. [Evidence and limits](evaluation/runs/{run}/REPORT.md)."
for f in ['docs/PROJECT_CONTEXT.md','docs/CURRENT_ARCHITECTURE.md','FEATURE_STATUS.md','docs/evaluation/CURRENT_STATUS.md']:
 d=r/f;text=d.read_text(encoding='utf-8');a,b=text.split('\n',1)
 # Preserve older entries as history, removing only obsolete identical duplicated latest labels.
 b=b.replace('ECC remediation 2026-11-03 (latest):','Historical ECC remediation 2026-11-03:')
 linkstatus=status.replace('](evaluation/runs/','](runs/') if f=='docs/evaluation/CURRENT_STATUS.md' else status
 d.write_text(a+'\n\n'+linkstatus+'\n'+b,encoding='utf-8')
gold=r/'docs/evaluation/golden50-v3/README.md';t=gold.read_text(encoding='utf-8').replace('The latest run pair is:','The historical September2026 run pair is:')
head,body=t.split('\n',1);gold.write_text(head+'\n\nLatest measurement (2026-11-03): `'+v['run_id']+'`, metric3.2.0, real production-service providers, mandatory guards, judge none. Exact prompt-context/hash and offline metric replay50/50. See [current report](../runs/'+run+'/REPORT.md) for numerators, skips and limits. The September commands/results below remain historical; the current full command uses `--backend production --judge none` and is recorded verbatim in the report receipts.\n'+body,encoding='utf-8')
plan=r/'docs/tasks/crg-golden50-20261103/PLAN.md';plan.write_text(plan.read_text(encoding='utf-8')+'\nCompleted actual CRG MCP, focused RED/GREEN/source review, fresh full25, baseline50/final50 and deterministic replay, release26 and fresh HTTP acceptance. L04 official source dossier complete within recorded coverage, legal-currentness/human approval not promoted. Final report: '+str(out/'REPORT.md')+'\n',encoding='utf-8')
diff=subprocess.run(['git','diff','--binary','HEAD'],capture_output=True,check=True).stdout;(out/'git-diff.patch').write_bytes(diff)
from app.config import Settings
from pydantic import SecretStr
class QA(Settings):
 PRODUCTION_AUDIT_ADMIN_EMAIL:SecretStr|None=None
 PRODUCTION_AUDIT_ADMIN_PASSWORD:SecretStr|None=None
 PRODUCTION_AUDIT_USER_EMAIL:SecretStr|None=None
 PRODUCTION_AUDIT_USER_PASSWORD:SecretStr|None=None
s=QA();secrets=[]
for n in type(s).model_fields:
 value=getattr(s,n)
 if isinstance(value,SecretStr):value=value.get_secret_value()
 elif not re.search(r'KEY|TOKEN|SECRET|PASSWORD|MONGO_URL',n):continue
 if isinstance(value,str) and len(value)>=8:secrets.append(value.encode())
hits=[f.relative_to(out).as_posix() for f in out.rglob('*') if f.is_file() and any(k in f.read_bytes() for k in secrets)];assert not hits,hits
assert all(sha(r/f)==h for f,h in snapshot.items())
validation={'source_snapshot_files':len(snapshot),'source_mismatches':[],'known_secret_values_checked':len(secrets),'secret_hits':hits,'benchmark_replay':50,'live_frozen_cases':8,'negative_controls':2,'roles':'ADMIN/USER','legal_human_promotion':False};(out/'validation.json').write_text(json.dumps(validation,indent=2))
manifest={'run_id':run,'created_at':datetime.now(timezone.utc).isoformat(),'git_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'git_dirty':True,'git_diff_sha256':hashlib.sha256(diff).hexdigest(),'git_diff_hash_contract':'literal tracked git diff --binary HEAD; benchmark canonical whole-workingtree provenance remains conservatively redacted, see command receipts','dataset_revision':'golden50-v3 unchanged; cases+labels SHA in benchmark-references.json','configuration_fingerprint':identity['configuration_sha256'],'app_fingerprint':identity['app_source_sha256'],'metric_version':'3.2.0','commands':'REPORT.md and raw command/exit receipts','changed_files':changed+['docs/tasks/crg-golden50-20261103/PLAN.md','docs/PROJECT_CONTEXT.md','docs/CURRENT_ARCHITECTURE.md','FEATURE_STATUS.md','docs/evaluation/CURRENT_STATUS.md','docs/evaluation/golden50-v3/README.md'],'limits':['L04 full currentness/human approval DEFERRED','native host CRG reload NOT RUN; actual stdio MCP succeeded','JS grammar unavailable, source+Node fallback','three preexisting inaccessible scratch dirs; exhaustive untracked inventory UNKNOWN','no representative full-corpus/legal correctness proof','judge none; optional Ragas NOT RUN'],'external_effects':['authorized real providers for preflight1+baseline50+final50 and frozen8/controls','authorized Vercel candidate deployment and promotion','ordinary QA logins and saved synthetic QA chat data','read-only legal-source/database checks; no corpus/vector mutations'],'files_sha256':{f.relative_to(out).as_posix():sha(f) for f in out.rglob('*') if f.is_file()}}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'report':str(out/'REPORT.md'),'validation':validation},ensure_ascii=False))
