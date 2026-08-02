import importlib


def _sparse_module():
    return importlib.import_module("app.ingestion.sparse_encoder")


def test_document_and_query_use_identical_term_ids() -> None:
    sparse = _sparse_module()
    encoder = sparse.SparseEncoder(average_document_length=100.0)

    document = encoder.encode_document("thuế thu nhập thuế")
    query = encoder.encode_query("thuế thu nhập")

    assert set(query.indices).issubset(set(document.indices))
    assert document.indices == sorted(document.indices)


def test_sparse_text_limit_bounds_index_growth() -> None:
    sparse = _sparse_module()
    encoder = sparse.SparseEncoder(
        average_document_length=100.0,
        max_terms=32,
    )

    vector = encoder.encode_document(
        " ".join(f"từ{index}" for index in range(500))
    )

    assert len(vector.indices) <= 32
    assert len(vector.indices) == len(vector.values)


def test_document_vector_caps_nonzeros_and_preserves_leading_terms() -> None:
    sparse = _sparse_module()
    encoder = sparse.SparseEncoder(
        average_document_length=100.0,
        max_terms=500,
        max_nonzero_terms=64,
        protected_leading_terms=16,
    )
    text = " ".join(f"term{index}" for index in range(300))

    vector = encoder.encode_document(text)
    protected_ids = {
        sparse.stable_term_id(f"term{index}")
        for index in range(16)
    }

    assert len(vector.indices) == 64
    assert protected_ids.issubset(set(vector.indices))
