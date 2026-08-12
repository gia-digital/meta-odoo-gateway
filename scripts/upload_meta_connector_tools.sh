#!/usr/bin/env bash
# Manage Meta Business Agent connector tools from agent_info/connector_tools.json
#
# Usage:
#   export META_GRAPH_TOKEN='...'
#   ./scripts/upload_meta_connector_tools.sh --list
#   ./scripts/upload_meta_connector_tools.sh --get
#   ./scripts/upload_meta_connector_tools.sh --dry-run --update
#   ./scripts/upload_meta_connector_tools.sh --update
#   ./scripts/upload_meta_connector_tools.sh --create
#   ./scripts/upload_meta_connector_tools.sh --run
#   ./scripts/upload_meta_connector_tools.sh --name create_lead --update
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${CONNECTOR_TOOLS_FILE:-$ROOT/agent_info/connector_tools.json}"
ENTITY_ID="${META_ENTITY_ID:-1247354378459524}"
API_VERSION="${META_API_VERSION:-2.0.0}"
DRY_RUN=0
ACTION=""
NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --list|--get|--create|--update|--run)
      ACTION="${1#--}"; shift ;;
    --name) NAME="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${ACTION}" ]]; then
  echo "Pass one of: --list --get --create --update --run" >&2
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

python3 - "$FILE" "$ACTION" "$DRY_RUN" "$ENTITY_ID" "$API_VERSION" "$NAME" <<'PY'
import json, os, sys, urllib.request, urllib.error

path, action, dry_s, entity_id, api_version, name_filter = sys.argv[1:7]
dry = dry_s == "1"
token = os.environ["META_GRAPH_TOKEN"]
data = json.load(open(path, encoding="utf-8"))
connector_id = (
    os.environ.get("META_CONNECTOR_ID")
    or data.get("connector_id")
    or ""
)
tool_id = os.environ.get("META_TOOL_ID") or data.get("live", {}).get("tool_id") or ""
base = f"https://api.facebook.com/{entity_id}/agent_connectors/{connector_id}/tools"

if not connector_id:
    print("Missing connector_id / META_CONNECTOR_ID", file=sys.stderr)
    sys.exit(1)

tools = data["tools"]
if name_filter:
    tools = [t for t in tools if t["name"] == name_filter]
    if not tools:
        print(f"Tool not in file: {name_filter}", file=sys.stderr)
        sys.exit(1)

def call(method, url, body=None):
    print(f"{method} {url}")
    payload = None if body is None else json.dumps(body, ensure_ascii=False)
    if dry:
        if payload:
            print(payload[:3000])
        return None
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
                try:
                    print(json.dumps(json.loads(text), ensure_ascii=False, indent=2)[:4000])
                except json.JSONDecodeError:
                    print(text[:2000])
            return text
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode()[:1500], file=sys.stderr)
        sys.exit(1)

if action == "list":
    call("GET", f"{base}/")
elif action == "get":
    if not tool_id:
        print("Missing live.tool_id / META_TOOL_ID", file=sys.stderr)
        sys.exit(1)
    call("GET", f"{base}/{tool_id}")
elif action == "create":
    for t in tools:
        body = {
            "name": t["name"],
            "description": t["description"],
            "user_auth_required": t["user_auth_required"],
            "request_definition": t["request_definition"],
        }
        call("POST", f"{base}/", body)
elif action == "update":
    if not tool_id:
        print("Missing live.tool_id / META_TOOL_ID", file=sys.stderr)
        sys.exit(1)
    for t in tools:
        body = {
            "name": t["name"],
            "description": t["description"],
            "user_auth_required": t["user_auth_required"],
            "request_definition": t["request_definition"],
        }
        call("PUT", f"{base}/{tool_id}", body)
elif action == "run":
    if not tool_id:
        print("Missing live.tool_id / META_TOOL_ID", file=sys.stderr)
        sys.exit(1)
    example = data.get("run_example") or {"input": "{}"}
    call("POST", f"{base}/{tool_id}/run", example)
else:
    print(f"Unknown action {action}", file=sys.stderr)
    sys.exit(1)
PY
