#!/usr/bin/env bash
set -euo pipefail

BASE="${LISA_BASE_URL:-http://localhost:8000}"
TIMEOUT="${SMOKE_TIMEOUT:-300}"

echo "[smoke] target $BASE"
curl -sf "$BASE/api/health" >/dev/null || {
  echo "[smoke] backend unreachable at $BASE, run: docker compose up -d"
  exit 1
}

echo "[smoke] 1/5 create agent"
AGENT_ID=$(curl -sf -X POST "$BASE/api/agents/generate" \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke","role":"developer","os_type":"linux","applications":["code"]}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["agent_id"])')
echo "[smoke]   agent_id=$AGENT_ID"

echo "[smoke] 2/5 wait for status ready (timeout ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
while true; do
  STATUS=$(curl -sf "$BASE/api/agents/$AGENT_ID/status" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["agent"]["status"])')
  echo "[smoke]   status=$STATUS"
  [ "$STATUS" = "ready" ] && break
  [ "$STATUS" = "failed" ] && { echo "[smoke] FAIL build failed"; exit 1; }
  [ "$(date +%s)" -ge "$deadline" ] && { echo "[smoke] FAIL timeout before ready"; exit 1; }
  sleep 3
done

echo "[smoke] 3/5 status exposes build urls"
read -r BURL IURL < <(curl -sf "$BASE/api/agents/$AGENT_ID/status" \
  | python3 -c 'import sys,json;a=json.load(sys.stdin)["agent"];print(a.get("binary_url") or "", a.get("installer_url") or "")')
echo "[smoke]   binary_url=$BURL"
echo "[smoke]   installer_url=$IURL"
[ -n "$BURL" ] || { echo "[smoke] FAIL binary_url missing"; exit 1; }
[ -n "$IURL" ] || { echo "[smoke] FAIL installer_url missing"; exit 1; }

echo "[smoke] 4/5 download installer"
case "$IURL" in
  http*) DL="$IURL" ;;
  *)     DL="$BASE$IURL" ;;
esac
OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT
curl -sf "$DL" -o "$OUT"
SIZE=$(wc -c < "$OUT")
echo "[smoke]   downloaded $SIZE bytes"

echo "[smoke] 5/5 verify installer shape"
[ "$SIZE" -gt 1000 ] || { echo "[smoke] FAIL installer too small ($SIZE b)"; exit 1; }
head -c 2 "$OUT" | grep -q '#!' || { echo "[smoke] FAIL not a shell installer"; exit 1; }
grep -qa "__LISA_AGENT_PAYLOAD_BELOW__" "$OUT" || { echo "[smoke] FAIL payload marker missing"; exit 1; }

echo "[smoke] PASS generate -> build -> ready -> installer served and well-formed"
