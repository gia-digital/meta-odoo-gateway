#!/usr/bin/env bash
# Manage Meta Business Agent connector from agent_info/connectors.json
#
# Usage:
#   export META_GRAPH_TOKEN='...'
#   export META_LEAD_WEBHOOK_TOKEN='...'   # replaces {{META_LEAD_WEBHOOK_TOKEN}}
#   ./scripts/upload_meta_connectors.sh --list
#   ./scripts/upload_meta_connectors.sh --get
#   ./scripts/upload_meta_connectors.sh --create
#   ./scripts/upload_meta_connectors.sh --update
#   ./scripts/upload_meta_connectors.sh --upsert-key
#   ./scripts/upload_meta_connectors.sh --logs
#   ./scripts/upload_meta_connectors.sh --dry-run --create
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${CONNECTORS_FILE:-$ROOT/agent_info/connectors.json}"
ENTITY_ID="${META_ENTITY_ID:-1247354378459524}"
API_VERSION="${META_API_VERSION:-2.0.0}"
BASE="https://api.facebook.com/${ENTITY_ID}/agent_connectors"
DRY_RUN=0
ACTION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --list|--get|--create|--update|--upsert-key|--logs)
      ACTION="${1#--}"; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${ACTION}" ]]; then
  echo "Pass one of: --list --get --create --update --upsert-key --logs" >&2
  exit 1
fi

if [[ -z "${META_GRAPH_TOKEN:-}" ]]; then
  echo "Set META_GRAPH_TOKEN" >&2
  exit 1
fi

if [[ ! -f "$FILE" ]]; then
  echo "Missing $FILE" >&2
  exit 1
fi

python3 - "$FILE" "$ACTION" "$DRY_RUN" "$BASE" "$API_VERSION" <<'PY'
import json, os, sys, urllib.request, urllib.error

path, action, dry_s, base, api_version = sys.argv[1:6]
dry = dry_s == "1"
token = os.environ["META_GRAPH_TOKEN"]
lead_token = os.environ.get("META_LEAD_WEBHOOK_TOKEN", "")
data = json.load(open(path, encoding="utf-8"))
connector_id = os.environ.get("META_CONNECTOR_ID") or data.get("live", {}).get("connector_id") or ""

def fill_secrets(obj):
    raw = json.dumps(obj, ensure_ascii=False)
    if "{{META_LEAD_WEBHOOK_TOKEN}}" in raw:
        if not lead_token and action in ("create", "update", "upsert-key") and not dry:
            print("Set META_LEAD_WEBHOOK_TOKEN for create/update/upsert-key", file=sys.stderr)
            sys.exit(1)
        raw = raw.replace("{{META_LEAD_WEBHOOK_TOKEN}}", lead_token or "<SET_META_LEAD_WEBHOOK_TOKEN>")
    return json.loads(raw)

def call(method, url, body=None):
    print(f"{method} {url}")
    payload = None if body is None else json.dumps(body, ensure_ascii=False)
    if dry:
        if payload:
            print(payload)
        return
    req = urllib.request.Request(
        url,
        data=None if payload is None else payload.encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Version": api_version,
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode()
            print(resp.status)
            if text:
                print(json.dumps(json.loads(text), ensure_ascii=False, indent=2)[:4000])
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode()[:1500], file=sys.stderr)
        sys.exit(1)

if action == "list":
    call("GET", f"{base}/")
elif action == "get":
    if not connector_id:
        print("Missing live.connector_id / META_CONNECTOR_ID", file=sys.stderr)
        sys.exit(1)
    call("GET", f"{base}/{connector_id}")
elif action == "create":
    call("POST", f"{base}/", fill_secrets(data["connector"]))
elif action == "update":
    if not connector_id:
        print("Missing live.connector_id / META_CONNECTOR_ID", file=sys.stderr)
        sys.exit(1)
    call("PUT", f"{base}/{connector_id}", fill_secrets(data["connector"]))
elif action == "upsert-key":
    if not connector_id:
        print("Missing live.connector_id / META_CONNECTOR_ID", file=sys.stderr)
        sys.exit(1)
    call("POST", f"{base}/{connector_id}/upsertApiKey", fill_secrets(data["upsert_api_key"]))
elif action == "logs":
    if not connector_id:
        print("Missing live.connector_id / META_CONNECTOR_ID", file=sys.stderr)
        sys.exit(1)
    call("GET", f"{base}/{connector_id}/logs?include_stats=true&summary_only=true")
else:
    print(f"Unknown action {action}", file=sys.stderr)
    sys.exit(1)
PY
