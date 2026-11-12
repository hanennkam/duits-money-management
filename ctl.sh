#!/usr/bin/env bash
# Duits expense tracker — local control script
#
#   ./ctl.sh start     start the server (background, logged)
#   ./ctl.sh stop      stop it
#   ./ctl.sh restart   stop then start
#   ./ctl.sh status    show listener, PID, health and whether the process is stale
#   ./ctl.sh logs      tail the server log
#   ./ctl.sh test      hit the API end-to-end (read-only, needs the key in .env)
#   ./ctl.sh open      open the web UI in the default browser
#
# Env overrides: PORT (default 8000), HOST (default 0.0.0.0)
set -uo pipefail

# Resolve the checkout this script lives in (following symlinks), so a worktree runs its own
# app/ and .venv instead of whichever checkout happens to be hardcoded.
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  SOURCE_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  case "$SOURCE" in /*) ;; *) SOURCE="$SOURCE_DIR/$SOURCE" ;; esac
done
PROJ="$(cd -P "$(dirname "$SOURCE")" && pwd)"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
PY="$PROJ/.venv/bin/python"
LOGFILE="/tmp/duits-${PORT}.log"

cd "$PROJ" || { echo "project dir missing: $PROJ"; exit 1; }

listener_pid() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1; }

cmd_start() {
  if [ -n "$(listener_pid)" ]; then
    echo "already running on port $PORT (pid $(listener_pid)) — use: ./ctl.sh restart"
    return 0
  fi
  if [ ! -x "$PY" ]; then echo "venv missing: $PY"; return 1; fi
  nohup "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" >"$LOGFILE" 2>&1 &
  for _ in $(seq 1 30); do
    [ -n "$(listener_pid)" ] && break
    sleep 1
  done
  pid="$(listener_pid)"
  if [ -z "$pid" ]; then echo "FAILED to start — last log lines:"; tail -20 "$LOGFILE"; return 1; fi
  echo "started on http://127.0.0.1:$PORT (pid $pid)  log: $LOGFILE"
}

cmd_stop() {
  pid="$(listener_pid)"
  if [ -z "$pid" ]; then echo "not running on port $PORT"; return 0; fi
  kill "$pid" 2>/dev/null
  for _ in $(seq 1 15); do
    [ -z "$(listener_pid)" ] && break
    sleep 1
  done
  if [ -n "$(listener_pid)" ]; then kill -9 "$(listener_pid)" 2>/dev/null; sleep 1; fi
  [ -z "$(listener_pid)" ] && echo "stopped (was pid $pid)" || { echo "could not stop pid $pid"; return 1; }
}

cmd_status() {
  pid="$(listener_pid)"
  if [ -z "$pid" ]; then echo "port $PORT: NOT LISTENING"; return 1; fi
  echo "port $PORT: listening (pid $pid)"
  echo "started : $(ps -p "$pid" -o lstart= | xargs)"
  echo "health  : HTTP $(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health")"
  # uvicorn runs without --reload, so code edited after start is NOT loaded.
  started_at="$(ps -p "$pid" -o lstart= | xargs -I{} date -j -f '%a %b %d %T %Y' '{}' '+%Y-%m-%d %H:%M:%S' 2>/dev/null)"
  changed="$(find "$PROJ/app" \( -name '*.py' -o -name '*.html' \) -newermt "$started_at" 2>/dev/null | wc -l | tr -d ' ')"
  if [ "${changed:-0}" != "0" ]; then
    echo "WARNING : $changed file(s) under app/ are NEWER than the process — restart needed"
    find "$PROJ/app" \( -name '*.py' -o -name '*.html' \) -newermt "$started_at" 2>/dev/null | sed 's|^|          |'
  else
    echo "code    : up to date (no app/ files newer than the process)"
  fi
}

cmd_logs() { tail -n "${1:-40}" "$LOGFILE"; }

cmd_test() {
  "$PY" - <<'PYEOF'
import json, urllib.request, urllib.error
vals = {}
for line in open(".env"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); vals[k.strip()] = v.strip().strip('"').strip("'")
key = vals.get("API_KEY"); BASE = "http://127.0.0.1:8000"
def get(p, auth=True):
    r = urllib.request.Request(BASE + p)
    if auth: r.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(r, timeout=30) as x: return x.status, x.read().decode()
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:200]
print("health      :", urllib.request.urlopen(BASE + "/health", timeout=10).status)
print("no key      :", get("/transactions?month=2026-01&mode=personal", auth=False)[0], "(expect 401)")
import datetime
m = datetime.date.today().strftime("%Y-%m")
s, b = get(f"/transactions?month={m}&mode=personal")
print(f"{m} txns :", s, f"({len(json.loads(b))} rows)" if s == 200 else b)
s, b = get(f"/summary?month={m}&mode=personal")
print(f"{m} total:", s, b[:160])
PYEOF
}

cmd_open() { open "http://127.0.0.1:$PORT/"; }

case "${1:-}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  logs)    cmd_logs "${2:-40}" ;;
  test)    cmd_test ;;
  open)    cmd_open ;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
