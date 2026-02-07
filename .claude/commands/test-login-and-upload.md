End-to-end test of the CLI on the **dev** environment. Run each step sequentially — stop and report if any step fails.

All CLI commands use: `DHUB_ENV=dev uv run --package dhub-cli dhub <command>`

## Test Skill

Create this skill in the scratchpad directory before publishing:

**Directory**: `<scratchpad>/e2e-test-skill/`

**`SKILL.md`**:
```
---
name: e2e-test-skill
description: A simple test skill for end-to-end testing
---

# E2E Test Skill

This skill prints "Hello from e2e-test-skill!" and exits.
```

**`src/main.py`**:
```python
print("Hello from e2e-test-skill!")
```

## Steps

### 1. Logout
```bash
DHUB_ENV=dev uv run --package dhub-cli dhub logout
```
Expected: `Logged out.`

### 2. Login
```bash
DHUB_ENV=dev uv run --package dhub-cli dhub login
```
This triggers the GitHub device flow. Print the code and URL, then **wait for the user to complete authentication** (timeout 5 min). Expected: `Authenticated as @<username>`

### 3. Publish test skill
```bash
DHUB_ENV=dev uv run --package dhub-cli dhub publish pymc-labs/e2e-test-skill <scratchpad>/e2e-test-skill
```
Expected: `Published: pymc-labs/e2e-test-skill@0.1.0 (Grade A)`

### 4. List skills
```bash
DHUB_ENV=dev uv run --package dhub-cli dhub list
```
Expected: Table includes `pymc-labs/e2e-test-skill` at version `0.1.0`

### 5. Search for the skill
```bash
DHUB_ENV=dev uv run --package dhub-cli dhub ask "I am looking for a simple test skill"
```
Expected: Output mentions `pymc-labs/e2e-test-skill` or its description. If the skill is not found in the results, **stop and report failure**.

### 6. Install for codex
```bash
DHUB_ENV=dev uv run --package dhub-cli dhub install pymc-labs/e2e-test-skill --agent codex
```
Expected output mentions:
- Installed to `~/.dhub/skills/pymc-labs/e2e-test-skill`
- Linked to codex at `~/.codex/skills/pymc-labs--e2e-test-skill`

Verify the symlink exists: `ls -la ~/.codex/skills/pymc-labs--e2e-test-skill`

### 7. Uninstall
```bash
DHUB_ENV=dev uv run --package dhub-cli dhub uninstall pymc-labs/e2e-test-skill
```
Expected: `Uninstalled pymc-labs/e2e-test-skill` and `Removed symlinks from: codex`

Verify symlink is gone: `ls ~/.codex/skills/pymc-labs--e2e-test-skill` should fail with "No such file"

### 8. Delete from registry
```bash
echo "y" | DHUB_ENV=dev uv run --package dhub-cli dhub delete pymc-labs/e2e-test-skill
```
Pipe `y` to confirm deletion. Expected: `Deleted 1 version(s) of pymc-labs/e2e-test-skill`

Verify with `dhub list` — skill should no longer appear.
