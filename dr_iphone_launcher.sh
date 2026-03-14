#!/usr/bin/env bash
set -u
set -o pipefail

# ============================================================================
# README
# ============================================================================
#
# Filename:
#   dr_iphone_launcher.sh
#
# Project:
#   Dr. iPhone
#
# Purpose:
#   Stable repo launcher for daily iPhone bench runs.
#
# What it does:
#   1. Activates the repo venv
#   2. Checks required tools
#   3. Verifies usbmuxd is active
#   4. Waits for a visible iPhone UDID
#   5. Validates pairing if possible
#   6. Runs bench or bench-plus through iphone_operator_console.py
#
# Default behavior:
#   bench
#
# Optional behavior:
#   bench-plus
#
# Safety:
#   - Read-only repo workflow
#   - No phone writes from this launcher
#   - No trust-cache deletion here
#   - No forced system mutation except usbmuxd status check
#
# ============================================================================

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$REPO_ROOT/.venv/bin/activate"
OPERATOR="$REPO_ROOT/iphone_operator_console.py"

MODE="${1:-bench}"
WAIT_SECONDS="${WAIT_SECONDS:-20}"

log() {
  printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

die() {
  log "ERROR: $*"
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

check_mode() {
  case "$MODE" in
    bench|bench-plus) ;;
    *)
      die "Invalid mode '$MODE'. Use: bench or bench-plus"
      ;;
  esac
}

wait_for_device() {
  local i udid
  for ((i=1; i<=WAIT_SECONDS; i++)); do
    udid="$(idevice_id -l 2>/dev/null | head -n 1 || true)"
    if [[ -n "${udid:-}" ]]; then
      printf '%s' "$udid"
      return 0
    fi
    sleep 1
  done
  return 1
}

main() {
  check_mode

  [[ -f "$VENV_PATH" ]] || die "Virtualenv not found at $VENV_PATH"
  # shellcheck disable=SC1090
  . "$VENV_PATH"

  need_cmd python3
  need_cmd idevice_id
  need_cmd idevicepair
  need_cmd systemctl

  [[ -f "$OPERATOR" ]] || die "Missing operator console: $OPERATOR"

  log "Repo root: $REPO_ROOT"
  log "Requested mode: $MODE"

  if [[ "$(systemctl is-active usbmuxd 2>/dev/null || true)" != "active" ]]; then
    die "usbmuxd is not active"
  fi

  log "Waiting for iPhone visibility (up to ${WAIT_SECONDS}s)..."
  UDID="$(wait_for_device || true)"

  if [[ -z "${UDID:-}" ]]; then
    log "No iPhone detected by idevice_id"
    log "Phone-side checklist:"
    log "  1. Plug in the iPhone"
    log "  2. Unlock it"
    log "  3. Stay on the home screen"
    log "  4. Tap Trust if prompted"
    exit 1
  fi

  log "Detected UDID: $UDID"

  if idevicepair validate >/dev/null 2>&1; then
    log "Pair validation: OK"
  else
    log "Pair validation did not pass yet"
    log "Attempting pair..."
    idevicepair pair || die "Pair attempt failed"
    idevicepair validate || die "Pair validate failed after pair attempt"
    log "Pair validation: OK after pair"
  fi

  chmod +x "$OPERATOR" || true

  log "Launching operator console: $MODE"
  cd "$REPO_ROOT" || exit 1
  "./iphone_operator_console.py" "$MODE"
}

main "$@"

# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   dr_iphone_launcher.sh
#
# Make executable:
#   chmod +x dr_iphone_launcher.sh
#
# Run default daily bench:
#   ./dr_iphone_launcher.sh
#
# Run explicit bench:
#   ./dr_iphone_launcher.sh bench
#
# Run extended bench:
#   ./dr_iphone_launcher.sh bench-plus
#
# Optional wait override:
#   WAIT_SECONDS=30 ./dr_iphone_launcher.sh bench
#
# Signature:
#   Dr. iPhone — Stable Launcher
# ============================================================================
