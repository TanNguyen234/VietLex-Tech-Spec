import os,sys,asyncio,json
from pathlib import Path
os.environ['APP_ENV']='test';sys.path.insert(0,str(Path.cwd()))
import logfire;logfire.configure(send_to_logfire=False,console=False)
from app.services import guardrails
from app.services.provider_runtime import capture_provider_usage,current_provider_calls
async def main():
 out=Path(__file__).parent/'local-guard-timeout20.json';assert not out.exists()
 assert guardrails.settings.GUARDRAIL_TIMEOUT_SECONDS==20.0
 rails=guardrails.get_rails()
 @capture_provider_usage
 async def check():
  safe,reason=await guardrails.check_input_guardrails('Theo pháp luật Việt Nam, tiền lương thử việc được quy định thế nào?');assert safe
  supported,_=await guardrails.check_output_guardrails('Theo tài liệu được cung cấp, mức thấp nhất là85% mức lương công việc.', ['Điều 26. Tiền lương thử việc ít nhất bằng85% mức lương của công việc đó.'],'Quy định lương thử việc?')
  row={'evidence':'live local NeMo/Vertex preflight after configuration validation; not HTTP authorization','guardrail_timeout_seconds':guardrails.settings.GUARDRAIL_TIMEOUT_SECONDS,'input_safe':safe,'output_safe':supported,'engine_class':type(rails).__module__+'.'+type(rails).__name__,'public_mode':guardrails.settings.PUBLIC_GUARDRAIL_MODE,'calls':current_provider_calls(),'passed':safe and supported,'required_flows':{'input':list(rails.config.rails.input.flows),'output':list(rails.config.rails.output.flows)}}
  row['passed']=row['passed'] and row['engine_class'].startswith('nemoguardrails.') and row['public_mode']=='enforce' and len(row['calls'])==2 and all(c.get('provider')=='google_vertex_ai' and c.get('model')==guardrails.settings.VERTEX_LLM_MODEL and c.get('use_case')=='guardrail' and c.get('success') is True for c in row['calls'])
  out.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passed':row['passed'],'calls':len(row['calls'])}));assert row['passed']
 await check()
asyncio.run(main())
