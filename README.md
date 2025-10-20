# Storage Insights API Toolkit

This repository captures the IBM Storage Insights OpenAPI specification and documents the minimal workflow for authenticating and calling the tenant-level REST APIs. It is intended as a lightweight reference for interacting with the service from the command line.

## Repository Layout

- `openapi.yaml` &mdash; IBM Storage Insights OpenAPI v1 document (downloaded from `https://dev.insights.ibm.com/openapi`).
- `.gitignore` &mdash; prevents the local `creds` file (containing secrets) from being committed.
- `creds` *(ignored)* &mdash; user-supplied API key and tenant id.
- `latest_block_storage.json`, `latest_token.b64` *(optional)* &mdash; scratch files produced by the example commands below.

## Prerequisites

- macOS or Linux shell with `curl`.
- [`jq`](https://stedolan.github.io/jq/) 1.6+ for JSON parsing.
- Python 3.9+ (optional) for tabular formatting helpers.

## Initial Setup

1. Create a `creds` file in the repository root (already in `.gitignore`) with the following structure:

   ```text
   apikey: <your-storage-insights-api-key>
   tenantid: <your-tenant-uuid>
   ```

2. Keep the `creds` file local. Do **not** add it to commits.

## Refreshing the OpenAPI Spec

If you need the latest API description, overwrite `openapi.yaml` with:

```bash
curl -sSL https://dev.insights.ibm.com/openapi -o openapi.yaml
```

Review the diff and commit only when changes are expected.

## Authenticating

1. Load your credentials from `creds`:

   ```bash
   APIKEY=$(grep '^apikey:' creds | cut -d: -f2- | xargs)
   TENANT=$(grep '^tenantid:' creds | cut -d: -f2- | xargs)
   ```

2. Request a short-lived API token using the API key header:

   ```bash
   TOKEN_RESPONSE=$(curl -sS \
     -X POST "https://dev.insights.ibm.com/restapi/v1/tenants/$TENANT/token" \
     -H "x-api-key: $APIKEY" \
     -H "Content-Type: application/json" \
     -d '{}')

   TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.result.token')
   EXPIRATION=$(echo "$TOKEN_RESPONSE" | jq -r '.result.expiration')
   date -u -r $((EXPIRATION/1000)) # optional: show expiry in UTC
   ```

   The token must be supplied on subsequent requests via the `x-api-token` header. Regenerate it after it expires.

## Listing Block Storage Systems

```bash
curl -sS "https://dev.insights.ibm.com/restapi/v1/tenants/$TENANT/storage-systems?storage-type=block" \
  -H "x-api-token: $TOKEN" \
  | jq '{tenantId, storageType, count: (.data | length)}'
```

To retain the full payload for later processing:

```bash
curl -sS "https://dev.insights.ibm.com/restapi/v1/tenants/$TENANT/storage-systems?storage-type=block" \
  -H "x-api-token: $TOKEN" > latest_block_storage.json
```

## Generating a Status Table (Optional)

Transform the JSON payload into a readable table that highlights each system, the last successful probe and monitor timestamps, and the current condition:

```bash
python - <<'PY'
import json, datetime
from pathlib import Path

def fmt(ts):
    if not ts:
        return '—'
    return datetime.datetime.fromtimestamp(ts/1000, datetime.timezone.utc).isoformat()

data = json.loads(Path('latest_block_storage.json').read_text())
rows = [(item.get('name',''), fmt(item.get('last_successful_probe')), fmt(item.get('last_successful_monitor')), item.get('condition','unknown')) for item in data.get('data', [])]
headers = ('Name', 'Last Successful Probe (UTC)', 'Last Successful Monitor (UTC)', 'Condition')
widths = [len(h) for h in headers]
for row in rows:
    for i, value in enumerate(row):
        widths[i] = max(widths[i], len(value))
fmt_row = ' | '.join(f'{{:{w}}}' for w in widths)
divider = '-+-'.join('-'*w for w in widths)
with Path('block_storage_table.txt').open('w') as f:
    f.write(fmt_row.format(*headers) + '\n')
    f.write(divider + '\n')
    for row in rows:
        f.write(fmt_row.format(*row) + '\n')
print("Wrote block_storage_table.txt")
PY
```

The output file `block_storage_table.txt` contains the formatted table and can be reviewed or shared as needed.

## Python Automation

The repository ships with a lightweight CLI helper, `storage_insights.py`, that bundles the steps above.

```bash
python storage_insights.py \
  --table \
  --json-out latest_block_storage.json \
  --table-out block_storage_table.txt
```

Key options:

- `--creds PATH` &mdash; alternate credentials file (defaults to `creds`).
- `--storage-type VALUE` &mdash; filter by `block` (default), `filer`, `object`, or leave empty for all.
- `--token-out PATH` &mdash; save the freshly issued token to a file.
- `--limit N` &mdash; cap the number of rows in the table output.
- `--quiet` &mdash; suppress summary logging when scripting the command.

Every invocation requests a fresh token, writes it when requested, and fetches the latest storage system payload before producing optional summaries.

## Housekeeping

- Remove `latest_token.b64`, `latest_block_storage.json`, or other scratch files when they are no longer needed.
- Tokens are tenant-specific and time-bound; keep them out of version control and storage logs.
- Consult the IBM Storage Insights [REST API documentation](https://www.ibm.com/docs/en/storage-insights) for endpoint semantics not covered here.
