"""Real services only. Expected URLs are used for scoring, never query construction."""
import asyncio, hashlib, json, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from app.services.official_query_planner import prepare_research_plan
from app.services.deep_research import run_deep_research
from app.services.trusted_source_reader import read_source, SourceReadError

def sha(data): return hashlib.sha256(data).hexdigest()
def git(*args): return subprocess.check_output(['git','-c','safe.directory=D:/Download/ProfessionalLegalRAG',*args])
def write(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
async def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=Path('docs/evaluation/runs')/('official-online-'+stamp)
    out.mkdir()
    cases=json.loads(Path('docs/verification/online-discovery-20260912/online10-2026-cases.json').read_text(encoding='utf-8'))
    cases+=json.loads(Path('tmp/online-evidence-20260912/holdout.json').read_text(encoding='utf-8'))
    write(out/'cases.json',cases)
    config={'page_limit':2,'native_then_explicit_ocr':True,'expected_url_used_for_search':False,'legal_completeness':'not assessed','internal_absence':'first 10 independently scanned; holdout absence NOT RUN','mocks':False}
    manifest={'started_at':stamp,'git_sha':git('rev-parse','HEAD').decode().strip(),'git_dirty':bool(git('status','--porcelain','--untracked-files=no')),'git_diff_sha256':sha(git('diff','HEAD')),'configuration':config,'configuration_fingerprint':sha(json.dumps(config,sort_keys=True).encode()),'dataset_sha256':sha((out/'cases.json').read_bytes()),'command':'.venv/Scripts/python.exe tmp/online-evidence-20260912/run_acceptance.py','metric_version':'official-discovery-readable-window-v1','source_hashes':{str(p):sha(p.read_bytes()) for folder in ['app/services','app/api'] for p in Path(folder).glob('*.py')}}
    write(out/'manifest.json',manifest)
    rows=[]
    print('RUN',out,flush=True)
    for case in cases:
        start=time.monotonic()
        plan=await prepare_research_plan(case['question'])
        result=await run_deep_research(plan)
        urls={s.url for step in result.steps for s in step.sources}
        hit=case['reference_url'] in urls
        record={'case':case,'plan':plan.model_dump(mode='json'),'result':result.model_dump(mode='json'),'expected_url_hit':hit}
        if hit:
            try:
                source=await read_source(case['reference_url'],page_limit=2)
                if source.get('requires_ocr'):
                    source=await read_source(case['reference_url'],use_ocr=True,page_limit=2)
                record['source']=source
            except SourceReadError as error: record['read_error']=error.kind
        else: record['read_skipped']='expected source not discovered'
        record['elapsed_seconds']=time.monotonic()-start
        write(out/(case['id']+'.json'),record)
        source=record.get('source',{})
        row={'id':case['id'],'hit':hit,'readable':source.get('content_status')=='readable','pages_read':len(source.get('pages',[])),'total_pages':source.get('page_count'),'error':record.get('read_error'),'query_method':plan.query_method}
        rows.append(row);print(json.dumps(row),flush=True)
    write(out/'summary.json',rows)
    write(out/'completed.json',{'completed_at':datetime.now(timezone.utc).isoformat(),'files':{p.name:sha(p.read_bytes()) for p in out.glob('*.json')}})
asyncio.run(main())
