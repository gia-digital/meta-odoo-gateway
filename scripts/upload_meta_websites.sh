#!/usr/bin/env bash
# POST Meta Business Agent knowledge websites from agent_info/websites.json
#
# Usage:
#   export META_GRAPH_TOKEN='...'
#   ./scripts/upload_meta_websites.sh --dry-run
#   ./scripts/upload_meta_websites.sh
#   ./scripts/upload_meta_websites.sh --list
#   ./scripts/upload_meta_websites.sh --url 'https://giacerero.com/'
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${WEBSITES_FILE:-$ROOT/agent_info/websites.json}"
ENTITY_ID="${META_ENTITY_ID:-1247354378459524}"
API_VERSION="${META_API_VERSION:-2.0.0}"
BASE="https://api.facebook.com/${ENTITY_ID}/agent_config/websites"
DRY_RUN=0
LIST_ONLY=0
ONLY_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    --url) ONLY_URL="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${META_GRAPH_TOKEN:-}" ]]; then
  echo "Set META_GRAPH_TOKEN" >&2
  exit 1
fi

HDR=(-H "Authorization: Bearer ${META_GRAPH_TOKEN}" -H "X-API-Version: ${API_VERSION}")

if [[ "$LIST_ONLY" -eq 1 ]]; then
  echo "GET ${BASE}/"
  curl -sS "${HDR[@]}" "${BASE}/" | python3 -m json.tool
  exit 0
fi

if [[ ! -f "$FILE" ]]; then
  echo "Missing $FILE" >&2
  exit 1
fi

python3 - "$FILE" "$ONLY_URL" "$DRY_RUN" "$BASE" "$API_VERSION" <<'PY'
import json, os, sys, urllib.request, urllib.error

path, only_url, dry_s, base, api_version = sys.argv[1:6]
dry = dry_s == "1"
token = os.environ["META_GRAPH_TOKEN"]
items = json.load(open(path, encoding="utf-8"))["websites"]
if only_url:
    items = [w for w in items if w["url"] == only_url]
    if not items:
        print(f"URL not in file: {only_url}", file=sys.stderr)
        sys.exit(1)

print(f"Uploading {len(items)} website(s) to {base}/")
ok = fail = 0
for i, w in enumerate(items, 1):
    body = {"url": w["url"]}
    print(f"\n[{i}/{len(items)}] {w['url']}")
    if dry:
        print(json.dumps(body, ensure_ascii=False))
        ok += 1
        continue
    req = urllib.request.Request(
        f"{base}/",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Version": api_version,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(resp.status, resp.read().decode()[:500])
            ok += 1
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode()[:800], file=sys.stderr)
        fail += 1

print(f"\nDone. ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
PY
