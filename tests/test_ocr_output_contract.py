import json
import pytest


def test_ocr_schema_is_transport_configuration_not_text_to_transcribe():
    from app.services.workspace_ocr import ocr_request
    prompt, schema = ocr_request(1)
    assert '$defs' not in prompt and '"properties"' not in prompt
    assert schema['properties']['pages']['minItems'] == 1
    assert schema['properties']['pages']['maxItems'] == 1
    assert 'pages' in schema['required']


def test_ocr_rejects_schema_echo_and_incomplete_page_coverage():
    from app.services.workspace_ocr import parse_ocr_output, OCRResponse
    from app.services.workspace_documents import DocumentExtractionError
    with pytest.raises(DocumentExtractionError, match='ocr_invalid_response'):
        parse_ocr_output(json.dumps(OCRResponse.model_json_schema()), 'STOP', 1)
    with pytest.raises(DocumentExtractionError, match='ocr_invalid_response'):
        parse_ocr_output('{"pages":[{"page":2,"text":"X"}]}', 'STOP', 1)
    with pytest.raises(DocumentExtractionError, match='ocr_incomplete'):
        parse_ocr_output('{"pages":[{"page":1,"text":"X"}]}', 'MAX_TOKENS', 1)
    assert parse_ocr_output('{"pages":[{"page":1,"text":"X"}]}', 'STOP', 1).pages[0].text == 'X'
