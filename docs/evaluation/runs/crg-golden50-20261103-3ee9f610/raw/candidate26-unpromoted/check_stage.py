import hashlib,json,os,re,subprocess
from pathlib import Path
from urllib.parse import urlsplit
p=Path(__file__).resolve().parent
root=Path.cwd();bundle=Path((p/"bundle-path.txt").read_text(encoding="utf-8").strip())
cli=["C:/Program Files/nodejs/node.exe","D:/Download/AntigravityData/npm-cache/_npx/69f9afb961c37556/node_modules/vercel/dist/index.js"]
env={**os.environ,"NODE_USE_SYSTEM_CA":"1","CI":"1"}
d=json.loads((p/"stage-deployment.json").read_text());url=d["url"]
u=urlsplit(url);assert u.scheme=="https" and u.netloc.endswith(".vercel.app") and not u.path
assert d["readyState"]=="READY" and d["target"]=="production"
r=subprocess.run(cli+["api","/v13/deployments/"+d["id"],"--method","GET","--raw","--scope","foxys-projects-5fe642e0","--non-interactive"],cwd=bundle,env=env,capture_output=True,text=True,encoding="utf-8",timeout=90)
assert r.returncode==0,r.stderr[-500:]
x=json.loads(r.stdout)
safe={k:x.get(k) for k in ("id","url","projectId","target","readyState","createdAt","ready","autoAssignCustomDomains")}
safe["source_metadata"]={k:x.get("meta",{}).get(k) for k in ("sourceSnapshotSha256","sourceManifestSha256","sourceUploadSha256","sourceDirty")}
(p/"deployment-inspect.json").write_text(json.dumps(safe,indent=2),encoding="utf-8")
assert safe["projectId"]=="prj_PZ1anb4DLevoKHI0ZRT39DtWCLrw" and safe["readyState"]=="READY",safe
checks={}
for name,path in (("health","/healthz"),("ready","/readyz"),("home","/"),("admin_auth_gate","/admin")):
 args=cli+["curl",path,"--deployment",url,"--scope","foxys-projects-5fe642e0","--","--silent","--show-error","--max-time","90","--write-out","\n%{http_code}"]
 r=subprocess.run(args,cwd=bundle,env=env,capture_output=True,text=True,encoding="utf-8",timeout=120)
 assert r.returncode==0,r.stderr[-500:]
 body,status=r.stdout.rsplit("\n",1);status=int(status.strip())
 checks[name]={"http_status":status,"body_sha256":hashlib.sha256(body.encode()).hexdigest(),"body_length":len(body)}
 if name in ("health","ready"):
  payload=json.loads(body)
  (p/("stage-"+name+".json")).write_text(json.dumps(payload,indent=2),encoding="utf-8")
  assert status==200,(name,status,payload)
  if name=="health":
   expected=json.loads((p/"expected-runtime.json").read_text())["app_source_sha256"]
   assert payload["identity"]["app_source_sha256"]==expected,"Runtime source hash mismatch"
   assert payload["identity"]["deployment_id"]==d["id"],"Wrong deployment response"
  else:
   assert payload["status"]=="ready" and payload["runtime"]["retrieval_backend"]=="vertex-qdrant-v3"
   assert payload["runtime"]["serverless_online_only"] is True
 elif name=="home":
  match=re.search(r"<title>(.*?)</title>",body,re.S|re.I)
  checks[name]["title"]=match.group(1).strip() if match else None
  assert status==200 and "VietLex" in body
 else:
  assert status in (401,403),"Admin must reject anonymous requests"
(p/"stage-smoke.json").write_text(json.dumps({"passed":True,"deployment_id":d["id"],"url":url,"checks":checks},indent=2),encoding="utf-8")
print(json.dumps({"passed":True,"deployment_id":d["id"],"checks":checks},ensure_ascii=True))
