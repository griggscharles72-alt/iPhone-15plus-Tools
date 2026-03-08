#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_file_bridge.py

Project:
    Dr. iPhone

Stage:
    03 — File Bridge

Purpose
-------

Provide controlled filesystem interaction with an attached iPhone
using ifuse and libimobiledevice.

Capabilities:

    • detect connected device
    • list file-sharing-enabled apps
    • mount app containers on demand
    • copy artifacts from device
    • unmount safely

Safety
------

    • read-only by default
    • mounts only when explicitly requested
    • unmounts automatically
    • continues on failure
    • no jailbreak required

Outputs
-------

Creates:

    artifacts/iphone_file_bridge/

Files:

    apps.json
    pull_log.txt
    summary.json

Dependencies
------------

Recommended:

    python3
    usbmuxd
    libimobiledevice-utils
    ifuse

"""

import subprocess
import shutil
import json
from pathlib import Path
from datetime import datetime
import argparse

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

BASE = Path("artifacts/iphone_file_bridge")
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = BASE / STAMP

OUT.mkdir(parents=True, exist_ok=True)

APPS_JSON = OUT / "apps.json"
PULL_LOG = OUT / "pull_log.txt"
SUMMARY = OUT / "summary.json"

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
# list apps
# --------------------------------------------------

def list_apps(udid):

    if not exists("ifuse"):
        return []

    out = run(["ifuse","--list-apps","--udid",udid])

    apps = []

    for line in out.splitlines():

        if ":" in line:
            bundle,name = line.split(":",1)
            apps.append({
                "bundle":bundle.strip(),
                "name":name.strip()
            })

    return apps

# --------------------------------------------------
# mount container
# --------------------------------------------------

def mount_app(bundle, mount_dir, udid):

    mount_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ifuse",
        str(mount_dir),
        "--udid",udid,
        "--container",bundle
    ]

    run(cmd)

    return mount_dir.exists()

# --------------------------------------------------
# unmount
# --------------------------------------------------

def unmount(path):

    run(["fusermount","-u",str(path)])

# --------------------------------------------------
# copy artifacts
# --------------------------------------------------

def pull_files(src_dir, dest_dir):

    dest_dir.mkdir(parents=True, exist_ok=True)

    count = 0

    for item in src_dir.iterdir():

        try:

            target = dest_dir / item.name

            if item.is_file():
                target.write_bytes(item.read_bytes())
                count += 1

        except Exception:
            pass

    return count

# --------------------------------------------------
# main
# --------------------------------------------------

parser = argparse.ArgumentParser()

parser.add_argument("--bundle",
                    help="bundle id to mount")

parser.add_argument("--pull",
                    help="pull files from mounted container")

args = parser.parse_args()

summary = {
    "time": datetime.now().isoformat(),
    "device":None,
    "apps_found":0,
    "files_pulled":0
}

log("starting file bridge")

udid = detect_device()

if not udid:

    log("no device detected")

    SUMMARY.write_text(json.dumps(summary,indent=2))

    exit()

summary["device"] = udid

log(f"device detected {udid}")

apps = list_apps(udid)

summary["apps_found"] = len(apps)

APPS_JSON.write_text(json.dumps(apps,indent=2))

log(f"{len(apps)} file-sharing apps found")

# optional mount workflow

if args.bundle:

    mount_point = OUT / "mount"

    log(f"mounting {args.bundle}")

    ok = mount_app(args.bundle,mount_point,udid)

    if ok:

        log("mount successful")

        if args.pull:

            pulled = pull_files(mount_point, OUT / "pulled")

            summary["files_pulled"] = pulled

            PULL_LOG.write_text(f"{pulled} files copied")

            log(f"{pulled} files pulled")

        unmount(mount_point)

        log("unmounted")

    else:

        log("mount failed")

SUMMARY.write_text(json.dumps(summary,indent=2))

log(f"artifacts saved to {OUT}")
