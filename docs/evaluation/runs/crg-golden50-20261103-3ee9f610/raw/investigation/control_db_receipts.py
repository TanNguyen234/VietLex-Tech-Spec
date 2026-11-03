import sys,asyncio,json
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from app.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
 p=Path(sys.argv[1]);s=Settings();client=AsyncIOMotorClient(s.MONGO_URL,serverSelectionTimeoutMS=9000);db=client.get_default_database();rows=[]
 try:
  for control in json.loads((p/'guard-controls.json').read_text()):
   doc=await db.evaluation_logs.find_one({'_id':control['trace_id']},{'contexts':1,'metrics':1,'request_metadata':1,'guardrail_state':1});assert doc
   m=doc.get('metrics') or {};calls=m.get('llm_calls',[])
   rows.append({'id':control['id'],'request_status':m.get('request_status'),'guardrail_state':doc.get('guardrail_state'),'contexts':len(doc.get('contexts',[])),'calls':calls,'engine':(doc.get('request_metadata') or {}).get('guardrail_engine'),'generation_calls':sum(x.get('use_case')=='answer' for x in calls)})
  result={'evidence':'live readonly Mongo negative-control persistence','mutations':0,'rows':rows,'passed':len(rows)==2 and all(x['request_status']=='blocked_input' and x['contexts']==0 and x['generation_calls']==0 and x['engine']=='direct_self_check' for x in rows)}
  (p/'control-database.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passed':result['passed'],'controls':len(rows)}));assert result['passed']
 finally:client.close()
asyncio.run(main())
