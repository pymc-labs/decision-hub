# IMPORTANT: .claude/ Directory Contains Internal Test Commands

## Summary

The `.claude/commands/` directory contains markdown files with test
instructions that reference internal infrastructure.

## Affected Files

- `.claude/commands/test-login-and-upload.md` — references `pymc-labs` (10 times)
- `.claude/commands/test-upload-evals-skill.md` — references `lfiaschi--api-dev.modal.run`
- `.claude/commands/prepare.md` — single instruction line

## Context

These are Claude Code slash commands used during development. They contain
specific org names, Modal URLs, and test procedures that are internal.

## Recommended Fix

Either:
1. Add `.claude/` to `.gitignore` (keep for internal use only)
2. Sanitize the commands to use generic references

## Deferral Rationale

These files are only used by AI coding assistants and don't affect the
project's functionality. Low priority.
