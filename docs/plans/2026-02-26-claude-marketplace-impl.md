# Claude Plugin Marketplace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Serve Decision Hub's top 1000 skills as a Claude plugin marketplace via a virtual git endpoint at `/marketplace.git/`.

**Architecture:** A dulwich `MemoryRepo` built from DB skill metadata + S3 SKILL.md content, served via Git Smart HTTP protocol as a WSGI sub-app mounted in FastAPI. A generation counter in the DB triggers cache invalidation when skills are published or deleted.

**Tech Stack:** dulwich (git protocol), FastAPI/Starlette WSGI mount, SQLAlchemy, S3 (boto3), PostgreSQL

**Design doc:** `docs/plans/2026-02-26-claude-marketplace-design.md`

---

### Task 1: Add dulwich dependency

**Files:**
- Modify: `server/pyproject.toml`

**Step 1: Add dulwich to server dependencies**

In `server/pyproject.toml`, add `"dulwich>=0.22.0"` to the `dependencies` list (after `"dhub-core"`):

```toml
dependencies = [
    # ... existing deps ...
    "dhub-core",
    "dulwich>=0.22.0",
]
```

**Step 2: Lock dependencies**

Run: `uv lock`
Expected: Lock file updated with dulwich and its transitive deps.

**Step 3: Verify import works**

Run: `cd server && uv run --package decision-hub-server python -c "from dulwich.repo import MemoryRepo; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add server/pyproject.toml uv.lock
git commit -m "build: add dulwich dependency for git marketplace endpoint"
```

---

### Task 2: DB migration — marketplace_generation counter

**Files:**
- Create: `server/migrations/YYYYMMDD_HHMMSS_add_marketplace_generation.sql`
- Modify: `server/src/decision_hub/infra/database.py`

**Step 1: Generate migration filename**

Run: `date +%Y%m%d_%H%M%S` to get the timestamp prefix. Use that for the filename.

**Step 2: Write the SQL migration**

Create `server/migrations/<timestamp>_add_marketplace_generation.sql`:

```sql
-- Lightweight key-value config table for server-internal counters.
-- Only the marketplace_generation row is used for now; more keys can be added later.
CREATE TABLE IF NOT EXISTS server_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '0',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE server_config ENABLE ROW LEVEL SECURITY;

-- Seed the marketplace generation counter.
INSERT INTO server_config (key, value)
VALUES ('marketplace_generation', '0')
ON CONFLICT (key) DO NOTHING;
```

**Step 3: Add SQLAlchemy table definition**

In `server/src/decision_hub/infra/database.py`, after the existing table definitions (near line 400, after `tracker_metrics_table`), add:

```python
server_config_table = Table(
    "server_config",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Text, nullable=False, server_default="0"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)
```

**Step 4: Add DB helper functions**

In `server/src/decision_hub/infra/database.py`, add two functions near the end of the file (before the closing section):

```python
def bump_marketplace_generation(conn: Connection) -> None:
    """Increment the marketplace generation counter.

    Called after publish, delete, or any operation that changes
    the set of skills visible in the Claude marketplace.
    """
    conn.execute(
        sa.text(
            "UPDATE server_config "
            "SET value = (value::int + 1)::text, updated_at = now() "
            "WHERE key = 'marketplace_generation'"
        )
    )


def get_marketplace_generation(conn: Connection) -> int:
    """Read the current marketplace generation counter."""
    row = conn.execute(
        sa.text("SELECT value FROM server_config WHERE key = 'marketplace_generation'")
    ).fetchone()
    return int(row[0]) if row else 0
```

**Step 5: Run migration against dev**

Run: `cd server && DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.run_migrations`
Expected: Migration applied successfully.

**Step 6: Verify table exists**

Run: `cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "
from decision_hub.settings import create_settings
from decision_hub.infra.database import create_engine, get_marketplace_generation
from sqlalchemy import Connection

settings = create_settings('dev')
engine = create_engine(settings.database_url)
with engine.connect() as conn:
    gen = get_marketplace_generation(conn)
    print(f'marketplace_generation={gen}')
"`
Expected: `marketplace_generation=0`

**Step 7: Commit**

