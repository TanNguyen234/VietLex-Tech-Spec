import json,os,subprocess,sys
from pathlib import Path
p=Path(__file__).resolve().parent;bundle=Path((p/"bundle-path.txt").read_text(encoding="utf-8").strip())
cli=["C:/Program Files/nodejs/node.exe","D:/Download/AntigravityData/npm-cache/_npx/69f9afb961c37556/node_modules/vercel/dist/index.js"]
env={**os.environ,"NODE_USE_SYSTEM_CA":"1","CI":"1"}
assert json.loads((p/"stage-smoke.json").read_text())["passed"] is True
candidate=json.loads((p/"stage-deployment.json").read_text())
inspection=json.loads((p/"deployment-inspect.json").read_text())
assert candidate["id"]==inspection["id"] and inspection["target"]=="production" and inspection["readyState"]=="READY"
assert inspection["projectId"]=="prj_PZ1anb4DLevoKHI0ZRT39DtWCLrw"
r=subprocess.run(cli+["api","/v4/aliases/vietlex-legal-rag.vercel.app","--method","GET","--raw","--scope","foxys-projects-5fe642e0","--non-interactive"],cwd=bundle,env=env,capture_output=True,text=True,encoding="utf-8",timeout=90)
assert r.returncode==0,r.stderr[-500:]
x=json.loads(r.stdout);current={k:x.get(k) for k in ("alias","deploymentId","projectId","createdAt")}
(p/"primary-alias-pre-promote.json").write_text(json.dumps(current,indent=2),encoding="utf-8")
before=json.loads((p/"primary-alias-before.json").read_text())
assert current["projectId"]==inspection["projectId"] and current["deploymentId"]==before["deploymentId"],"Primary changed concurrently"
args=cli+["promote",candidate["url"],"--yes","--timeout","3m","--scope","foxys-projects-5fe642e0","--non-interactive"]
(p/"promote-command.json").write_text(json.dumps({"argv":args,"cwd":str(bundle)},indent=2),encoding="utf-8")
with (p/"promote.stdout.log").open("wb") as out,(p/"promote.stderr.log").open("wb") as err:
 r=subprocess.run(args,cwd=bundle,env=env,stdout=out,stderr=err,timeout=240)
print(json.dumps({"exit_code":r.returncode,"promoted_candidate":candidate["id"]}))
sys.exit(r.returncode)
