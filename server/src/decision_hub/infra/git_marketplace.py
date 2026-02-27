"""Virtual git marketplace — builds an in-memory git repo from DB skill data.

Claude Code expects marketplaces to be git repos. Instead of maintaining a
physical GitHub repo, we build a dulwich MemoryRepo on-the-fly and serve it
via the Git Smart HTTP protocol. The repo contains:

  .claude-plugin/marketplace.json
  plugins/<org>--<skill>/.claude-plugin/plugin.json
  plugins/<org>--<skill>/skills/<skill>/SKILL.md
"""

from __future__ import annotations

import time

from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import MemoryRepo

from decision_hub.domain.marketplace import (
    SkillPluginEntry,
    build_marketplace_json,
    build_plugin_json,
    plugin_name_from_skill,
)


def build_marketplace_repo(
    entries: list[SkillPluginEntry],
    skill_md_contents: dict[str, str],
) -> MemoryRepo:
    """Build a MemoryRepo containing the full marketplace structure.

    Args:
        entries: Skill metadata for marketplace entries.
        skill_md_contents: Map of "org_slug/skill_name" -> SKILL.md content.

    Returns:
        A dulwich MemoryRepo with a single commit on refs/heads/main.
    """
    repo = MemoryRepo()
    blobs: dict[str, Blob] = {}

    # 1. Generate marketplace.json
    marketplace_json = build_marketplace_json(entries)
    _add_blob(repo, blobs, ".claude-plugin/marketplace.json", marketplace_json)

    # 2. Generate plugin directories for each skill
    for entry in entries:
        pname = plugin_name_from_skill(entry.org_slug, entry.skill_name)
        prefix = f"plugins/{pname}"

        # plugin.json
        plugin_json = build_plugin_json(
            org_slug=entry.org_slug,
            skill_name=entry.skill_name,
            version=entry.version,
            description=entry.description,
            source_repo_url=entry.source_repo_url,
            category=entry.category,
            gauntlet_grade=entry.gauntlet_grade,
            eval_status=entry.eval_status,
        )
        _add_blob(repo, blobs, f"{prefix}/.claude-plugin/plugin.json", plugin_json)

        # SKILL.md
        key = f"{entry.org_slug}/{entry.skill_name}"
        skill_md = skill_md_contents.get(key, "")
        if skill_md:
            _add_blob(repo, blobs, f"{prefix}/skills/{entry.skill_name}/SKILL.md", skill_md)

    # 3. Build tree hierarchy from flat paths
    root_tree = _build_tree_from_paths(repo, blobs)

    # 4. Create commit
    commit = Commit()
    commit.tree = root_tree.id
    commit.author = commit.committer = b"Decision Hub <support@decision.ai>"
    commit_time = int(time.time())
    commit.author_time = commit.commit_time = commit_time
    commit.author_timezone = commit.commit_timezone = 0
    commit.encoding = b"UTF-8"
    commit.message = f"marketplace generation ({len(entries)} skills)".encode()
    repo.object_store.add_object(commit)

    # 5. Set refs/heads/main
    repo.refs[b"refs/heads/main"] = commit.id
    repo.refs[b"HEAD"] = commit.id

    return repo


def _add_blob(repo: MemoryRepo, blobs: dict[str, Blob], path: str, content: str) -> None:
    """Create a blob and register it by path."""
    blob = Blob.from_string(content.encode())
    repo.object_store.add_object(blob)
    blobs[path] = blob


def _build_tree_from_paths(repo: MemoryRepo, blobs: dict[str, Blob]) -> Tree:
    """Build a nested Tree hierarchy from a flat {path: blob} mapping."""
    # Group blobs by their parent directory
    tree_entries: dict[str, list] = {}  # dir_path -> [(name, mode, sha)]

    for path, blob in blobs.items():
        parts = path.split("/")
        parent = "/".join(parts[:-1])
        filename = parts[-1]
        tree_entries.setdefault(parent, []).append((filename, 0o100644, blob.id))

    # Pre-compute all ancestor directories so the bottom-up pass is complete.
    # For a blob at "a/b/c/file.txt", parent dirs are "a/b/c", "a/b", "a", "".
    all_dir_paths: set[str] = {""}
    for dir_path in list(tree_entries.keys()):
        parts = dir_path.split("/")
        for i in range(len(parts)):
            all_dir_paths.add("/".join(parts[: i + 1]))

    # Build trees bottom-up: deepest directories first, root ("") last.
    # Depth uses component count so "plugins" (depth 1) is processed before "" (depth 0).
    def _depth(d: str) -> int:
        return len(d.split("/")) if d else 0

    sorted_dirs = sorted(all_dir_paths, key=_depth, reverse=True)
    dir_trees: dict[str, Tree] = {}

    for dir_path in sorted_dirs:
        tree = Tree()
        for name, mode, sha in sorted(tree_entries.get(dir_path, [])):
            tree.add(name.encode(), mode, sha)
        repo.object_store.add_object(tree)
        dir_trees[dir_path] = tree

        # Register this tree in its parent
        if dir_path:
            parent = "/".join(dir_path.split("/")[:-1])
            dirname = dir_path.split("/")[-1]
            tree_entries.setdefault(parent, []).append((dirname, 0o040000, tree.id))

    # The root tree is at ""
    if "" in dir_trees:
        return dir_trees[""]

    # Edge case: no blobs at all (empty marketplace)
    root = Tree()
    repo.object_store.add_object(root)
    return root
