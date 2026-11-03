import sys,asyncio,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path.cwd()))
from app.config import Settings
from pydantic import SecretStr
from motor.motor_asyncio import AsyncIOMotorClient
class QA(Settings):
 PRODUCTION_AUDIT_ADMIN_EMAIL:SecretStr|None=None
 PRODUCTION_AUDIT_USER_EMAIL:SecretStr|None=None
async def main():
 folder=Path(sys.argv[1]);s=QA();client=AsyncIOMotorClient(s.MONGO_URL,serverSelectionTimeoutMS=9000,socketTimeoutMS=9000);db=client.get_default_database();rows=[]
 try:
  admin=await db.users.find_one({'email':s.PRODUCTION_AUDIT_ADMIN_EMAIL.get_secret_value()},{'_id':1});user=await db.users.find_one({'email':s.PRODUCTION_AUDIT_USER_EMAIL.get_secret_value()},{'_id':1});assert admin and user
  for case in json.loads((folder/'receipts.json').read_text())['cases']:
   trace=await db.evaluation_logs.find_one({'_id':case['trace_id'],'user_id':str(admin['_id'])},{'request_metadata':1,'metrics':1,'contexts':1,'retrieval_trace':1,'guardrail_state':1,'bot_response':1});assert trace is not None
   foreign=await db.evaluation_logs.count_documents({'_id':case['trace_id'],'user_id':str(user['_id'])});stages=(trace.get('retrieval_trace') or {}).get('context_stages',[]);prompt=next((x.get('sha256',[]) for x in reversed(stages) if x['stage']=='prompt'),[])
   metrics=trace.get('metrics') or {};hashes=[hashlib.sha256(x.encode()).hexdigest() for x in trace.get('contexts',[])];calls=metrics.get('llm_calls') or [];usage=metrics.get('provider_usage') or {}
   answer=(folder/(case['id']+'-answer.txt')).read_text(encoding='utf-8');response=trace.get('bot_response') or ''
   rows.append({'case':case['id'],'owner_record_found':True,'foreign_owner_count':foreign,'request_status':metrics.get('request_status'),'contexts_match_prompt':hashes==prompt,'context_count':len(hashes),'saved_answer_matches_HTTP':answer.strip()==response.strip(),'provider':metrics.get('observed_provider'),'model':metrics.get('observed_model'),'guardrail_engine':(trace.get('request_metadata') or {}).get('guardrail_engine'),'provider_calls':calls,'provider_usage':usage,'guardrail_state':trace.get('guardrail_state')})
  day=datetime.now(timezone.utc).strftime('%Y-%m-%d');record=await db.demo_usage.find_one({'_id':'auth:'+day},{'count':1,'subjects':1}) or {};subjects=record.get('subjects',{})
  result={'evidence':'live readonly Mongo verification of the just-completed public HTTP cases','database_name_sha256':hashlib.sha256(db.name.encode()).hexdigest(),'mutations':0,'cases':rows,'auth_window':{'UTC_date':day,'count':record.get('count'),'subjects':len(subjects),'max_personal':max(subjects.values(),default=0),'cap_unchanged':{'personal':15,'global':200}}}
  (folder/'database-roundtrip.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8');print(json.dumps({'cases':len(rows),'hashes_match':all(x['contexts_match_prompt'] for x in rows),'saved_answers_match_HTTP':all(x['saved_answer_matches_HTTP'] for x in rows),'foreign_records':sum(x['foreign_owner_count'] for x in rows),'auth_window':result['auth_window']}))
 finally:client.close()
asyncio.run(main())
