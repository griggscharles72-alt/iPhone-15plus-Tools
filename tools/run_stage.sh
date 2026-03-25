#!/usr/bin/env bash
set -u
set -o pipefail

# =============================================================================
# File: tools/run_stage.sh
# Purpose:
#   Simple stage runner for validated Dr. iPhone modules.
# =============================================================================

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin/activate"

usage() {
  cat <<'EOF'
Usage:
  ./tools/run_stage.sh doctor
  ./tools/run_stage.sh watch
  ./tools/run_stage.sh bridge
  ./tools/run_stage.sh apps
  ./tools/run_stage.sh crashlab
  ./tools/run_stage.sh pcap
EOF
}

if [ $# -lt 1 ]; then
  usage
  exit 1
fi

if [ ! -f "$VENV" ]; then
  log "ERROR: venv not found at $VENV"
  exit 2
fi

# shellcheck disable=SC1090
. "$VENV"

case "$1" in
  doctor)
    exec "$ROOT/dr_iphone.py"
    ;;
  watch)
    exec "$ROOT/iphone_signal_watch.py" --duration 30 --interval 5 --syslog-seconds 5
    ;;
  bridge)
    exec "$ROOT/iphone_file_bridge.py"
    ;;
  apps)
    exec "$ROOT/iphone_app_inventory.py"
    ;;
  crashlab)
    exec "$ROOT/iphone_crash_and_syslog_lab.py"
    ;;
  pcap)
    exec "$ROOT/iphone_pcap_lab.py" --seconds 10
    ;;
  *)
    usage
    exit 3
    ;;
esac
