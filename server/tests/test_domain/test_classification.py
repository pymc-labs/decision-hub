"""Tests for domain/classification.py -- taxonomy, parsing, and classification."""

import json

import pytest

from decision_hub.domain.classification import (
    ALL_SUBCATEGORIES,
    CATEGORY_TAXONOMY,
    DEFAULT_CATEGORY,
    SUBCATEGORY_TO_GROUP,
    SkillClassification,
    build_taxonomy_prompt_fragment,
    parse_classification_response,
)


class TestTaxonomy:
    def test_all_subcategories_non_empty(self):
        assert len(ALL_SUBCATEGORIES) > 0

    def test_default_category_in_taxonomy(self):
        assert DEFAULT_CATEGORY in ALL_SUBCATEGORIES

    def test_reverse_lookup_covers_all_subcategories(self):
        for sub in ALL_SUBCATEGORIES:
            assert sub in SUBCATEGORY_TO_GROUP

    def test_every_group_has_subcategories(self):
        for group, subs in CATEGORY_TAXONOMY.items():
            assert len(subs) > 0, f"Group {group} has no subcategories"

    def test_no_duplicate_subcategories(self):
        all_subs = [sub for subs in CATEGORY_TAXONOMY.values() for sub in subs]
        assert len(all_subs) == len(set(all_subs)), "Duplicate subcategories found"


class TestBuildTaxonomyPromptFragment:
    def test_contains_all_groups(self):
        fragment = build_taxonomy_prompt_fragment()
        for group in CATEGORY_TAXONOMY:
            assert group in fragment

    def test_contains_all_subcategories(self):
        fragment = build_taxonomy_prompt_fragment()
        for sub in ALL_SUBCATEGORIES:
            assert sub in fragment


class TestParseClassificationResponse:
    def test_valid_json(self):
        response = json.dumps({"category": "Backend & APIs", "confidence": 0.95})
        result = parse_classification_response(response)
        assert result.category == "Backend & APIs"
        assert result.group == "Development"
        assert result.confidence == 0.95

    def test_valid_json_with_code_fences(self):
        response = '```json\n{"category": "AI & LLM", "confidence": 0.8}\n```'
        result = parse_classification_response(response)
        assert result.category == "AI & LLM"
        assert result.group == "AI & Automation"
        assert result.confidence == 0.8

    def test_invalid_category_falls_back(self):
        response = json.dumps({"category": "Nonexistent Category", "confidence": 0.9})
        result = parse_classification_response(response)
        assert result.category == DEFAULT_CATEGORY
        assert result.confidence == 0.0

    def test_missing_category_key(self):
        response = json.dumps({"confidence": 0.5})
        result = parse_classification_response(response)
        assert result.category == DEFAULT_CATEGORY

    def test_invalid_json(self):
        response = "not valid json at all"
        result = parse_classification_response(response)
        assert result.category == DEFAULT_CATEGORY
        assert result.confidence == 0.0

    def test_empty_string(self):
        result = parse_classification_response("")
        assert result.category == DEFAULT_CATEGORY

    def test_all_valid_subcategories_accepted(self):
        for sub in ALL_SUBCATEGORIES:
            response = json.dumps({"category": sub, "confidence": 0.7})
            result = parse_classification_response(response)
            assert result.category == sub
            assert result.group == SUBCATEGORY_TO_GROUP[sub]

    def test_confidence_defaults_to_zero(self):
        response = json.dumps({"category": "Testing & QA"})
        result = parse_classification_response(response)
        assert result.confidence == 0.0
        assert result.category == "Testing & QA"
