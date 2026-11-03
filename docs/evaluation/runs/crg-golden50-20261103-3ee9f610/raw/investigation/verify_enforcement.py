import json,sys
from pathlib import Path
p=Path(sys.argv[1]);cases=json.loads((p/'receipts.json').read_text())['cases'];assert len(cases)==8
rows=[]
for case in cases:
 t=json.loads((p/(case['id']+'-trace.json')).read_text(encoding='utf-8'));g=t['guardrail_state']
 row={'id':case['id'],'http':case['status'],'cached':t.get('cached'),'guardrail_state':g,'request_status':t.get('request_status')}
 row['passed']=case['status']==200 and t.get('cached') is False and g['mode']=='enforce' and g['requested'] is True and g['executed'] is True and g['status']=='passed' and all(g['stages'][s]['status']=='passed' and g['stages'][s]['safe'] is True for s in ['input','output'])
 rows.append(row)
controls=json.loads((p/'guard-controls.json').read_text())
result={'evidence':'live public HTTP retrieval trace; model judgment is not legal-currentness certification','cases':rows,'passed_cases':sum(x['passed'] for x in rows),'controls':controls,'all_pass':all(x['passed'] for x in rows+controls)}
(p/'guardrails-verified.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passed_cases':result['passed_cases'],'controls':len(controls),'all_pass':result['all_pass']}));assert result['all_pass']
