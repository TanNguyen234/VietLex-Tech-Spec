import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
root=Path(__file__).parent
state=json.loads(Path('tmp/online-evidence-20260912/api-state.json').read_text())
base='http://127.0.0.1:8770'
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1050},device_scale_factor=1)
    context.add_cookies([dict(c,expires=-1,httpOnly=False,secure=False,sameSite='Lax') for c in state['cookies']])
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    result={'workspace':state['workspace'],'checks':[]}
    def record(name):
        overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth + 2')
        result['checks'].append({'name':name,'horizontal_overflow':overflow,'url':page.url})
        print(name,'overflow',overflow,flush=True)
        page.screenshot(path=str(root/(name+'.png')),full_page=True)
        assert not overflow
    response=page.goto(base+state['workspace'],wait_until='networkidle',timeout=120000)
    assert response.status==200
    record('overview-desktop')
    page.locator('[data-workspace-view="sources"]').click()
    record('sources-desktop')
    first=page.locator('[name="selected_evidence"]').first
    first.check()
    page.locator('[data-workspace-view="analysis"]').click()
    assert page.locator('[data-selected-source-list] li').count()==1
    page.reload(wait_until='networkidle')
    assert page.locator('[data-selected-source-list] li').count()==1
    result['selection_survived_reload']=True
    page.locator('[data-workspace-view="sources"]').click()
    page.locator('[data-evidence-search]').fill('definitely absent string 7835')
    assert page.locator('.evidence-row:visible').count()==0
    assert '1 căn cứ đã chọn' in page.locator('[data-selection-summary]').inner_text()
    page.locator('[data-evidence-search]').fill('')
    row=page.locator('.evidence-row').first
    row.locator('.evidence-review summary').click()
    form=row.locator('.evidence-review form')
    revision=form.locator('[name="revision"]').input_value()
    action=form.get_attribute('action')
    csrf=form.locator('[name="csrf_token"]').input_value()
    form.locator('[name="status"]').select_option('follow_up')
    form.locator('[name="note"]').fill('Kiểm tra lại chữ “báo cáo/báo giá” với PDF gốc trước khi sử dụng.')
    form.get_by_role('button',name='Lưu đối chiếu').click()
    expect(page.locator('.evidence-review [name="revision"]').first).to_have_value(str(int(revision)+1), timeout=45000)
    stale=context.request.post(base+action,form={'csrf_token':csrf,'status':'to_check','revision':revision})
    assert stale.status==409
    result['review_saved_and_stale_write_rejected']=True
    reader=page.locator('.source-library-card>a').first.get_attribute('href')
    response=page.goto(base+reader,wait_until='networkidle',timeout=60000)
    assert response.status==200
    pre=page.locator('.source-excerpt').first
    chosen=pre.evaluate("node => { const range=document.createRange(); range.setStart(node.firstChild,0); range.setEnd(node.firstChild,150); const s=getSelection(); s.removeAllRanges(); s.addRange(range); return s.toString(); }")
    page.get_by_role('button',name='Dùng đoạn đang bôi chọn').first.click()
    assert page.locator('textarea[name="quote"]').first.input_value()==chosen
    result['selected_real_source_text_into_pin_form']=True
    record('reader-desktop')
    page.set_viewport_size({'width':390,'height':844})
    record('reader-mobile')
    page.goto(base+state['workspace']+'#sources',wait_until='networkidle')
    record('sources-mobile')
    page.locator('[data-workspace-view="analysis"]').click()
    record('analysis-mobile')
    result['page_errors']=errors
    assert not errors
    (root/'browser-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    browser.close()
