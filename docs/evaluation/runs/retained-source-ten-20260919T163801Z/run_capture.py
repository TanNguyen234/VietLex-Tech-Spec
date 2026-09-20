import asyncio,dataclasses,datetime,hashlib,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import truststore
truststore.inject_into_ssl()
from app.services import retained_source_analysis as service
from app.services.clients import close_clients
from app.config import get_settings
root=Path('tmp/continuation-20260919/retained-ten-metadata');root.mkdir(exist_ok=False)
cases=['agriculture','aviation','credit','electricity','health','imports','maritime','procurement','reserves','resources_tax']
source_paths=['app/services/retained_source_analysis.py','app/services/research_analysis.py','app/services/direct_llm.py','app/config.py']
git=['git','-c','safe.directory=D:/Download/ProfessionalLegalRAG']
settings=get_settings()
config={'use_legacy_free_pipeline':settings.USE_LEGACY_FREE_PIPELINE,'vertex_model':settings.VERTEX_LLM_MODEL,'max_output_tokens':4096,'thinking_level':'MINIMAL','max_characters':service.MAX_CHARACTERS,'max_words':service.MAX_WORDS}
manifest={'run_id':root.name,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'git_sha':subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip(),'git_dirty':bool(subprocess.check_output(git+['status','--porcelain','--untracked-files=no'])),'git_diff_sha256':hashlib.sha256(subprocess.check_output(git+['diff','HEAD'])).hexdigest(),'source_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in source_paths},'configuration':config,'configuration_sha256':hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),'command':'.venv/Scripts/python.exe tmp/continuation-20260919/retained_ten_metadata.py','dataset_revision':'captured public official PDF OCR 20260913; original ten questions unchanged','dataset_sha256':{},'metric_version':'retained-source-operational-v1','scope':'real service/provider with captured real OCR; no HTTP route or legal-correctness certification'}
for name in cases:
 for kind,path in [('source',Path('tmp/data-integrity-20260913/full-reading')/name/'result.json'),('question',Path('tmp/selected-context-20260914/ten-live')/(name+'.json'))]:manifest['dataset_sha256'][name+'-'+kind]=hashlib.sha256(path.read_bytes()).hexdigest()
for name in cases:
 for path in sorted((Path('tmp/data-integrity-20260913/full-reading')/name).glob('attempt-*.json')):manifest['dataset_sha256'][name+'-'+path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
(root/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
original=service._generate
observed=[]
async def capture(*args,**kwargs):
 result=await original(*args,**kwargs)
 raw=dataclasses.asdict(result);raw.pop('project',None)
 observed.append({'response':raw,'prompt_sha256':hashlib.sha256(args[0].encode()).hexdigest(),'system_sha256':hashlib.sha256(args[1].encode()).hexdigest()})
 return result
service._generate=capture
async def main():
 for name in cases:
  full=json.loads((Path('tmp/data-integrity-20260913/full-reading')/name/'result.json').read_text(encoding='utf-8'))
  old=json.loads((Path('tmp/selected-context-20260914/ten-live')/(name+'.json')).read_text(encoding='utf-8'))
  assert len(full['document_hashes'])==1 and full['same_document_version']
  reads=[]
  for path in sorted((Path('tmp/data-integrity-20260913/full-reading')/name).glob('attempt-*.json')):
   captured=json.loads(path.read_text(encoding='utf-8'))
   if captured.get('source') and captured['source'].get('document_sha256') in full['document_hashes']:
    reads.append({'analysis_id':path.stem,'kind':'trusted_sources','result':{'sources':[captured['source']]}})
  source=service.collect_retained_source({'analyses':reads},reads[0]['analysis_id'],0)
  assert {str(p['page']):p['text'] for p in source['pages']}==full['full_page_text']
  (root/(name+'-input.json')).write_text(json.dumps({'question':old['question'],'source':source},ensure_ascii=False,indent=2),encoding='utf-8')
  observed.clear();start=time.monotonic()
  try:result=await asyncio.wait_for(service.analyze_retained_source(old['question'],source),180)
  except Exception as e:result={'status':'exception','error_type':type(e).__name__}
  record={'case':name,'result':result,'observed':list(observed),'seconds':time.monotonic()-start,'coverage':{k:source[k] for k in ['page_count','readable_pages','missing_pages','characters','input_sha256']}}
  (root/(name+'-result.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
  print(name,result['status'],len(result.get('citations',[])),flush=True)
 await close_clients()
asyncio.run(main())
