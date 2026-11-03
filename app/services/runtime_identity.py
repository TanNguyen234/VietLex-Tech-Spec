"""Provider-free identity of the code and public runtime contract actually loaded.

This is an observed app-file fingerprint, not proof of a clean Git checkout.
Build identifiers are optional attestations; missing values stay unknown.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.paths import APP_ROOT


_CONFIG_FIELDS = (
    'USE_LEGACY_FREE_PIPELINE', 'SERVERLESS_ONLINE_ONLY',
    'PROVIDER_HTTP_ATTEMPT_LIMIT',
    'VERTEX_LLM_MODEL', 'ANSWER_PROMPT_VERSION', 'VERTEX_EMBEDDING_MODEL',
    'VERTEX_QDRANT_VECTOR_SIZE', 'VERTEX_QDRANT_COLLECTION_NAME',
    'DENSE_INFERENCE_MODEL', 'DENSE_VECTOR_SIZE', 'PINECONE_NAMESPACE',
    'FINAL_EVIDENCE_LIMIT', 'LLM_CONTEXT_MAX_TOKENS',
    'CHAT_OFFICIAL_DEEP_READING_ENABLED', 'CHAT_OFFICIAL_WEB_SUPPLEMENT_ENABLED',
    'RETRIEVAL_DOCUMENT_LIMIT', 'RESOLVED_DOCUMENT_LIMIT',
    'QUERY_CHUNK_MAX_TOKENS', 'QUERY_CHUNK_OVERLAP_TOKENS',
    'RERANK_INPUT_LIMIT', 'RERANK_RETURN_LIMIT', 'RERANK_MIN_SCORE',
    'QDRANT_FULL_DOC_BODY_SEARCH_ENABLED', 'SUPABASE_BODY_SEARCH_ENABLED',
    'PUBLIC_NEMO_DEFAULT_ENABLED', 'PUBLIC_GUARDRAIL_MODE',
    'GUARDRAIL_TIMEOUT_SECONDS', 'RAGAS_EVALUATION_MODE',
)
_SOURCE_SUFFIXES = {'.py', '.html', '.js', '.css', '.json', '.cjs'}


def source_fingerprint(root: Path) -> str:
    entries = [
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob('*'))
        if path.is_file() and path.suffix in _SOURCE_SUFFIXES
        and '__pycache__' not in path.parts
    ]
    return hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def _loaded_source_fingerprint() -> str:
    try:
        return source_fingerprint(APP_ROOT)
    except OSError:
        return 'unknown'


def runtime_identity(settings: Any, *, source_root: Path | None = None) -> dict[str, Any]:
    config = {name: getattr(settings, name, None) for name in _CONFIG_FIELDS}
    legacy = config['USE_LEGACY_FREE_PIPELINE']
    git_sha = str(getattr(settings, 'VERCEL_GIT_COMMIT_SHA', '') or '')
    deployment = str(getattr(settings, 'VERCEL_DEPLOYMENT_ID', '') or '')
    try:
        source_hash = source_fingerprint(source_root) if source_root is not None else _loaded_source_fingerprint()
    except OSError:
        source_hash = 'unknown'
    return {
        'schema_version': 'runtime-identity-v1',
        'public_guardrail_policy': 'enforce',
        'build_git_sha': git_sha if re.fullmatch(r'[a-fA-F0-9]{40,64}', git_sha) else 'unknown',
        'deployment_id': deployment if re.fullmatch(r'dpl_[A-Za-z0-9_-]{1,100}', deployment) else 'unknown',
        'app_source_sha256': source_hash,
        'source_scope': 'app:py,html,js,css,json,cjs',
        'configuration_sha256': hashlib.sha256(json.dumps(config, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'retrieval_backend': 'pinecone-v1' if legacy is True else 'vertex-qdrant-v3' if legacy is False else 'unknown',
        'chat_context_profile': 'official-deep-reading' if legacy is False and config['CHAT_OFFICIAL_DEEP_READING_ENABLED'] else 'standard',
    }
