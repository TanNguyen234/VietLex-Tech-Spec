from pathlib import Path
import json,subprocess
from code_review_graph.graph import GraphStore
from code_review_graph.incremental import get_db_path,incremental_update
def main():
 r=Path.cwd();w=Path(__file__).parent
 raw=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard','--','app','tests','scripts','run_answer_eval.py','run_retrieval_eval.py'])
 files=sorted(set(x.decode('utf-8') for x in raw.split(b'\0') if x and x.decode('utf-8').endswith(('.py','.js','.html','.css','.cjs'))))
 store=GraphStore(get_db_path(r))
 try:result=incremental_update(r,store,base='HEAD',changed_files=files)
 finally:store.close()
 (w/'crg-worktree-index.json').write_text(json.dumps({'evidence':'installed CRG2.3.7 SDK worktree supplement; upstream MCP build enumerates tracked files only','source_file_inputs':files,'result':result},indent=2,default=str));print(json.dumps({'files_requested':len(files),'files_updated':result.get('files_updated'),'errors':result.get('errors')}),flush=True)

if __name__=='__main__':main()
