# Decision Hub (v1.0)
**The Package Manager & Runtime for AI Agent Skills**

---

## 1. Executive Summary

Decision Hub is the `npm` or `cargo` for AI agents. It is a CLI-first registry that allows developers to publish, discover, and securely install "Skills"—modular capabilities (code + prompts) that agents like Claude, Cursor, and OpenClaw can use.

Unlike standard package managers, Decision Hub solves the **Runtime Problem**: it ensures skills run in deterministic, isolated environments (via `uv` locally or `Modal` remotely) so they never break the user's machine or pollute global dependencies.

**Core Philosophy:**
1.  **Headless First:** No web UI in v1. Discovery and management happen entirely in the terminal (`dhub ask`, `dhub org`).
2.  **Managed Runtimes:** Skills define *where* they run (Local Sandbox vs. Cloud Container).
3.  **Trust via Evals:** We don't just host code; we grade it. Every skill undergoes automated security scanning and functional testing ("The Gauntlet") before publishing.

---

## 2. User Experience (The CLI)

### Discovery & Installation
```bash
# Intelligent Search (Uses LLM Index)
$ dhub ask "I need to analyze A/B test results"
> Recommended: pymc/causalpy (v1.4.2)
  Type: Local (runs on your machine via uv)
  Trust: A (Passed all 7 tests)

# Installation
$ dhub install pymc/causalpy
> Downloading...
> Verifying checksum...
> Hydrating environment (uv sync)...
> Installed to ~/.dhub/skills/pymc-labs/causalpy
Publishing (The Developer)Bash# Login (GitHub Device Flow)
$ dhub login
> Authenticated as @lfiaschi

# Create Organization
$ dhub org create pymc-labs
> Organization 'pymc-labs' created.

# Add Team Member
$ dhub org invite pymc-labs --user "jchu" --role "admin"
> Invite sent to @jchu.

# Publish Skill
$ dhub publish
> Validating SKILL.md... OK
> Uploading zip... OK
> Triggering Remote Evals...
  [====================] 100%
> PASS: Functional Tests (5/5)
> PASS: Security Scan
> Published: pymc-labs/causalpy@1.4.2
3. Skill Format & Runtime SpecificationSkills are distributed as .zip archives. The core contract is the SKILL.md manifest, which defines Metadata (for the Agent) and Runtime (for the Execution Engine).File StructurePlaintextmy-skill/
├── SKILL.md            # Manifest
├── uv.lock             # Dependency Freeze (Required for local)
├── src/
│   └── main.py         # Entrypoint
└── tests/
    └── cases.json      # Required for Evals
SKILL.md SpecificationYAML---
name: causalpy
version: "1.4.2"
description: >
  Bayesian causal inference for experiment analysis.
  Use when the user asks about A/B tests or lift analysis.

# The Runtime Contract
runtime:
  # Option A: Local Isolation (Default)
  driver: "local/uv"
  config:
    entrypoint: "src/main.py"
    lockfile: "uv.lock"
    # Env vars the user must provide
    env: ["OPENAI_API_KEY"]

  # Option B: Cloud Execution (Heavy/Private)
  # driver: "remote/modal"
  # config:
  #   function: "decision-hub/video-gen::generate"
  #   revision: "sha256:..."

# The Trust Contract
testing:
  cases: "tests/cases.json" # Input/Output pairs
---
# System Prompt for the Agent
You are an expert statistician. When analyzing data...
4. The Evaluations Framework ("The Gauntlet")We treat all uploaded code as "Unsafe." The Registry runs a pipeline on every dhub publish.A. Static Analysis (The Linter)Manifest Check: Validates YAML schema (Pydantic).Dependency Audit: Scans uv.lock for CVEs.Safety Scan: Greps source code for blocked patterns (subprocess.call, hardcoded AWS keys, eval()).B. Functional Testing (The Unit Tests)Mechanism: The Registry spins up a Modal Sandbox.Execution:Installs skill dependencies (via uv).Runs src/main.py with inputs from tests/cases.json.Compares STDOUT against expected output.Result: If the skill crashes or JSON schema mismatches, Publish Rejected.5. Technical ArchitectureThe StackComponentTechnologyReasoningCLIPython (Typer)Type-safe, intuitive CLI building. Native to AI devs.APIFastAPIAsync, auto-docs, easy integration with Modal/S3.DatabasePostgreSQLRelational data for Orgs, Users, Versions.StorageS3 / R2Cheap storage for skill artifacts (.zip).ComputeModalServerless python environments for running Evals.SearchLLM (Gemini/GPT)"Context Window" search. No vector DB needed yet.Database Schema (PostgreSQL)SQL-- Identity
CREATE TABLE users (
  id UUID PRIMARY KEY,
  github_id TEXT UNIQUE,
  username TEXT UNIQUE
);

CREATE TABLE organizations (
  id UUID PRIMARY KEY,
  slug TEXT UNIQUE, -- "pymc-labs"
  owner_id UUID REFERENCES users(id)
);

CREATE TABLE org_members (
  org_id UUID REFERENCES organizations(id),
  user_id UUID REFERENCES users(id),
  role TEXT DEFAULT 'member', -- owner, admin, member
  PRIMARY KEY (org_id, user_id)
);

CREATE TABLE org_invites (
  id UUID PRIMARY KEY,
  org_id UUID REFERENCES organizations(id),
  invitee_github_username TEXT,
  status TEXT DEFAULT 'pending'
);

-- Registry
CREATE TABLE skills (
  id UUID PRIMARY KEY,
  org_id UUID REFERENCES organizations(id),
  name TEXT, -- "causalpy"
  UNIQUE(org_id, name)
);

CREATE TABLE versions (
  id UUID PRIMARY KEY,
  skill_id UUID REFERENCES skills(id),
  semver TEXT, -- "1.0.0"
  s3_key TEXT,
  checksum TEXT,
  runtime_config JSONB, -- Stores the parsed runtime block
  eval_status TEXT DEFAULT 'pending', -- pending, passed, failed
  UNIQUE(skill_id, semver)
);
6. Implementation RoadmapSprint 1: The "Dumb" Registry (Multi-User MVP)Goal: Teams can create orgs, invite members, and share skills securely.Repo: Monorepo setup (CLI + API).Auth: Implement GitHub Device Flow & JIT User Creation.Orgs: Implement create, invite, accept logic.Publish: Basic .zip upload to S3 + DB record creation.Install: CLI downloads zip, verifies SHA256, unzips to ~/.dhub.Sprint 2: The Local Runtime (uv)Goal: Skills actually run on the user's machine without breaking it.Spec: Implement strict Pydantic validation for SKILL.md.CLI Runtime: Implement dhub run wrapper.Checks for uv.Runs uv sync in the skill directory.Executes entrypoint with isolated environment.Sprint 3: The Gauntlet (Modal Evals)Goal: Automated trust.Evaluator: Create the Modal function that runs tests/cases.json.Integration: Trigger this function via API webhooks on Publish.Gating: Update DB to only allow installation of skills with eval_status = 'passed'.Sprint 4: Intelligence (Search)Goal: Natural language discovery.Indexer: Cron job to dump Skill Metadata to index.jsonl.Search API: Endpoint using LLM to map user query -> skill list.CLI: Implement dhub ask.7. API Contract (Critical Endpoints)AuthPOST /auth/github/code -> Start device flow.POST /auth/github/token -> Exchange code for JWT.OrgsPOST /v1/orgs -> { slug: "pymc" }POST /v1/orgs/{org}/invites -> { github_user: "jchu", role: "admin" }POST /v1/invites/{id}/acceptRegistryPOST /v1/publish -> Multipart (Metadata JSON + Zip File).GET /v1/resolve/{org}/{skill}?spec=1.4.2 -> Returns download URL + Checksum.
