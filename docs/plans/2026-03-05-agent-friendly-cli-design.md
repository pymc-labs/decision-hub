# Agent-Friendly CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the dhub CLI scriptable by AI agents with `--output json`, `--dry-run`, structured errors, and a `doctor` command.

**Architecture:** Add a global `--output` flag via Typer callback that sets module-level state. Each command checks this state and either passes server JSON through to stdout or renders Rich tables (existing behavior). A new `output.py` module centralizes format state and helpers.

**Tech Stack:** Typer, Rich, httpx, respx (tests), json (stdlib)

**Reference:** [Rewrite Your CLI for AI Agents](https://justin.poehnelt.com/posts/rewrite-your-cli-for-ai-agents/) — design doc at `docs/plans/2026-03-05-agent-friendly-cli-design.md`

---

## Task 1: Create output module and global `--output` flag

**Files:**
- Create: `client/src/dhub/cli/output.py`
- Modify: `client/src/dhub/cli/app.py`
- Test: `client/tests/test_cli/test_output.py`

**Step 1: Write the failing test**

```python
# client/tests/test_cli/test_output.py
"""Tests for dhub.cli.output -- output format module."""

from dhub.cli.output import OutputFormat, is_json, set_format


class TestOutputFormat:
    def test_default_is_text(self) -> None:
        set_format(OutputFormat.text)
        assert not is_json()

    def test_set_json(self) -> None:
        set_format(OutputFormat.json)
        assert is_json()
        # Reset for other tests
        set_format(OutputFormat.text)
```

**Step 2: Run test to verify it fails**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_output.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dhub.cli.output'`

**Step 3: Write minimal implementation**

```python
# client/src/dhub/cli/output.py
"""Output format state and helpers for JSON/text mode."""

import json
import sys
from enum import Enum
from typing import Any


class OutputFormat(str, Enum):
    text = "text"
    json = "json"


_current_format: OutputFormat = OutputFormat.text


def set_format(fmt: OutputFormat) -> None:
    """Set the global output format. Called once by the app callback."""
    global _current_format
    _current_format = fmt


def is_json() -> bool:
    """Check if current output format is JSON."""
    return _current_format == OutputFormat.json


def print_json(data: Any) -> None:
    """Write JSON to stdout (no Rich markup)."""
    sys.stdout.write(json.dumps(data, default=str) + "\n")
    sys.stdout.flush()


def print_json_err(data: dict) -> None:
    """Write JSON error to stderr."""
    sys.stderr.write(json.dumps(data, default=str) + "\n")
    sys.stderr.flush()
```

**Step 4: Run test to verify it passes**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_output.py -v`
Expected: PASS

**Step 5: Wire up the global `--output` flag in app.py**

Modify `client/src/dhub/cli/app.py` — change the `main` callback to accept `--output`:

```python
@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    output: str = typer.Option(
        "text",
        "--output",
        help="Output format: 'text' or 'json'.",
    ),
) -> None:
    """Decision Hub - The AI Skill Manager for Data Science Agents."""
    from dhub.cli.output import OutputFormat, set_format

    set_format(OutputFormat(output))

    if not is_json():
        from dhub.cli.version_check import show_update_notice
        show_update_notice(Console(stderr=True))
```

**Step 6: Test the global flag via CLI runner**

Add to `client/tests/test_cli/test_output.py`:

```python
from typer.testing import CliRunner
from dhub.cli.app import app

runner = CliRunner()


class TestGlobalOutputFlag:
    def test_output_json_flag_accepted(self) -> None:
        result = runner.invoke(app, ["--output", "json", "--help"])
        assert result.exit_code == 0

    def test_invalid_output_rejected(self) -> None:
        result = runner.invoke(app, ["--output", "xml", "env"])
        assert result.exit_code != 0
```

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_output.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add client/src/dhub/cli/output.py client/src/dhub/cli/app.py client/tests/test_cli/test_output.py
git commit -m "feat(cli): add output module and global --output json flag"
```

---

