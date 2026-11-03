import asyncio,json,tomllib,sys
from pathlib import Path
from datetime import timedelta
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
w=Path(__file__).parent;r=Path.cwd()
async def main():
 cfg=tomllib.loads((Path.home()/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['crg']
 cfg.update(tomllib.loads((r/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['crg'])
 p=StdioServerParameters(command=cfg['command'],args=cfg['args'],cwd=str(r),env=cfg.get('env'))
 with (w/'crg-final-stderr.log').open('w',encoding='utf-8') as err:
  async with stdio_client(p,errlog=err) as (read,write):
   async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=300)) as s:
    init=await s.initialize();ls=await s.list_tools()
    (w/'crg-schema.json').write_text(ls.model_dump_json(indent=2),encoding='utf-8');print('TOOLS '+str(len(ls.tools)),flush=True)
    for label,name,args in [
     ('coverage-minimal','get_minimal_context_tool',{'task':'Cover current untracked source and tests','base':'HEAD'}),
     ('worktree-postprocess','run_postprocess_tool',{'flows':True,'communities':False,'fts':True}),
     ('pack-tests-final','query_graph_tool',{'pattern':'tests_for','target':'pack_sources','detail_level':'standard','max_results':12}),
     ('eval-tests-final','query_graph_tool',{'pattern':'tests_for','target':'run_stage_a_online','detail_level':'standard','max_results':12}),
     ('pack-callers-final','query_graph_tool',{'pattern':'callers_of','target':'pack_sources','detail_level':'minimal','max_results':12})]:
     print('START '+label,flush=True)
     res=await s.call_tool(name,{'repo_root':str(r),**args});(w/('crg-'+label+'.json')).write_text(res.model_dump_json(indent=2),encoding='utf-8')
     print(label+' '+str(res.isError),flush=True)
if __name__=='__main__':asyncio.run(main())
