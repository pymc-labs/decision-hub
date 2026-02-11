"""Tests for domain/classification.py -- taxonomy prompt building and response parsing."""

from decision_hub.domain.classification import (
    build_taxonomy_prompt_fragment,
    parse_classification_response,
)
from dhub_core.taxonomy import (
    ALL_SUBCATEGORIES,
    CATEGORY_TAXONOMY,
    DEFAULT_CATEGORY,
    SUBCATEGORY_TO_GROUP,
)


def test_build_taxonomy_prompt_fragment_includes_all_groups():
    fragment = build_taxonomy_prompt_fragment()
    for group in CATEGORY_TAXONOMY:
        assert group in fragment


def test_build_taxonomy_prompt_fragment_includes_all_subcategories():
    fragment = build_taxonomy_prompt_fragment()
    for sub in ALL_SUBCATEGORIES:
        assert sub in fragment


def test_parse_valid_response():
    raw = '{"category": "Backend & APIs", "confidence": 0.95}'
    result = parse_classification_response(raw)
    assert result.category == "Backend & APIs"
    assert result.group == "Development"
    assert result.confidence == 0.95


def test_parse_response_with_code_fences():
    raw = '```json\n{"category": "AI & LLM", "confidence": 0.8}\n```'
    result = parse_classification_response(raw)
    assert result.category == "AI & LLM"
    assert result.group == "AI & Automation"
    assert result.confidence == 0.8


def test_parse_response_invalid_json_returns_default():
    raw = "This is not JSON at all"
    result = parse_classification_response(raw)
    assert result.category == DEFAULT_CATEGORY
    assert result.group == SUBCATEGORY_TO_GROUP[DEFAULT_CATEGORY]
    assert result.confidence == 0.0


def test_parse_response_unknown_category_returns_default():
    raw = '{"category": "Nonexistent Category", "confidence": 0.9}'
    result = parse_classification_response(raw)
    assert result.category == DEFAULT_CATEGORY
    assert result.confidence == 0.0


def test_parse_response_missing_confidence():
    raw = '{"category": "Data & Database"}'
    result = parse_classification_response(raw)
    assert result.category == "Data & Database"
    assert result.group == "Data & Documents"
    assert result.confidence == 0.0


def test_parse_response_non_dict_json_returns_default():
    """LLMs sometimes wrap output in arrays — should fall back gracefully."""
    raw = '[{"category": "AI & LLM"}]'
    result = parse_classification_response(raw)
    assert result.category == DEFAULT_CATEGORY
    assert result.confidence == 0.0


def test_parse_response_json_string_returns_default():
    raw = '"Backend & APIs"'
    result = parse_classification_response(raw)
    assert result.category == DEFAULT_CATEGORY
    assert result.confidence == 0.0


def test_parse_response_empty_string():
    result = parse_classification_response("")
    assert result.category == DEFAULT_CATEGORY


def test_all_subcategories_have_groups():
    """Every subcategory in the taxonomy maps to a group."""
    for sub in ALL_SUBCATEGORIES:
        assert sub in SUBCATEGORY_TO_GROUP, f"{sub} missing from SUBCATEGORY_TO_GROUP"


def test_taxonomy_group_count():
    assert len(CATEGORY_TAXONOMY) == 7


def test_taxonomy_subcategory_count():
    total = sum(len(subs) for subs in CATEGORY_TAXONOMY.values())
    assert total == 24
