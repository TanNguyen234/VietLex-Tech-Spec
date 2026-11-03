import hashlib,json,os,stat,subprocess,sys
from pathlib import Path
p=Path(__file__).resolve().parent
root=Path.cwd();bundle=Path((p/"bundle-path.txt").read_text(encoding="utf-8").strip())
assert json.loads((p/"full-result.json").read_text())["status"]=="PASS"
assert json.loads((p/"deploy-dry-validation.json").read_text())["passed"] is True
link=json.loads((bundle/".vercel/project.json").read_text())
assert link["projectId"]=="prj_PZ1anb4DLevoKHI0ZRT39DtWCLrw" and link["orgId"]=="team_s747HDjxGPguw7LFihhRSWlM"
before=json.loads((p/"source-before-full.json").read_text())
assert all(hashlib.sha256((root/f).read_bytes()).hexdigest()==h for f,h in before.items()),"Source changed after full gate"
m=json.loads((p/"release-bundle-manifest-final.json").read_text())
d=json.loads((p/"deploy-dry.json").read_text(encoding="utf-8-sig"))
files=sorted((e["path"].replace("\\","/"),hashlib.sha256((bundle/e["path"]).read_bytes()).hexdigest()) for e in d["files"] if not stat.S_ISDIR(e["mode"]))
app=[(name[4:],digest) for name,digest in files if name.startswith("app/") and Path(name).suffix in {".py",".html",".js",".css",".json",".cjs"}]
expected={"app_source_sha256":hashlib.sha256(json.dumps(app,separators=(",",":")).encode()).hexdigest(),"app_file_count":len(app),"upload_sha256":hashlib.sha256("".join(f"{digest}  {name}\n" for name,digest in files).encode()).hexdigest()}
(p/"expected-runtime.json").write_text(json.dumps(expected,indent=2),encoding="utf-8")
args=["C:/Program Files/nodejs/node.exe","D:/Download/AntigravityData/npm-cache/_npx/69f9afb961c37556/node_modules/vercel/dist/index.js","deploy","--prod","--skip-domain","--yes","--non-interactive","--json","--scope","foxys-projects-5fe642e0","--meta","sourceSnapshotSha256="+m["included_file_list_sha256"],"--meta","sourceManifestSha256="+m["source_baseline"]["manifest_sha256"],"--meta","sourceUploadSha256="+expected["upload_sha256"],"--meta","sourceDirty=true"]
(p/"deploy-command.json").write_text(json.dumps({"argv":args,"cwd":str(bundle)},indent=2),encoding="utf-8")
with (p/"deploy.stdout.json").open("wb") as out,(p/"deploy.stderr.log").open("wb") as err:
 r=subprocess.run(args,cwd=bundle,stdout=out,stderr=err,timeout=600,env={**os.environ,"NODE_USE_SYSTEM_CA":"1","CI":"1"})
print(json.dumps({"exit_code":r.returncode,"stdout_path":str(p/"deploy.stdout.json")}))
sys.exit(r.returncode)
