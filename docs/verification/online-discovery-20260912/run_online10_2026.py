import asyncio,json,sqlite3,sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from app.config import get_settings
from app.services.legal_browser import SupabaseLegalStore
from app.services.deep_research import build_research_plan,run_deep_research
s=get_settings();root=Path('tmp')/('online10-rerun-'+str(time.time_ns()));root.mkdir(parents=True);cases=json.loads(Path(__file__).with_name('online10-2026-cases.json').read_text(encoding='utf-8'))
store=SupabaseLegalStore(url=s.SUPABASE_URL,publishable_key=s.SUPABASE_PUBLISHABLE_KEY)
async def main():
 for case in cases:
  started=time.perf_counter()
  with sqlite3.connect('file:'+str(s.V3_CONTENT_STORE_PATH)+'?mode=ro',uri=True) as c:
   local=c.execute('SELECT document_id FROM metadata WHERE document_number = ? COLLATE NOCASE',(case['reference_number'],)).fetchall()
  try:remote=await asyncio.to_thread(store.search,case['reference_number'],limit=20)
  except Exception as err:remote={'error':type(err).__name__}
  out={**case,'local_reference_ids':[x[0] for x in local],'supabase_reference_ids':remote,'absence_verified':not local and remote==[]}
  if out['absence_verified']:
   plan=build_research_plan(case['question']);result=await run_deep_research(plan);out['plan']=plan.model_dump(mode='json');out['result']=result.model_dump(mode='json')
  out['elapsed_seconds']=round(time.perf_counter()-started,3)
  (root/('online10-2026-'+case['id']+'.json')).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
  print(case['id'],'absent',out['absence_verified'],'status',out.get('result',{}).get('status'),'sources',sum(len(x['sources']) for x in out.get('result',{}).get('steps',[])),flush=True)
asyncio.run(main())
