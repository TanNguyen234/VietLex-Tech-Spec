"""Loopback-only synthetic rendering harness; never imports the production app.

Run with the repository Python to inspect the real templates/JS/CSS without
credentials, provider clients, or persistent writes. This is not local-app
or production acceptance.
"""
from pathlib import Path
import hashlib

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


ROOT = Path(__file__).resolve().parents[2]
app = FastAPI()
app.state.reviewer_demo_mode = True
app.state.demo_ai_daily_limit = 20
app.state.free_web_research_enabled = False
app.state.fixture_reports = []
templates = Jinja2Templates(directory=ROOT / 'app/templates')
app.mount('/static', StaticFiles(directory=ROOT / 'app/static'), name='static')


@app.get('/workspaces/local-browser-fixture')
def workspace(request: Request):
    response = templates.TemplateResponse(request, 'research_workspace.html', {
        'workspace': {'workspace_id': 'local-browser-fixture',
                      'title': 'VL — Kiểm tra hồ sơ trên điện thoại',
                      'description': 'Dữ liệu tổng hợp cho kiểm thử giao diện.',
                      'created_at': '2026-10-26T08:00:00', 'updated_at': '2026-10-26T08:05:00',
                      'expires_at': '2026-11-25T08:00:00',
                      'documents': [], 'evidence': [{'evidence_id': 'synthetic-evidence',
                          'citation': 'Nguồn tổng hợp kiểm thử', 'excerpt': 'Chỉ kiểm tra giao diện, không phải quy định pháp luật.',
                          'original': 'Synthetic UI fixture, no legal authority.'}],
                      'analyses': app.state.fixture_reports},
        'workspace_user': {'_id': 'synthetic-user'},
        'csrf_token': 'synthetic-token', 'official_research_enabled': False,
        'source_library': [], 'workspace_summary': {'reports': len(app.state.fixture_reports)},
    })
    version = hashlib.sha256((ROOT / 'app/static/js/research-workspace.js').read_bytes()).hexdigest()[:12]
    response.body = response.body.replace(b'/static/js/research-workspace.js"',
                                          ('/static/js/research-workspace.js?v=' + version + '"').encode())
    response.headers['content-length'] = str(len(response.body))
    response.headers['cache-control'] = 'no-store'
    return response


@app.post('/workspaces/local-browser-fixture/analyses/report')
async def report_fixture(request: Request):
    # Synthetic in-memory write only; no persistence or production app imports.
    form = await request.form()
    assert form.get('evidence_ids') == 'synthetic-evidence'
    report = {'analysis_id': 'synthetic-report-' + str(len(app.state.fixture_reports) + 1),
              'kind': 'research_report', 'status': 'insufficient_evidence',
              'created_at': '2026-10-26T08:10:00',
              'result': {'report': {'issue': 'Báo cáo kiểm thử tổng hợp', 'analysis': [],
                                    'exceptions': [], 'checklist': [],
                                    'unknown': ['Không phải kết luận pháp luật.']}}}
    app.state.fixture_reports.append(report)
    return report


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8767, access_log=False)
