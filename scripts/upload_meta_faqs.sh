#!/usr/bin/env bash
# Create (POST) Meta Business Agent FAQs from agent_info/faqs.json
#
# Usage:
#   export META_GRAPH_TOKEN='EAAB...'   # same as Postman {{bearer_token_1db5}}
#   ./scripts/upload_meta_faqs.sh
#   ./scripts/upload_meta_faqs.sh --dry-run
#   ./scripts/upload_meta_faqs.sh --limit 5
#   ./scripts/upload_meta_faqs.sh --list
#   ./scripts/upload_meta_faqs.sh --category producto
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAQS_FILE="${FAQS_FILE:-$ROOT/agent_info/faqs.json}"
ENTITY_ID="${META_ENTITY_ID:-1247354378459524}"
API_VERSION="${META_API_VERSION:-2.0.0}"
BASE="https://api.facebook.com/${ENTITY_ID}/agent_config/faq"
DRY_RUN=0
LIMIT=0
LIST_ONLY=0
CATEGORY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --list) LIST_ONLY=1; shift ;;
    --limit) LIMIT="${2:?}"; shift 2 ;;
    --category) CATEGORY="${2:?}"; shift 2 ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "${META_GRAPH_TOKEN:-}" ]]; then
  echo "Set META_GRAPH_TOKEN (Postman bearer_token_1db5)." >&2
  exit 1
fi

auth_hdr=(-H "Authorization: Bearer ${META_GRAPH_TOKEN}" -H "X-API-Version: ${API_VERSION}")

if [[ "$LIST_ONLY" -eq 1 ]]; then
  echo "GET ${BASE}/"
  curl -sS "${auth_hdr[@]}" "${BASE}/" | python3 -m json.tool
  exit 0
fi

if [[ ! -f "$FAQS_FILE" ]]; then
  echo "Missing $FAQS_FILE" >&2
  exit 1
fi

python3 - "$FAQS_FILE" "$CATEGORY" "$LIMIT" "$DRY_RUN" "$BASE" "$API_VERSION" <<'PY'
import json, os, sys, urllib.request, urllib.error, time

faqs_file, category, limit_s, dry_s, base, api_version = sys.argv[1:7]
limit = int(limit_s)
dry = dry_s == "1"
token = os.environ["META_GRAPH_TOKEN"]

data = json.load(open(faqs_file, encoding="utf-8"))
items = data["faqs"]
if category:
    items = [f for f in items if f.get("metadata", {}).get("category") == category]
if limit > 0:
    items = items[:limit]

print(f"Uploading {len(items)} FAQ(s) to {base}/")
ok = fail = 0
for i, faq in enumerate(items, 1):
    body = {
        "question": faq["question"],
        "answer": faq["answer"],
    }
    meta = faq.get("metadata") or {}
    # Meta metadata is string->string map
    if meta:
        body["metadata"] = {k: str(v) for k, v in meta.items()}

    print(f"\n[{i}/{len(items)}] {faq['question'][:80]}")
    if dry:
        print(json.dumps(body, ensure_ascii=False)[:300], "...")
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
            print(f"HTTP {resp.status} {raw[:200]}")
            ok += 1
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        print(f"HTTP {e.code} {raw[:400]}")
        fail += 1
        if e.code == 429:
            print("Rate limited; sleeping 5s...")
            time.sleep(5)
    time.sleep(0.35)

print(f"\nDone. ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
PY
