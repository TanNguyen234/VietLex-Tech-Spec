import asyncio,json,tomllib,sys
from pathlib import Path
from datetime import timedelta
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
w=Path(__file__).parent;r=Path.cwd()
async def main():
 cfg=tomllib.loads((Path.home()/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['crg']
 cfg.update(tomllib.loads((r/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['crg'])
 p=StdioServerParameters(command=cfg['command'],args=cfg['args'],cwd=str(r))
 with (w/'crg-stderr.log').open('w',encoding='utf-8') as err:
  async with stdio_client(p,errlog=err) as (read,write):
   async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=300)) as s:
    init=await s.initialize();ls=await s.list_tools()
    (w/'crg-schema.json').write_text(ls.model_dump_json(indent=2),encoding='utf-8');print('TOOLS '+str(len(ls.tools)),flush=True)
    res=await s.call_tool('get_minimal_context_tool',{'repo_root':str(r),'task':'Review current guardrail/effect diagnostics and production Golden50 evaluation contracts','base':'HEAD','changed_files':['app/services/deep_official_search.py','app/services/guardrails.py','app/api/routes.py','run_answer_eval.py']})
    (w/'crg-minimal.json').write_text(res.model_dump_json(indent=2),encoding='utf-8');print(res.model_dump_json(indent=2),flush=True)
if __name__=='__main__':asyncio.run(main())