```bash
git add server/migrations/*marketplace_generation* server/src/decision_hub/infra/database.py
git commit -m "feat: add marketplace_generation counter table and helpers"
```

---

### Task 3: Bump generation counter on publish and delete

**Files:**
- Modify: `server/src/decision_hub/api/registry_routes.py`

**Step 1: Write the failing test**

Create `server/tests/test_api/test_marketplace_generation.py`:

```python
"""Verify marketplace generation counter is bumped on publish and delete."""

from unittest.mock import MagicMock, patch

import pytest


def test_bump_marketplace_generation_called_on_publish():
    """bump_marketplace_generation should be called after a successful publish commit."""
    from decision_hub.infra.database import bump_marketplace_generation

    # Verify the function exists and is callable
    assert callable(bump_marketplace_generation)


def test_bump_marketplace_generation_called_on_delete():
    """bump_marketplace_generation should be called after a successful delete."""
    from decision_hub.infra.database import bump_marketplace_generation

    assert callable(bump_marketplace_generation)
```

Run: `cd server && uv run --package decision-hub-server pytest tests/test_api/test_marketplace_generation.py -v`
Expected: PASS (just verifying the function exists)

**Step 2: Add generation bump to publish endpoint**

In `server/src/decision_hub/api/registry_routes.py`, add import at the top (with other database imports):

```python
from decision_hub.infra.database import bump_marketplace_generation
```

After line 525 (`conn.commit()`), add:

```python
    # Bump marketplace generation so the Claude plugin marketplace
    # picks up the new/updated skill on next git fetch.
    try:
        bump_marketplace_generation(conn)
        conn.commit()
    except Exception:
        logger.opt(exception=True).warning("Failed to bump marketplace generation")
```

**Step 3: Add generation bump to delete endpoints**

In the `delete_skill_version` function (after line 943, `delete_skill_zip(...)`), add:

```python
    try:
        bump_marketplace_generation(conn)
        conn.commit()
    except Exception:
        logger.opt(exception=True).warning("Failed to bump marketplace generation")
```

In the `delete_all_versions` function (after line 902, the S3 deletion loop), add the same block.

**Step 4: Commit**

```bash
git add server/src/decision_hub/api/registry_routes.py server/tests/test_api/test_marketplace_generation.py
git commit -m "feat: bump marketplace generation on publish and delete"
```

---

### Task 4: Marketplace data query — fetch top 1000 skills with SKILL.md

**Files:**
- Create: `server/src/decision_hub/domain/marketplace.py`
- Create: `server/tests/test_domain/test_marketplace.py`

**Step 1: Write the failing test**

Create `server/tests/test_domain/test_marketplace.py`:

```python
"""Tests for marketplace skill-to-plugin mapping."""

import json

from decision_hub.domain.marketplace import (
    SkillPluginEntry,
    build_marketplace_json,
    build_plugin_json,
    plugin_name_from_skill,
)


def test_plugin_name_from_skill():
    assert plugin_name_from_skill("pymc-labs", "bayesian-modeling") == "pymc-labs--bayesian-modeling"
    assert plugin_name_from_skill("alice", "hello") == "alice--hello"


def test_build_plugin_json():
    result = build_plugin_json(
        org_slug="pymc-labs",
        skill_name="bayesian-modeling",
        version="1.2.0",
        description="Bayesian stats",
        source_repo_url="https://github.com/pymc-labs/skills",
        category="data-science",
        gauntlet_grade="A",
        eval_status="passed",
    )
    parsed = json.loads(result)
    assert parsed["name"] == "pymc-labs--bayesian-modeling"
    assert parsed["version"] == "1.2.0"
    assert parsed["description"] == "Bayesian stats"
    assert parsed["author"]["name"] == "pymc-labs"
    assert parsed["repository"] == "https://github.com/pymc-labs/skills"
    assert "safety-grade-A" in parsed["keywords"]
    assert "evals-passing" in parsed["keywords"]


def test_build_plugin_json_no_repo_url():
    result = build_plugin_json(
        org_slug="alice",
        skill_name="hello",
        version="0.1.0",
        description="A greeting skill",
        source_repo_url=None,
        category="",
        gauntlet_grade="B",
        eval_status="pending",
    )
    parsed = json.loads(result)
    assert "repository" not in parsed
    assert "safety-grade-B" in parsed["keywords"]
    assert "evals-passing" not in parsed["keywords"]


def test_build_marketplace_json():
    entries = [
        SkillPluginEntry(
            org_slug="pymc-labs",
            skill_name="bayesian-modeling",
            version="1.2.0",
            description="Bayesian stats",
            category="data-science",
            gauntlet_grade="A",
            eval_status="passed",
            download_count=1200,
        ),
        SkillPluginEntry(
            org_slug="alice",
            skill_name="hello",
            version="0.1.0",
            description="Greeting",
            category="",
            gauntlet_grade="B",
            eval_status="pending",
            download_count=50,
        ),
    ]
    result = build_marketplace_json(entries)
    parsed = json.loads(result)
    assert parsed["name"] == "decision-hub"
    assert len(parsed["plugins"]) == 2
    first = parsed["plugins"][0]
    assert first["name"] == "pymc-labs--bayesian-modeling"
    assert first["source"] == "./plugins/pymc-labs--bayesian-modeling"
    assert first["version"] == "1.2.0"
    assert first["category"] == "data-science"
    assert "safety-A" in first["tags"]
```

