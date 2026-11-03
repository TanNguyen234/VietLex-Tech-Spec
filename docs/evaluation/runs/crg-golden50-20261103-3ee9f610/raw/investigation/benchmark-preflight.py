import sys,json,os,subprocess,uuid,hashlib
from pathlib import Path
r=Path.cwd();w=Path(__file__).parent
sys.path.insert(0,str(r))
from app.config import Settings
s=Settings();(w/'provider-presence.json').write_text(json.dumps({'QDRANT_URL':bool(s.QDRANT_URL),'QDRANT_API_KEY':bool(s.QDRANT_API_KEY),'SUPABASE_URL':bool(s.SUPABASE_URL),'SUPABASE_PUBLISHABLE_KEY':bool(s.SUPABASE_PUBLISHABLE_KEY),'Vertex_project_configured':bool(s.GOOGLE_CLOUD_PROJECT),'credential_values_saved':False},indent=2))
run='answer-golden50-preflight-20261103-'+uuid.uuid4().hex[:8]
cmd=[sys.executable,'run_answer_eval.py','--dataset','docs/evaluation/golden50-v3/cases.json','--sidecar','docs/evaluation/golden50-v3/labels.json','--backend','production','--ranking','rrf-dbsf','--profile','separated_intent','--rewrite','off','--guardrails','enforce','--reranker','current','--concurrency','1','--gold-policy','none','--judge','none','--case-ids','case_001','--run-id',run]
env={**os.environ,'SERVERLESS_ONLINE_ONLY':'true','USE_LEGACY_FREE_PIPELINE':'false','APP_ENV':'development','LOGFIRE_TOKEN':''}
(w/'benchmark-preflight-command.json').write_text(json.dumps({'argv':cmd,'env_overrides':{k:env[k] for k in ['SERVERLESS_ONLINE_ONLY','USE_LEGACY_FREE_PIPELINE','APP_ENV','LOGFIRE_TOKEN']},'run_id':run,'evidence':'live local execution of production chat service; real remote providers; not deployed HTTP'},indent=2))
with (w/'benchmark-preflight.log').open('wb') as f:x=subprocess.run(cmd,cwd=r,env=env,stdout=f,stderr=subprocess.STDOUT)
(w/'benchmark-preflight-exit.json').write_text(json.dumps({'exit_code':x.returncode,'run_id':run},indent=2));print('PREFLIGHT '+str(x.returncode)+' '+run,flush=True)
sys.exit(x.returncode)
