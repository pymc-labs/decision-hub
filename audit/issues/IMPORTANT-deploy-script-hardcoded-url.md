# Hardcoded Deployment URLs in Scripts

## Description
The `scripts/deploy.sh` script outputs hardcoded URLs after deployment:

```bash
echo "    URL: https://pymc-labs--api.modal.run"
```

## Impact
This is a minor issue, but it can be confusing for a user deploying to their own Modal account if the script tells them their URL is `pymc-labs--...` when it's actually `their-username--...`.

## Recommendation
- Dynamically determine the Modal workspace name if possible, or print a generic message like "Deployed to Modal. Check your Modal dashboard for the URL."
- Or, use the `modal` CLI to fetch the URL.
