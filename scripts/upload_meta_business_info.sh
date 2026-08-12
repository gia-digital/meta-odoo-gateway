#!/usr/bin/env bash
# PUT Meta Business Agent business_info from agent_info/business_info.json
#
# Usage:
#   export META_GRAPH_TOKEN='...'
#   ./scripts/upload_meta_business_info.sh
#   ./scripts/upload_meta_business_info.sh --dry-run
#   ./scripts/upload_meta_business_info.sh --get
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${BUSINESS_INFO_FILE:-$ROOT/agent_info/business_info.json}"
ENTITY_ID="${META_ENTITY_ID:-1247354378459524}"
API_VERSION="${META_API_VERSION:-2.0.0}"
URL="https://api.facebook.com/${ENTITY_ID}/agent_config/business_info"
DRY_RUN=0
GET_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --get) GET_ONLY=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${META_GRAPH_TOKEN:-}" ]]; then
  echo "Set META_GRAPH_TOKEN" >&2
  exit 1
fi

HDR=(-H "Authorization: Bearer ${META_GRAPH_TOKEN}" -H "X-API-Version: ${API_VERSION}")

if [[ "$GET_ONLY" -eq 1 ]]; then
  echo "GET ${URL}"
  curl -sS "${HDR[@]}" "${URL}" | python3 -m json.tool
  exit 0
fi

if [[ ! -f "$FILE" ]]; then
  echo "Missing $FILE" >&2
  exit 1
fi

PAYLOAD="$(python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1],encoding='utf-8'))['payload'],ensure_ascii=False))" "$FILE")"

echo "PUT ${URL}"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "$PAYLOAD" | python3 -m json.tool
  exit 0
fi

curl -sS -w "\nHTTP %{http_code}\n" \
  -X PUT "${URL}" \
  "${HDR[@]}" \
  -H "Content-Type: application/json" \
  --data "$PAYLOAD"
