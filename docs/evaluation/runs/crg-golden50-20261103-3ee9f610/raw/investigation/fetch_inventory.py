from pathlib import Path
import sys,json,httpx,hashlib
from datetime import datetime,timezone
from bs4 import BeautifulSoup
sys.path.insert(0,str(Path.cwd()))
from app.config import system_ssl_context
w=Path(__file__).parent/'legal'
with httpx.Client(verify=system_ssl_context(),timeout=25,follow_redirects=True) as c:
 for label,section in [('history','lichsu'),('related','vanbanlienquan')]:
  url='https://vbpl.moj.gov.vn/TW/Pages/vbpq-'+section+'.aspx?ItemID=146609';row={'url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),'evidence':'live public official inventory attempt'}
  try:
   r=c.get(url);row.update({'http':r.status_code,'final_url':str(r.url),'bytes':len(r.content),'sha256':hashlib.sha256(r.content).hexdigest()});(w/('inventory-'+label+'.html')).write_bytes(r.content);s=BeautifulSoup(r.text,'html.parser');(w/('inventory-'+label+'.txt')).write_text(s.get_text(' ',strip=True),encoding='utf-8');row['links']=[{'text':a.get_text(' ',strip=True),'url':a.get('href')} for a in s.select('a[href]') if '/QH' in a.get_text() or '/NĐ' in a.get_text() or '2026' in a.get_text()]
  except Exception as e:row.update({'status':'error','type':type(e).__name__,'reason':str(e)[:160]})
  (w/('inventory-'+label+'-receipt.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(row,ensure_ascii=True)[:1500],flush=True)