Run: `cd server && uv run --package decision-hub-server pytest tests/test_domain/test_marketplace.py -v`
Expected: FAIL (module not found)

**Step 2: Implement the marketplace domain module**

Create `server/src/decision_hub/domain/marketplace.py`:

```python
"""Skill-to-Claude-plugin mapping and marketplace.json generation.

Transforms Decision Hub skill metadata into Claude Code plugin format.
SKILL.md is already Claude's native skill format — only the wrapping
metadata (plugin.json, marketplace.json) needs to be generated.
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillPluginEntry:
    """Skill metadata needed to generate a Claude plugin entry."""

    org_slug: str
    skill_name: str
    version: str
    description: str
    category: str
    gauntlet_grade: str  # A/B/C — F is excluded upstream
    eval_status: str  # passed/failed/pending/error
    download_count: int
    source_repo_url: str | None = None


def plugin_name_from_skill(org_slug: str, skill_name: str) -> str:
    """Build Claude plugin name from org and skill.

    Uses double-dash separator since both org and skill can contain
    single hyphens (e.g. pymc-labs--bayesian-modeling).
    """
    return f"{org_slug}--{skill_name}"


def _keywords(category: str, grade: str, eval_status: str) -> list[str]:
    """Build keyword list for plugin.json."""
    kw: list[str] = []
    if category:
        kw.append(category)
    kw.append(f"safety-grade-{grade}")
    if eval_status == "passed":
        kw.append("evals-passing")
    return kw


def build_plugin_json(
    *,
    org_slug: str,
    skill_name: str,
    version: str,
    description: str,
    source_repo_url: str | None,
    category: str,
    gauntlet_grade: str,
    eval_status: str,
) -> str:
    """Generate plugin.json content for a single skill.

    Returns JSON string ready to write as .claude-plugin/plugin.json.
    """
    data: dict = {
        "name": plugin_name_from_skill(org_slug, skill_name),
        "version": version,
        "description": description,
        "author": {"name": org_slug},
        "keywords": _keywords(category, gauntlet_grade, eval_status),
    }
    if source_repo_url:
        data["repository"] = source_repo_url
    return json.dumps(data, indent=2)


def _tags(grade: str, eval_status: str, download_count: int) -> list[str]:
    """Build tag list for marketplace.json entry."""
    tags = [f"safety-{grade}"]
    if eval_status == "passed":
        tags.append("evals-passing")
    tags.append(f"downloads-{download_count}")
    return tags


def build_marketplace_json(entries: list[SkillPluginEntry]) -> str:
    """Generate marketplace.json for all plugin entries.

    Returns JSON string conforming to Claude Code's marketplace schema.
    """
    plugins = []
    for e in entries:
        name = plugin_name_from_skill(e.org_slug, e.skill_name)
        plugins.append(
            {
                "name": name,
                "source": f"./plugins/{name}",
                "description": e.description,
                "version": e.version,
                "category": e.category or "uncategorized",
                "tags": _tags(e.gauntlet_grade, e.eval_status, e.download_count),
            }
        )

    marketplace = {
        "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
        "name": "decision-hub",
        "description": (
            "AI skills marketplace with safety guarantees and automated evals. "
            "Published via Decision Hub (hub.decision.ai)."
        ),
        "owner": {
            "name": "Decision Hub",
            "email": "support@decision.ai",
        },
        "metadata": {
            "version": "1.0.0",
            "pluginRoot": "./plugins",
        },
        "plugins": plugins,
    }
    return json.dumps(marketplace, indent=2)
```

