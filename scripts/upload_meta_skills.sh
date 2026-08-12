#!/usr/bin/env bash
# POST Meta Business Agent skills from agent_info/skills.json
#
# Usage:
#   export META_GRAPH_TOKEN='...'
#   ./scripts/upload_meta_skills.sh
#   ./scripts/upload_meta_skills.sh --dry-run
#   ./scripts/upload_meta_skills.sh --list
#   ./scripts/upload_meta_skills.sh --limit 2
#   ./scripts/upload_meta_skills.sh --title create-qualified-lead
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${SKILLS_FILE:-$ROOT/agent_info/skills.json}"
ENTITY_ID="${META_ENTITY_ID:-1247354378459524}"
API_VERSION="${META_API_VERSION:-2.0.0}"
BASE="https://api.facebook.com/${ENTITY_ID}/agent_config/skills"
DRY_RUN=0
LIST_ONLY=0
LIMIT=0
TITLE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    --limit) LIMIT="${2:?}"; shift 2 ;;
    --title) TITLE="${2:?}"; shift 2 ;;
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

python3 - "$FILE" "$TITLE" "$LIMIT" "$DRY_RUN" "$BASE" "$API_VERSION" <<'PY'
import json, os, sys, urllib.request, urllib.error, time

path, title, limit_s, dry_s, base, api_version = sys.argv[1:7]
limit = int(limit_s)
dry = dry_s == "1"
token = os.environ["META_GRAPH_TOKEN"]
data = json.load(open(path, encoding="utf-8"))
items = data["skills"]
if title:
    items = [s for s in items if s["title"] == title]
if limit > 0:
    items = items[:limit]

print(f"Uploading {len(items)} skill(s) to {base}/")
print("create_lead tool ref:", json.dumps(data.get("create_lead_tool"), ensure_ascii=False))
ok = fail = 0
for i, skill in enumerate(items, 1):
    body = {
        "title": skill["title"],
        "description": skill["description"],
        "skill": skill["skill"],
    }
    print(f"\n[{i}/{len(items)}] {skill['title']}")
    if dry:
        print(json.dumps({**body, "skill": body["skill"][:120] + "..."}, ensure_ascii=False))
        ok += 1
        continue
    req = urllib.request.Request(
        base if base.endswith("/") else base + "/",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-API-Version": api_version,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            print(f"HTTP {resp.status} {raw[:240]}")
            ok += 1
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        print(f"HTTP {e.code} {raw[:500]}")
        fail += 1
        if e.code == 429:
            time.sleep(5)
    time.sleep(0.35)
print(f"\nDone. ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
PY
