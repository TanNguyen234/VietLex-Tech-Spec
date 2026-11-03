from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader


def _render(user=None):
    env = Environment(loader=FileSystemLoader(Path(__file__).parents[1] / 'app/templates'), autoescape=True)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        reviewer_demo_mode=True, demo_ai_daily_limit=20)))
    return env.get_template('demo_notice.html').render(request=request, workspace_user=user)


def test_signed_in_notice_is_compact_and_keeps_limits_discoverable():
    html = _render({'_id': 'test-user'})
    assert 'data-demo-notice="signed-in"' in html
    assert 'href="/account"' not in html
    assert '<details' in html and '<summary' in html
    assert '20' in html and 'UTC' in html and '3 lượt/phút' in html
    assert 'admin' in html and 'nhà cung cấp' in html


def test_guest_notice_still_has_login_action_and_no_false_signed_in_state():
    html = _render()
    assert 'data-demo-notice="guest"' in html
    assert 'href="/account"' in html
    assert 'Đã đăng nhập' not in html
