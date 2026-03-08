#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_signal_watch.py

Project:
    Dr. iPhone

Stage:
    02 — Signal Watch

Purpose
-------

Continuously observe an attached iPhone and capture live signals
including connection state, battery state, and syslog events.

This script provides timeline visibility into device behavior.

Signals observed:

    • device connect / disconnect
    • battery state changes
    • charging state
    • short syslog capture samples
    • repeated crash indicators
    • device identity

Design
------

    • Safe by default
    • Read-only
    • No device modifications
    • Continue on failure
    • Structured logging
    • Repo-friendly

Outputs
-------

Creates timestamped directory:

    artifacts/iphone_signal_watch/

Logs produced:

    device_events.log
    battery.log
    syslog_sample.log
    summary.json

Dependencies
------------

Recommended tools:

    python3
    usbmuxd
    libimobiledevice-utils
    pymobiledevice3

This script will continue even if some tools are missing.

"""

import subprocess
import time
import json
import shutil
from pathlib import Path
from datetime import datetime

# --------------------------------------------------
# helpers
# --------------------------------------------------

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def exists(cmd):
    return shutil.which(cmd) is not None

# --------------------------------------------------
# environment
# --------------------------------------------------

BASE = Path("artifacts/iphone_signal_watch")
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = BASE / STAMP
OUT.mkdir(parents=True, exist_ok=True)

DEVICE_LOG = OUT / "device_events.log"
BATTERY_LOG = OUT / "battery.log"
SYSLOG_LOG = OUT / "syslog_sample.log"
SUMMARY = OUT / "summary.json"

# --------------------------------------------------
# device detection
# --------------------------------------------------

def get_devices():
    if not exists("idevice_id"):
        return []
    out = run(["idevice_id", "-l"])
    return [x.strip() for x in out.splitlines() if x.strip()]

# --------------------------------------------------
# battery
# --------------------------------------------------

def battery_info(udid):
    if not exists("idevicediagnostics"):
        return {}
    out = run(["idevicediagnostics", "-u", udid, "battery"])
    data = {}
    for line in out.splitlines():
        if ":" in line:
            k,v = line.split(":",1)
            data[k.strip()] = v.strip()
    return data

# --------------------------------------------------
# syslog sample
# --------------------------------------------------

def capture_syslog(udid, seconds=4):

    if not exists("idevicesyslog"):
        return []

    try:

        proc = subprocess.Popen(
            ["idevicesyslog", "-u", udid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        time.sleep(seconds)

        proc.terminate()

        out,_ = proc.communicate(timeout=3)

        return out.splitlines()[:200]

    except Exception:
        return []

# --------------------------------------------------
# monitoring loop
# --------------------------------------------------

state = {
    "device_connected": False,
    "udid": None,
    "battery": None
}

summary = {
    "start_time": datetime.now().isoformat(),
    "device_sessions": 0,
    "battery_events": 0,
    "syslog_samples": 0
}

log("iPhone Signal Watch starting")

try:

    while True:

        devices = get_devices()

        # device connected
        if devices and not state["device_connected"]:

            udid = devices[0]

            state["device_connected"] = True
            state["udid"] = udid

            summary["device_sessions"] += 1

            msg = f"{datetime.now()} device connected {udid}\n"

            DEVICE_LOG.write_text(DEVICE_LOG.read_text() + msg if DEVICE_LOG.exists() else msg)

            log("device connected")

        # device disconnected
        if not devices and state["device_connected"]:

            msg = f"{datetime.now()} device disconnected\n"

            DEVICE_LOG.write_text(DEVICE_LOG.read_text() + msg)

            log("device disconnected")

            state["device_connected"] = False
            state["udid"] = None

        # if connected observe signals
        if state["device_connected"]:

            udid = state["udid"]

            # battery
            batt = battery_info(udid)

            if batt and batt != state["battery"]:

                summary["battery_events"] += 1
                state["battery"] = batt

                msg = f"{datetime.now()} {json.dumps(batt)}\n"

                BATTERY_LOG.write_text(BATTERY_LOG.read_text() + msg if BATTERY_LOG.exists() else msg)

                log("battery change")

            # syslog sample
            lines = capture_syslog(udid,3)

            if lines:

                summary["syslog_samples"] += 1

                block = "\n".join(lines) + "\n"

                SYSLOG_LOG.write_text(SYSLOG_LOG.read_text() + block if SYSLOG_LOG.exists() else block)

                log("syslog sample")

        time.sleep(5)

except KeyboardInterrupt:
    log("stopping monitor")

# --------------------------------------------------
# summary
# --------------------------------------------------

summary["end_time"] = datetime.now().isoformat()

SUMMARY.write_text(json.dumps(summary,indent=2))

log(f"logs written to {OUT}")