**Step 3: Run tests**

Run: `cd server && uv run --package decision-hub-server pytest tests/test_domain/test_marketplace.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add server/src/decision_hub/domain/marketplace.py server/tests/test_domain/test_marketplace.py
git commit -m "feat: marketplace domain — skill-to-plugin mapping and JSON generation"
```

---

### Task 5: Fetch top 1000 skills from DB

**Files:**
- Modify: `server/src/decision_hub/infra/database.py`
- Create: `server/tests/test_infra/test_marketplace_query.py`

**Step 1: Write the DB query function**

In `server/src/decision_hub/infra/database.py`, add a new function near `fetch_all_skills_for_index`:

```python
def fetch_marketplace_skills(conn: Connection, limit: int = 1000) -> list[dict]:
    """Fetch top skills for the Claude plugin marketplace.

    Returns the top N public skills by download count, excluding F-graded
    skills and those without a published version. Each dict contains:
    org_slug, skill_name, description, latest_version, category,
    gauntlet_summary, eval_status, download_count, source_repo_url, s3_key.
    """
    j = skills_table.join(
        organizations_table,
        skills_table.c.org_id == organizations_table.c.id,
    ).join(
        versions_table,
        sa.and_(
            versions_table.c.skill_id == skills_table.c.id,
            versions_table.c.semver == skills_table.c.latest_semver,
        ),
    )

    stmt = (
        sa.select(
            organizations_table.c.slug.label("org_slug"),
            skills_table.c.name.label("skill_name"),
            skills_table.c.description,
            skills_table.c.latest_semver.label("latest_version"),
            skills_table.c.category,
            skills_table.c.latest_gauntlet_summary.label("gauntlet_summary"),
            skills_table.c.latest_eval_status.label("eval_status"),
            skills_table.c.download_count,
            skills_table.c.source_repo_url,
            versions_table.c.s3_key,
        )
        .select_from(j)
        .where(
            sa.and_(
                skills_table.c.visibility == "public",
                skills_table.c.latest_semver.isnot(None),
            )
        )
        .order_by(skills_table.c.download_count.desc(), skills_table.c.name.asc())
        .limit(limit)
    )

    rows = conn.execute(stmt).fetchall()
    return [dict(row._mapping) for row in rows]
```

**Step 2: Write a unit test**

Create `server/tests/test_infra/test_marketplace_query.py`:

```python
"""Test that fetch_marketplace_skills function is importable and has the right signature."""

from decision_hub.infra.database import fetch_marketplace_skills
import inspect


def test_fetch_marketplace_skills_signature():
    sig = inspect.signature(fetch_marketplace_skills)
    params = list(sig.parameters.keys())
    assert "conn" in params
    assert "limit" in params
```

Run: `cd server && uv run --package decision-hub-server pytest tests/test_infra/test_marketplace_query.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add server/src/decision_hub/infra/database.py server/tests/test_infra/test_marketplace_query.py
git commit -m "feat: add fetch_marketplace_skills query for top 1000 skills"
```

---

### Task 6: Build dulwich MemoryRepo from skill data

**Files:**
- Create: `server/src/decision_hub/infra/git_marketplace.py`
- Create: `server/tests/test_infra/test_git_marketplace.py`

**Step 1: Write the failing test**

Create `server/tests/test_infra/test_git_marketplace.py`:

