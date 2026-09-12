import asyncio,sys,json,hashlib,time
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path.cwd()))
from app.evaluation.retrieval_backends import get_vertex_qdrant_retriever
async def main():
 r=get_vertex_qdrant_retriever();root=Path('docs/verification/online-discovery-20260912')
 cases=json.loads((root/'online10-2026-cases.json').read_text(encoding='utf-8'))
 targets={c['reference_number'].upper():[] for c in cases};count=missing=pages=0;offset=None;digest=hashlib.sha256()
 started=datetime.now(timezone.utc).isoformat()
 try:
  while True:
   points,offset=await r.client.scroll(r.contract.collection_name,limit=1000,offset=offset,with_payload=['document_number'],with_vectors=False)
   pages+=1
   for point in points:
    number=str((point.payload or {}).get('document_number','')).strip().upper();count+=1;missing+=not bool(number)
    digest.update((str(point.id)+'|'+number+'\n').encode())
    if number in targets:targets[number].append(str(point.id))
   if pages%25==0:print('scanned',count,flush=True)
   if offset is None:break
  out={'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),'collection':r.contract.collection_name,'method':'unfiltered scroll, all pages, document_number payload only, no vectors','points_scanned':count,'missing_document_number':missing,'pages':pages,'reached_end':True,'stream_sha256':digest.hexdigest(),'matches':targets}
  destination=Path('tmp')/('qdrant-absence-'+str(time.time_ns())+'.json');destination.parent.mkdir(exist_ok=True)
  destination.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False),flush=True)
 finally:await r.client.close()
asyncio.run(main())
