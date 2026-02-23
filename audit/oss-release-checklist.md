# Open Source Release Audit Checklist

Status Legend:
- [x] **PASS**: Checked and confirmed safe/present.
- [ ] **FAIL**: Issue identified (see `audit/issues/`).
- [-] **N/A**: Not applicable or deferred.

## 1. Legal & Compliance
- [x] **Root License**: `LICENSE` file (MIT) is present in root.
- [ ] **Sub-package Licenses**: Check `client/`, `server/`, `shared/` for license metadata. -> **FAIL** (See `BLOCKER-missing-license-declarations.md`)
- [x] **Third-Party Dependencies**: All Python/JS dependencies have compatible licenses (mostly MIT/Apache).
- [ ] **Trademarks**: "Decision Hub" and "PyMC Labs" usage. -> **FAIL** (See `CRITICAL-branding-hardcoding.md`)
- [ ] **Copyright Headers**: Check for consistent headers. -> **FAIL** (Inconsistent/Personal vs Org)

## 2. Security & Secrets
- [x] **Hardcoded Secrets**: Scanned for API keys/tokens (AWS, Modal, OpenAI). **PASS** (None found in code).
- [ ] **Internal URLs/IPs**: Check for hardcoded internal URLs. -> **FAIL** (See `BLOCKER-hardcoded-api-urls-in-client.md`)
- [ ] **Auth Rate Limiting**: Verify rate limits on public auth endpoints. -> **FAIL** (See `CRITICAL-missing-auth-rate-limits.md`)
- [ ] **Security Policy**: `SECURITY.md` for vulnerability reporting. -> **FAIL** (See `BLOCKER-missing-security-policy.md`)
- [x] **Input Validation**: `max_length` constraints on API parameters. **PASS**.
- [x] **SQL Injection**: Uses SQLAlchemy/parameterized queries. **PASS**.

## 3. Infrastructure & Deployment
- [ ] **Deployment Config**: `modal_app.py` allows third-party deployment. -> **FAIL** (See `BLOCKER-hardcoded-modal-domains.md`)
- [ ] **Client Config**: CLI defaults to public/local, not internal. -> **FAIL** (See `BLOCKER-hardcoded-api-urls-in-client.md`)
- [ ] **SEO/Frontend Config**: Canonical URLs are configurable. -> **FAIL** (See `CRITICAL-hardcoded-seo-urls.md`)
- [ ] **Deploy Scripts**: Scripts output generic/correct info. -> **FAIL** (See `IMPORTANT-hardcoded-deploy-url-output.md`)

## 4. Documentation & Community
- [x] **README.md**: Comprehensive project description and setup. **PASS**.
- [ ] **Internal Docs**: No internal/sensitive docs committed. -> **FAIL** (See `BLOCKER-internal-docs-committed.md`)
- [ ] **Contribution Guide**: `CONTRIBUTING.md` exists. -> **FAIL** (See `CRITICAL-missing-community-docs.md`)
- [ ] **Code of Conduct**: `CODE_OF_CONDUCT.md` exists. -> **FAIL** (See `CRITICAL-missing-community-docs.md`)
- [ ] **Issue Templates**: GitHub issue templates exist. -> **FAIL** (Missing)

## 5. Code Quality & Metadata
- [ ] **Package Metadata**: Author emails are generic/org-based. -> **FAIL** (See `IMPORTANT-personal-email-metadata.md`)
- [ ] **CODEOWNERS**: Uses teams/orgs, not individuals. -> **FAIL** (See `IMPORTANT-codeowners-personal-username.md`)
- [x] **Linting**: Ruff/Mypy configured and passing. **PASS**.
- [x] **Tests**: Unit tests present for core logic. **PASS**.

## 6. Build & Release
- [x] **CI Workflows**: GitHub Actions present. **PASS**.
- [x] **Lockfiles**: `uv.lock` and `package-lock.json` are up-to-date. **PASS**.
- [x] **Versioning**: Semantic versioning used. **PASS**.
