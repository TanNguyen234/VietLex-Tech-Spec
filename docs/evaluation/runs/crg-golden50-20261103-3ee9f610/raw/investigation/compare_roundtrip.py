"""Compare real stored/exported source blocks with recorded prompt hashes."""
import json,re,hashlib,sys
from pathlib import Path
from bs4 import BeautifulSoup
folder=Path(sys.argv[1]);rows=[]
for case in json.loads((folder/'receipts.json').read_text())['cases']:
 trace_path=folder/(case['id']+'-trace.json')
 key=trace_path.name.removesuffix('-trace.json');trace=json.loads(trace_path.read_text(encoding='utf-8'));receipt=json.loads((folder/'receipts.json').read_text());row=next(x for x in receipt['cases'] if x['id']==key);tid=row['trace_id']
 stages=[x for x in trace.get('context_stages',[]) if x['stage']=='prompt'];expected=stages[-1]['sha256'] if stages else []
 exp=(folder/(key+'-export.txt')).read_text(encoding='utf-8');marker='**Trace:** `'+tid+'`';section=exp.split(marker,1)[1].split('\n**Trace:**',1)[0];sources=section.split('### Nguồn tham chiếu\n',1)[1] if '### Nguồn tham chiếu\n' in section else ''
 blocks=re.findall(r'(?m)^>.*(?:\n>.*)*',sources);contexts=['\n'.join(line[2:] if line.startswith('> ') else line[1:] for line in block.splitlines()) for block in blocks];actual=[hashlib.sha256(x.encode()).hexdigest() for x in contexts]
 def templates(name):
  soup=BeautifulSoup((folder/(key+name)).read_text(encoding='utf-8'),'html.parser');return {t['id']:t.find('pre').get_text(types=None) for t in soup.select('template[id]') if t['id'].startswith('source-'+tid+'-') and t.find('pre')}
 original=templates('-answer.html');replay=templates('-replay.txt');guards=trace.get('guardrail_state') or {};guard_safe=(guards.get('mode')!='off' or (guards.get('executed') is False and guards.get('input_safe') is None and guards.get('output_safe') is None))
 result={'id':key,'trace_id':tid,'expected_prompt_contexts':len(expected),'export_contexts':len(actual),'export_hash_sequence_matches_prompt':actual==expected,'original_templates':len(original),'replay_templates':len(replay),'replay_source_bodies_equal':original==replay,'guardrails_mode':guards.get('mode'),'disabled_guards_do_not_claim_safe':guard_safe,'cached':trace.get('cached')};rows.append(result)
(folder/'source-roundtrip.json').write_text(json.dumps(rows,indent=2),encoding='utf-8');print(json.dumps(rows));assert rows, 'No trace evidence; not a PASS';assert all(x['export_hash_sequence_matches_prompt'] and x['replay_source_bodies_equal'] and x['disabled_guards_do_not_claim_safe'] for x in rows)
