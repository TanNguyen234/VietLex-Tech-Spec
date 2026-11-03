from pathlib import Path
import subprocess,sys,json
r=Path.cwd();w=Path(__file__).parent;c=r/'.tmp-finish-real-20261030/cycle27'
assert json.loads((c/'full-result.json').read_text())['status']=='PASS'
offline=json.loads((w/'metric33-final-summary.json').read_text());assert offline['cases']==50 and offline['original_answers_contexts_metadata_unchanged'] and offline['unchanged_non_citation_metrics']
v=json.loads((w/'timeout50-validation.json').read_text());assert v['replay_passed_cases']==50 and v['retrieval_gate']['passed'] and v['technical_error_cases']==0 and v['input_safe_count']==50 and v['output_safe_count']==50
steps=[('local-NeMo',[w/'local_guard_timeout20.py']),('promote',[c/'promote_release.py']),('primary',[r/'.tmp-finish-real-20261030/acceptance-followup-20261102/verify_primary.py',c,w/'primary-final27']),('production',[w/'accept_enforced.py',w/'production-final27',c]),('roundtrip',[w/'compare_roundtrip.py',w/'production-final27']),('guard-enforcement',[w/'verify_enforcement.py',w/'production-final27']),('database',[w/'production_db_receipts.py',w/'production-final27']),('control-database',[w/'control_db_receipts.py',w/'production-final27']),('frontend',[w/'verify_frontend.py',w/'frontend-final27']),('log-scan',[w/'log_scan_final27.py'])]
receipts=[]
for name,args in steps:
 cmd=[sys.executable,'-X','utf8',*map(str,args)];print('START '+name,flush=True)
 with (w/(name+'-final27.log')).open('wb') as f: result=subprocess.run(cmd,cwd=r,stdout=f,stderr=subprocess.STDOUT)
 receipts.append({'step':name,'command':cmd,'exit_code':result.returncode});(w/'execution-final27.json').write_text(json.dumps(receipts,indent=2));print(name+' '+str(result.returncode),flush=True)
 if result.returncode:sys.exit(result.returncode)
