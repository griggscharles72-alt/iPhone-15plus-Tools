#!/bin/bash
# full_device_check_suspicious.sh - Full device info and suspicious activity check
# Save this in the repo root

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"

# Activate virtualenv and set pymobiledevice3 CLI
source "$VENV_DIR/bin/activate"
export PMD3_CLI="$VENV_DIR/bin/pymobiledevice3"

# Timestamped artifacts directory
ARTIFACTS_DIR="$REPO_DIR/artifacts/full_device_check/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$ARTIFACTS_DIR"

REPORT_FILE="$ARTIFACTS_DIR/device_report.txt"

echo "[+] Starting full device check..." | tee -a "$REPORT_FILE"
echo "========================================================================" | tee -a "$REPORT_FILE"

# ----------------------------
# Dr. iPhone baseline
DR_OUTPUT=$(python "$REPO_DIR/dr_iphone.py")
echo "=== Dr. iPhone Baseline ===" | tee -a "$REPORT_FILE"
echo "$DR_OUTPUT" | tee -a "$REPORT_FILE"

# ----------------------------
# Crash / Syslog lab
CRASH_OUTPUT=$(python "$REPO_DIR/iphone_crash_and_syslog_lab.py")
echo "=== Crash / Syslog ===" | tee -a "$REPORT_FILE"
echo "$CRASH_OUTPUT" | tee -a "$REPORT_FILE"

# Detect suspicious crash keywords
CRASH_KEYWORDS=$(echo "$CRASH_OUTPUT" | grep "Crash keyword hits:" | awk '{print $4}')
if [ -n "$CRASH_KEYWORDS" ] && [ "$CRASH_KEYWORDS" -gt 0 ]; then
    echo "[!] Crash keywords detected: $CRASH_KEYWORDS" | tee -a "$REPORT_FILE"
fi

# ----------------------------
# App Inventory
APP_OUTPUT=$(python "$REPO_DIR/iphone_app_inventory.py")
echo "=== App Inventory ===" | tee -a "$REPORT_FILE"
echo "$APP_OUTPUT" | tee -a "$REPORT_FILE"

# Check for app changes
APPS_ADDED=$(echo "$APP_OUTPUT" | grep "Apps added:" | awk '{print $3}')
APPS_REMOVED=$(echo "$APP_OUTPUT" | grep "Apps removed:" | awk '{print $3}')
if [ "$APPS_ADDED" -eq 0 ] && [ "$APPS_REMOVED" -eq 0 ]; then
    echo "[OK] No app inventory changes" | tee -a "$REPORT_FILE"
else
    echo "[!] App inventory changed: Added=$APPS_ADDED Removed=$APPS_REMOVED" | tee -a "$REPORT_FILE"
fi

# ----------------------------
# Developer Surface
DEV_OUTPUT=$(python "$REPO_DIR/iphone_dev_surface.py")
echo "=== Developer Surface ===" | tee -a "$REPORT_FILE"
echo "$DEV_OUTPUT" | tee -a "$REPORT_FILE"

# Check unreachable surfaces safely
UNREACHABLE_SURFACES=$(echo "$DEV_OUTPUT" | grep "Unreachable surfaces" | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+$/) print $i}')
if [ -n "$UNREACHABLE_SURFACES" ] && [ "$UNREACHABLE_SURFACES" -gt 0 ]; then
    echo "[!] Unreachable developer surfaces detected: $UNREACHABLE_SURFACES" | tee -a "$REPORT_FILE"
else
    echo "[OK] All developer surfaces reachable" | tee -a "$REPORT_FILE"
fi

echo "[+] Full device check complete. Report saved to $REPORT_FILE" | tee -a "$REPORT_FILE"
