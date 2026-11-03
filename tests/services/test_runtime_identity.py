import json
from types import SimpleNamespace

from app.services.runtime_identity import runtime_identity, source_fingerprint


def test_source_fingerprint_includes_templates_and_untracked_python(tmp_path):
    (tmp_path / 'a.py').write_text('value = 1', encoding='utf-8')
    (tmp_path / 'page.html').write_text('VietLex', encoding='utf-8')
    first = source_fingerprint(tmp_path)
    (tmp_path / 'page.html').write_text('Changed', encoding='utf-8')
    assert source_fingerprint(tmp_path) != first
    (tmp_path / 'new.py').write_text('value = 2', encoding='utf-8')
    assert len(source_fingerprint(tmp_path)) == 64


def test_identity_is_allowlisted_and_missing_build_is_unknown(tmp_path):
    settings = SimpleNamespace(
        USE_LEGACY_FREE_PIPELINE=False,
        CHAT_OFFICIAL_DEEP_READING_ENABLED=True,
        VERTEX_EMBEDDING_MODEL='embedding',
        VERTEX_QDRANT_VECTOR_SIZE=1024,
        PINECONE_API_KEY='secret-must-not-leak',
        MONGO_URL='mongodb://private-host',
    )
    result = runtime_identity(settings, source_root=tmp_path)
    assert result['build_git_sha'] == 'unknown'
    assert result['deployment_id'] == 'unknown'
    assert result['retrieval_backend'] == 'vertex-qdrant-v3'
    assert result['chat_context_profile'] == 'official-deep-reading'
    encoded = json.dumps(result)
    assert 'secret-must-not-leak' not in encoded
    assert 'private-host' not in encoded
    before = result['configuration_sha256']
    settings.PINECONE_API_KEY = 'another-secret'
    assert runtime_identity(settings, source_root=tmp_path)['configuration_sha256'] == before
    settings.CHAT_OFFICIAL_DEEP_READING_ENABLED = False
    assert runtime_identity(settings, source_root=tmp_path)['configuration_sha256'] != before


def test_legacy_identity_never_claims_deep_profile(tmp_path):
    settings = SimpleNamespace(USE_LEGACY_FREE_PIPELINE=True,
                               CHAT_OFFICIAL_DEEP_READING_ENABLED=True,
                               VERCEL_GIT_COMMIT_SHA='a' * 40,
                               VERCEL_DEPLOYMENT_ID='dpl_example')
    result = runtime_identity(settings, source_root=tmp_path)
    assert result['retrieval_backend'] == 'pinecone-v1'
    assert result['chat_context_profile'] == 'standard'
    assert result['build_git_sha'] == 'a' * 40
    assert result['deployment_id'] == 'dpl_example'


def test_invalid_identity_values_are_not_reflected(tmp_path):
    settings = SimpleNamespace(VERCEL_GIT_COMMIT_SHA='token=private',
                               VERCEL_DEPLOYMENT_ID='<script>private</script>')
    result = runtime_identity(settings, source_root=tmp_path)
    assert result['build_git_sha'] == 'unknown'
    assert result['deployment_id'] == 'unknown'
