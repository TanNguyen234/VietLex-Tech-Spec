import json
from pathlib import Path
from playwright.sync_api import sync_playwright
state=json.loads(Path('tmp/online-evidence-20260912/api-state.json').read_text())
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1050},device_scale_factor=1)
    context.add_cookies([dict(c,expires=-1,httpOnly=False,secure=False,sameSite='Lax') for c in state['cookies']])
    page=context.new_page()
    response=page.goto('http://127.0.0.1:8766'+state['workspace']+'#sources',wait_until='networkidle',timeout=60000)
    assert response.status==200
    page.keyboard.press('Control+Home')
    page.screenshot(path=str(Path('docs/images/vietlex-official-workflow-20260912.png').resolve()),full_page=True)
    print('screenshot',page.title(),flush=True)
    browser.close()
