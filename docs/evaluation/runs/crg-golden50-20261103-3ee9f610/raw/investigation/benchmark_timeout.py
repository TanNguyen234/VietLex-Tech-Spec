from pathlib import Path
import os,sys,json,hashlib,subprocess,uuid,time
r=Path.cwd();w=Path(__file__).parent;run='answer-golden50-production-timeout20-20261103-'+uuid.uuid4().hex[:8]
assert json.loads((r/'.tmp-finish-real-20261030/cycle26/full-result.json').read_text())['status']=='PASS'
files={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for d in ('app','tests','guardrails_config') for p in (r/d).rglob('*') if p.is_file() and p.suffix in {'.py','.html','.js','.css','.json','.cjs','.yml','.co'} and '__pycache__' not in p.parts}
for n in ['pyproject.toml','uv.lock','requirements-demo.lock','vercel.json','pytest.ini','.vercelignore','.env.example','AGENTS.md','.codex/config.toml','.code-review-graphignore','run_answer_eval.py','run_retrieval_eval.py']:files[n]=hashlib.sha256((r/n).read_bytes()).hexdigest()
cmd=[sys.executable,'-u','run_answer_eval.py','--dataset','docs/evaluation/golden50-v3/cases.json','--sidecar','docs/evaluation/golden50-v3/labels.json','--backend','production','--ranking','rrf-dbsf','--profile','separated_intent','--rewrite','off','--guardrails','enforce','--reranker','current','--concurrency','2','--gold-policy','none','--judge','none','--run-id',run]
env={**os.environ,'SERVERLESS_ONLINE_ONLY':'true','USE_LEGACY_FREE_PIPELINE':'false','APP_ENV':'development','LOGFIRE_TOKEN':'','LOGFIRE_IGNORE_NO_CONFIG':'1','PYTHONUNBUFFERED':'1'}
diff=subprocess.run(['git','diff','--binary','HEAD'],capture_output=True,check=True).stdout
receipt={'run_id':run,'evidence':'live local execution of pinned production chat service with real Vertex/Qdrant/Supabase and direct input/output guards; not deployed HTTP','argv':cmd,'source_files_sha256':files,'git_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'git_dirty':True,'git_diff_sha256':hashlib.sha256(diff).hexdigest(),'git_diff_hash_contract':'literal git diff --binary HEAD tracked workingtree bytes; distinct from evaluator redacted whole-workingtree provenance','evaluator_provenance_limit':'public .env.example.patch artifact filenames are conservatively sensitive, so evaluator own git_diff_status redacted; companion tracked diff hash and explicit source snapshot supplied without relaxing sensitive path rules','dataset_sha256':hashlib.sha256((r/'docs/evaluation/golden50-v3/cases.json').read_bytes()).hexdigest(),'sidecar_sha256':hashlib.sha256((r/'docs/evaluation/golden50-v3/labels.json').read_bytes()).hexdigest(),'env_overrides':{k:env[k] for k in ['SERVERLESS_ONLINE_ONLY','USE_LEGACY_FREE_PIPELINE','APP_ENV','LOGFIRE_TOKEN','LOGFIRE_IGNORE_NO_CONFIG']},'judge':'none','guardrails':'enforce','cases':50,'concurrency':2}
sys.path.insert(0,str(r))
from app.config import Settings
receipt['guardrail_timeout_seconds']=Settings().GUARDRAIL_TIMEOUT_SECONDS
assert receipt['guardrail_timeout_seconds']==20.0
(w/'benchmark-timeout-command.json').write_text(json.dumps(receipt,indent=2));print('START '+run,flush=True)
start=time.monotonic()
with (w/'benchmark-timeout.log').open('wb') as f:x=subprocess.run(cmd,cwd=r,env=env,stdout=f,stderr=subprocess.STDOUT)
bad=[n for n,h in files.items() if hashlib.sha256((r/n).read_bytes()).hexdigest()!=h]
(w/'benchmark-timeout-exit.json').write_text(json.dumps({'run_id':run,'exit_code':x.returncode,'seconds':time.monotonic()-start,'source_mismatches':bad,'snapshot_files':len(files)},indent=2));print('DONE '+str(x.returncode)+' '+run+' source_mismatches='+str(bad),flush=True)
assert not bad
sys.exit(x.returncode)