```python
"""Test virtual git marketplace repo construction."""

import subprocess
import tempfile
from pathlib import Path

from decision_hub.domain.marketplace import SkillPluginEntry
from decision_hub.infra.git_marketplace import build_marketplace_repo


def test_build_marketplace_repo_creates_cloneable_repo():
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
```

Run: `cd server && uv run --package decision-hub-server pytest tests/test_infra/test_git_marketplace.py -v`
Expected: FAIL (module not found)

**Step 2: Implement git_marketplace.py**

Create `server/src/decision_hub/infra/git_marketplace.py`:

```python
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
    repo = MemoryRepo.init_bare([])
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
    # Group by directory
    tree_entries: dict[str, list] = {}  # dir_path -> [(name, mode, sha)]

    for path, blob in blobs.items():
        parts = path.split("/")
        # Register the blob in its parent directory
        parent = "/".join(parts[:-1])
        filename = parts[-1]
        tree_entries.setdefault(parent, []).append(
            (filename, 0o100644, blob.id)
        )

    # Build trees bottom-up: deepest directories first
    all_dirs = sorted(tree_entries.keys(), key=lambda d: d.count("/"), reverse=True)
    dir_trees: dict[str, Tree] = {}

    for dir_path in all_dirs:
        tree = Tree()
        for name, mode, sha in sorted(tree_entries[dir_path]):
            tree.add(name.encode(), mode, sha)
        repo.object_store.add_object(tree)
        dir_trees[dir_path] = tree

        # Register this tree in its parent
        if dir_path:
            parent = "/".join(dir_path.split("/")[:-1])
            dirname = dir_path.split("/")[-1]
            tree_entries.setdefault(parent, []).append(
                (dirname, 0o040000, tree.id)
            )

    # The root tree is at ""
    if "" in dir_trees:
        return dir_trees[""]

    # Edge case: no blobs at all (empty marketplace)
    root = Tree()
    repo.object_store.add_object(root)
    return root
```

**Step 3: Run tests**

Run: `cd server && uv run --package decision-hub-server pytest tests/test_infra/test_git_marketplace.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add server/src/decision_hub/infra/git_marketplace.py server/tests/test_infra/test_git_marketplace.py
git commit -m "feat: build virtual git marketplace repo from skill data"
```

---

### Task 7: WSGI handler and cache — serve the repo over HTTP

**Files:**
- Modify: `server/src/decision_hub/infra/git_marketplace.py`
- Create: `server/tests/test_infra/test_git_wsgi.py`

**Step 1: Write the failing test**

Create `server/tests/test_infra/test_git_wsgi.py`:

```python
"""Test the git marketplace WSGI handler."""

from decision_hub.infra.git_marketplace import create_git_wsgi_app


def test_create_git_wsgi_app_returns_callable():
    """The factory should return a WSGI-compatible callable."""
    app = create_git_wsgi_app(repo_builder=lambda: None)
    assert callable(app)
```

Run: `cd server && uv run --package decision-hub-server pytest tests/test_infra/test_git_wsgi.py -v`
Expected: FAIL (function not found)

**Step 2: Add WSGI handler and cache to git_marketplace.py**

Add to the end of `server/src/decision_hub/infra/git_marketplace.py`:

