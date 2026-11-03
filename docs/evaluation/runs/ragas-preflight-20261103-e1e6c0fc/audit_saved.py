"""Explicit opt-in Ragas audit of immutable saved answers; no generation/DB writes."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,asyncio,json,hashlib,math,sys,time,uuid,os,inspect,importlib.metadata,shutil
sys.path.insert(0,str(Path.cwd()))
os.environ['LOGFIRE_TOKEN']=''
import logfire
logfire.configure(send_to_logfire=False,console=False)
from app.config import Settings
from app.evaluation.case_selection import build_cases
from run_eval_suite import _install_ragas_vertex_shim,_build_vertex_ragas_llm
_install_ragas_vertex_shim()
from ragas.metrics.collections import Faithfulness,AnswerAccuracy,ContextPrecision,ContextRecall
from app.services.vertex_ai import close_vertex_provider
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,data):
 with p.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
async def main():
 parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--limit',type=int,choices=[1,50],default=1);args=parser.parse_args()
 r=Path.cwd();w=Path(__file__).parent;s=Settings();parent=r/'docs/evaluation/runs/answer-golden50-offline-metrics33-20261103-2349369e'
 cases=build_cases(json.loads((r/'docs/evaluation/golden50-v3/cases.json').read_text(encoding='utf-8')),{});references={x.case_id:x for x in cases};data=json.loads((parent/'answer_results.json').read_text(encoding='utf-8'))[:args.limit]
 assert not s.USE_LEGACY_FREE_PIPELINE and len(data)==args.limit
 preflight={'versions':{n:importlib.metadata.version(n) for n in ['ragas','instructor','google-genai']},'metric_signatures':{c.__name__:str(inspect.signature(c.ascore)) for c in [Faithfulness,AnswerAccuracy,ContextPrecision,ContextRecall]},'vertex_project_present':bool(s.GOOGLE_CLOUD_PROJECT),'vertex_model':s.VERTEX_LLM_MODEL,'legacy_free':s.USE_LEGACY_FREE_PIPELINE,'provider_http_attempt_limit':s.PROVIDER_HTTP_ATTEMPT_LIMIT,'source_rows':len(data),'secret_values_retained':False,'live_opt_in':args.live}
 print(json.dumps(preflight),flush=True)
 if not args.live:return
 run=('ragas-preflight' if args.limit==1 else 'ragas-golden50')+'-20261103-'+uuid.uuid4().hex[:8];out=r/'docs/evaluation/runs'/run;out.mkdir(exist_ok=False);(w/'latest-run-path.txt').write_text(str(out),encoding='utf-8')
 snapshot=json.loads((r/'.tmp-finish-real-20261030/cycle27/source-before-full.json').read_text());assert all(sha(r/f)==h for f,h in snapshot.items())
 config={'mode':'live_judge_on_saved_answers','parent_run':parent.name,'parent_answer_results_sha256':sha(parent/'answer_results.json'),'metrics':['faithfulness','answer_accuracy','context_precision','context_recall'],'judge_provider':'google_vertex_ai','judge_model_requested':s.VERTEX_LLM_MODEL,'fallback':False,'case_concurrency':2,'max_simultaneous_llm_requests':4,'metric_deadline_seconds':300,'empty_context_policy':'skip context-dependent metrics; score answer_accuracy','independence':'same model family as generator; secondary audit, not independent legal approval','runtime_source_sha256':snapshot,'preflight':preflight}
 diff=__import__('subprocess').run(['git','diff','--binary','HEAD'],capture_output=True,check=True).stdout
 write(out/'configuration.json',config);write(out/'manifest.json',{'run_id':run,'created_at':datetime.now(timezone.utc).isoformat(),'git_sha':__import__('subprocess').check_output(['git','rev-parse','HEAD'],text=True).strip(),'git_dirty':True,'git_diff_sha256':hashlib.sha256(diff).hexdigest(),'git_diff_hash_contract':'literal tracked git diff --binary HEAD','dataset_sha256':sha(r/'docs/evaluation/golden50-v3/cases.json'),'labels_sha256':sha(r/'docs/evaluation/golden50-v3/labels.json'),'configuration_fingerprint':hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),'command':__import__('subprocess').list2cmdline([sys.executable,*sys.argv]),'provider_model_ids':['google_vertex_ai/'+s.VERTEX_LLM_MODEL],'metric_version':'ragas-'+preflight['versions']['ragas'],'evidence':'live judge; saved unchanged responses and contexts; no online retrieval/generation/guard rerun; no DB access'})
 shutil.copy2(__file__,out/'audit_saved.py');write(out/'source-case-hashes.json',[{'case_id':x['case_id'],'response_sha256':hashlib.sha256(x['final_response'].encode()).hexdigest(),'context_sha256':[hashlib.sha256(t.encode()).hexdigest() for t in x['prompt_contexts']]} for x in data])
 sem=asyncio.Semaphore(4);calls=[];base=_build_vertex_ragas_llm()
 class MeasuredLLM(type(base)):
  async def agenerate(self,prompt,response_model):
   async with sem:
    start=time.monotonic();row={'provider_binding':'google_vertex_ai','model_requested':s.VERTEX_LLM_MODEL,'response_model':response_model.__name__,'success':False,'tokens':'UNKNOWN; production structured adapter does not expose raw response usage'}
    try:result=await super().agenerate(prompt,response_model);row['success']=True;return result
    except Exception as error:row['error_kind']=type(error).__name__;raise
    finally:row['latency_seconds']=round(time.monotonic()-start,4);calls.append(row)
 llm=MeasuredLLM();metrics={'faithfulness':Faithfulness(llm=llm),'answer_accuracy':AnswerAccuracy(llm=llm),'context_precision':ContextPrecision(llm=llm),'context_recall':ContextRecall(llm=llm)};case_sem=asyncio.Semaphore(2)
 async def case(row):
  async with case_sem:
   ref=references[row['case_id']];result={'case_id':row['case_id'],'metrics':{},'evidence':'live_judge','answer_sha256':hashlib.sha256(row['final_response'].encode()).hexdigest()}
   for name,metric in metrics.items():
    if name!='answer_accuracy' and not row['prompt_contexts']:result['metrics'][name]={'status':'skipped','reason':'no_prompt_contexts','value':None};continue
    kw={'user_input':ref.question}
    if name in {'faithfulness','answer_accuracy'}:kw['response']=row['final_response']
    if name!='faithfulness':kw['reference']=ref.reference_answer
    if name!='answer_accuracy':kw['retrieved_contexts']=row['prompt_contexts']
    t=time.monotonic()
    try:
     value=float((await asyncio.wait_for(metric.ascore(**kw),timeout=300)).value)
     if not math.isfinite(value) or not 0<=value<=1:raise ValueError('nonfinite_or_out_of_range_metric')
     result['metrics'][name]={'status':'ok','value':value,'seconds':round(time.monotonic()-t,4)}
    except Exception as error:result['metrics'][name]={'status':'error','value':None,'error_kind':type(error).__name__,'seconds':round(time.monotonic()-t,4)}
   write(out/(row['case_id']+'.json'),result);print('CASE '+row['case_id']+' '+json.dumps(result['metrics']),flush=True);return result
 try:results=await asyncio.gather(*(case(x) for x in data))
 finally:await close_vertex_provider()
 summary={}
 for name in metrics:
  scored=[x['metrics'][name]['value'] for x in results if x['metrics'][name]['status']=='ok'];skipped=[x['metrics'][name] for x in results if x['metrics'][name]['status']=='skipped'];errors=[x['case_id'] for x in results if x['metrics'][name]['status']=='error']
  summary[name]={'mean':sum(scored)/len(scored) if scored else None,'numerator':sum(scored),'denominator':len(scored),'total_cases':len(results),'coverage':len(scored)/len(results),'skipped':len(skipped),'skip_reasons':{'no_prompt_contexts':len(skipped)} if skipped else {},'technical_errors':errors}
 assert all(sha(r/f)==h for f,h in snapshot.items())
 write(out/'results.json',results);write(out/'summary.json',summary);write(out/'judge-call-ledger.json',calls)
 report='# Ragas audit of saved Golden50 answers\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n\nSame model family as generator; secondary evidence only. No independent human legal sign-off. No new answers/contexts or DB writes. Token usage/model response version UNKNOWN at this adapter boundary.\n'
 (out/'REPORT.md').write_text(report,encoding='utf-8');write(out/'files-sha256.json',{f.name:sha(f) for f in out.iterdir() if f.is_file()});print('COMPLETE '+run+' '+json.dumps(summary),flush=True)
 if any(v['technical_errors'] for v in summary.values()):sys.exit(2)
if __name__=='__main__':asyncio.run(main())
