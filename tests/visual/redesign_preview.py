"""Provider-free visual fixtures. Run with Python; serves only on loopback.

All records are synthetic layout data, never benchmark/provider evidence.
"""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
import json

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[2]
ENV = Environment(loader=FileSystemLoader(ROOT / 'app/templates'), autoescape=select_autoescape())
NOW = datetime(2026, 9, 9, 9, tzinfo=timezone.utc)
PAGES = {
    '/': 'index.html', '/search': 'legal_search.html', '/documents/sample': 'legal_document.html',
    '/workspaces': 'research_workspaces.html', '/workspaces/sample': 'research_workspace.html',
    '/evaluation-lab': 'evaluation_lab.html', '/login': 'account_form.html', '/register': 'account_form.html',
    '/forgot-password': 'account_form.html', '/reset-password': 'account_form.html', '/verify-email': 'account_form.html',
    '/settings': 'settings.html', '/privacy': 'privacy.html', '/terms': 'terms.html',
    '/admin': 'admin.html', '/admin/requests': 'admin_requests_page.html', '/admin/usage': 'admin_usage_page.html',
    '/admin/users': 'admin_users_page.html', '/admin/providers': 'admin_providers_page.html',
    '/admin/evaluations': 'evaluation_lab.html', '/admin/system': 'admin_system_page.html',
    '/admin/audit': 'admin_audit_page.html', '/admin/details/sample': 'admin_details.html',
    '/admin/error': 'admin_error_page.html',
}


