import sys
import os
import pytest
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ingestion.schemas import LegalDocumentSchema, ProcessingDisposition
from app.ingestion.postprocessing.pipeline import LegalPreprocessingPipeline

@pytest.fixture
def pipeline():
    return LegalPreprocessingPipeline()

def test_article_clause_point_parsing(pipeline):
    doc_text = """
    NGHỊ ĐỊNH
    Số: 52/2006/NĐ-CP
    Chương I
    QUY ĐỊNH CHUNG
    Mục 1
    PHẠM VI
    Điều 1. Phạm vi điều chỉnh
    Luật này quy định về hoạt động đầu tư.
    1. Khoản thứ nhất về áp dụng.
    a) Điểm a quy định chi tiết.
    b) Điểm b quy định chi tiết.
    2. Khoản thứ hai áp dụng theo khoản 1 Điều 5.
    Điều 2. Đối tượng áp dụng
    Theo Điều 10 của Luật này, đối tượng bao gồm...
    """
    doc = LegalDocumentSchema(
        source_id="test_01",
        source="moj.gov.vn",
        url="https://moj.gov.vn/test",
        title="Nghị định quy định chi tiết",
        full_text=doc_text
    )

    res = pipeline.process(doc)
    assert res.metadata.official_number.value == "52/2006/NĐ-CP"
    assert res.metadata.document_type.value == "Nghị định"
    assert res.validation.status == "PASS"
    assert len(res.chunks) > 0

def test_missing_and_duplicate_sequence(pipeline):
    doc_text = """
    Điều 1. Đầu tiên
    Nội dung điều 1
    Điều 2. Thứ hai
    Nội dung điều 2
    Điều 2. Trùng lặp
    Nội dung trùng điều 2
    Điều 5. Nhảy số
    Nội dung điều 5
    """
    doc = LegalDocumentSchema(
        source_id="test_02",
        source="vbpl.vn",
        url="https://vbpl.vn/test",
        title="Luật Kiểm thử Dãy số",
        full_text=doc_text
    )

    res = pipeline.process(doc)
    assert len(res.validation.duplicate_numberings) > 0
    assert len(res.validation.missing_sequences) > 0

def test_empty_full_text(pipeline):
    doc = LegalDocumentSchema(
        source_id="test_empty",
        source="test",
        url="https://test.com",
        title="Empty Doc",
        full_text=""
    )
    res = pipeline.process(doc)
    assert res.validation.char_count_raw == 0

def test_real_sample_moj(pipeline):
    sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "scrapling_raw", "trial_samples", "moj_sample.json")
    if os.path.exists(sample_path):
        with open(sample_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc = LegalDocumentSchema(**data)
        res = pipeline.process(doc)
        assert res.source_id == data["source_id"]
        assert res.audit_id
        if res.disposition in {ProcessingDisposition.PASS, ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA}:
            assert len(res.chunks) > 0
            assert all(chunk.audit_id == res.audit_id for chunk in res.chunks)
        else:
            assert len(res.chunks) == 0
            assert res.validation.errors

def test_real_sample_vbpl(pipeline):
    sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "scrapling_raw", "trial_samples", "vbpl_sample.json")
    if os.path.exists(sample_path):
        with open(sample_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc = LegalDocumentSchema(**data)
        res = pipeline.process(doc)
        assert res.source_id == data["source_id"]
        assert res.audit_id
        if res.disposition in {ProcessingDisposition.PASS, ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA}:
            assert len(res.chunks) > 0
            assert all(chunk.audit_id == res.audit_id for chunk in res.chunks)
        else:
            assert len(res.chunks) == 0
            assert res.validation.errors

def test_real_sample_vietlaw(pipeline):
    sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "scrapling_raw", "trial_samples", "vietlaw_sample.json")
    if os.path.exists(sample_path):
        with open(sample_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc = LegalDocumentSchema(**data)
        res = pipeline.process(doc)
        assert res.source_id == data["source_id"]
        assert res.audit_id
        if res.disposition in {ProcessingDisposition.PASS, ProcessingDisposition.PASS_WITH_UNKNOWN_METADATA}:
            assert len(res.chunks) > 0
            assert all(chunk.audit_id == res.audit_id for chunk in res.chunks)
        else:
            assert len(res.chunks) == 0
            assert res.validation.errors
