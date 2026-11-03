from pathlib import Path
import subprocess,json,os,hashlib
w=Path(__file__).parent
cli=['C:/Program Files/nodejs/node.exe','D:/Download/AntigravityData/npm-cache/_npx/69f9afb961c37556/node_modules/vercel/dist/index.js']
cmd=cli+['api','/v10/projects/prj_PZ1anb4DLevoKHI0ZRT39DtWCLrw/env','--method','GET','--raw','--scope','foxys-projects-5fe642e0','--non-interactive']
result=subprocess.run(cmd,cwd=Path.cwd(),capture_output=True,timeout=90,env={**os.environ,'NODE_USE_SYSTEM_CA':'1','CI':'1'})
assert result.returncode==0,'Readonly environment metadata query failed'
data=json.loads(result.stdout);rows=data['envs'];assert isinstance(rows,list) and all(isinstance(x,dict) and 'key' in x for x in rows)
matches=[x for x in rows if x['key']=='GUARDRAIL_TIMEOUT_SECONDS' and 'production' in (x.get('target') or [])]
receipt={'evidence':'live readonly project environment metadata; secret values not emitted/persisted','command':cmd,'exit_code':result.returncode,'schema_root_keys':sorted(data),'env_entries':len(rows),'hiddenProductionEnvCount':data.get('hiddenProductionEnvCount'),'production_guard_timeout_override_present':bool(matches),'matching_entry_metadata':[{'key':x['key'],'target':x.get('target'),'type':x.get('type')} for x in matches],'raw_response_sha256':hashlib.sha256(result.stdout).hexdigest(),'raw_values_retained':False}
(w/'timeout-env-preflight-complete.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt));assert data.get('hiddenProductionEnvCount')==0,'Hidden production environment coverage UNKNOWN; no absence claim'
assert not matches,'Explicit production timeout override needs separate authority; no environment mutation attempted'
