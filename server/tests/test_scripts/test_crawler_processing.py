"""Tests for crawler parallel skill processing."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import sqlalchemy.exc

from decision_hub.scripts.crawler.processing import (
    _prepare_skill,
    _publish_one_skill,
    process_repo_on_modal,
)
from tests.factories import make_org

# ---------------------------------------------------------------------------
# _publish_one_skill return values
# ---------------------------------------------------------------------------

_PROCESSING = "decision_hub.scripts.crawler.processing"


def _make_engine_mock():
    """Create a mock engine whose connect() works as a context manager."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine


@pytest.fixture
def mock_skill_deps():
    """Patch all heavy dependencies used by _publish_one_skill.

    Top-level imports on the processing module are patched via the processing
    module namespace. Locally-imported functions (inside _prepare_skill /
    _finalize_skill) are patched at their source modules.
    """
    patches = {
        # Locally imported inside _prepare_skill
        "parse_skill_md": patch("dhub_core.manifest.parse_skill_md"),
        # Top-level imports on processing module
        "validate_skill_name": patch(f"{_PROCESSING}.validate_skill_name"),
        "create_zip": patch(f"{_PROCESSING}.create_zip"),
        "extract_body": patch(f"{_PROCESSING}.extract_body"),
        "extract_description": patch(f"{_PROCESSING}.extract_description"),
        "extract_for_evaluation": patch(f"{_PROCESSING}.extract_for_evaluation"),
        # DB functions (locally imported inside _prepare_skill / _finalize_skill)
        "find_skill": patch("decision_hub.infra.database.find_skill"),
        "find_version": patch("decision_hub.infra.database.find_version"),
        "insert_skill": patch("decision_hub.infra.database.insert_skill"),
        "insert_version": patch("decision_hub.infra.database.insert_version"),
        "insert_audit_log": patch("decision_hub.infra.database.insert_audit_log"),
        "resolve_latest_version": patch("decision_hub.infra.database.resolve_latest_version"),
        "update_skill_category": patch("decision_hub.infra.database.update_skill_category"),
        "update_skill_description": patch("decision_hub.infra.database.update_skill_description"),
        "update_skill_source_repo_url": patch("decision_hub.infra.database.update_skill_source_repo_url"),
        "compute_checksum": patch("decision_hub.infra.storage.compute_checksum"),
        "upload_skill_zip": patch("decision_hub.infra.storage.upload_skill_zip"),
        # Locally imported inside _publish_one_skill / _finalize_skill
        "run_gauntlet_pipeline": patch("decision_hub.api.registry_service.run_gauntlet_pipeline"),
        "classify_skill_category": patch("decision_hub.api.registry_service.classify_skill_category"),
        "generate_and_store_skill_embedding": patch("decision_hub.infra.embeddings.generate_and_store_skill_embedding"),
    }
    mocks = {}
    for name, p in patches.items():
        mocks[name] = p.start()

    # Set up sensible defaults for the manifest mock
    manifest_mock = MagicMock()
    manifest_mock.name = "test-skill"
    manifest_mock.description = "A test skill"
    manifest_mock.allowed_tools = []
    mocks["parse_skill_md"].return_value = manifest_mock
    mocks["create_zip"].return_value = b"fake-zip"
    mocks["compute_checksum"].return_value = "checksum-abc"
    mocks["extract_for_evaluation"].return_value = ("", {}, "", [])

    yield mocks

    for p in patches.values():
        p.stop()


class TestPrepareSkillReturnsStatus:
    """Verify _prepare_skill returns the correct status or _SkillPrep."""

    def test_returns_skipped_on_checksum_match(self, mock_skill_deps, tmp_path):
        """When the latest version has the same checksum, returns 'skipped'."""
        conn = MagicMock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock

        latest_mock = MagicMock()
        latest_mock.checksum = "checksum-abc"  # matches compute_checksum
        latest_mock.semver = "0.1.0"
        mock_skill_deps["resolve_latest_version"].return_value = latest_mock

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        result = _prepare_skill(conn, MagicMock(), org, skill_dir)
        assert result == "skipped"

    def test_returns_skipped_on_existing_version(self, mock_skill_deps, tmp_path):
        """When the computed version already exists, returns 'skipped'."""
        conn = MagicMock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock
        mock_skill_deps["resolve_latest_version"].return_value = None
        mock_skill_deps["find_version"].return_value = MagicMock()  # version exists

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        result = _prepare_skill(conn, MagicMock(), org, skill_dir)
        assert result == "skipped"

    def test_returns_failed_on_extraction_error(self, mock_skill_deps, tmp_path):
        """When extract_for_evaluation raises ValueError, returns 'failed'."""
        conn = MagicMock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock
        mock_skill_deps["resolve_latest_version"].return_value = None
        mock_skill_deps["find_version"].return_value = None
        mock_skill_deps["extract_for_evaluation"].side_effect = ValueError("bad zip")

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        result = _prepare_skill(conn, MagicMock(), org, skill_dir)
        assert result == "failed"

    def test_returns_skill_prep_when_ready(self, mock_skill_deps, tmp_path):
        """When skill needs gauntlet, returns _SkillPrep with all data."""
        from decision_hub.scripts.crawler.processing import _SkillPrep

        conn = MagicMock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock
        mock_skill_deps["resolve_latest_version"].return_value = None
        mock_skill_deps["find_version"].return_value = None

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        result = _prepare_skill(conn, MagicMock(), org, skill_dir)
        assert isinstance(result, _SkillPrep)
        assert result.name == "test-skill"
        assert result.version == "0.1.0"
        assert result.skill_id == skill_mock.id