```python
import threading
from collections.abc import Callable

from dulwich.web import HTTPGitApplication


class MarketplaceCache:
    """Thread-safe cache for the marketplace MemoryRepo.

    Rebuilds the repo when the generation counter changes.
    Checks the counter at most once per `ttl_seconds`.
    """

    def __init__(
        self,
        build_fn: Callable[[], MemoryRepo],
        generation_fn: Callable[[], int],
        ttl_seconds: int = 300,
    ) -> None:
        self._build_fn = build_fn
        self._generation_fn = generation_fn
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._repo: MemoryRepo | None = None
        self._generation: int = -1
        self._last_check: float = 0.0

    def get_repo(self) -> MemoryRepo:
        """Return the cached repo, rebuilding if stale."""
        now = time.time()
        if self._repo is not None and (now - self._last_check) < self._ttl_seconds:
            return self._repo

        with self._lock:
            # Double-check after acquiring lock
            if self._repo is not None and (now - self._last_check) < self._ttl_seconds:
                return self._repo

            current_gen = self._generation_fn()
            self._last_check = time.time()

            if self._repo is not None and current_gen == self._generation:
                return self._repo

            self._repo = self._build_fn()
            self._generation = current_gen
            return self._repo


def create_git_wsgi_app(
    repo_builder: Callable[[], MemoryRepo | None] | None = None,
    cache: MarketplaceCache | None = None,
) -> Callable:
    """Create a WSGI app that serves the marketplace as a git repo.

    Uses dulwich's HTTPGitApplication to handle the Git Smart HTTP protocol.
    The cache controls when the repo is rebuilt.
    """

    def app(environ, start_response):
        repo = None
        if cache is not None:
            repo = cache.get_repo()
        elif repo_builder is not None:
            repo = repo_builder()

        if repo is None:
            start_response("503 Service Unavailable", [("Content-Type", "text/plain")])
            return [b"Marketplace not available"]

        # dulwich HTTPGitApplication expects a backend that maps paths to repos.
        # For a single repo, we use a simple dict backend.
        git_app = HTTPGitApplication({"/": repo})
        return git_app(environ, start_response)

    return app
```

**Step 3: Run tests**

Run: `cd server && uv run --package decision-hub-server pytest tests/test_infra/test_git_wsgi.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add server/src/decision_hub/infra/git_marketplace.py server/tests/test_infra/test_git_wsgi.py
git commit -m "feat: WSGI handler and cache for git marketplace endpoint"
```

---

### Task 8: Mount the git endpoint in FastAPI

**Files:**
- Modify: `server/src/decision_hub/api/app.py`
- Modify: `server/src/decision_hub/settings.py`

**Step 1: Add marketplace settings**

In `server/src/decision_hub/settings.py`, add after the tracker settings (line 102):

```python
    # Claude marketplace
    marketplace_skill_limit: int = 1000  # max skills in the marketplace
    marketplace_cache_ttl: int = 300  # seconds between generation checks
```

**Step 2: Wire up the git endpoint in app.py**

In `server/src/decision_hub/api/app.py`, add the marketplace mount. This should go **before** the SPA catch-all (before line 186) but **after** all API routers. Add:

```python
    # --- Claude Plugin Marketplace (virtual git repo) ---
    # Mount before the SPA catch-all so /marketplace.git/* is handled by
    # the git protocol handler, not served as index.html.
    _mount_marketplace(app, engine, s3_client, settings)
```

Then add the helper function at module level (before `create_app`):

```python
def _mount_marketplace(app: FastAPI, engine, s3_client, settings) -> None:
    """Mount the virtual git marketplace at /marketplace.git/."""
    from starlette.middleware.wsgi import WSGIMiddleware

    from decision_hub.domain.marketplace import SkillPluginEntry
    from decision_hub.infra.git_marketplace import (
        MarketplaceCache,
        build_marketplace_repo,
        create_git_wsgi_app,
    )
    from decision_hub.infra.database import (
        fetch_marketplace_skills,
        get_marketplace_generation,
    )
    from decision_hub.infra.storage import download_skill_zip
    from decision_hub.domain.publish import extract_for_evaluation

    def _get_generation() -> int:
        with engine.connect() as conn:
            return get_marketplace_generation(conn)

    def _build_repo():
        with engine.connect() as conn:
            rows = fetch_marketplace_skills(conn, limit=settings.marketplace_skill_limit)

        # Fetch SKILL.md content from S3 for each skill
        skill_md_contents: dict[str, str] = {}
        entries: list[SkillPluginEntry] = []

        for row in rows:
            # Parse gauntlet grade from summary (e.g. "A" from "A: ...")
            grade = _parse_grade(row.get("gauntlet_summary", ""))
            if grade == "F":
                continue

            entry = SkillPluginEntry(
                org_slug=row["org_slug"],
                skill_name=row["skill_name"],
                version=row["latest_version"],
                description=row["description"],
                category=row["category"],
                gauntlet_grade=grade,
                eval_status=row.get("eval_status", "pending"),
                download_count=row["download_count"],
                source_repo_url=row.get("source_repo_url"),
            )
            entries.append(entry)

            # Download SKILL.md from S3
            s3_key = row.get("s3_key", "")
            if s3_key:
                try:
                    zip_bytes = download_skill_zip(s3_client, settings.s3_bucket, s3_key)
                    skill_md, _, _, _ = extract_for_evaluation(zip_bytes)
                    skill_md_contents[f"{row['org_slug']}/{row['skill_name']}"] = skill_md
                except Exception:
                    logger.opt(exception=True).warning(
                        "Failed to fetch SKILL.md for {}/{}",
                        row["org_slug"],
                        row["skill_name"],
                    )

        return build_marketplace_repo(entries, skill_md_contents)

    cache = MarketplaceCache(
        build_fn=_build_repo,
        generation_fn=_get_generation,
        ttl_seconds=settings.marketplace_cache_ttl,
    )

    wsgi_app = create_git_wsgi_app(cache=cache)
    app.mount("/marketplace.git", WSGIMiddleware(wsgi_app))
    logger.info("Mounted Claude marketplace at /marketplace.git/")


def _parse_grade(gauntlet_summary: str | None) -> str:
    """Extract letter grade from gauntlet summary string.

    The summary format is 'A: ...' or just 'A'. Returns 'B' as default
    if the summary is missing or unparseable (benefit of the doubt).
    """
    if not gauntlet_summary:
        return "B"
    grade = gauntlet_summary.strip()[:1].upper()
    return grade if grade in ("A", "B", "C", "F") else "B"
```

