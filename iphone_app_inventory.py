#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_app_inventory.py

Project:
    Dr. iPhone

Stage:
    04 — App Inventory

Purpose
-------

Enumerate installed iPhone applications and maintain historical
state so changes between runs can be detected.

Capabilities:

    • detect connected device
    • enumerate installed apps
    • normalize bundle identifiers
    • persist app inventory
    • diff current vs previous state

Outputs
-------

artifacts/iphone_app_inventory/

Files:

    apps_current.json
    apps_previous.json
    apps_added.json
    apps_removed.json
    summary.json

Dependencies
------------

Recommended tools:

    python3
    usbmuxd
    pymobiledevice3

Safe operation:
    read-only
"""

import subprocess
import json
import shutil
from pathlib import Path
from datetime import datetime

# --------------------------------------------------
# helpers
# --------------------------------------------------

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def exists(cmd):
    return shutil.which(cmd) is not None

# --------------------------------------------------
# artifact paths
# --------------------------------------------------

BASE = Path("artifacts/iphone_app_inventory")
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = BASE / STAMP
OUT.mkdir(parents=True, exist_ok=True)

CURRENT = OUT / "apps_current.json"
ADDED = OUT / "apps_added.json"
REMOVED = OUT / "apps_removed.json"
SUMMARY = OUT / "summary.json"

STATE_DIR = BASE / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

PREVIOUS = STATE_DIR / "apps_previous.json"

# --------------------------------------------------
# device detection
# --------------------------------------------------

def detect_device():

    if not exists("idevice_id"):
        return None

    out = run(["idevice_id", "-l"])

    for line in out.splitlines():
        if line.strip():
            return line.strip()

    return None

# --------------------------------------------------
# enumerate apps
# --------------------------------------------------

def enumerate_apps():

    if exists("pymobiledevice3"):

        out = run(["pymobiledevice3","apps","list"])

        apps = []

        for line in out.splitlines():

            if "." in line:
                bundle = line.strip()

                apps.append({
                    "bundle":bundle
                })

        return apps

    return []

# --------------------------------------------------
# diff logic
# --------------------------------------------------

def diff_apps(current, previous):

    curr_set = set(a["bundle"] for a in current)
    prev_set = set(a["bundle"] for a in previous)

    added = curr_set - prev_set
    removed = prev_set - curr_set

    return list(added), list(removed)

# --------------------------------------------------
# main
# --------------------------------------------------

summary = {
    "time": datetime.now().isoformat(),
    "device": None,
    "apps_total": 0,
    "apps_added": 0,
    "apps_removed": 0
}

log("starting app inventory")

udid = detect_device()

if not udid:

    log("no device detected")

    SUMMARY.write_text(json.dumps(summary,indent=2))

    exit()

summary["device"] = udid

log(f"device {udid}")

apps = enumerate_apps()

summary["apps_total"] = len(apps)

CURRENT.write_text(json.dumps(apps,indent=2))

log(f"{len(apps)} apps found")

# load previous state

previous = []

if PREVIOUS.exists():

    try:
        previous = json.loads(PREVIOUS.read_text())
    except Exception:
        previous = []

# diff

added, removed = diff_apps(apps, previous)

summary["apps_added"] = len(added)
summary["apps_removed"] = len(removed)

ADDED.write_text(json.dumps(added,indent=2))
REMOVED.write_text(json.dumps(removed,indent=2))

# update state

PREVIOUS.write_text(json.dumps(apps,indent=2))

SUMMARY.write_text(json.dumps(summary,indent=2))

log(f"apps added {len(added)}")
log(f"apps removed {len(removed)}")

log(f"artifacts saved to {OUT}")
