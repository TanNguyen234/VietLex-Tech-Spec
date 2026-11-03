import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import httpx
from app.config import system_ssl_context
out=Path(sys.argv[1]);out.mkdir(exist_ok=False)
with httpx.Client(base_url='https://vietlex-legal-rag.vercel.app',verify=system_ssl_context(),timeout=60,follow_redirects=False) as c:
 r=c.get('/static/js/vietlex.js');expected=hashlib.sha256(Path('app/static/js/vietlex.js').read_bytes()).hexdigest();actual=hashlib.sha256(r.content).hexdigest();receipt={'evidence':'live production static frontend delivery','path':'/static/js/vietlex.js','http':r.status_code,'body_sha256':actual,'local_sha256':expected,'matches_tested_source':actual==expected,'headers':{k:r.headers.get(k) for k in ['content-type','cache-control','etag','age','last-modified']},'limit':'not an authenticated browser interaction; frontend source unchanged in this citation/timeout follow-up, existing behavior covered by Node suite; older sandbox evidence remains historical'};(out/'receipt.json').write_text(json.dumps(receipt,indent=2));assert r.status_code==200 and actual==expected;print(json.dumps(receipt))
