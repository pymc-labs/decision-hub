"""CLI catalog filters, ordering, and pagination against a mocked registry."""

import json

import httpx
import pytest
from typer.testing import CliRunner

from dhub.cli.app import app
from dhub.cli.output import OutputFormat, set_format

runner = CliRunner()
REGISTRY = "https://registry.example"


@pytest.fixture
def catalog(monkeypatch, respx_mock):
    monkeypatch.setenv("DHUB_NO_UPDATE_CHECK", "1")
    monkeypatch.setattr("dhub.cli.config.get_api_url", lambda: REGISTRY)
    monkeypatch.setattr("dhub.cli.config.get_optional_token", lambda: None)
    yield respx_mock.get(f"{REGISTRY}/v1/skills")
    set_format(OutputFormat.text)


@pytest.mark.parametrize(
    ("options", "sort", "direction"),
    [
        ([], "downloads", "desc"),
        (["--sort", "updated"], "updated", "desc"),
        (["--sort", "github_stars"], "github_stars", "desc"),
        (["--sort", "safety_rating"], "safety_rating", "desc"),
        (["--sort-dir", "asc"], "downloads", "asc"),
    ],
)
def test_list_sort_defaults_and_overrides(catalog, options, sort, direction):
    catalog.respond(json={"items": [], "total": 0, "total_pages": 1})

    result = runner.invoke(app, ["list", *options])

    assert result.exit_code == 0, result.output
    assert "No skills found." in result.stdout
    assert dict(catalog.calls.last.request.url.params) == {
        "page": "1",
        "page_size": "50",
        "sort": sort,
        "sort_dir": direction,
    }


@pytest.mark.parametrize(("output", "flags", "pages"), [("text", [], 1), ("text", ["--all"], 2), ("json", [], 2)])
def test_list_sends_combined_filters_on_every_page(catalog, output, flags, pages):
    items = [
        {"org_slug": "acme", "skill_name": name, "latest_version": "1.0.0", "safety_rating": "B"}
        for name in ("doc-a", "doc-b")
    ]
    catalog.side_effect = [
        httpx.Response(200, json={"items": [item], "total": 2, "page": page, "page_size": 1, "total_pages": 2})
        for page, item in enumerate(items, start=1)
    ]
    category = "Documents & Files,Backend & APIs"
    result = runner.invoke(
        app,
        [
            "--output",
            output,
            "list",
            "--org",
            "acme",
            "--skill",
            "doc",
            "--category",
            category,
            "--grade",
            "b",
            "--sort",
            "name",
            "--sort-dir",
            "asc",
            "--page-size",
            "1",
            *flags,
        ],
    )

    assert result.exit_code == 0, result.output
    assert [dict(call.request.url.params) for call in catalog.calls] == [
        {
            "page": str(page),
            "page_size": "1",
            "org": "acme",
            "search": "doc",
            "category": category,
            "grade": "B",
            "sort": "name",
            "sort_dir": "asc",
        }
        for page in range(1, pages + 1)
    ]
    if output == "json":
        assert json.loads(result.stdout) == {"items": items, "total": 2, "page_size": 2, "total_pages": 1}
    else:
        assert "Published Skills" in result.stdout
        assert "Page 1 of 2 (2 total skills)" in result.stdout
        assert ("Page 2 of 2 (2 total skills)" in result.stdout) == (pages == 2)


@pytest.mark.parametrize("grade", ["A", "C", "F"])
def test_list_accepts_safety_grades(catalog, grade):
    catalog.respond(json={"items": [], "total": 0, "total_pages": 1})

    result = runner.invoke(app, ["list", "--grade", grade])

    assert result.exit_code == 0, result.output
    assert catalog.calls.last.request.url.params["grade"] == grade


@pytest.mark.parametrize(("option", "value"), [("--grade", "D"), ("--sort", "stars"), ("--sort-dir", "up")])
def test_list_rejects_invalid_choices_before_request(catalog, option, value):
    result = runner.invoke(app, ["--output", "json", "list", option, value])

    assert result.exit_code == 2
    assert result.stdout == ""
    assert option in result.stderr
    assert value in result.stderr
    assert not catalog.called
