from pathlib import Path
import runpy

from fastapi.testclient import TestClient


def test_real_workspace_template_exposes_canonical_readback_fragments():
    root = Path(__file__).resolve().parents[1]
    app = runpy.run_path(str(root / 'tests/visual/browser_remediation_harness.py'))['app']
    response = TestClient(app).get('/workspaces/local-browser-fixture')
    assert response.status_code == 200
    assert 'id="workspace-source-library"' in response.text
    assert 'data-source-library-count' in response.text
    assert 'id="workspace-reports"' in response.text
    assert 'data-workspace-revision=' in response.text
