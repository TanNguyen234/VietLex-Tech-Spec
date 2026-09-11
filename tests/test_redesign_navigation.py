from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from fastapi import FastAPI


def test_shared_navigation_identifies_nested_research_page():
    env = Environment(loader=FileSystemLoader('app/templates'), autoescape=select_autoescape())
    request = Request({'type': 'http', 'path': '/workspaces/example', 'headers': [], 'query_string': b'', 'app': FastAPI()})
    html = env.get_template('product_nav.html').render(request=request)
    assert 'href="/workspaces" aria-current="page"' in html
    assert html.count('aria-current="page"') == 1


def test_every_full_page_loads_shared_redesign_after_existing_styles():
    for path in Path('app/templates').glob('*.html'):
        html = path.read_text(encoding='utf-8')
        if '<!doctype html>' not in html.lower():
            continue
        assert '/static/css/vietlex-redesign.css' in html, path.name
        assert html.index('/static/css/vietlex-redesign.css') > html.index('/static/css/vietlex-enhancements.css'), path.name
