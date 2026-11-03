import asyncio,json,tomllib
from pathlib import Path
from datetime import timedelta
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
w=Path(__file__).parent;r=Path.cwd()
async def main():
 cfg=tomllib.loads((Path.home()/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['crg']
 cfg.update(tomllib.loads((r/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['crg'])
 params=StdioServerParameters(command=cfg['command'],args=cfg['args'],cwd=str(r),env=cfg.get('env'))
 changed=['app/config.py','app/services/serverless_guardrails.py','app/services/guardrails.py']
 with (w/'crg-timeout-stderr.log').open('w',encoding='utf-8') as err:
  async with stdio_client(params,errlog=err) as (read,write):
   async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=300)) as session:
    await session.initialize()
    queries=[('minimal','get_minimal_context_tool',{'task':'Review bounded mandatory guard timeout default8 to20; preserve fail-closed cancellation/no retries','base':'HEAD','changed_files':changed}),('build','build_or_update_graph_tool',{'full_rebuild':False,'base':'HEAD','postprocess':'full'}),('detect','detect_changes_tool',{'base':'HEAD','changed_files':changed,'detail_level':'minimal','max_depth':1}),('flows','get_affected_flows_tool',{'base':'HEAD','changed_files':changed}),('callers','query_graph_tool',{'pattern':'callers_of','target':'check_input_guardrails','detail_level':'standard','max_results':20}),('tests','query_graph_tool',{'pattern':'tests_for','target':'check_input_guardrails','detail_level':'standard','max_results':20}),('context','get_review_context_tool',{'base':'HEAD','changed_files':changed,'max_depth':1,'detail_level':'minimal'})]
    for label,name,args in queries:
     print('START '+label,flush=True);result=await session.call_tool(name,{'repo_root':str(r),**args});(w/('crg-timeout-'+label+'.json')).write_text(result.model_dump_json(indent=2),encoding='utf-8');print(label+' error='+str(result.isError),flush=True)
if __name__=='__main__':asyncio.run(main())
