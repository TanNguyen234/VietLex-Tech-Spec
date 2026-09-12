import json, time
from pathlib import Path
import httpx

root = Path(__file__).parent
out = root / 'api'
out.mkdir(exist_ok=True)
client = httpx.Client(base_url='http://127.0.0.1:8766', timeout=330)
def request(name, method, path, data=None):
    if data is not None:
        data = dict(data, csrf_token=client.cookies.get('csrf_token', ''))
    started = time.monotonic()
    response = client.request(method, path, data=data)
    text = response.text
    for cookie in client.cookies.jar:
        text = text.replace(cookie.value, '[REDACTED_COOKIE]')
    (out / (name+'.txt')).write_text(text, encoding='utf-8')
    with (out/'requests.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'name':name,'status':response.status_code,'seconds':time.monotonic()-started})+'\n')
    print(name, response.status_code, flush=True)
    if response.status_code >= 400:
        response.raise_for_status()
    return response

request('login_page','GET','/login')
credentials=json.loads(Path('tmp/live-api-af8c9f5/credentials.json').read_text(encoding='utf-8-sig'))
request('login','POST','/login',credentials)
r=request('create','POST','/workspaces',{'title':'Official evidence live acceptance 20260912','description':'Quy định lựa chọn nhà thầu được sửa đổi ra sao trong tháng 9/2026?'})
workspace=r.headers['location']
(root/'api-state.json').write_text(json.dumps({'workspace':workspace,'cookies':[dict(name=c.name,value=c.value,domain=c.domain,path=c.path) for c in client.cookies.jar]}))
plan=request('plan','POST',workspace+'/research/plan',{'question':'Quy định lựa chọn nhà thầu được sửa đổi ra sao trong tháng 9/2026?','suggest_keywords':'true'}).json()
request('search','POST',workspace+'/research/run',{'plan':json.dumps(plan,ensure_ascii=False)})
read=request('read','POST',workspace+'/analyses/sources',{'urls':'https://vanban.chinhphu.vn/?pageid=27160&docid=219431','use_ocr':'true','page_limit':'2'}).json()
source=read['result']['sources'][0]
start=source['text'].index('Điều 1.')
quote=source['text'][start:start+2200]
pin=request('pin','POST',workspace+'/sources/pin',{'analysis_id':read['analysis_id'],'source_index':'0','quote':quote}).json()
request('analysis','POST',workspace+'/analyses/selected',{'evidence_ids':pin['evidence_id'],'question':'Chỉ theo đoạn đã chọn, thời hạn gửi báo giá tối thiểu là bao lâu? Phân biệt trường hợp thông thường và gói thầu y tế. Không kết luận hiệu lực hiện hành.'})
request('readback','GET',workspace)