def context(path):
    request = Request({'type': 'http', 'path': path, 'root_path': '', 'scheme': 'http',
                       'server': ('127.0.0.1', 8765), 'headers': [], 'query_string': b'',
                       'app': SimpleNamespace(state=SimpleNamespace(reviewer_demo_mode=False))})
    workspace = dict(workspace_id='sample', title='Hồ sơ quan hệ lao động', description='Tập hợp nguồn và các vấn đề cần đối chiếu trong quá trình nghiên cứu.',
                     evidence=[], documents=[], analyses=[], created_at=NOW, updated_at=NOW, expires_at='09/10/2026')
    logs = [dict(trace_id='sample-'+str(i), timestamp=NOW, user_query=q, bot_response='Nội dung minh họa bố cục, không phải kết quả phân tích pháp lý.',
                 cached=False, metrics={'request_status': 'ok', 'observed_model': 'Mô hình minh họa'},
                 usage={'total_token_count': 1240, 'measured_calls': 1, 'calls': 1}, contexts=[],
                 safety_status={'input_safe': None, 'output_safe': None}, feedback={}, stored_context_count=0)
            for i, q in enumerate(['Nghiên cứu điều kiện giao kết hợp đồng', 'Đối chiếu nguồn trong hồ sơ lao động', 'Tổng hợp nghĩa vụ của các bên'])]
    stats = dict(status='available', total_queries=128, technical_error_count=3,
                 daily=[{'_id': f'2026-09-0{i}', 'requests': n, 'tokens': 1200*n, 'measured_calls': n} for i,n in enumerate([12,19,8,24,16,21,28],1)],
                 token_usage={'total_token_count': 158720, 'total_token_count_coverage': 128, 'calls': 130},
                 latency={'avg': 3.42, 'max': 12.4, 'count': 128}, avg_faithfulness=None, avg_relevance=None)
    section = path.split('/')[-1] if path != '/admin' else 'overview'
    titles = dict(overview='Tổng quan', requests='Requests', usage='Usage & chất lượng', users='Tài khoản', providers='Nhà cung cấp', evaluations='Đánh giá', system='Hệ thống', audit='Nhật ký quản trị')
    return dict(request=request, csrf_token='visual-fixture-only', current_user=None, prefill_question='', progress_transport='sse',
                query='hợp đồng lao động', results=[dict(document_id='sample', legal_type='Văn bản minh họa', title=t, document_number='MẪU / CHƯA XÁC MINH', issuing_authority='Dữ liệu bố cục') for t in ['Bộ luật Lao động', 'Quy định về hợp đồng lao động', 'Hướng dẫn thực hiện chính sách lao động']],
                document={'metadata': {'title': 'Bộ luật Lao động', 'legal_type': 'Văn bản minh họa', 'document_number': 'MẪU / CHƯA XÁC MINH', 'issuing_authority': 'Dữ liệu bố cục', 'issuance_date': None}},
                sections=[{'id': 'section-'+str(i), 'title': t, 'text': t+'\n\nNội dung mẫu phục vụ kiểm tra khả năng đọc, khoảng cách dòng và cách trình bày văn bản. Đây không phải trích dẫn pháp luật. Khi sử dụng, cần đối chiếu nội dung và tình trạng hiệu lực với nguồn chính thức.\n\nPhần nội dung này minh họa cách bố trí đoạn văn dài trong không gian nghiên cứu.'} for i,t in enumerate(['Chương I. Quy định chung', 'Điều 1. Phạm vi', 'Điều 2. Đối tượng'])], source_url=None,
                workspace=workspace, workspaces=[workspace, dict(workspace, workspace_id='sample-2', title='Rà soát hợp đồng dịch vụ')], official_research_enabled=True,
                mode={'/login':'login','/register':'register','/forgot-password':'forgot','/reset-password':'reset','/verify-email':'verify'}.get(path,'login'),
                message='Email đã được xác minh. Bạn có thể đăng nhập.' if path == '/verify-email' else '', token='sample',
                user={'email':'researcher@example.test'}, sessions=[{'id':'sample','created_at':'09/09/2026','last_used_at':'09/09/2026','current':True}], demo_quota={'status':'disabled'},
                stats=stats, logs=logs, log=logs[0], inventory={'status':'unavailable','error_kind':'visual_fixture'},
                current_admin={'_id':'sample-admin'}, users=[{'_id':'sample-user','email':'researcher@example.test','role':'user','status':'active','email_verified':True,'created_at':NOW}],
                admin_section=section, page_title=titles.get(section,'Chi tiết'), admin_view=path.startswith('/admin'),
                filter_action=path, export_url='/admin/export.csv', prev_url=None, next_url=None, skip=0, limit=25,
                filters={}, role='', account_status='', audit_logs=[], error_kind='database_unavailable',
                provider_status=[{'provider':p,'state':'UNKNOWN','configured':False,'recent':None} for p in ['Vertex AI','Groq','NVIDIA']],
                system_status={'status':'unobserved','runtime':{'retrieval_backend':'Chưa kiểm tra trong preview'},'checks':{'Database':'Chưa kiểm tra','Retrieval':'Chưa kiểm tra'}},
                settings=SimpleNamespace(SERVERLESS_ONLINE_ONLY=True,LOGFIRE_TOKEN=None,PUBLIC_NEMO_DEFAULT_ENABLED=False,DATA_RETENTION_DAYS=30,CHAT_RATE_LIMIT='3/minute'),
                demo_admission=None, lab={'status':'unavailable','error_kind':'visual_fixture','boundary':'Dữ liệu mẫu, không phải bằng chứng benchmark.'}, runs=[], selected_run='')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/__pages':
            data = json.dumps(list(PAGES), ensure_ascii=False).encode(); kind='application/json'
        elif path.startswith('/static/'):
            target = (ROOT / 'app' / path.lstrip('/')).resolve()
            if not target.is_relative_to(ROOT / 'app/static') or not target.is_file():
                self.send_error(404); return
            data=target.read_bytes(); kind={'.css':'text/css','.js':'text/javascript','.ttf':'font/ttf'}.get(target.suffix,'application/octet-stream')
        elif path == '/sessions':
            data='<p class="muted">Lịch sử minh họa trống.</p>'.encode(); kind='text/html'
        elif path == '/readyz':
            data=b'{"status":"not_ready"}'; kind='application/json'
        elif path in PAGES:
            try:
                html=ENV.get_template(PAGES[path]).render(**context(path))
                if urlsplit(self.path).query == 'figma':
                    html=html.replace('</head>', '<script src="https://mcp.figma.com/mcp/html-to-design/capture.js" async></script></head>')
                data=html.encode(); kind='text/html'
            except Exception as exc:
                self.send_error(500, str(exc)); return
        else:
            self.send_error(404); return
        self.send_response(200); self.send_header('Content-Type',kind+'; charset=utf-8'); self.end_headers(); self.wfile.write(data)


if __name__ == '__main__':
    print('Synthetic visual fixtures: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
