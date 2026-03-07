# IMPORTANT: Personal Modal URLs in Example Files

## Summary

Several example and documentation files contain a personal Modal deployment
URL (`lfiaschi--api-dev.modal.run`) instead of the organization URL or a
placeholder.

## Affected Files

- `frontend/.env.example:3`
  ```
  VITE_API_URL=https://lfiaschi--api-dev.modal.run
  ```
- `bootstrap-skills/dhub-cli/SKILL.md:48-49`
  ```
  https://lfiaschi--api.modal.run
  https://lfiaschi--api-dev.modal.run
  ```
- `bootstrap-skills/dhub-cli/references/command_reference.md:26`

## Recommended Fix

Replace with placeholder URLs:
```
VITE_API_URL=http://localhost:8000
```

Or use the organization URL pattern:
```
VITE_API_URL=https://your-workspace--api-dev.modal.run
```

## Deferral Rationale

Cosmetic issue in documentation/examples. Does not affect runtime behavior.
