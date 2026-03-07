# Gauntlet False Positive Analysis — March 2026

## Summary

Re-ran the current gauntlet on all 102 skills graded F in prod.
**57 (56%) were false positives** that now receive correct grades.

| New Grade | Count |
|-----------|-------|
| A         | 21    |
| B         | 28    |
| C         | 4     |
| Still F   | 43    |
| Error     | 2     |

## Root Cause Categories

### 1. Fail-closed LLM errors (16 skills)

The Gemini API returned no response or an unparseable response, triggering
the fail-closed default (dangerous=True). These were transient API
failures — re-running with the same code produces correct results.

Skills: a5c-ai/memory-summarization, a5c-ai/weaviate-integration,
aiskillstore/coder, doodledood/auto-optimize-prompt, erp-core-dev/generate-endpoint,
erp-core-dev/generate-helm-chart, erp-core-dev/generate-service,
michealwayne/bilingual-jsdoc, murabcd/memory, nickcrew/git-ops,
robertpelloni/rot13-encryption, starlake-ai/extract,
starwreckntx/cognitive-trap-detector, starwreckntx/symbol-map-entropy-calc,
szymonkaliski/git-review, xdg/isolated

Root cause: Transient Gemini failures + fail-closed design.
Fix: No code fix needed — self-heal on re-run. Consider adding
retry logic or a manual re-grade mechanism.

### 2. Entropy credential false positives (8 skills)

The Shannon entropy scanner flagged high-entropy strings that the LLM
judge then incorrectly confirmed as credentials. Common patterns:
- SHA-256 hashes in skill-report.json (integrity checksums, not secrets)
- Regex patterns that search for API keys (e.g. grep OPENAI_API_KEY)
- Environment variable names mentioned in documentation
- Placeholder example values

Skills: aiskillstore/ccxt, aiskillstore/data-visualization,
aiskillstore/planning-framework, aiskillstore/skill-builder,
coffelix2023/build-app-step01, coffelix2023/build-app-workflow,
hainamchung/legacy-modernizer, kunwl123456/byterover

Root cause: LLM credential judge confused regex patterns searching
for secrets with actual embedded secrets. Also: SHA-256 hashes in
skill-report.json are integrity checksums, not credentials.

### 3. Holistic body review false positives (8 skills)

The holistic SKILL.md body review flagged legitimate skill instructions
as dangerous prompt injection:
- Shell variable syntax like ARGUMENTS flagged as "unsanitized input"
- Debugging instructions flagged as covert signaling
- CTF flag patterns flagged as prompt injection
- Skill invocation instructions flagged as "forcing agent behavior"

Skills: aiskillstore/lovable, aiskillstore/receiving-code-review,
alps-asd/alps, coffelix2023/meta-superpowers, hermit403/gift,
nickcrew/receiving-code-review, oyi77/google-flow, xdg/refactor

Root cause: LLM body reviewer too aggressive — flagging normal
skill patterns (shell vars, agent workflow instructions) as attacks.

### 4. Holistic code review false positives (7 skills)

The holistic code review flagged files that contain documentation
examples or reference material showing security patterns:
- Security reference docs showing attack examples (for educational use)
- Code sending to well-known APIs flagged as exfiltration
- Documentation code snippets treated as executable code
- Non-hit review missing context about already-cleared hit files

Skills: aiskillstore/claude-cookbooks, aiskillstore/mcp-builder,
boboc135612/receiving-code-review, cisco-ai-defense/eicar-test,
kunwl123456/mind-blow, kunwl123456/speedtest, oyi77/agent-docs

Root cause: LLM code reviewer does not distinguish documentation
examples from executable code. The non-hit holistic review also
lacked context about already-cleared hit files (fixed in this PR).

### 5. Safety scan LLM confirmed false positives (7 skills)

The per-file LLM judge incorrectly confirmed regex hits as dangerous:
- subprocess calls to ffmpeg/imagemagick for media conversion
- subprocess calls to dot (Graphviz) for rendering graphs
- subprocess calls to libreoffice for spreadsheet recalculation
- Documentation examples showing dangerous patterns (not executable code)

Skills: aiskillstore/writing-skills, boboc135612/writing-skills,
hainamchung/media-processing, oyi77/content-generator,
oyi77/writing-skills, sd0xdev/security-review, wenjunduan/xlsx

Root cause: LLM judge treats legitimate tool invocations
(ffmpeg, graphviz, libreoffice) as dangerous subprocess usage.

### 6. Hardcoded credential in documentation (4 skills)

Example/placeholder credentials in README or reference docs were
flagged as real hardcoded credentials:
- password="example" in README setup instructions
- Example tokens in documentation
- Example API keys in OWASP reference material

Skills: a5c-ai/mlflow-experiment-tracker, a5c-ai/rag-hybrid-search,
nickcrew/owasp-top-10, nymbo/model-trainer

Root cause: Regex + LLM cannot distinguish "example showing what
a credential looks like" from "actual credential in code."

### 7. Prompt safety pattern false positives (4 skills)

curl commands to well-known APIs or localhost were flagged as
exfiltration URLs:
- curl to localhost (local API testing)
- curl to well-known cloud platform URLs (Cloudflare Workers docs)

Skills: aiskillstore/ai-maestro-documentation-search,
aiskillstore/internationalizing-websites, aiskillstore/proxychains,
hainamchung/building-ai-agent-on-cloudflare

Root cause: Any curl URL in skill content triggers the
exfiltration URL regex, and the LLM judge is too cautious about
documentation examples.

### 8. LLM parse failures (3 skills)

The LLM returned unparseable JSON, treated as dangerous (fail-closed).

Skills: aiskillstore/theme-factory, boboc135612/xlsx, hainamchung/xlsx

Root cause: Same as fail-closed. Transient API issues.

## Changes in this PR

### Bug fix: non-hit holistic review missing context

When the per-file LLM judge clears regex hits in file A, the holistic
review of non-hit files (B, C, ...) did not know file A existed in the
package. The LLM would hallucinate that imports from A were
"unverifiable" and flag the skill as dangerous.

Fix: prepend a _CLEARED_FILES.txt context note listing already-cleared
hit file names to the holistic review input.

### Regression tests

Added regression tests covering the top false positive patterns:
- f-string URL interpolation falsely flagged as credential
- Placeholder API keys in error messages falsely flagged
- Non-hit holistic review receiving cleared-file context
- Documentation examples of credentials not flagged
- Legitimate subprocess calls (ffmpeg, graphviz, libreoffice) not flagged
- curl to localhost not flagged as exfiltration
- SHA-256 hashes not flagged as credentials
