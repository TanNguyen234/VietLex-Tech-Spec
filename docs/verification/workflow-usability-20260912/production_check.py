import json,hashlib,subprocess,datetime
from pathlib import Path
import truststore
truststore.inject_into_ssl()
import httpx
base='https://vietlex-legal-rag.vercel.app'
root=Path('tmp/workflow-usability-20260912')
state=json.loads(Path('tmp/online-evidence-20260912/api-state.json').read_text())
delivery=json.loads((root/'delivery-result.json').read_text())
cookies=httpx.Cookies()
for c in json.loads(Path('tmp/live-api-af8c9f5/cookies.json').read_text()):
    cookies.set(c['name'],c['value'],domain=c['domain'],path=c['path'])
checks=[]
with httpx.Client(cookies=cookies,timeout=120,follow_redirects=False) as client:
    paths=['/healthz','/readyz','/','/search?q=45%2F2019%2FQH14','/evaluation-lab',state['workspace'],state['workspace']+'/sources/cdb49180-70b6-447a-a233-9476b4ce1c5e',delivery['new_report']]
    for path in paths:
        r=client.get(base+path)
        item={'path':path,'status':r.status_code,'sha256':hashlib.sha256(r.content).hexdigest(),'cache_control':r.headers.get('cache-control')}
        if '/sources/' in path: item['saved_reader_rendered']='data-saved-analysis' in r.text
        if '/reports/' in path: item['report_preview_rendered']='report-paper' in r.text
        if path==state['workspace']: item['source_library_rendered']='source-library-card' in r.text
        checks.append(item);print(path,r.status_code,flush=True)
    for path in ['app/static/css/research-workflow.css','app/static/js/workflow-controls.js','app/static/favicon.svg']:
        r=client.get(base+'/'+path.removeprefix('app/'))
        expected=subprocess.check_output(['git','-c','safe.directory=D:/Download/ProfessionalLegalRAG','show','HEAD:'+path])
        package=Path('tmp/product-deploy-workflow-final',path).read_bytes()
        checks.append({'path':path,'status':r.status_code,'package_byte_match':r.content==package,'git_text_match_after_crlf_normalization':r.content.replace(b'\r\n',b'\n')==expected,'sha256':hashlib.sha256(r.content).hexdigest(),'git_blob_sha256':hashlib.sha256(expected).hexdigest()})
result={'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base_url':base,'checks':checks,'new_ai_calls':0,'mutations':0}
(root/'production-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
assert all(c['status']==200 for c in checks),checks
assert all(c.get('package_byte_match',True) and c.get('git_text_match_after_crlf_normalization',True) for c in checks)
assert all(c.get('saved_reader_rendered',True) and c.get('report_preview_rendered',True) and c.get('source_library_rendered',True) for c in checks)