class TestPublishOneSkillReturnsStatus:
    """Verify _publish_one_skill returns the correct status string."""

    def test_returns_skipped_on_checksum_match(self, mock_skill_deps, tmp_path):
        """When the latest version has the same checksum, returns 'skipped'."""
        engine = _make_engine_mock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock

        latest_mock = MagicMock()
        latest_mock.checksum = "checksum-abc"  # matches compute_checksum
        latest_mock.semver = "0.1.0"
        mock_skill_deps["resolve_latest_version"].return_value = latest_mock

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        status = _publish_one_skill(
            engine,
            MagicMock(),
            MagicMock(),
            org,
            skill_dir,
        )
        assert status == "skipped"

    def test_returns_quarantined_on_grade_f(self, mock_skill_deps, tmp_path):
        """When the gauntlet fails (grade F), returns 'quarantined'."""
        engine = _make_engine_mock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock
        mock_skill_deps["resolve_latest_version"].return_value = None
        mock_skill_deps["find_version"].return_value = None

        report = MagicMock()
        report.passed = False
        report.grade = "F"
        mock_skill_deps["run_gauntlet_pipeline"].return_value = (report, {}, "reasoning")

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        status = _publish_one_skill(
            engine,
            MagicMock(),
            MagicMock(),
            org,
            skill_dir,
        )
        assert status == "quarantined"

    def test_returns_published_on_grade_a(self, mock_skill_deps, tmp_path):
        """When the gauntlet passes, returns 'published'."""
        engine = _make_engine_mock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock
        mock_skill_deps["resolve_latest_version"].return_value = None
        mock_skill_deps["find_version"].return_value = None

        report = MagicMock()
        report.passed = True
        report.grade = "A"
        report.gauntlet_summary = "All checks passed"
        mock_skill_deps["run_gauntlet_pipeline"].return_value = (report, {}, "reasoning")
        mock_skill_deps["classify_skill_category"].return_value = "devops"
        mock_skill_deps["insert_version"].return_value = MagicMock(id=uuid4())

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        status = _publish_one_skill(
            engine,
            MagicMock(),
            MagicMock(),
            org,
            skill_dir,
        )
        assert status == "published"

    def test_version_race_raises_version_conflict_error(self, mock_skill_deps, tmp_path):
        """When insert_version hits a UniqueViolation, raises VersionConflictError.

        This lets the caller at process_repo_on_modal catch it and return
        'skipped' instead of logging a noisy WARNING with full traceback.
        """
        from decision_hub.domain.publish_pipeline import VersionConflictError

        engine = _make_engine_mock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock
        mock_skill_deps["resolve_latest_version"].return_value = None
        mock_skill_deps["find_version"].return_value = None

        report = MagicMock()
        report.passed = True
        report.grade = "A"
        report.gauntlet_summary = "All checks passed"
        mock_skill_deps["run_gauntlet_pipeline"].return_value = (report, {}, "reasoning")
        mock_skill_deps["classify_skill_category"].return_value = "devops"
        mock_skill_deps["insert_version"].side_effect = sqlalchemy.exc.IntegrityError(
            "INSERT ...", {}, Exception("duplicate key")
        )

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        with pytest.raises(VersionConflictError):
            _publish_one_skill(
                engine,
                MagicMock(),
                MagicMock(),
                org,
                skill_dir,
            )

    def test_returns_failed_on_extraction_error(self, mock_skill_deps, tmp_path):
        """When extract_for_evaluation raises ValueError, returns 'failed'."""
        engine = _make_engine_mock()
        org = make_org()

        skill_mock = MagicMock()
        skill_mock.id = uuid4()
        skill_mock.source_repo_url = None
        mock_skill_deps["find_skill"].return_value = skill_mock
        mock_skill_deps["resolve_latest_version"].return_value = None
        mock_skill_deps["find_version"].return_value = None
        mock_skill_deps["extract_for_evaluation"].side_effect = ValueError("bad zip")

        skill_dir = tmp_path / "skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# Test Skill\nA test skill")

        status = _publish_one_skill(
            engine,
            MagicMock(),
            MagicMock(),
            org,
            skill_dir,
        )
        assert status == "failed"


# ---------------------------------------------------------------------------
# Parallel processing result collection
# ---------------------------------------------------------------------------


