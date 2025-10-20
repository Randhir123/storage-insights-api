#!/usr/bin/env python3
"""CLI helper for IBM Storage Insights APIs."""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib import error, parse, request

API_BASE = "https://dev.insights.ibm.com"
TOKEN_PATH = "/restapi/v1/tenants/{tenant_uuid}/token"
STORAGE_SYSTEMS_PATH = "/restapi/v1/tenants/{tenant_uuid}/storage-systems"


def read_creds(path: Path) -> Tuple[str, str]:
    """Return (api_key, tenant_uuid) parsed from a simple key:value file."""
    if not path.exists():
        raise FileNotFoundError(f"Credential file not found: {path}")

    api_key = None
    tenant_id = None
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "apikey":
            api_key = value
        elif key == "tenantid":
            tenant_id = value

    if not api_key or not tenant_id:
        raise ValueError("Both 'apikey' and 'tenantid' must be present in creds file")

    return api_key, tenant_id


def request_json(url: str, *, method: str = "GET", headers: Dict[str, str] | None = None,
                 data: bytes | str | None = None, timeout: int = 30) -> Dict:
    """Perform an HTTP request and parse the JSON response."""
    body: bytes | None
    if data is not None and isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = data

    req = request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    if headers:
        for key, value in headers.items():
            req.add_header(key, value)

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            payload = resp.read().decode(charset)
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON response from {url}: {exc}") from exc


def obtain_token(api_key: str, tenant_uuid: str) -> Tuple[str, int]:
    """Request an API token and return (token, expiration_ms)."""
    url = f"{API_BASE}{TOKEN_PATH.format(tenant_uuid=tenant_uuid)}"
    response = request_json(
        url,
        method="POST",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
        },
        data="{}",
    )

    try:
        result = response["result"]
        token = result["token"]
        expiration = int(result["expiration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Unexpected token response structure: {response}") from exc

    return token, expiration


def fetch_storage_systems(tenant_uuid: str, token: str, storage_type: str | None = None) -> Dict:
    """Fetch storage systems payload for the tenant."""
    params = {}
    if storage_type:
        params["storage-type"] = storage_type
    query = f"?{parse.urlencode(params)}" if params else ""
    url = f"{API_BASE}{STORAGE_SYSTEMS_PATH.format(tenant_uuid=tenant_uuid)}{query}"
    return request_json(url, headers={"x-api-token": token})


def _format_ts(ms: int | None) -> str:
    if not ms:
        return "—"
    try:
        dt = _dt.datetime.fromtimestamp(ms / 1000, tz=_dt.timezone.utc)
    except Exception:
        return str(ms)
    return dt.isoformat()


def build_table(items: Iterable[Dict], *, limit: int | None = None) -> str:
    """Return a table with name, last probe/monitor, and condition."""
    rows: List[Tuple[str, str, str, str]] = []
    for idx, item in enumerate(items):
        if limit is not None and idx >= limit:
            break
        rows.append(
            (
                str(item.get("name", "")),
                _format_ts(item.get("last_successful_probe")),
                _format_ts(item.get("last_successful_monitor")),
                str(item.get("condition", "")),
            )
        )

    headers: Sequence[str] = (
        "Name",
        "Last Successful Probe (UTC)",
        "Last Successful Monitor (UTC)",
        "Condition",
    )

    widths = [len(header) for header in headers]
    for row in rows:
        for idx, column in enumerate(row):
            widths[idx] = max(widths[idx], len(column))

    fmt = " | ".join(f"{{:{width}}}" for width in widths)
    divider = "-+-".join("-" * width for width in widths)

    lines = [fmt.format(*headers), divider]
    lines.extend(fmt.format(*row) for row in rows)
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interact with IBM Storage Insights APIs")
    parser.add_argument(
        "--creds",
        default="creds",
        type=Path,
        help="Path to credentials file containing apikey and tenantid (default: creds)",
    )
    parser.add_argument(
        "--storage-type",
        default="block",
        help="Storage type filter (block, filer, object). Use blank for all.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path to write the raw storage systems JSON payload.",
    )
    parser.add_argument(
        "--table",
        action="store_true",
        help="Print the storage systems summary table to stdout.",
    )
    parser.add_argument(
        "--table-out",
        type=Path,
        help="Optional path to write the summary table.",
    )
    parser.add_argument(
        "--token-out",
        type=Path,
        help="Optional path to write the latest API token (base64 string).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of rows displayed in the table.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress non-essential console output.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    api_key, tenant_uuid = read_creds(args.creds)

    if not args.quiet:
        print(f"Using tenant: {tenant_uuid}")

    token, expiration_ms = obtain_token(api_key, tenant_uuid)

    if args.token_out:
        args.token_out.write_text(token + "\n")
        if not args.quiet:
            print(f"Wrote token to {args.token_out}")

    if not args.quiet:
        print("Token expiration (UTC):", _format_ts(expiration_ms))

    storage_type = args.storage_type or None
    payload = fetch_storage_systems(tenant_uuid, token, storage_type=storage_type)
    systems = payload.get("data", [])

    if not args.quiet:
        summary_type = payload.get("storageType") or storage_type or "all"
        print(f"Retrieved {len(systems)} storage systems (storageType={summary_type})")

    if args.json_out:
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n")
        if not args.quiet:
            print(f"Wrote JSON payload to {args.json_out}")

    if args.table or args.table_out:
        table_text = build_table(systems, limit=args.limit)
        if args.table:
            print(table_text)
        if args.table_out:
            args.table_out.write_text(table_text + "\n")
            if not args.quiet:
                print(f"Wrote table to {args.table_out}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