**Step 3: Verify the app starts**

Run: `cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "from decision_hub.api.app import create_app; app = create_app(); print('App created with marketplace mount')"`
Expected: Output includes "Mounted Claude marketplace at /marketplace.git/"

**Step 4: Commit**

```bash
git add server/src/decision_hub/api/app.py server/src/decision_hub/settings.py
git commit -m "feat: mount virtual git marketplace endpoint in FastAPI"
```

---

### Task 9: End-to-end test — git clone the marketplace

**Files:**
- Create: `server/tests/test_infra/test_git_marketplace_e2e.py`

This is the critical validation step. We need to verify that `git clone` actually works against our WSGI endpoint.

**Step 1: Write the E2E test**

Create `server/tests/test_infra/test_git_marketplace_e2e.py`:

```python
"""End-to-end test: verify git clone works against the virtual marketplace.

This test builds a MemoryRepo, serves it via the dulwich WSGI handler,
and runs `git clone` against it using a local WSGI test server.
"""

import json
import subprocess
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

import pytest

from decision_hub.domain.marketplace import SkillPluginEntry
from decision_hub.infra.git_marketplace import (
    build_marketplace_repo,
    create_git_wsgi_app,
)


@pytest.fixture
def sample_entries():
    return [
        SkillPluginEntry(
            org_slug="test-org",
            skill_name="test-skill",
            version="1.0.0",
            description="A test skill for E2E",
            category="testing",
            gauntlet_grade="A",
            eval_status="passed",
            download_count=42,
        ),
    ]


@pytest.fixture
def sample_skill_md():
    return {"test-org/test-skill": "---\nname: test-skill\n---\nTest skill prompt content"}


@pytest.fixture
def git_server(sample_entries, sample_skill_md):
    """Start a local WSGI server serving the virtual git repo."""
    repo = build_marketplace_repo(sample_entries, sample_skill_md)
    wsgi_app = create_git_wsgi_app(repo_builder=lambda: repo)

    server = make_server("127.0.0.1", 0, wsgi_app)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def test_git_clone_marketplace(git_server):
    """Verify that `git clone` succeeds and produces expected file structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / "marketplace"
        result = subprocess.run(
            ["git", "clone", f"{git_server}/", str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"git clone failed: {result.stderr}"

        # Verify marketplace.json
        mj = clone_dir / ".claude-plugin" / "marketplace.json"
        assert mj.exists(), f"marketplace.json not found. Files: {list(clone_dir.rglob('*'))}"
        marketplace = json.loads(mj.read_text())
        assert marketplace["name"] == "decision-hub"
        assert len(marketplace["plugins"]) == 1
        assert marketplace["plugins"][0]["name"] == "test-org--test-skill"

        # Verify plugin structure
        plugin_dir = clone_dir / "plugins" / "test-org--test-skill"
        assert (plugin_dir / ".claude-plugin" / "plugin.json").exists()
        plugin_json = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
        assert plugin_json["version"] == "1.0.0"

        # Verify SKILL.md
        skill_md_path = plugin_dir / "skills" / "test-skill" / "SKILL.md"
        assert skill_md_path.exists()
        assert "Test skill prompt content" in skill_md_path.read_text()
```

