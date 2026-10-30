#!/bin/bash
# Development -> live on this box. Run from anywhere:
#   sudo bash deploy/deploy.sh             put this folder's backend live
#   sudo bash deploy/deploy.sh --rollback  put back the code saved by the last deploy
#
# Copies agent/plc_agent, agent/run_agent.py and agent/rust_jobs of this folder to the live
# install (/opt/neuract/loggerfast/agent) and restarts the backend. The engine keeps logging.
#   1. lists the files that will change; stops if none;
#   2. checks every Python file of agent/plc_agent parses;
#   3. saves the live code (/opt/neuract/loggerfast/agent.bak-deploy-<time>) and the metadata
#      DB (/home/neuract/loggerfast-backups/<time>-deploy/meta.dump);
#   4. installs, restarts the backend, waits for /health. If it doesn't come up healthy, the
#      saved code is put back and the backend restarted.
# --rollback leaves the databases alone. Every run is logged to
# /home/neuract/loggerfast-backups/deploy.log.
# The engine binary is not built here (no Rust toolchain): a change under agent/rust_jobs is
# copied but does nothing until a new neuract-job-runner is installed.
set -euo pipefail
SRC=$(cd "$(dirname "$0")/../agent" && pwd)
L=/opt/neuract/loggerfast
A=$L/agent
B=/home/neuract/loggerfast-backups
PY=$L/venv/bin/python
KEEP=(--exclude logs --exclude pki --exclude '*.log' --exclude __pycache__)
[ "$(id -u)" = 0 ] || { echo "STOP: run with sudo"; exit 1; }
TS=$(date +%Y%m%d-%H%M%S)
log() { echo "$TS $*" >> "$B/deploy.log"; }

healthy() {
  for _ in $(seq 1 60); do
    curl -s -m 2 http://127.0.0.1:8003/health | grep -q '"ok"' && return 0
    sleep 2
  done
  return 1
}

restore() {  # restore <backup dir>
  systemctl stop loggerfast-backend
  rm -rf "$A" && cp -a "$1" "$A"
  systemctl start loggerfast-backend
  healthy && echo "backend healthy on the restored code" || echo "BACKEND STILL NOT HEALTHY: journalctl -u loggerfast-backend"
}

if [ "${1:-}" = "--rollback" ]; then
  BAK=$(ls -d "$L"/agent.bak-deploy-* 2>/dev/null | sort | tail -1)
  [ -n "$BAK" ] || { echo "STOP: no deploy backup in $L"; exit 1; }
  echo "== putting back $BAK"
  restore "$BAK"
  log "rollback to $(basename "$BAK")"
  exit 0
fi

echo "== changes going live (this folder -> $A)"
CHANGES=$( { diff -rq "${KEEP[@]/#--exclude/-x}" "$SRC/plc_agent" "$A/plc_agent" || true
             diff -q "$SRC/run_agent.py" "$A/run_agent.py" || true
             diff -rq -x target "${KEEP[@]/#--exclude/-x}" "$SRC/rust_jobs" "$A/rust_jobs" || true; } \
           | sed -e "s#^Files $SRC/\(.*\) and .* differ\$#changed  \1#" \
                 -e "s#^Only in $SRC/\(.*\): \(.*\)\$#new      \1/\2#" \
                 -e "s#^Only in $A/\(.*\): \(.*\)\$#removed  \1/\2#" )
[ -n "$CHANGES" ] || { echo "nothing to deploy: live already matches this folder"; exit 0; }
sed 's/^/  /' <<<"$CHANGES"
grep -q 'rust_jobs' <<<"$CHANGES" && echo "  NOTE: rust_jobs changed; the engine binary is not rebuilt by this script"

echo "== checking the Python code parses"
"$PY" -c '
import ast, os, sys
bad = []
for d, _, files in os.walk(sys.argv[1]):
    for f in files:
        if f.endswith(".py"):
            p = os.path.join(d, f)
            try:
                ast.parse(open(p, encoding="utf-8").read(), p)
            except SyntaxError as e:
                bad.append(f"{p}:{e.lineno}: {e.msg}")
print("\n".join(bad) or "  ok")
sys.exit(1 if bad else 0)' "$SRC/plc_agent" || { echo "STOP: fix the syntax errors above; nothing changed"; exit 1; }

echo "== backup"
BAK=$L/agent.bak-deploy-$TS
[ ! -e "$BAK" ] || { echo "STOP: $BAK exists (two deploys in one second); run again"; exit 1; }
cp -a "$A" "$BAK"
mkdir -p "$B/$TS-deploy"
set -a; . /etc/neuract/loggerfast.env; set +a
META=$(sed -E 's#^postgres(ql)?\+[a-z0-9]+://#postgresql://#' <<<"$APP_DB_URL")
runuser -u loggerfast -- pg_dump -Fc -d "$META" > "$B/$TS-deploy/meta.dump"
[ -s "$B/$TS-deploy/meta.dump" ] || { echo "STOP: metadata DB dump is empty; nothing changed"; exit 1; }
chown -R neuract:neuract "$B"
echo "  code: $BAK"
echo "  metadata DB: $B/$TS-deploy/meta.dump"

echo "== installing and restarting the backend"
rsync -a --chown=root:root --delete "${KEEP[@]}" "$SRC/plc_agent/" "$A/plc_agent/"
install -o root -g root -m 644 "$SRC/run_agent.py" "$A/run_agent.py"
rsync -a --chown=root:root --delete --exclude 'target/' "${KEEP[@]}" "$SRC/rust_jobs/" "$A/rust_jobs/"
START=$(date '+%Y-%m-%d %H:%M:%S')
systemctl restart loggerfast-backend
if healthy; then
  journalctl -u loggerfast-backend --since "$START" --no-pager | grep -iE 'error|traceback|warning' | tail -15 || true
  log "deployed: $(tr -s ' \n' ' ;' <<<"$CHANGES")"
  echo "LIVE. Backend healthy on :8003. Undo with: sudo bash $(dirname "$SRC")/deploy/deploy.sh --rollback"
else
  journalctl -u loggerfast-backend --since "$START" --no-pager | tail -30
  echo "BACKEND NOT HEALTHY: putting the previous code back"
  restore "$BAK"
  log "FAILED, restored $(basename "$BAK"): $(tr -s ' \n' ' ;' <<<"$CHANGES")"
  exit 1
fi