## Task 2: Add JSON output to `env` command

The simplest command — good for establishing the pattern.

**Files:**
- Modify: `client/src/dhub/cli/env.py`
- Test: `client/tests/test_cli/test_output.py` (add to existing)

**Step 1: Write the failing test**

```python
class TestEnvJsonOutput:
    def test_env_json_output(self) -> None:
        import json
        result = runner.invoke(app, ["--output", "json", "env"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "environment" in data
        assert "config_file" in data
        assert "api_url" in data
```

**Step 2: Run test to verify it fails**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_output.py::TestEnvJsonOutput -v`
Expected: FAIL — output is Rich text, not JSON

**Step 3: Implement JSON branch in env.py**

```python
# client/src/dhub/cli/env.py
"""Show the active dhub environment configuration."""

from rich.console import Console

from dhub.cli.config import config_file, get_api_url, get_env


def env_command() -> None:
    """Show the active environment, config file path, and API URL."""
    from dhub.cli.output import is_json, print_json

    env = get_env()
    data = {
        "environment": env,
        "config_file": str(config_file(env)),
        "api_url": get_api_url(),
    }

    if is_json():
        print_json(data)
        return

    console = Console()
    console.print(f"Environment: {env}")
    console.print(f"Config: {config_file(env)}")
    console.print(f"API URL: {get_api_url()}")
```

**Step 4: Run test to verify it passes**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_output.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add client/src/dhub/cli/env.py client/tests/test_cli/test_output.py
git commit -m "feat(cli): add --output json to env command"
```

---

## Task 3: Add JSON output to `ask` command

**Files:**
- Modify: `client/src/dhub/cli/search.py`
- Modify: `client/tests/test_cli/test_search_cli.py`

**Step 1: Write the failing test**

Add to `client/tests/test_cli/test_search_cli.py`:

```python
class TestAskJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_json_output(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/ask").mock(
            return_value=httpx.Response(200, json=_ASK_RESPONSE)
        )

        result = runner.invoke(app, ["--output", "json", "ask", "analyze A/B test results"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["query"] == "analyze A/B test results"
        assert data["answer"].startswith("Here are skills")
        assert len(data["skills"]) == 2
        assert data["skills"][0]["skill_name"] == "ab-test-analyzer"

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_ask_json_503(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/ask").mock(return_value=httpx.Response(503))

        result = runner.invoke(app, ["--output", "json", "ask", "some query"])

        assert result.exit_code == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_search_cli.py::TestAskJsonOutput -v`
Expected: FAIL — output is Rich markup, not JSON

**Step 3: Add JSON branch to search.py**

In `ask_command()`, after `data = resp.json()`, add the JSON early-return:

```python
    from dhub.cli.output import is_json, print_json

    # ... existing fetch code ...

    if is_json():
        print_json(data)
        return

    # ... existing Rich rendering ...
```

