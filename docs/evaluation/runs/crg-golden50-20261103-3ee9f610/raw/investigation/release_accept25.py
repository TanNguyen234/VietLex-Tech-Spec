from pathlib import Path
import subprocess,sys,json
r=Path.cwd();w=Path(__file__).parent;c=r/'.tmp-finish-real-20261030/cycle25'
assert json.loads((c/'full-result.json').read_text())['status']=='PASS'
assert json.loads((w/'fixed50-validation.json').read_text())['replay_passed_cases']==50
steps=[('promote',[c/'promote_release.py']),('primary',[r/'.tmp-finish-real-20261030/acceptance-followup-20261102/verify_primary.py',c,w/'primary-final25']),('production',[w/'accept_enforced.py',w/'production-final25',c]),('roundtrip',[w/'compare_roundtrip.py',w/'production-final25']),('guard-enforcement',[w/'verify_enforcement.py',w/'production-final25']),('database',[w/'production_db_receipts.py',w/'production-final25']),('control-database',[w/'control_db_receipts.py',w/'production-final25']),('frontend',[w/'verify_frontend.py',w/'frontend-final25']),('log-scan',[w/'log_scan_final25.py'])]
receipts=[]
for name,args in steps:
 cmd=[sys.executable,'-X','utf8',*map(str,args)];print('START '+name,flush=True)
 with (w/(name+'-final25.log')).open('wb') as f: result=subprocess.run(cmd,cwd=r,stdout=f,stderr=subprocess.STDOUT)
 receipts.append({'step':name,'command':cmd,'exit_code':result.returncode});(w/'execution-final25.json').write_text(json.dumps(receipts,indent=2));print(name+' '+str(result.returncode),flush=True)
 if result.returncode:sys.exit(result.returncode)
