import json,subprocess,os,hashlib
from pathlib import Path
w=Path(__file__).parent;r=Path('.tmp-finish-real-20261030/cycle27');d=json.loads((r/'stage-deployment.json').read_text());bundle=(r/'bundle-path.txt').read_text().strip()
cmd=['C:/Program Files/nodejs/node.exe','D:/Download/AntigravityData/npm-cache/_npx/69f9afb961c37556/node_modules/vercel/dist/index.js','logs',d['id'],'--level','error','--since','1h','--json','--limit','50','--scope','foxys-projects-5fe642e0','--non-interactive']
x=subprocess.run(cmd,cwd=bundle,capture_output=True,timeout=120,env={**os.environ,'NODE_USE_SYSTEM_CA':'1','CI':'1'});parsed=[];other=0
for line in x.stdout.decode('utf-8','replace').splitlines():
 try:parsed.append(json.loads(line))
 except ValueError:other+=1
row={'evidence':'live_readonly_vercel_log_query','command':cmd,'exit_code':x.returncode,'deployment_id':d['id'],'stdout_bytes':len(x.stdout),'stdout_sha256':hashlib.sha256(x.stdout).hexdigest(),'stderr_bytes':len(x.stderr),'stderr_sha256':hashlib.sha256(x.stderr).hexdigest(),'JSON_records':len(parsed),'non_JSON_lines':other,'record_schemas':[sorted(v) for v in parsed if isinstance(v,dict)],'limit':50,'window':'1h','filter':'error','raw_message_persisted':False,'privacy':'raw logs held only in memory, hash/structure retained','limits':'No returned error records is bounded observability only; not legal quality or exhaustive monitoring proof; drains NOT RUN'}
(w/'log-scan.json').write_text(json.dumps(row,indent=2));print(json.dumps(row))