class TestParallelProcessingCountCollection:
    """Verify that process_repo_on_modal correctly collects parallel results."""

    @patch(f"{_PROCESSING}.discover_skills")
    @patch(f"{_PROCESSING}.clone_repo")
    @patch("decision_hub.settings.create_settings")
    @patch("decision_hub.infra.database.create_engine")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.infra.database.upsert_user")
    @patch("decision_hub.infra.database.find_org_by_slug")
    @patch("decision_hub.infra.database.insert_organization")
    @patch("decision_hub.infra.database.insert_org_member")
    @patch("decision_hub.infra.database.find_org_member")
    @patch(f"{_PROCESSING}._publish_one_skill")
    def test_mixed_results_counted_correctly(
        self,
        mock_publish,
        mock_find_member,
        mock_insert_member,
        mock_insert_org,
        mock_find_org,
        mock_upsert_user,
        mock_create_s3,
        mock_create_engine,
        mock_create_settings,
        mock_clone_repo,
        mock_discover,
        tmp_path,
    ):
        """Simulate 5 skills with mixed statuses and verify counts."""
        # Set up settings mock
        settings = MagicMock()
        settings.database_url = "postgresql://test"
        settings.aws_region = "us-east-1"
        settings.aws_access_key_id = "key"
        settings.aws_secret_access_key = "secret"
        settings.s3_endpoint_url = ""
        settings.crawler_parallel_skills = 3
        mock_create_settings.return_value = settings

        # Set up engine mock with working connect() context manager
        engine = _make_engine_mock()
        mock_create_engine.return_value = engine

        # Set up org
        org = make_org()
        mock_find_org.return_value = org
        mock_find_member.return_value = MagicMock()

        # Set up clone
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        mock_clone_repo.return_value = repo_root

        # Set up skill dirs
        skill_dirs = []
        for i in range(5):
            sd = tmp_path / f"skill-{i}"
            sd.mkdir()
            (sd / "SKILL.md").write_text(f"# Skill {i}\nDescription {i}")
            skill_dirs.append(sd)
        mock_discover.return_value = skill_dirs

        # Simulate mixed results: 2 published, 1 skipped, 1 quarantined, 1 failed
        statuses = ["published", "published", "skipped", "quarantined"]
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 4:
                raise RuntimeError("gauntlet exploded")
            return statuses[idx]

        mock_publish.side_effect = side_effect

        repo_dict = {
            "full_name": "test-org/test-repo",
            "owner_login": "test-org",
            "owner_type": "Organization",
            "clone_url": "https://github.com/test-org/test-repo.git",
        }

        with patch("subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = MagicMock(returncode=0, stdout="abc123\n")
            result = process_repo_on_modal(repo_dict, str(uuid4()), "fake-token")

        assert result["skills_published"] == 2
        assert result["skills_skipped"] == 1
        assert result["skills_quarantined"] == 1
        assert result["skills_failed"] == 1
        assert result["status"] == "ok"

    @patch(f"{_PROCESSING}.discover_skills")
    @patch(f"{_PROCESSING}.clone_repo")
    @patch("decision_hub.settings.create_settings")
    @patch("decision_hub.infra.database.create_engine")
    @patch("decision_hub.infra.storage.create_s3_client")
    @patch("decision_hub.infra.database.upsert_user")
    @patch("decision_hub.infra.database.find_org_by_slug")
    @patch("decision_hub.infra.database.find_org_member")
    @patch(f"{_PROCESSING}._publish_one_skill")
    def test_all_skills_skipped(
        self,
        mock_publish,
        mock_find_member,
        mock_find_org,
        mock_upsert_user,
        mock_create_s3,
        mock_create_engine,
        mock_create_settings,
        mock_clone_repo,
        mock_discover,
        tmp_path,
    ):
        """When all skills are skipped, counts reflect that."""
        settings = MagicMock()
        settings.database_url = "postgresql://test"
        settings.aws_region = "us-east-1"
        settings.aws_access_key_id = "key"
        settings.aws_secret_access_key = "secret"
        settings.s3_endpoint_url = ""
        settings.crawler_parallel_skills = 5
        mock_create_settings.return_value = settings

        engine = _make_engine_mock()
        mock_create_engine.return_value = engine

        org = make_org()
        mock_find_org.return_value = org
        mock_find_member.return_value = MagicMock()

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        mock_clone_repo.return_value = repo_root

        skill_dirs = []
        for i in range(3):
            sd = tmp_path / f"skill-{i}"
            sd.mkdir()
            (sd / "SKILL.md").write_text(f"# Skill {i}\nDesc {i}")
            skill_dirs.append(sd)
        mock_discover.return_value = skill_dirs

        mock_publish.return_value = "skipped"

        repo_dict = {
            "full_name": "test-org/test-repo",
            "owner_login": "test-org",
            "owner_type": "Organization",
            "clone_url": "https://github.com/test-org/test-repo.git",
        }

        with patch("subprocess.run") as mock_subprocess:
            mock_subprocess.return_value = MagicMock(returncode=0, stdout="abc123\n")
            result = process_repo_on_modal(repo_dict, str(uuid4()), "fake-token")

        assert result["skills_published"] == 0
        assert result["skills_skipped"] == 3
        assert result["skills_quarantined"] == 0
        assert result["skills_failed"] == 0
