#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_crash_and_syslog_lab.py

Project:
    Dr. iPhone

Stage:
    05 — Crash + Syslog Evidence Lab

Purpose
-------

Collect crash report metadata and syslog samples from an attached iPhone
to build a structured evidence layer.

Capabilities:

    • detect connected device
    • capture short syslog windows
    • categorize crash indicators
    • extract app identifiers
    • persist evidence artifacts

Safety
------

    read-only
    bounded capture
    no device modification

Outputs
-------

artifacts/iphone_crash_and_syslog_lab/

Files:

    syslog_sample.log
    crash_keywords.log
    crash_apps.json
    summary.json

Dependencies
------------

Recommended:

    python3
    usbmuxd
    libimobiledevice-utils
    pymobiledevice3 (optional)

"""

import subprocess
import json
import shutil
import time
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

BASE = Path("artifacts/iphone_crash_and_syslog_lab")
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = BASE / STAMP
OUT.mkdir(parents=True, exist_ok=True)

SYSLOG_FILE = OUT / "syslog_sample.log"
KEYWORDS_FILE = OUT / "crash_keywords.log"
CRASH_APPS_FILE = OUT / "crash_apps.json"
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
# syslog capture
# --------------------------------------------------

def capture_syslog(udid, seconds=5):

    if not exists("idevicesyslog"):
        return []

    try:

        proc = subprocess.Popen(
            ["idevicesyslog","-u",udid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        time.sleep(seconds)

        proc.terminate()

        out,_ = proc.communicate(timeout=3)

        return out.splitlines()

    except Exception:
        return []

# --------------------------------------------------
# crash keyword detection
# --------------------------------------------------

CRASH_WORDS = [
    "crash",
    "exception",
    "fault",
    "panic",
    "abort",
    "segmentation",
    "killed",
    "termination"
]

def detect_keywords(lines):

    hits = []

    for line in lines:

        low = line.lower()

        for word in CRASH_WORDS:

            if word in low:
                hits.append(line)
                break

    return hits

# --------------------------------------------------
# extract app bundle identifiers
# --------------------------------------------------

def extract_apps(lines):

    apps = set()

    for line in lines:

        parts = line.split()

        for p in parts:

            if "." in p and "/" not in p and ":" not in p:

                if len(p) > 6:

                    apps.add(p)

    return list(apps)

# --------------------------------------------------
# main
# --------------------------------------------------

summary = {
    "time": datetime.now().isoformat(),
    "device":None,
    "syslog_lines":0,
    "crash_hits":0,
    "apps_detected":0
}

log("starting crash/syslog lab")

udid = detect_device()

if not udid:

    log("no device detected")

    SUMMARY.write_text(json.dumps(summary,indent=2))

    exit()

summary["device"] = udid

log(f"device detected {udid}")

lines = capture_syslog(udid,5)

summary["syslog_lines"] = len(lines)

SYSLOG_FILE.write_text("\n".join(lines))

log(f"{len(lines)} syslog lines captured")

hits = detect_keywords(lines)

summary["crash_hits"] = len(hits)

KEYWORDS_FILE.write_text("\n".join(hits))

apps = extract_apps(lines)

summary["apps_detected"] = len(apps)

CRASH_APPS_FILE.write_text(json.dumps(apps,indent=2))

SUMMARY.write_text(json.dumps(summary,indent=2))

log(f"{len(hits)} crash indicators")
log(f"{len(apps)} apps detected")

log(f"artifacts saved to {OUT}")
