from pathlib import Path
import sys,json,hashlib,httpx,concurrent.futures
from datetime import datetime,timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from pypdf import PdfReader
sys.path.insert(0,str(Path.cwd()))
from app.config import system_ssl_context
from app.services.trusted_source_reader import validate_source_url
w=Path(__file__).parent/'legal';w.mkdir(exist_ok=True)
sources=[('nd136','https://congbao.chinhphu.vn/tai-ve-van-ban-so-136-2025-nd-cp-45098-56797'),('nd05','https://congbao.chinhphu.vn/tai-ve-van-ban-so-05-2025-nd-cp-43838-54238'),('nd08','https://congbao.chinhphu.vn/van-ban/nghi-dinh-so-08-2022-nd-cp-36666.htm'),('vbhn49','https://datafiles.chinhphu.vn/cpp/files/vbpq/2026/4/49-vbhn-bnnmt.pdf')]
def one(pair):
 name,url=pair;row={'id':name,'landing_url':url,'retrieved_utc':datetime.now(timezone.utc).isoformat(),'evidence':'live official primary, no OCR/model'}
 try:
  validate_source_url(url)
  with httpx.Client(verify=system_ssl_context(),timeout=60,follow_redirects=True) as c:
   res=c.get(url);res.raise_for_status();data=res.content
   if data.startswith(b'%PDF'):pdfurl=str(res.url)
   else:
    (w/(name+'-landing.html')).write_bytes(data);links=[urljoin(str(res.url),x.get('href','')) for x in BeautifulSoup(data,'html.parser').select('a[href]') if '.pdf' in x.get('href','').lower()];row['pdf_links']=list(dict.fromkeys(links));assert links,'No PDF links'
    pdfurl=links[0];validate_source_url(pdfurl);res=c.get(pdfurl);res.raise_for_status();data=res.content
   assert data.startswith(b'%PDF') and len(data)<25000000
   pdf=w/(name+'.pdf');pdf.write_bytes(data);reader=PdfReader(pdf);pages=[{'pdf_page':i+1,'text':page.extract_text() or ''} for i,page in enumerate(reader.pages)];(w/(name+'-pages.json')).write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8');(w/(name+'.txt')).write_text('\n'.join(x['text'] for x in pages),encoding='utf-8')
   row.update({'http':res.status_code,'pdf_url':pdfurl,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'pages':len(pages),'chars':sum(len(x['text']) for x in pages),'status':'downloaded'})
 except Exception as e:row.update({'status':'error','error_type':type(e).__name__,'reason':str(e)[:240]})
 (w/(name+'-receipt.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(row,ensure_ascii=True),flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:list(ex.map(one,sources))
