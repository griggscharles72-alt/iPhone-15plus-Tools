#!/usr/bin/env bash
set -u
set -o pipefail

# =============================================================================
# File: tools/repair_pairing.sh
# Purpose:
#   Repair Linux <-> iPhone trust/pairing state for the connected device.
# =============================================================================

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

need_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    log "Re-running under sudo..."
    exec sudo bash "$0" "$@"
  fi
}

main() {
  need_root "$@"

  if ! command -v idevice_id >/dev/null 2>&1; then
    log "ERROR: idevice_id not found"
    exit 1
  fi

  UDID="$(idevice_id -l | head -n 1)"
  if [ -z "${UDID:-}" ]; then
    log "ERROR: no device detected"
    exit 2
  fi

  log "Restarting usbmuxd"
  systemctl restart usbmuxd

  log "Removing stale lockdown record for $UDID"
  rm -f "/var/lib/lockdown/${UDID}.plist"

  log "Attempting unpair"
  idevicepair unpair || true

  log "Pairing device"
  idevicepair pair

  log "Validating pair"
  idevicepair validate

  log "Fetching device identity"
  ideviceinfo -u "$UDID" | sed -n '1,20p'

  log "Done"
}

main "$@"
