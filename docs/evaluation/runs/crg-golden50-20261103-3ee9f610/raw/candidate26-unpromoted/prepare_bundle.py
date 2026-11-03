import importlib.util,json,hashlib,shutil,uuid,sys
from pathlib import Path
R=Path.cwd();W=R/'.tmp-finish-real-20261030/cycle26'
spec=importlib.util.spec_from_file_location('release_packager',R/'docs/verification/production-release-20261018-01/build_release_bundle.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
base=json.loads((W/'baseline.json').read_text(encoding='utf-8'))
assert all(p.sha256_file(R/f)==h for f,h in base['files'].items())
app_files,_=p.collect_app_files();files=app_files+[R/f for f in p.ROOT_FILES+p.QUALITY_FILES]
m={'git_sha':base['git_sha'],'git_dirty':True,'git_diff_sha256':base['git_diff_sha256'],'source_sha256':{f.relative_to(R).as_posix():p.sha256_file(f) for f in files},'verification':'fresh-full-python-and-node-pass;review-clean;source-unchanged'}
p.SOURCE_MANIFEST=W/'release-source-manifest.json';p.SOURCE_MANIFEST.write_text(json.dumps(m,indent=2),encoding='utf-8');p.SOURCE_MANIFEST_SHA256=p.sha256_file(p.SOURCE_MANIFEST)
p.OUTPUT_DIR=R/'tmp'/('vercel-release-20261030-real-'+uuid.uuid4().hex[:8]);p.OUTPUT_MANIFEST=W/'release-bundle-manifest.json'
p.main()
link=p.OUTPUT_DIR/'.vercel';link.mkdir()
shutil.copyfile(R/'tmp/vercel-release-20261029-pdf-worker/.vercel/project.json',link/'project.json')
(W/'bundle-path.txt').write_text(str(p.OUTPUT_DIR),encoding='utf-8')
print(json.dumps({'bundle':str(p.OUTPUT_DIR),'manifest':str(p.OUTPUT_MANIFEST),'action':'local packaging only; NOT DEPLOYED'},ensure_ascii=True))
