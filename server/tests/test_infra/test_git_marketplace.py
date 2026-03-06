"""Test virtual git marketplace repo construction."""

from decision_hub.domain.marketplace import SkillPluginEntry
from decision_hub.infra.git_marketplace import build_marketplace_repo


def test_build_marketplace_repo_creates_valid_repo():
    """Build a MemoryRepo and verify it contains the expected files."""
    entries = [
        SkillPluginEntry(
            org_slug="test-org",
            skill_name="test-skill",
            version="1.0.0",
            description="A test skill",
            category="testing",
            gauntlet_grade="A",
            eval_status="passed",
            download_count=100,
        ),
    ]
    skill_md_contents = {"test-org/test-skill": "---\nname: test-skill\n---\nHello world"}

    repo = build_marketplace_repo(entries, skill_md_contents)

    # Verify the repo has a HEAD ref pointing to main
    assert repo.refs[b"refs/heads/main"] is not None

    # Read the tree and verify expected files exist
    commit = repo[repo.refs[b"refs/heads/main"]]
    tree = repo[commit.tree]

    # Collect all file paths in the tree recursively
    file_paths = _collect_paths(repo, tree, "")

    assert ".claude-plugin/marketplace.json" in file_paths
    assert "plugins/test-org--test-skill/.claude-plugin/plugin.json" in file_paths
    assert "plugins/test-org--test-skill/skills/test-skill/SKILL.md" in file_paths


def test_build_marketplace_repo_empty():
    """An empty marketplace should still produce a valid repo."""
    repo = build_marketplace_repo([], {})
    assert repo.refs[b"refs/heads/main"] is not None


def _collect_paths(repo, tree, prefix: str) -> set[str]:
    """Recursively collect all file paths in a dulwich tree."""
    paths = set()
    for item in tree.items():
        name = item.path.decode()
        full = f"{prefix}{name}" if not prefix else f"{prefix}/{name}"
        obj = repo[item.sha]
        if obj.type_name == b"tree":
            paths |= _collect_paths(repo, obj, full)
        else:
            paths.add(full)
    return paths
