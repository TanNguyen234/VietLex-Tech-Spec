# Reviewer demo packaging verification — 2026-09-08

Scope: package existing functions with guest read-only access and verified-account quotas. No unfinished product feature from F01–F10 was implemented. See ../../UNFINISHED_FEATURES_REVIEW_20260908.md and ../../REVIEWER_GUIDE.md.

## Evidence

Independent stable review: clean after fixes for package-relative resources, home-page demo notice, and shared-quota exemption for protective/privacy endpoints. Auth, CSRF and body bounds remain enforced.

Focused RED observed: 4 admission/IP tests; packaging dependency test; outside-checkout TemplateNotFound and missing app/static; 5 privacy-control tests. Focused GREEN: 42 packaging/security/template tests, 48 API/account/workspace/public tests, 21 path/demo/template tests, final demo module 15 passed. Ruff clean.

Full provider-free suite after clean review: **1084 passed, 2 skipped, 20 deprecation warnings, 538.48 seconds**, exit 0. No runtime source/config edits followed. Later changes were documentation and release metadata only.

Exact final commands (PowerShell):

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/services/test_reviewer_demo.py
.venv/Scripts/python.exe -m ruff check app tests
$env:GIT_CONFIG_COUNT='1'
$env:GIT_CONFIG_KEY_0='safe.directory'
$env:GIT_CONFIG_VALUE_0='D:/Download/ProfessionalLegalRAG'
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp='C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/05/01a071a4-6fcb-7d02-9030-6250073c3697/pytest-demo-full-20260908'
git -c safe.directory=D:/Download/ProfessionalLegalRAG diff --check
uv --system-certs pip compile pyproject.toml --python-version 3.12 --universal --generate-hashes --output-file requirements-demo.lock --quiet
```

Release root: `C:/Users/VI TINH THANH AN/.codex/visualizations/2026/09/05/01a071a4-6fcb-7d02-9030-6250073c3697`. Packaging commands (paths relative to that root where noted): stdlib `python -m venv --without-pip reviewer-demo-env-20260907`; `uv --system-certs pip sync requirements-demo.lock --require-hashes --python <root>/reviewer-demo-env-20260907/Scripts/python.exe --quiet`; `uv --system-certs build --wheel --out-dir <root>/reviewer-release-20260908 --python .venv/Scripts/python.exe`; `uv pip install --no-deps --reinstall --python <root>/reviewer-demo-env-20260907/Scripts/python.exe <root>/reviewer-release-20260908/vietlex_online_ssr-0.1.0-py3-none-any.whl --quiet`.

Final wheel installed into the clean locked runtime. ASGI smoke outside checkout: root/health/static/login 200, admin 401, anonymous POST chat 401 demo_login_required; home demo notice present. See wheel-smoke.json. Lifespan and live providers were not invoked.

Lock fetch initially failed TLS UnknownIssuer; system certificates fixed trust without disabling verification. uv venv initially failed inherited cache ACL; stdlib venv worked. Quiet wheel builds intermittently failed without detailed cause; diagnostic retries succeeded unchanged. Final log retained beside release. Wheel read required escalation for build-created file ACL; recorded SHA was obtained with Get-FileHash.

## Online and limits

Pre-change public read-only smoke: /, /healthz, /readyz, /evaluation-lab all 200; demo notice absent. This was the old deployment, not proof of new rollout. Post-push outcome is recorded separately.

Docker image build (CLI unavailable), authenticated email/AI/upload flow online, live Mongo atomic/TTL checks, WAF activation/readback, load/pentest and backup restore: **NOT RUN**. Vercel dashboard access timed out. No paid AI/provider calls, secret changes, corpus migrations or vector deletion. Quota is attempts, not dollars; WAF still required for read traffic and denial-of-service. Wheel has resources but companion source bundle supplies external Evaluation Lab artifacts.

Inherited .codex/config.toml and four existing untracked evaluation directories excluded. Generated build/ and egg-info are not delivered. Commit/push authority to main persists; push alone is not deployment proof.

## Changed files

- `.env.example`
- `Dockerfile`
- `README.md`
- `app/api/account_routes.py`
- `app/api/evaluation_lab_routes.py`
- `app/api/legal_routes.py`
- `app/api/routes.py`
- `app/api/workspace_routes.py`
- `app/config.py`
- `app/database.py`
- `app/main.py`
- `app/paths.py`
- `app/server.py`
- `app/services/reviewer_demo.py`
- `app/services/web_security.py`
- `app/templates/demo_notice.html`
- `app/templates/index.html`
- `app/templates/product_nav.html`
- `app/templates/research_workspace.html`
- `deploy/vercel-proxy/README.md`
- `docs/CURRENT_ARCHITECTURE.md`
- `docs/REVIEWER_GUIDE.md`
- `docs/UNFINISHED_FEATURES_REVIEW_20260908.md`
- `docs/reviewer/sample-contract.txt`
- `docs/superpowers/plans/2026-09-07-reviewer-demo-packaging.md`
- `pyproject.toml`
- `requirements-demo.lock`
- `tests/services/test_reviewer_demo.py`
- `tests/test_deployment_contract.py`
- `tests/test_web_security.py`
- `vercel.json`
- This verification directory.
