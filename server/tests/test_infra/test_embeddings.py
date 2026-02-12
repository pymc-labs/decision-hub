"""Tests for decision_hub.infra.embeddings -- embedding utilities."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from decision_hub.infra.embeddings import build_embedding_text, generate_and_store_skill_embedding


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
