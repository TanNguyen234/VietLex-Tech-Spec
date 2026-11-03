from pathlib import Path
import json,hashlib,subprocess
from code_review_graph.graph import GraphStore
from code_review_graph.incremental import CodeParser,get_db_path
r=Path.cwd();w=Path(__file__).parent;parser=CodeParser(r);store=GraphStore(get_db_path(r));rows=[]
try:
 raw=subprocess.check_output(['git','ls-files','-z','--others','--exclude-standard','--','app','tests','scripts'])
 for name in sorted(x.decode('utf-8') for x in raw.split(bytes([0])) if x):
  p=r/name
  if p.suffix!='.py' or p.is_symlink():continue
  data=p.read_bytes();nodes,edges=parser.parse_bytes(p,data);store.store_file_nodes_edges(str(p),nodes,edges,hashlib.sha256(data).hexdigest());rows.append({'path':name,'nodes':len(nodes),'edges':len(edges),'source_sha256':hashlib.sha256(data).hexdigest()})
 store.commit()
finally:store.close()
(w/'crg-untracked-coverage.json').write_text(json.dumps({'evidence':'installed CRG parser/store explicit untracked source supplement; no app mutation','files':rows},indent=2));print(json.dumps({'files':len(rows),'nodes':sum(x['nodes'] for x in rows),'deep_file_present':any(x['path']=='app/services/deep_official_search.py' for x in rows)}),flush=True)
