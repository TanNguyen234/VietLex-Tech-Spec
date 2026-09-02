# Vercel Online-Only SSR Implementation Plan

> **For agentic workers:** Execute inline in the current worktree. Do not create a worktree, commit, push, ingest, migrate, or delete remote data.

**Goal:** Deploy the existing FastAPI/Jinja SSR application directly to Vercel using only online Qdrant, Vertex, Pinecone, and MongoDB services.

**Architecture:** Export the existing `app.main:app` from a Vercel-supported FastAPI entrypoint. Use a runtime-only `pyproject.toml`, keep evaluation dependencies in the existing local requirements file, and exclude local corpus/evidence directories from the function bundle.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Vercel Python Functions, Qdrant, Vertex AI, Pinecone, MongoDB.

## Global Constraints

- `USE_LEGACY_FREE_PIPELINE=false` remains the only selector for Vertex/Qdrant v3.
- Do not package `data/`, `.env`, credentials, tests, reports, or local output.
- Preserve the user's dirty worktree and do not commit or push.
- Deployment proof requires live HTTP output; configuration alone is not proof.

---

### Task 1: Direct FastAPI serverless contract

**Files:**
- Create: `app/server.py`
- Create: `pyproject.toml`
- Modify: `vercel.json`
- Modify: `.vercelignore`
- Modify: `tests/test_deployment_contract.py`

**Interfaces:**
- Consumes: `app.main.app`
- Produces: Vercel-supported `app.server.app` ASGI entrypoint

- [ ] Change the deployment test to require the direct ASGI entrypoint, a 300-second duration, online runtime dependencies, and corpus/secret exclusions.
- [ ] Run `\.\.venv\Scripts\python.exe -B -m pytest tests/test_deployment_contract.py -q` and observe RED against the proxy configuration.
- [ ] Add the minimal entrypoint/configuration files.
- [ ] Run the focused deployment test and require GREEN.

### Task 2: Keep ingestion-only PyArrow out of web startup

**Files:**
- Modify: `app/ingestion/content_store.py`
- Modify: `tests/test_deployment_contract.py`

**Interfaces:**
- Consumes: ingestion functions `_import_metadata` and `_import_contents`
- Produces: unchanged ingestion behavior with lazy `pyarrow.parquet` imports

- [ ] Extend the subprocess import test to assert that importing the web app does not import `pyarrow`.
- [ ] Run the focused test and observe RED.
- [ ] Move PyArrow imports into the two ingestion-only functions.
- [ ] Run focused tests, inspect the stable diff, then run the full suite once.
- [ ] Link/create the Vercel project, add production secrets without logging values, deploy production, and verify `/healthz`, `/`, and one bounded online chat request.

Commit and push are **NOT AUTHORIZED** and remain **NOT RUN**.
