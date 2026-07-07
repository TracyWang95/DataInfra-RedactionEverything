#!/bin/bash
# Server-side upgrade with health gate + automatic rollback.
# Usage: bash upgrade.sh /path/to/redaction-release-*.tar.gz
# Assumes the standard bare-metal layout: ~/redaction-deploy + ~/backend_g0.sh.
# Only the backend process (:8000) restarts; GPU model services are untouched.
set -u

BUNDLE="${1:?usage: upgrade.sh <release.tar.gz>}"
BASE="$HOME/redaction-deploy"
STAMP="$(date +%Y%m%d%H%M%S)"
BAK="$HOME/upgrade-backups/$STAMP"
HEALTH_URL="http://127.0.0.1:8000/api/v1/auth/status"

echo "== 1/5 backup current code -> $BAK"
mkdir -p "$BAK"
cp -r "$BASE/backend/app" "$BAK/app"
cp -r "$BASE/backend/config" "$BAK/config"
cp -r "$BASE/frontend/dist" "$BAK/dist"

echo "== 2/5 unpack release"
WORK="$(mktemp -d)"
tar -xzf "$BUNDLE" -C "$WORK"
[ -f "$WORK/RELEASE.json" ] && cat "$WORK/RELEASE.json"

echo "== 3/5 apply"
cp -rf "$WORK/backend/app/." "$BASE/backend/app/"
cp -rf "$WORK/backend/config/." "$BASE/backend/config/"
cp -rf "$WORK/backend/scripts/." "$BASE/backend/scripts/"
rm -rf "$BASE/frontend/dist"
cp -r "$WORK/frontend/dist" "$BASE/frontend/dist"

echo "== 4/5 restart backend (:8000)"
fuser -k 8000/tcp 2>/dev/null || true
sleep 1
setsid nohup bash "$HOME/backend_g0.sh" > "$HOME/backend.log" 2>&1 < /dev/null &

echo "== 5/5 health gate (max 90s)"
ok=0
for i in $(seq 1 45); do
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || echo 000)
  [ "$code" = "200" ] && { ok=1; break; }
done

if [ "$ok" = "1" ]; then
  rm -rf "$WORK"
  echo "UPGRADE_OK backup=$BAK"
  # keep the 5 most recent backups
  ls -dt "$HOME"/upgrade-backups/* 2>/dev/null | tail -n +6 | xargs -r rm -rf
  exit 0
fi

echo "!! health gate FAILED - rolling back from $BAK"
cp -rf "$BAK/app/." "$BASE/backend/app/"
cp -rf "$BAK/config/." "$BASE/backend/config/"
rm -rf "$BASE/frontend/dist"
cp -r "$BAK/dist" "$BASE/frontend/dist"
fuser -k 8000/tcp 2>/dev/null || true
sleep 1
setsid nohup bash "$HOME/backend_g0.sh" > "$HOME/backend.log" 2>&1 < /dev/null &
for i in $(seq 1 45); do
  sleep 2
  code=$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || echo 000)
  [ "$code" = "200" ] && { echo "ROLLBACK_OK"; rm -rf "$WORK"; exit 1; }
done
echo "ROLLBACK_HEALTH_UNCONFIRMED - inspect ~/backend.log"
exit 2
