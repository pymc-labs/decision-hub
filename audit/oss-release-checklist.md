# OSS Release Checklist — Decision Hub

This checklist covers all items that must be verified before the Decision Hub
codebase is made publicly available.

---

## 1. Secrets & Credentials

- [x] **No real API keys in source** — all keys are placeholders or loaded from env vars
- [x] **No `.env` files tracked** — only `.env.example` templates are committed
- [x] **No private keys or certificates** — `.pem`/`.key` files are git-ignored
- [x] **No secrets in git history** — verified via `git log --diff-filter=A`
- [x] **No hardcoded database credentials** — connection strings use placeholders
- [x] **No AWS credentials** — loaded from environment / Modal secrets
- [x] **Test files use fake keys** — e.g. `sk-ant-test-key`, `ghp_test`
- [ ] **Personal Modal URLs in examples** — `frontend/.env.example` contains `lfiaschi--api-dev.modal.run`
- [ ] **Personal Modal URLs in bootstrap skills** — `bootstrap-skills/dhub-cli/SKILL.md` and `references/command_reference.md`

## 2. Hardcoded Infrastructure References

- [ ] **Client API URLs** — `config.py` hardcodes `pymc-labs--api.modal.run` / `pymc-labs--api-dev.modal.run`
- [ ] **Custom domains** — `modal_app.py` hardcodes `hub.decision.ai` / `hub-dev.decision.ai`
- [ ] **SEO base URL** — `seo_routes.py` hardcodes `https://decisionhub.dev` and `hub.decision.ai`
- [ ] **Frontend SEO** — `useSEO.ts` hardcodes `https://hub.decision.ai`
- [ ] **Structured data** — `HomePage.tsx` hardcodes `hub.decision.ai` in JSON-LD
- [ ] **Deploy script URLs** — `scripts/deploy.sh` hardcodes `pymc-labs--api.modal.run`
- [ ] **Modal secret names** — `modal_app.py` uses `decision-hub-db`, `decision-hub-secrets`, etc.
- [ ] **S3 bucket name** — `.env.example` shows `decision-hub-skills`

## 3. Organization & Company References

- [ ] **`pymc-labs` in client config** — hardcoded as Modal workspace in API URLs (2 occurrences)
- [ ] **`pymc-labs` in frontend** — Layout footer, GitHub repo links, example terminal output
- [ ] **`pymc-labs` in featured orgs** — `featuredOrgs.ts` includes `pymc-labs` in curated list
- [ ] **`pymc-labs` in legal pages** — TermsPage and PrivacyPage reference `info@pymc-labs.com`
- [ ] **`pymc-labs` in HowItWorksPage** — example commands show `pymc-labs/` org
- [ ] **`pymc-labs` in AnimatedTerminal** — example output references `pymc-labs`
- [ ] **`@lfiaschi` in CODEOWNERS** — personal username as sole code owner
- [ ] **PyMC Labs website link** — `Layout.tsx` footer links to `pymc-labs.com`
- [ ] **Personal email in LICENSE** — `luca.fiaschi@pymc-labs.com` (may be intentional)
- [ ] **Personal email in client pyproject.toml** — `luca.fiaschi@gmail.com`

## 4. License & Legal

- [x] **LICENSE file exists** — MIT License present at root
- [x] **No GPL/copyleft dependency conflicts** — all deps are MIT/Apache/BSD compatible
- [ ] **Missing license in server/pyproject.toml** — no `license = "MIT"` field
- [ ] **Missing license in shared/pyproject.toml** — no `license = "MIT"` field
- [ ] **Missing license in frontend/package.json** — no `"license": "MIT"` field
- [ ] **Terms of Service page** — references PyMC Labs as operator
- [ ] **Privacy Policy page** — references PyMC Labs as data controller

## 5. Documentation Readiness

- [ ] **CLAUDE.md contains sensitive info** — GitHub App IDs, Modal secret names, internal deployment details
- [ ] **AGENTS.md contains sensitive info** — duplicates CLAUDE.md content
- [ ] **PRD.md is internal** — product requirements document with internal planning
- [ ] **tasks.md is internal** — task tracking file
- [ ] **No CONTRIBUTING.md** — missing contributor guidelines
- [ ] **No CODE_OF_CONDUCT.md** — missing code of conduct
- [ ] **No SECURITY.md** — missing security disclosure policy
- [ ] **No CHANGELOG.md** — missing changelog (GitHub Releases exist but no file)
- [ ] **No issue templates** — `.github/ISSUE_TEMPLATE/` directory missing
- [x] **README.md is public-quality** — good overview, install instructions, usage examples
- [ ] **README.md references internal URLs** — `hub.decision.ai` hardcoded
- [ ] **.claude/ directory** — contains test commands with personal Modal URLs
- [ ] **docs/skill-scanner-integration-analysis.md** — internal analysis document

## 6. Security

- [x] **Parameterized SQL queries** — SQLAlchemy Core with bind parameters throughout
- [x] **JWT authentication** — write endpoints protected, proper validation
- [x] **Rate limiting** — all public endpoints rate-limited
- [x] **Input validation** — max_length constraints, Pydantic models, custom validators
- [x] **Error messages sanitized** — no credential leakage in errors
- [x] **Subprocess credentials sanitized** — tokens stripped from error messages
- [x] **API keys encrypted at rest** — Fernet encryption for stored keys
- [ ] **No explicit CORS middleware** — relies on same-origin serving
- [ ] **Missing security headers** — no HSTS, CSP, X-Frame-Options
- [ ] **print() in production code** — `modal_app.py:387` uses print instead of logger

## 7. GitHub App & OAuth Configuration

- [ ] **GitHub App IDs documented in CLAUDE.md** — dev App ID 2887189, prod App ID 2887208
- [ ] **GitHub App Installation IDs** — dev 111380021, prod 111379955
- [x] **App credentials in Modal secrets** — not in source code
- [x] **OAuth client_id configurable** — loaded from env var

## 8. CI/CD & Deployment

- [x] **Workflows use secret references** — `${{ secrets.* }}` pattern
- [x] **Deploy script is env-aware** — respects DHUB_ENV
- [ ] **Deploy script hardcodes Modal workspace** — `pymc-labs--api` in URL echo
- [ ] **GitHub Actions references** — dev environment tied to specific GitHub Environment

## 9. Test Data

- [x] **Test keys are fake** — all test API keys are placeholder values
- [x] **Test DB URLs are local** — `postgresql://test` or `localhost:5432`
- [ ] **Test data references `pymc-labs`** — 50+ references across test files (acceptable as org examples)

## 10. Git History

- [x] **No secrets ever committed** — clean history verified
- [x] **No .env files in history** — only .env.example tracked
- [x] **No private keys in history** — clean
- [x] **Commit messages are clean** — no internal details leaked
