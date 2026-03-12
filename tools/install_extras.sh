#!/usr/bin/env bash
set -u
set -o pipefail

# =============================================================================
# README
# -----------------------------------------------------------------------------
# File: tools/install_extras.sh
# Purpose:
#   Install critical helper programs for the Dr. iPhone bench.
#
# Installs:
#   - tshark
#   - tcpdump
#   - jq
#   - sqlite3
#   - ripgrep
#
# Notes:
#   - Safe host-side install only
#   - Does not modify the iPhone
#   - Best-effort summary at end
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

  export DEBIAN_FRONTEND=noninteractive

  log "Updating apt metadata"
  apt-get update

  log "Installing critical helper packages"
  apt-get install -y \
    tshark \
    tcpdump \
    jq \
    sqlite3 \
    ripgrep

  log "Installed versions"
  {
    printf '\n=== versions ===\n'
    tshark --version 2>/dev/null | head -1 || true
    tcpdump --version 2>/dev/null | head -1 || true
    jq --version 2>/dev/null || true
    sqlite3 --version 2>/dev/null || true
    rg --version 2>/dev/null | head -1 || true
  }

  log "Done"
}

main "$@"

# -----------------------------------------------------------------------------
# INSTRUCTIONS
# -----------------------------------------------------------------------------
# chmod +x tools/install_extras.sh
# ./tools/install_extras.sh
# -----------------------------------------------------------------------------
