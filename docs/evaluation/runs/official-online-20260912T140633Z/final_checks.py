import sys,asyncio,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path.cwd()))
import httpx
from app.config import system_ssl_context
from app.services.trusted_source_reader import read_source,SourceReadError
out=Path('docs/evaluation/runs/official-online-20260912T140633Z')
async def main():
    case=json.loads((out/'maritime.json').read_text(encoding='utf-8'))['case']
    result={'started_at':datetime.now(timezone.utc).isoformat(),'reason':'Explicit retry of recorded source_transport_error; first attempt retained unchanged.'}
    try: result['source']=await read_source(case['reference_url'],use_ocr=True,page_limit=2)
    except SourceReadError as error: result['error']=error.kind
    (out/'maritime-retry.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    checks=[]
    async with httpx.AsyncClient(verify=system_ssl_context(),timeout=120) as client:
        for path in ['/healthz','/readyz','/static/js/research-workspace.js']:
            r=await client.get('https://vietlex-legal-rag.vercel.app'+path)
            checks.append({'path':path,'status':r.status_code,'sha256':hashlib.sha256(r.content).hexdigest(),'official_reader_present': 'Đọc toàn văn / bản gốc' in r.text if path.endswith('.js') else None})
    (out/'production-smoke.json').write_text(json.dumps(checks,indent=2)+'\n',encoding='utf-8',newline='\n')
    print('retry',result.get('error') or result['source']['content_status'],checks,flush=True)
asyncio.run(main())
