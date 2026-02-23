# Open Source Release Audit Checklist

This document outlines the checklist for auditing the codebase before an open-source release. The goal is to ensure legal compliance, security, code quality, and usability for external contributors.

## 1. Legal & Compliance
- [ ] **LICENSE**: Ensure a valid open-source license (e.g., MIT, Apache 2.0) is present in the root directory and clearly states the terms.
- [ ] **Copyright Headers**: Check for consistent copyright headers in source files if required by the license.
- [ ] **Third-Party Dependencies**: verify that all dependencies (Python, JS) have compatible licenses.
- [ ] **Trademarks**: Ensure no trademarked names or logos are used inappropriately or without permission.
- [ ] **Contributor License Agreement (CLA)**: Decide if a CLA is needed and if so, set it up.

## 2. Security & Secrets
- [ ] **Hardcoded Secrets**: Scan for API keys, passwords, tokens, and private keys in the codebase (git history included if possible, but definitely in HEAD).
    - AWS credentials
    - Modal tokens
    - OpenAI/Anthropic/Gemini keys
    - Database URLs/passwords
    - GitHub tokens
- [ ] **Internal URLs/IPs**: Check for hardcoded internal URLs, IP addresses, or domain names that are not public.
- [ ] **Configuration Management**: Ensure configuration is loaded from environment variables or external config files, not hardcoded.
- [ ] **Dependency Vulnerabilities**: Audit dependencies for known security vulnerabilities (e.g., using `safety` or `npm audit`).
- [ ] **Data Privacy**: Ensure no PII (Personally Identifiable Information) or sensitive user data is included in test data or fixtures.

## 3. Documentation & Community
- [ ] **README.md**: comprehensive README with:
    - Project description and purpose.
    - Installation and setup instructions.
    - Usage examples.
    - Badge links (CI, coverage, version).
- [ ] **CONTRIBUTING.md**: Guidelines for contributors (reporting bugs, submitting PRs, coding standards).
- [ ] **CODE_OF_CONDUCT.md**: standard code of conduct (e.g., Contributor Covenant).
- [ ] **Changelog**: A `CHANGELOG.md` or release notes mechanism.
- [ ] **Issue Templates**: GitHub issue and PR templates to guide users.
- [ ] **Contact Information**: Clear way to contact maintainers for security issues or general questions.

## 4. Code Quality & Standards
- [ ] **Linting & Formatting**: Ensure code adheres to stated style guides (ruff, mypy, prettier, eslint).
- [ ] **Testing**: Verify that tests pass and cover core functionality.
- [ ] **Dead Code**: Remove unused files, functions, and variables.
- [ ] **TODOs/FIXMEs**: Review and address critical TODOs or FIXMEs.
- [ ] **Comments**: Ensure comments are helpful and not revealing internal implementation details that shouldn't be public.

## 5. Build, Release & Infrastructure
- [ ] **CI/CD**: specific CI workflows that might fail in a public fork (e.g., due to missing secrets) or run unnecessary internal checks.
- [ ] **Package Configuration**: `pyproject.toml`, `package.json` metadata (authors, urls, classifiers) is correct for public release.
- [ ] **Docker/Containerization**: `Dockerfile` or container build scripts (Modal) are clean and functional.
- [ ] **Environment Setup**: `Makefile` or setup scripts work for external users without internal access.
- [ ] **Dependencies**: `uv.lock` and `package-lock.json` are up-to-date and consistent.

## 6. Product Specific (Decision Hub)
- [ ] **Default Configuration**: Ensure default config points to public/local endpoints, not internal prod/dev by default if possible, or clearly documents how to set them.
- [ ] **Modal specific**: Check `modal_app.py` for hardcoded secrets or internal-only logic.
- [ ] **LLM specific**: Ensure prompt templates don't contain sensitive system instructions unless intended to be public.
