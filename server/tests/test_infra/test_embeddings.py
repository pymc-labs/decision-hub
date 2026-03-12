"""Tests for decision_hub.infra.embeddings -- embedding utilities."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import respx

from decision_hub.infra.embeddings import build_embedding_text, embed_query, generate_and_store_skill_embedding
from decision_hub.infra.gemini import create_gemini_client


class TestBuildEmbeddingText:
    """Tests for build_embedding_text()."""

    def test_all_fields(self):
        result = build_embedding_text("my-skill", "acme", "Data Science", "A great skill")
        assert result == "my-skill | acme | Data Science | A great skill"

    def test_empty_optional_fields(self):
        result = build_embedding_text("my-skill", "", "", "")
        assert result == "my-skill"

    def test_partial_fields(self):
        result = build_embedding_text("my-skill", "acme", "", "Description only")
        assert result == "my-skill | acme | Description only"

    def test_name_and_org_only(self):
        result = build_embedding_text("my-skill", "acme", "", "")
        assert result == "my-skill | acme"

    def test_name_and_category_only(self):
        result = build_embedding_text("my-skill", "", "Testing", "")
        assert result == "my-skill | Testing"


class TestGenerateAndStoreSkillEmbedding:
    """Tests for generate_and_store_skill_embedding() -- fail-open behavior."""

    def test_no_api_key_skips(self):
        """Should silently skip when google_api_key is empty."""
        settings = MagicMock()
        settings.google_api_key = ""
        conn = MagicMock()

        # Should not raise
        generate_and_store_skill_embedding(conn, uuid4(), "skill", "org", "cat", "desc", settings)

    @patch("decision_hub.infra.embeddings.embed_query", side_effect=Exception("API down"))
    @patch("decision_hub.infra.gemini.create_gemini_client", return_value={"api_key": "k", "base_url": "u"})
    def test_swallows_errors(self, _mock_client, _mock_embed):
        """Should log warning but not raise on embedding failure."""
        settings = MagicMock()
        settings.google_api_key = "test-key"
        settings.embedding_model = "gemini-embedding-001"
        conn = MagicMock()

        # Should not raise
        generate_and_store_skill_embedding(conn, uuid4(), "skill", "org", "cat", "desc", settings)

    @patch("decision_hub.infra.embeddings.update_skill_embedding")
    @patch("decision_hub.infra.embeddings.embed_query", return_value=[0.1] * 768)
    @patch("decision_hub.infra.gemini.create_gemini_client", return_value={"api_key": "k", "base_url": "u"})
    def test_stores_embedding_on_success(self, _mock_client, _mock_embed, mock_store):
        """Should call update_skill_embedding with the generated vector."""
        settings = MagicMock()
        settings.google_api_key = "test-key"
        settings.embedding_model = "gemini-embedding-001"
        conn = MagicMock()
        skill_id = uuid4()

        generate_and_store_skill_embedding(conn, skill_id, "skill", "org", "cat", "desc", settings)

        mock_store.assert_called_once_with(conn, skill_id, [0.1] * 768)


_EMBED_MODEL = "gemini-embedding-001"
_EMBED_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_EMBED_MODEL}:embedContent"


@pytest.fixture
def gemini_client() -> dict:
    return create_gemini_client("test-api-key")


class TestEmbedQueryRetry:
    """Tests for embed_query retry with exponential backoff on transient errors."""

    @respx.mock
    def test_retries_on_503_then_succeeds(self, gemini_client: dict) -> None:
        route = respx.post(_EMBED_URL).mock(
            side_effect=[
                httpx.Response(503, text="Unavailable"),
                httpx.Response(200, json={"embedding": {"values": [0.1, 0.2]}}),
            ]
        )
        with (
            patch("decision_hub.infra.gemini.time.sleep") as mock_sleep,
            patch("decision_hub.infra.gemini.random.uniform", return_value=0.25),
        ):
            result = embed_query(gemini_client, "test", _EMBED_MODEL, 768, max_retries=3)
        assert result == [0.1, 0.2]
        assert route.call_count == 2
        mock_sleep.assert_called_once_with(1.25)

    @respx.mock
    def test_retries_on_429_with_backoff(self, gemini_client: dict) -> None:
        route = respx.post(_EMBED_URL).mock(
            side_effect=[
                httpx.Response(429, text="Rate limited"),
                httpx.Response(429, text="Rate limited"),
                httpx.Response(200, json={"embedding": {"values": [0.3]}}),
            ]
        )
        with (
            patch("decision_hub.infra.gemini.time.sleep") as mock_sleep,
            patch("decision_hub.infra.gemini.random.uniform", return_value=0.25),
        ):
            result = embed_query(gemini_client, "test", _EMBED_MODEL, 768, max_retries=3)
        assert result == [0.3]
        assert route.call_count == 3
        assert mock_sleep.call_args_list == [
            ((1.25,),),
            ((2.25,),),
        ]

    @respx.mock
    def test_raises_after_max_retries_exhausted(self, gemini_client: dict) -> None:
        respx.post(_EMBED_URL).mock(return_value=httpx.Response(503, text="Unavailable"))
        with patch("decision_hub.infra.gemini.time.sleep"), pytest.raises(httpx.HTTPStatusError) as exc_info:
            embed_query(gemini_client, "test", _EMBED_MODEL, 768, max_retries=2)
        assert exc_info.value.response.status_code == 503

    @respx.mock
    def test_non_retriable_error_raises_immediately(self, gemini_client: dict) -> None:
        route = respx.post(_EMBED_URL).mock(return_value=httpx.Response(400, text="Bad Request"))
        with (
            patch("decision_hub.infra.gemini.time.sleep") as mock_sleep,
            pytest.raises(httpx.HTTPStatusError) as exc_info,
        ):
            embed_query(gemini_client, "test", _EMBED_MODEL, 768, max_retries=3)
        assert exc_info.value.response.status_code == 400
        assert route.call_count == 1
        mock_sleep.assert_not_called()
