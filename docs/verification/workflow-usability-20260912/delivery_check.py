import json,hashlib
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).parent
state=json.loads(Path('tmp/online-evidence-20260912/api-state.json').read_text())
old=json.loads(Path('tmp/live-api-af8c9f5/state.json').read_text(encoding='utf-8'))
base='http://127.0.0.1:8770'
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1050},device_scale_factor=1)
    context.add_cookies([dict(c,expires=-1,httpOnly=False,secure=False,sameSite='Lax') for c in state['cookies']])
    page=context.new_page(); errors=[]; results=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    def visit(path,name):
        response=page.goto(base+path,wait_until='networkidle',timeout=120000)
        overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth+2')
        results.append({'name':name,'path':path,'status':response.status,'overflow':overflow})
        print(name,response.status,'overflow',overflow,flush=True)
        assert response.status==200
        page.screenshot(path=str(root/(name+'.png')),full_page=True)
        return response
    visit(old['workspace_path']+'#reports','old-workspace')
    report=page.locator('a[href*="/reports/"]').first.get_attribute('href')
    finding=page.locator('a[href*="/findings/"]').first.get_attribute('href')
    visit(report,'report-desktop')
    assert page.locator('.report-paper h1').count()==1
    sources=page.locator('.report-source').count(); assert sources>0
    assert page.locator('.report-paper a[href^="#report-source-"]').count()>0
    page.pdf(path=str(root/'report-print.pdf'),format='A4',print_background=True)
    page.locator('a[href="#report-edit"]').click()
    expect(page.locator('#report-edit')).to_have_attribute('open','')
    textarea=page.locator('[name="markdown"]')
    textarea.fill(textarea.input_value()+'\n')
    with page.expect_navigation(wait_until='networkidle',timeout=60000):
        page.get_by_role('button',name='Lưu phiên bản mới').click()
    assert page.locator('.report-source').count()==sources
    new_report=page.url.replace(base,'')
    for fmt in ['md','docx']:
        response=context.request.get(base+new_report+'/export?format='+fmt)
        assert response.status==200
        body=response.body(); (root/('report-export.'+fmt)).write_bytes(body)
        if fmt=='docx':
            with ZipFile(BytesIO(body)) as z: assert b'<w:document' in z.read('word/document.xml')
        results.append({'name':'export-'+fmt,'status':response.status,'sha256':hashlib.sha256(body).hexdigest()})
    page.set_viewport_size({'width':390,'height':844})
    visit(new_report,'report-mobile')
    visit(finding,'findings-mobile')
    page.locator('[data-finding-filter]').select_option('resolved')
    assert page.locator('[data-finding-status]:visible:not([data-finding-status="resolved"])').count()==0
    page.set_viewport_size({'width':1440,'height':1050})
    visit(finding,'findings-desktop')
    for path,name in [('/','home'),('/search?q=45%2F2019%2FQH14','search'),('/admin','admin'),('/admin/usage','admin-usage'),('/admin/providers','admin-providers'),('/admin/system','admin-system'),('/admin/users','admin-users'),('/admin/audit','admin-audit')]:
        page.set_viewport_size({'width':390,'height':844})
        visit(path,name+'-mobile')
    result={'checks':results,'page_errors':errors,'new_report':new_report,'saved_source_count':sources}
    (root/'delivery-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    assert not errors
    assert not any(row.get('overflow') for row in results)
    browser.close()
