#!/bin/bash
# Step 5. Run:  sudo bash 5-load-equipment.sh            dry run: checks everything, saves nothing
#               sudo bash 5-load-equipment.sh --commit   saves (backs up the metadata DB first)
# Builds the electrical map from the EMS inventory (ems_mfm.md, 2026-10-30): its 9 panels with
# their incoming / outgoing / spare MFMs on Bus A, and the 17 standalone production MFMs.
# Each panel MFM measures an element named after the MFM, as in the EMS; no panel-to-panel feed
# is invented. The workbook goes through the normal spreadsheet import (all or nothing). The
# backend and the engine keep running.
# The workbook is generated (the metadata dump is the v1 one from step 4):
#   python parse_ems_mfm.py ../../ems_mfm.md <meta dump .sql.gz> ems_mfm.json
#   python gen_equipment_xlsx.py ems_mfm.json ems_equipment_naidupet.xlsx
set -euo pipefail
D=$(cd "$(dirname "$0")" && pwd)
BOOK=$D/ems_equipment_naidupet.xlsx
A=/opt/neuract/loggerfast/agent
[ "$(id -u)" = 0 ] || { echo "STOP: run with sudo"; exit 1; }
[ -s "$BOOK" ] || { echo "STOP: workbook not found: $BOOK"; exit 1; }
[ -f "$A/plc_agent/api/equipment_import.py" ] || { echo "STOP: the release is not installed yet"; exit 1; }
COMMIT=
[ "${1:-}" = "--commit" ] && COMMIT=--commit
W=$(mktemp -d /tmp/eqload.XXXXXX); chmod 755 "$W"
trap 'rm -rf "$W"' EXIT
install -m 644 "$D/load_equipment.py" "$BOOK" "$W/"

if [ -n "$COMMIT" ]; then
  echo "== backup of the metadata DB"
  set -a; . /etc/neuract/loggerfast.env; set +a
  META=$(sed -E 's#^postgres(ql)?\+[a-z0-9]+://#postgresql://#' <<<"$APP_DB_URL")
  OUT=/home/neuract/loggerfast-backups/$(date +%Y%m%d-%H%M%S)-before-equipment
  mkdir -p "$OUT"
  runuser -u loggerfast -- pg_dump -Fc -d "$META" > "$OUT/meta.dump"
  [ -s "$OUT/meta.dump" ] || { echo "STOP: metadata dump is empty; nothing changed"; exit 1; }
  chown -R neuract:neuract "$OUT"
  echo "  $OUT/meta.dump"
fi

echo "== importing $(basename "$BOOK") ($([ -n "$COMMIT" ] && echo commit || echo "dry run"))"
runuser -u loggerfast -- /bin/sh -c 'set -a; . /etc/neuract/loggerfast.env; set +a; export PYTHONPATH=/opt/neuract/loggerfast/agent; cd /opt/neuract/loggerfast/agent && exec /opt/neuract/loggerfast/venv/bin/python "$1" "$2" $3' \
  sh "$W/load_equipment.py" "$W/$(basename "$BOOK")" "$COMMIT"
[ -n "$COMMIT" ] && echo "DONE. The map is in Elements / Mappings." || echo "Dry run clean. Save it with: sudo bash $D/5-load-equipment.sh --commit"
