import unicodedata

import pytest

from app.evaluation.answer_metrics import calculate_case_answer_metrics


@pytest.mark.parametrize("entity", ["Bộ Tài chính", "Ủy ban nhân dân", "Hà Nội"])
def test_expected_vietnamese_entity_is_scored_when_present(entity):
    response = unicodedata.normalize("NFD", entity.upper())
    result = calculate_case_answer_metrics(
        response, entity, "fact", [entity], expected_entities=[entity]
    )
    assert result["entity_precision"] == 1.0
    assert result["entity_recall"] == 1.0


def test_entity_metrics_count_extra_names_missing_labels_and_word_boundaries():
    def metrics(response):
        return calculate_case_answer_metrics(
            response, "Bộ Tài chính", "fact", ["context"],
            expected_entities=["Bộ Tài chính"],
        )

    extra = metrics("Bộ Tài chính; Hà Nội")
    assert (extra["entity_precision"], extra["entity_recall"]) == (0.5, 1.0)
    missing = metrics("Hà Nội")
    assert (missing["entity_precision"], missing["entity_recall"]) == (0.0, 0.0)
    assert metrics("Bộ Tài chínhs")["entity_recall"] == 0.0
    skipped = calculate_case_answer_metrics("Hà Nội", "Hà Nội", "fact", [])
    assert skipped["entity_precision"] is None
    assert skipped["metric_skip_reasons"]["entity_precision"] == "no_expected_entities"


def test_answer_metrics_identify_the_changed_entity_contract():
    result = calculate_case_answer_metrics("Hà Nội", "Hà Nội", "fact", [])
    assert result["answer_metric_version"] == "3.3.0"
def test_entity_precision_does_not_hide_an_extra_name_next_to_a_gold_mention():
    result = calculate_case_answer_metrics(
        'Hà Nội Paris', 'Hà Nội', 'fact', ['context'], expected_entities=['Hà Nội']
    )
    assert (result['entity_precision'], result['entity_recall']) == (0.5, 1.0)
