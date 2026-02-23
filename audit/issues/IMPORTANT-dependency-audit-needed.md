# IMPORTANT: Dependency Security Audit Not Performed

## Summary

No automated dependency vulnerability scanning is configured. The project
should verify that all Python and JavaScript dependencies are free of known
CVEs before public release.

## Action Items

### Python Dependencies

```bash
uv pip install pip-audit
pip-audit --requirement server/pyproject.toml
pip-audit --requirement client/pyproject.toml
pip-audit --requirement shared/pyproject.toml
```

### JavaScript Dependencies

```bash
cd frontend && npm audit
```

### Ongoing

Consider adding:
- `pip-audit` or `safety` to CI pipeline
- `npm audit` to frontend CI step
- Dependabot or Renovate for automated dependency updates
- GitHub's native dependency scanning (free for public repos)

## Deferral Rationale

The dependency versions appear current and no known issues were found in
manual review. However, an automated scan should be performed and CI
integration added. Can be done post-release as GitHub enables free scanning
for public repos automatically.