**Step 2: Run the E2E test**

Run: `cd server && uv run --package decision-hub-server pytest tests/test_infra/test_git_marketplace_e2e.py -v -s`
Expected: PASS — git clone succeeds, all files present

**Step 3: Commit**

```bash
git add server/tests/test_infra/test_git_marketplace_e2e.py
git commit -m "test: E2E git clone test for virtual marketplace"
```

---

### Task 10: Deploy to dev and test with Claude Code

**Step 1: Deploy to dev**

Run: `make deploy-dev`
Expected: Deploy succeeds

**Step 2: Test git clone manually**

Run: `git clone https://hub-dev.decision.ai/marketplace.git /tmp/dhub-marketplace-test`
Expected: Clone succeeds, directory contains `.claude-plugin/marketplace.json` and `plugins/` directories

**Step 3: Inspect cloned marketplace**

Run:
```bash
cat /tmp/dhub-marketplace-test/.claude-plugin/marketplace.json | python3 -m json.tool | head -30
ls /tmp/dhub-marketplace-test/plugins/ | head -20
```
Expected: Well-formed JSON with plugin entries; plugin directories with double-dash naming

**Step 4: Test with Claude Code**

Run: `claude plugin marketplace add https://hub-dev.decision.ai/marketplace.git`
Expected: Marketplace added, skills visible in `/plugin` Discover tab

**Step 5: Clean up test clone**

Run: `rm -rf /tmp/dhub-marketplace-test`

**Step 6: Commit any fixes found during testing**

```bash
git add -A
git commit -m "fix: adjustments from dev deployment testing"
```

---

### Task 11: Filter out F-graded skills in the DB query

**Files:**
- Modify: `server/src/decision_hub/infra/database.py`

**Step 1: Add grade filtering to the query**

The `fetch_marketplace_skills` query already joins with the skills table which has `latest_gauntlet_summary`. We need to exclude rows where the grade starts with 'F'. Add to the `.where()` clause:

```python
        .where(
            sa.and_(
                skills_table.c.visibility == "public",
                skills_table.c.latest_semver.isnot(None),
                # Exclude F-graded skills from marketplace
                sa.or_(
                    skills_table.c.latest_gauntlet_summary.is_(None),
                    ~skills_table.c.latest_gauntlet_summary.startswith("F"),
                ),
            )
        )
```

**Step 2: Run all tests**

Run: `cd server && uv run --package decision-hub-server pytest tests/ -v --ignore=tests/test_domain/test_arxiv_gauntlet.py -x`
Expected: All PASS

**Step 3: Commit**

```bash
git add server/src/decision_hub/infra/database.py
git commit -m "feat: exclude F-graded skills from marketplace query"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Add dulwich dependency | `server/pyproject.toml`, `uv.lock` |
| 2 | DB migration — generation counter | `server/migrations/`, `database.py` |
| 3 | Bump counter on publish/delete | `registry_routes.py` |
| 4 | Marketplace domain (JSON generation) | `domain/marketplace.py` + tests |
| 5 | DB query for top 1000 skills | `database.py` + tests |
| 6 | Build dulwich MemoryRepo | `infra/git_marketplace.py` + tests |
| 7 | WSGI handler and cache | `infra/git_marketplace.py` + tests |
| 8 | Mount in FastAPI | `api/app.py`, `settings.py` |
| 9 | E2E git clone test | integration test |
| 10 | Deploy + test with Claude Code | manual verification |
| 11 | F-grade filtering | `database.py` |

Total: **11 tasks**, each independently committable. Tasks 4-7 are the core logic. Task 9 is the critical validation gate. Task 10 is the real-world proof.
