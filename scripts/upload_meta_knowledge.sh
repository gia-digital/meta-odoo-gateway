#!/usr/bin/env bash
# Upload a PDF to Meta Business Agent knowledge base.
# Usage:
#   export META_GRAPH_TOKEN='EAAB...'   # same token as Postman {{bearer_token_1db5}}
#   ./scripts/upload_meta_knowledge.sh "agent_info/Carta Presentación GIA.pdf"
#   ./scripts/upload_meta_knowledge.sh "agent_info/Presentación GIA.pdf" "Presentacion GIA.pdf"
set -euo pipefail

ENTITY_ID="${META_ENTITY_ID:-1247354378459524}"
API_VERSION="${META_API_VERSION:-2.0.0}"
FILE_PATH="${1:?Usage: $0 <pdf-path> [file_name]}"

# Resolve path when accents differ (NFC vs NFD), e.g. Presentación vs Presentación
if [[ ! -f "$FILE_PATH" ]]; then
  RESOLVED="$(python3 - "$FILE_PATH" <<'PY'
import sys, unicodedata
from pathlib import Path
wanted = Path(sys.argv[1])
parent = wanted.parent if str(wanted.parent) != "." else Path(".")
target_nfc = unicodedata.normalize("NFC", wanted.name)
target_nfd = unicodedata.normalize("NFD", wanted.name)
if not parent.is_dir():
    sys.exit(0)
for p in parent.iterdir():
    name_nfc = unicodedata.normalize("NFC", p.name)
    name_nfd = unicodedata.normalize("NFD", p.name)
    if name_nfc == target_nfc or name_nfd == target_nfd or p.name == wanted.name:
        print(p)
        break
PY
)"
  if [[ -n "${RESOLVED}" && -f "${RESOLVED}" ]]; then
    echo "Resolved unicode path: ${RESOLVED}"
    FILE_PATH="${RESOLVED}"
  fi
fi

FILE_NAME="${2:-$(basename "$FILE_PATH")}"
# Prefer ASCII-ish display name without combining marks for Meta file_name
FILE_NAME="$(python3 -c "import sys,unicodedata; print(unicodedata.normalize('NFC', sys.argv[1]))" "$FILE_NAME")"

if [[ -z "${META_GRAPH_TOKEN:-}" ]]; then
  echo "Set META_GRAPH_TOKEN to your Meta Graph/Bearer token (Postman bearer_token_1db5)." >&2
  exit 1
fi
if [[ ! -f "$FILE_PATH" ]]; then
  echo "File not found: $FILE_PATH" >&2
  echo "Hint: ls agent_info/ | cat -v   # accents may be NFD-encoded on disk" >&2
  exit 1
fi

URL="https://api.facebook.com/${ENTITY_ID}/agent_config/files/"

echo "POST $URL"
echo "file_name=$FILE_NAME"
echo "file=$FILE_PATH (Content-Type forced: application/pdf)"

# Critical: ;type=application/pdf — without it Meta returns
# {"title":"JSON Schema Validation Error","detail":"Unsupported content type: ","status":400}
curl -sS -w "\nHTTP %{http_code}\n" \
  --request POST \
  --url "$URL" \
  --header "Authorization: Bearer ${META_GRAPH_TOKEN}" \
  --header "X-API-Version: ${API_VERSION}" \
  -F "file_name=${FILE_NAME}" \
  -F "file=@${FILE_PATH};type=application/pdf;filename=${FILE_NAME}"
