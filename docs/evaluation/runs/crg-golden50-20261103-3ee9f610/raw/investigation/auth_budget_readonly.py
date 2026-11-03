from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
import sys,asyncio,json
sys.path.insert(0,str(Path.cwd()))
from app.config import Settings
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
 s=Settings();assert s.MONGO_URL
 client=AsyncIOMotorClient(s.MONGO_URL,serverSelectionTimeoutMS=s.MONGO_TIMEOUT_MS,connectTimeoutMS=s.MONGO_TIMEOUT_MS,socketTimeoutMS=s.MONGO_TIMEOUT_MS)
 try:
  now=datetime.now(timezone.utc);key='auth:'+now.strftime('%Y-%m-%d')
  record=await client.get_default_database().demo_usage.find_one({'_id':key},{'count':1,'subjects':1}) or {}
  counts=list((record.get('subjects') or {}).values())
  receipt={'evidence':'live readonly daily auth counter aggregate; no index/init/update/reservation/login','observed_utc':now.isoformat(),'window':key,'global_used':record.get('count',0),'global_cap_source':200,'personal_cap_source':15,'subject_count_distribution':dict(Counter(map(int,counts))),'subject_identities_retained':False,'limit':'Distribution does not identify current outbound subject; ordinary HTTP login still governs actual authorization'}
  out=Path(__file__).parent/('auth-budget-'+now.strftime('%H%M%S')+'.json');out.write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
 finally:client.close()
if __name__=='__main__':asyncio.run(main())