**Step 4: Run test to verify it passes**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_search_cli.py -v`
Expected: ALL PASS (old + new)

**Step 5: Commit**

```bash
git add client/src/dhub/cli/search.py client/tests/test_cli/test_search_cli.py
git commit -m "feat(cli): add --output json to ask command"
```

---

## Task 4: Add JSON output to `list` command

**Files:**
- Modify: `client/src/dhub/cli/registry.py` (the `list_command` function)
- Modify: `client/tests/test_cli/test_registry_cli.py`

**Step 1: Write the failing test**

Add to `client/tests/test_cli/test_registry_cli.py`:

```python
class TestListJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_json_output(self, _mock_url, _mock_token) -> None:
        response = {
            "items": [
                {
                    "org_slug": "acme",
                    "skill_name": "test-skill",
                    "description": "A test",
                    "latest_version": "1.0.0",
                    "updated_at": "2026-01-01T00:00:00",
                    "safety_rating": "A",
                    "author": "alice",
                    "download_count": 42,
                    "category": "Testing",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
            "total_pages": 1,
        }
        respx.get("http://test:8000/v1/skills").mock(
            return_value=httpx.Response(200, json=response)
        )

        result = runner.invoke(app, ["--output", "json", "list"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["skill_name"] == "test-skill"

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_json_fetches_all_pages(self, _mock_url, _mock_token) -> None:
        """In JSON mode, list fetches all pages and merges items."""
        page1 = {
            "items": [{"org_slug": "a", "skill_name": "s1", "description": "", "latest_version": "1.0.0",
                        "updated_at": "", "safety_rating": "A", "author": "", "download_count": 0, "category": ""}],
            "total": 2, "page": 1, "page_size": 1, "total_pages": 2,
        }
        page2 = {
            "items": [{"org_slug": "a", "skill_name": "s2", "description": "", "latest_version": "1.0.0",
                        "updated_at": "", "safety_rating": "A", "author": "", "download_count": 0, "category": ""}],
            "total": 2, "page": 2, "page_size": 1, "total_pages": 2,
        }
        route = respx.get("http://test:8000/v1/skills")
        route.side_effect = [
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]

        result = runner.invoke(app, ["--output", "json", "list", "--page-size", "1"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 2
        assert len(data["items"]) == 2
```

**Step 2: Run test to verify it fails**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_registry_cli.py::TestListJsonOutput -v`
Expected: FAIL

**Step 3: Implement JSON branch in list_command**

In `list_command()`, after importing the output module, add a JSON path that collects all pages:

```python
def list_command(...) -> None:
    from dhub.cli.output import is_json, print_json

    json_mode = is_json()

    if not json_mode:
        print_banner(console)
        console.print(f"Registry: [dim]{api_url}[/]")

    # In JSON mode, fetch all pages silently
    all_items: list[dict] = []
    page = 1
    total = 0
    total_pages = 0
    found_any = False

    with httpx.Client(timeout=60) as client:
        while True:
            params = {"page": page, "page_size": page_size, "sort": "downloads"}
            if org:
                params["org"] = org
            if skill:
                params["search"] = skill
            resp = client.get(f"{api_url}/v1/skills", headers=headers, params=params)
            raise_for_status(resp)
            data = resp.json()

            items = data["items"]
            total = data["total"]
            total_pages = data["total_pages"]

            if json_mode:
                all_items.extend(items)
                if page >= total_pages or total == 0:
                    break
                page += 1
                continue

            # ... existing Rich rendering (unchanged) ...
```

After the loop, for JSON mode:

```python
    if json_mode:
        print_json({"items": all_items, "total": total, "page": 1, "page_size": len(all_items), "total_pages": 1})
        return
```

**Step 4: Run tests**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_registry_cli.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add client/src/dhub/cli/registry.py client/tests/test_cli/test_registry_cli.py
git commit -m "feat(cli): add --output json to list command"
```

---

## Task 5: Add JSON output to `org list`, `keys list`, `access list`

**Files:**
- Modify: `client/src/dhub/cli/org.py`
- Modify: `client/src/dhub/cli/keys.py`
- Modify: `client/src/dhub/cli/access.py`
- Modify: `client/tests/test_cli/test_org_cli.py`
- Modify: `client/tests/test_cli/test_keys_cli.py`
- Modify: `client/tests/test_cli/test_access_cli.py`

**Step 1: Write the failing tests**

Add JSON test to each test file following the same pattern as Task 2:

For `test_org_cli.py`:
```python
class TestOrgListJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_org_list_json(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/orgs").mock(
            return_value=httpx.Response(200, json=[{"slug": "acme", "id": "1", "is_personal": False}])
        )
        result = runner.invoke(app, ["--output", "json", "org", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["slug"] == "acme"
```

For `test_keys_cli.py`:
```python
class TestKeysListJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_keys_list_json(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/keys").mock(
            return_value=httpx.Response(200, json=[{"key_name": "ANTHROPIC_API_KEY", "created_at": "2026-01-01"}])
        )
        result = runner.invoke(app, ["--output", "json", "keys", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["key_name"] == "ANTHROPIC_API_KEY"
```

For `test_access_cli.py`:
```python
class TestAccessListJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_list_json(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/skills/acme/my-skill/access").mock(
            return_value=httpx.Response(200, json=[
                {"grantee_org_slug": "partner", "granted_by": "alice", "created_at": "2026-01-01T00:00:00"}
            ])
        )
        result = runner.invoke(app, ["--output", "json", "access", "list", "acme/my-skill"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["grantee_org_slug"] == "partner"
```

**Step 2: Run tests to verify they fail**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_org_cli.py::TestOrgListJsonOutput client/tests/test_cli/test_keys_cli.py::TestKeysListJsonOutput client/tests/test_cli/test_access_cli.py::TestAccessListJsonOutput -v`
Expected: FAIL

**Step 3: Implement JSON branches**

Each command gets the same pattern — after `data = resp.json()`:

```python
from dhub.cli.output import is_json, print_json

if is_json():
    print_json(data)
    return
```

**Step 4: Run all tests**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/test_org_cli.py client/tests/test_cli/test_keys_cli.py client/tests/test_cli/test_access_cli.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add client/src/dhub/cli/org.py client/src/dhub/cli/keys.py client/src/dhub/cli/access.py \
  client/tests/test_cli/test_org_cli.py client/tests/test_cli/test_keys_cli.py client/tests/test_cli/test_access_cli.py
git commit -m "feat(cli): add --output json to org/keys/access list commands"
```

---

## Task 6: Add JSON output to `info` and `eval-report`

**Files:**
- Modify: `client/src/dhub/cli/registry.py` (`info_command`, `eval_report_command`)
- Modify: `client/tests/test_cli/test_registry_cli.py`

**Step 1: Write the failing tests**

```python
class TestInfoJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_info_json_output(self, _mock_url, _mock_token) -> None:
        summary = {
            "org_slug": "acme", "skill_name": "test-skill", "description": "A test",
            "latest_version": "1.0.0", "updated_at": "2026-01-01", "safety_rating": "A",
            "author": "alice", "download_count": 42, "category": "Testing", "visibility": "public",
        }
        respx.get("http://test:8000/v1/skills/acme/test-skill/summary").mock(
            return_value=httpx.Response(200, json=summary)
        )
        respx.get("http://test:8000/v1/skills/acme/test-skill/audit-log").mock(
            return_value=httpx.Response(200, json={"items": [], "total": 0, "page": 1, "page_size": 1, "total_pages": 0})
        )
        respx.get("http://test:8000/v1/skills/acme/test-skill/eval-report").mock(
            return_value=httpx.Response(200, json=None)
        )

        result = runner.invoke(app, ["--output", "json", "info", "acme/test-skill"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["summary"]["skill_name"] == "test-skill"


class TestEvalReportJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_eval_report_json(self, _mock_url, _mock_token) -> None:
        report = {
            "id": "r1", "version_id": "v1", "agent": "claude", "judge_model": "claude-3",
            "case_results": [], "passed": 3, "total": 3, "total_duration_ms": 5000,
            "status": "completed", "error_message": None, "created_at": "2026-01-01",
        }
        respx.get("http://test:8000/v1/skills/acme/test-skill/versions/1.0.0/eval-report").mock(
            return_value=httpx.Response(200, json=report)
        )

        result = runner.invoke(app, ["--output", "json", "eval-report", "acme/test-skill@1.0.0"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] == 3
        assert data["status"] == "completed"
```

**Step 2: Run to verify failure, then implement**

For `info_command`: after fetching summary, audit_entry, and eval_report, add:

```python
if is_json():
    result = {"summary": summary, "audit_log": audit_entry, "eval_report": eval_report}
    print_json(result)
    return
```

For `eval_report_command`: after `data = resp.json()`, add:

```python
if is_json():
    print_json(data)
    return
```

**Step 3: Run tests, commit**

```bash
git commit -m "feat(cli): add --output json to info and eval-report commands"
```

---

## Task 7: Add JSON output to `publish`, `delete`, `install`, `visibility`, `logs`

**Files:**
- Modify: `client/src/dhub/cli/registry.py`
- Modify: `client/tests/test_cli/test_registry_cli.py`

**Step 1: Write failing tests for each**

For `publish` — after `resp.json()` in `_publish_skill_directory`, return structured result. The `publish_command` in JSON mode should collect results from `_publish_skill_directory` and output JSON. Key behavior: skip eval log tailing in JSON mode.

For `delete`:
```python
class TestDeleteJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_version_json(self, _mock_url, _mock_token) -> None:
        respx.delete("http://test:8000/v1/skills/acme/test-skill/1.0.0").mock(
            return_value=httpx.Response(200, json={"org_slug": "acme", "skill_name": "test-skill", "version": "1.0.0"})
        )
        result = runner.invoke(app, ["--output", "json", "delete", "acme/test-skill", "--version", "1.0.0"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["version"] == "1.0.0"
```

For `install`: return `{"org": org, "skill": name, "version": resolved_version, "path": str(skill_path)}`.

For `visibility`: return `{"org": org, "skill": name, "visibility": visibility}`.

For `logs` (list mode): return the runs array as JSON. For `logs --follow`: emit NDJSON events.

**Step 2: Implement JSON branches in each**

Pattern for mutating commands — in JSON mode:
- Skip Rich spinners/banners
- Skip interactive confirmation (e.g., `delete` without `--version`)
- Return the server response or structured result as JSON

For `publish` specifically:
- `_publish_skill_directory` should return the result dict (not just True/False) in JSON mode
- Skip `_tail_eval_logs` — just include `eval_run_id` in the output
- For multi-skill publishes, output one JSON per skill (NDJSON)

For `logs`:
- `_list_recent_runs`: if JSON, `print_json(runs)` and return
- `_show_run_status`: if JSON, `print_json(run)` and return
- `_tail_eval_logs` + `_render_event`: if JSON, emit each event as NDJSON line

**Step 3: Run full test suite**

Run: `uv run --package dhub-cli pytest client/tests/test_cli/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git commit -m "feat(cli): add --output json to publish, delete, install, visibility, logs"
```

---

## Task 8: Add `--dry-run` to `publish`

**Files:**
- Modify: `client/src/dhub/cli/registry.py`
- Modify: `client/tests/test_cli/test_registry_cli.py`

**Step 1: Write failing test**

```python
class TestPublishDryRun:
    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_dry_run_no_post(self, _mock_url, _mock_token, _mock_org, tmp_path: Path) -> None:
        """--dry-run should NOT call the publish endpoint."""
        _write_skill_md(tmp_path)
        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(
            return_value=httpx.Response(404)
        )
        # No POST mock — if publish is called, respx will error

        result = runner.invoke(app, ["publish", str(tmp_path), "--dry-run"])

        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "would publish" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_dry_run_json(self, _mock_url, _mock_token, _mock_org, tmp_path: Path) -> None:
        _write_skill_md(tmp_path)
        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(
            return_value=httpx.Response(404)
        )

        result = runner.invoke(app, ["--output", "json", "publish", str(tmp_path), "--dry-run"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "myorg"
        assert data["skill"] == "test-skill"
        assert data["version"] == "0.1.0"
        assert "size_bytes" in data
```

**Step 2: Implement**

Add `--dry-run` flag to `publish_command`:

```python
dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be published without actually publishing"),
```

In `_publish_skill_directory`, before the HTTP POST:

```python
if dry_run:
    result = {"org": org, "skill": name, "version": version, "files": file_count, "size_bytes": len(zip_data)}
    if is_json():
        print_json(result)
    else:
        console.print(f"[yellow]Dry run:[/] Would publish {org}/{name}@{version} ({len(zip_data):,} bytes)")
    return True
```

Thread the `dry_run` parameter through `_publish_skill_directory`, `_publish_discovered_skills`, `_publish_from_directory`, and `_publish_from_git_repo`.

**Step 3: Run tests, commit**

```bash
git commit -m "feat(cli): add --dry-run to publish command"
```

---

## Task 9: Add `--dry-run` to `delete` and `access grant`

**Files:**
- Modify: `client/src/dhub/cli/registry.py` (`delete_command`)
- Modify: `client/src/dhub/cli/access.py` (`grant_command`)
- Modify: `client/tests/test_cli/test_registry_cli.py`
- Modify: `client/tests/test_cli/test_access_cli.py`

**Step 1: Write failing tests**

For `delete --dry-run`: should call the summary endpoint to list versions, NOT the delete endpoint.

```python
class TestDeleteDryRun:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_dry_run(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/skills/acme/test-skill/summary").mock(
            return_value=httpx.Response(200, json={
                "org_slug": "acme", "skill_name": "test-skill", "latest_version": "1.0.0",
            })
        )
        # No DELETE mock — if delete is called, respx will error
        result = runner.invoke(app, ["--output", "json", "delete", "acme/test-skill", "--version", "1.0.0", "--dry-run"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "acme"
```

**Step 2: Implement `--dry-run` flag for delete**

```python
dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted without actually deleting"),
```

For `access grant --dry-run`: validate inputs and check skill exists via GET, don't POST.

**Step 3: Run tests, commit**

```bash
git commit -m "feat(cli): add --dry-run to delete and access grant"
```

---

## Task 10: Add structured error codes and `exit_error` helper

**Files:**
- Modify: `client/src/dhub/cli/output.py`
- Modify: `client/tests/test_cli/test_output.py`

**Step 1: Write the failing test**

```python
class TestExitError:
    def test_exit_error_text_mode(self) -> None:
        from dhub.cli.output import ErrorCode, exit_error, set_format, OutputFormat
        import typer

        set_format(OutputFormat.text)
        with pytest.raises(typer.Exit):
            exit_error(ErrorCode.NOT_FOUND, "Skill not found")

    def test_exit_error_json_mode(self, capsys) -> None:
        from dhub.cli.output import ErrorCode, exit_error, set_format, OutputFormat
        import typer

        set_format(OutputFormat.json)
        with pytest.raises(typer.Exit):
            exit_error(ErrorCode.NOT_FOUND, "Skill not found", status=404)
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"
        assert data["message"] == "Skill not found"
        assert data["status"] == 404
        set_format(OutputFormat.text)
```

**Step 2: Implement ErrorCode and exit_error in output.py**

```python
class ErrorCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    VERSION_EXISTS = "VERSION_EXISTS"
    GAUNTLET_FAILED = "GAUNTLET_FAILED"
    UPGRADE_REQUIRED = "UPGRADE_REQUIRED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


def exit_error(code: ErrorCode, message: str, *, status: int | None = None) -> None:
    """Print an error message and raise typer.Exit(1).

    In JSON mode, writes structured error to stderr.
    In text mode, prints Rich-formatted error to stderr.
    """
    import typer

    if is_json():
        err = {"error": True, "code": code.value, "message": message}
        if status is not None:
            err["status"] = status
        print_json_err(err)
    else:
        from rich.console import Console
        Console(stderr=True).print(f"[red]Error: {message}[/]")

    raise typer.Exit(1)
```

**Step 3: Migrate error handling in commands to use exit_error**

Replace patterns like:
```python
console.print(f"[red]Error: Skill '{skill_ref}' not found.[/]")
raise typer.Exit(1)
```

With:
```python
from dhub.cli.output import ErrorCode, exit_error
exit_error(ErrorCode.NOT_FOUND, f"Skill '{skill_ref}' not found.", status=404)
```

Do this for the most common error paths across registry.py, search.py, access.py, keys.py, config.py. Also update `raise_for_status` in config.py for the 426 case.

**Step 4: Run full test suite to verify nothing broke**

Run: `uv run --package dhub-cli pytest client/tests/ -v`

**Step 5: Commit**

```bash
git commit -m "feat(cli): add structured error codes with exit_error helper"
```

---

## Task 11: Add `dhub doctor` command

**Files:**
- Create: `client/src/dhub/cli/doctor.py`
- Modify: `client/src/dhub/cli/app.py` (register command)
- Create: `client/tests/test_cli/test_doctor_cli.py`

**Step 1: Write the failing test**

```python
# client/tests/test_cli/test_doctor_cli.py
"""Tests for dhub doctor command."""

import json
from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


class TestDoctorCommand:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.config.load_config")
    @patch("dhub.cli.config.get_client_version", return_value="0.6.0")
    def test_doctor_json(self, _mock_ver, _mock_config, _mock_url, _mock_token) -> None:
        from dhub.cli.config import CliConfig
        _mock_config.return_value = CliConfig(
            api_url="http://test:8000", token="test-token",
            orgs=("acme",), default_org="acme",
        )
        respx.get("http://test:8000/health").mock(return_value=httpx.Response(200))

        result = runner.invoke(app, ["--output", "json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["authenticated"] is True
        assert data["org"] == "acme"
        assert data["api_reachable"] is True
        assert data["cli_version"] == "0.6.0"
        assert data["env"] is not None

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value=None)
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.config.load_config")
    @patch("dhub.cli.config.get_client_version", return_value="0.6.0")
    def test_doctor_not_authenticated(self, _mock_ver, _mock_config, _mock_url, _mock_token) -> None:
        from dhub.cli.config import CliConfig
        _mock_config.return_value = CliConfig(api_url="http://test:8000")
        respx.get("http://test:8000/health").mock(return_value=httpx.Response(200))

        result = runner.invoke(app, ["--output", "json", "doctor"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["authenticated"] is False
```

**Step 2: Implement doctor.py**

```python
# client/src/dhub/cli/doctor.py
"""Diagnostic command to validate CLI environment."""

import time

import httpx
from rich.console import Console

console = Console()


def doctor_command() -> None:
    """Check CLI configuration, authentication, and API connectivity."""
    from dhub.cli.config import get_api_url, get_client_version, get_env, get_optional_token, load_config
    from dhub.cli.output import is_json, print_json

    env = get_env()
    api_url = get_api_url()
    token = get_optional_token()
    config = load_config()
    cli_version = get_client_version()

    authenticated = token is not None
    org = config.default_org or (config.orgs[0] if len(config.orgs) == 1 else None)

    # Check API connectivity
    api_reachable = False
    latency_ms = 0
    try:
        start = time.monotonic()
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{api_url}/health")
            api_reachable = resp.status_code == 200
        latency_ms = int((time.monotonic() - start) * 1000)
    except httpx.HTTPError:
        pass

    result = {
        "env": env,
        "cli_version": cli_version,
        "authenticated": authenticated,
        "org": org,
        "api_url": api_url,
        "api_reachable": api_reachable,
        "api_latency_ms": latency_ms,
    }

    if is_json():
        print_json(result)
        return

    # Rich text output
    def _check(ok: bool, msg: str) -> None:
        icon = "[green]OK[/]" if ok else "[red]FAIL[/]"
        console.print(f"  {icon}  {msg}")

    console.print()
    _check(authenticated, f"Authenticated" + (f" (org: {org})" if org else ""))
    _check(api_reachable, f"API reachable at {api_url} ({latency_ms}ms)")
    console.print(f"  [dim]--[/]   CLI version: {cli_version}")
    console.print(f"  [dim]--[/]   Environment: {env}")
    console.print()
```

**Step 3: Register in app.py**

```python
from dhub.cli.doctor import doctor_command
app.command("doctor")(doctor_command)
```

**Step 4: Run tests, commit**

```bash
git add client/src/dhub/cli/doctor.py client/src/dhub/cli/app.py client/tests/test_cli/test_doctor_cli.py
git commit -m "feat(cli): add dhub doctor diagnostic command"
```

---

## Task 12: Update SKILL.md with agent invariants

**Files:**
- Modify: `bootstrap-skills/dhub-cli/SKILL.md`
- Modify: `bootstrap-skills/dhub-cli/references/command_reference.md`

**Step 1: Add "Agent Usage" section to SKILL.md**

Add after the existing agent guidance section:

```markdown
## Agent Usage (Scripting & Automation)

### Output format

Always use `--output json` when calling dhub programmatically:

```bash
dhub --output json list
dhub --output json ask "find data science skills"
dhub --output json info acme/my-skill
```

JSON goes to stdout; errors go to stderr. Never parse the default text output.

### Dry-run before mutations

Always preview destructive operations before executing:

```bash
dhub publish ./my-skill --dry-run          # see what would be published
dhub delete acme/my-skill --dry-run        # see what would be deleted
```

### Pre-flight checks

Run `dhub doctor --output json` before any workflow to verify auth, connectivity, and version.

### Idempotency

| Command | Safe to retry? | Notes |
|---------|---------------|-------|
| `install` | Yes | Overwrites existing installation |
| `publish` | Yes | Same checksum = skip (no-op) |
| `delete` | No | Second call returns 404 |
| `ask` | Yes | Pure query, no side effects |
| `list` | Yes | Pure query |
| `info` | Yes | Pure query |

### Atomicity

| Command | Atomic? | Notes |
|---------|---------|-------|
| `install` | Yes | Download + verify + extract all succeed or none |
| `publish` | Partial | Skill published even if tracker creation fails |
| `delete` | Yes | Single API call |

### Error codes

In `--output json` mode, errors are structured JSON on stderr:

```json
{"error": true, "code": "NOT_FOUND", "message": "Skill 'acme/foo' not found.", "status": 404}
```

Codes: `AUTH_REQUIRED`, `PERMISSION_DENIED`, `NOT_FOUND`, `VERSION_EXISTS`,
`GAUNTLET_FAILED`, `UPGRADE_REQUIRED`, `VALIDATION_ERROR`, `SERVICE_UNAVAILABLE`
```

**Step 2: Update command_reference.md**

Add `--output json` and `--dry-run` flags to each command's documentation.

**Step 3: Commit**

```bash
git commit -m "docs: add agent usage section with idempotency, error codes, and scripting guide"
```

---

## Task 13: Run full test suite and lint

**Step 1: Run all client tests**

Run: `uv run --package dhub-cli pytest client/tests/ -v`
Expected: ALL PASS

**Step 2: Run linter**

Run: `make lint` (from repo root)
Expected: PASS

**Step 3: Run type checker**

Run: `make typecheck` (from repo root)
Expected: PASS (or only pre-existing issues)

**Step 4: Final commit if any fixups needed**

```bash
git commit -m "fix: lint and type check fixups"
```

---

## Task 14: Open PR

Create branch, push, and open PR:

```bash
git checkout -b feat/agent-friendly-cli
git push -u origin feat/agent-friendly-cli
gh pr create --title "feat(cli): agent-friendly output with --output json, --dry-run, and doctor" \
  --body "$(cat <<'EOF'
## Summary

Makes the dhub CLI scriptable by AI agents:

- Global `--output json` flag for machine-readable output on all commands
- `--dry-run` flag on `publish`, `delete`, and `access grant`
- Structured error codes in JSON mode (stderr)
- New `dhub doctor` diagnostic command
- Updated SKILL.md with agent usage guide (idempotency, error codes, scripting)

Ref: https://justin.poehnelt.com/posts/rewrite-your-cli-for-ai-agents/

## Test plan

- [ ] `dhub --output json list` returns valid JSON
- [ ] `dhub --output json ask "data science"` returns structured response
- [ ] `dhub publish --dry-run .` shows what would be published without POSTing
- [ ] `dhub delete acme/skill --dry-run` shows what exists without deleting
- [ ] `dhub --output json doctor` returns environment diagnostics
- [ ] All existing tests still pass
- [ ] New tests cover JSON mode for each command

Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
