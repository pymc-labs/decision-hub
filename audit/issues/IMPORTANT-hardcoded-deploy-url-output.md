# Hardcoded Deployment URL in Output

## Description
`scripts/deploy.sh` echoes a hardcoded URL (`pymc-labs--api.modal.run`) upon success.

## Impact
**IMPORTANT**. Confusing for users deploying to their own namespaces.

## Recommendation
Dynamically fetch the URL or print a generic success message.
