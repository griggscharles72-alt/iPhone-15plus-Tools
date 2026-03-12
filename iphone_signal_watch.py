#!/usr/bin/env python3
"""
===============================================================================
iphone_signal_watch.py
Dr. iPhone — Stage 02 Signal Watch

Purpose
- monitor connected iPhone state over time
- detect connect/disconnect events
- sample battery state
- capture bounded syslog windows
- build a structured timeline
- write timestamped artifacts

Design
- safe by default
- read-only
- location-independent
- continue-on-failure
- bounded test mode supported
===============================================================================
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_NAME = "iphone_signal_watch"
DEFAULT_INTERVAL = 5
DEFAULT_SYSLOG_SECONDS = 3
DEFAULT_DURATION = 60


# ============================================================================
# PATHS / TIME
# ============================================================================

def repo_root() -> Path:
    return Path(__file__).resolve().parent


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return utc_now().strftime("%Y%m%d_%H%M%SZ")


def make_out_dir() -> Path:
    out = repo_root() / "artifacts" / SCRIPT_NAME / stamp()
    out.mkdir(parents=True, exist_ok=True)
    return out


# ============================================================================
# IO HELPERS
# ============================================================================

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ============================================================================
# COMMAND HELPERS
# ============================================================================

def exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], timeout: int = 20) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "duration_s": round(time.time() - started, 3),
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": "",
            "stderr": f"timeout after {timeout}s",
            "duration_s": round(time.time() - started, 3),
            "cmd": cmd,
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.time() - started, 3),
            "cmd": cmd,
        }


# ============================================================================
# DEVICE HELPERS
# ============================================================================

def get_devices() -> list[str]:
    if not exists("idevice_id"):
        return []
    result = run(["idevice_id", "-l"], timeout=15)
    if not result["ok"]:
        return []
    return [line.strip() for line in result["stdout"].splitlines() if line.strip()]


def validate_pairing(udid: str) -> dict[str, Any]:
    if not exists("idevicepair"):
        return {"ok": False, "paired": False, "reason": "idevicepair missing"}
    result = run(["idevicepair", "-u", udid, "validate"], timeout=20)
    text = f"{result['stdout']} {result['stderr']}".lower()
    return {
        "ok": result["ok"],
        "paired": result["ok"] or "success" in text or "validated pairing" in text,
        "raw": result,
    }


def battery_info(udid: str) -> dict[str, str]:
    if not exists("idevicediagnostics"):
        return {}
    result = run(["idevicediagnostics", "-u", udid, "battery"], timeout=20)
    if not result["ok"]:
        return {}

    data: dict[str, str] = {}
    for line in result["stdout"].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()
    return data


def capture_syslog(udid: str, seconds: int = 3, line_cap: int = 200) -> list[str]:
    if not exists("idevicesyslog"):
        return []

    try:
        proc = subprocess.Popen(
            ["idevicesyslog", "-u", udid],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(seconds)
        proc.terminate()

        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()

        lines = [line.rstrip() for line in (out or "").splitlines()]
        return lines[:line_cap]
    except Exception:
        return []


def syslog_tags(lines: list[str]) -> dict[str, int]:
    tags = {
        "crash": 0,
        "error": 0,
        "warning": 0,
        "thermal": 0,
        "battery": 0,
        "springboard": 0,
        "runningboard": 0,
        "assertion": 0,
    }
    for line in lines:
        low = line.lower()
        if "crash" in low:
            tags["crash"] += 1
        if "error" in low:
            tags["error"] += 1
        if "warning" in low:
            tags["warning"] += 1
        if "thermal" in low:
            tags["thermal"] += 1
        if "battery" in low:
            tags["battery"] += 1
        if "springboard" in low:
            tags["springboard"] += 1
        if "runningboard" in low:
            tags["runningboard"] += 1
        if "assertion" in low:
            tags["assertion"] += 1
    return tags


# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor iPhone live signals from Linux")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="Total run duration in seconds")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help="Polling interval in seconds")
    parser.add_argument("--syslog-seconds", type=int, default=DEFAULT_SYSLOG_SECONDS, help="Seconds per syslog sample")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = make_out_dir()

    device_log = out_dir / "device_events.log"
    battery_log = out_dir / "battery.log"
    syslog_log = out_dir / "syslog_sample.log"
    timeline_jsonl = out_dir / "timeline.jsonl"
    summary_json = out_dir / "summary.json"

    summary: dict[str, Any] = {
        "script": SCRIPT_NAME,
        "start_time_utc": now_iso(),
        "duration_requested_s": args.duration,
        "interval_s": args.interval,
        "syslog_seconds": args.syslog_seconds,
        "device_sessions": 0,
        "connect_events": 0,
        "disconnect_events": 0,
        "battery_events": 0,
        "syslog_samples": 0,
        "paired_validations": 0,
        "last_udid": None,
        "helper_inventory": {
            "idevice_id": exists("idevice_id"),
            "idevicepair": exists("idevicepair"),
            "idevicediagnostics": exists("idevicediagnostics"),
            "idevicesyslog": exists("idevicesyslog"),
        },
    }

    state: dict[str, Any] = {
        "device_connected": False,
        "udid": None,
        "battery": None,
    }

    log(f"{SCRIPT_NAME} starting")
    log(f"output directory: {out_dir}")

    started = time.time()

    try:
        while True:
            elapsed = time.time() - started
            if elapsed >= args.duration:
                log("duration reached")
                break

            devices = get_devices()

            if devices and not state["device_connected"]:
                udid = devices[0]
                state["device_connected"] = True
                state["udid"] = udid
                state["battery"] = None

                summary["device_sessions"] += 1
                summary["connect_events"] += 1
                summary["last_udid"] = udid

                pairing = validate_pairing(udid)
                if pairing.get("paired"):
                    summary["paired_validations"] += 1

                msg = f"{now_iso()} device connected {udid}\n"
                append_text(device_log, msg)
                append_jsonl(timeline_jsonl, {
                    "ts": now_iso(),
                    "event": "device_connected",
                    "udid": udid,
                    "pair_valid": pairing.get("paired"),
                })
                log(f"device connected: {udid}")

            elif not devices and state["device_connected"]:
                append_text(device_log, f"{now_iso()} device disconnected\n")
                append_jsonl(timeline_jsonl, {
                    "ts": now_iso(),
                    "event": "device_disconnected",
                    "udid": state["udid"],
                })
                log("device disconnected")

                summary["disconnect_events"] += 1
                state["device_connected"] = False
                state["udid"] = None
                state["battery"] = None

            if state["device_connected"] and state["udid"]:
                udid = state["udid"]

                batt = battery_info(udid)
                if batt and batt != state["battery"]:
                    state["battery"] = batt
                    summary["battery_events"] += 1

                    append_text(battery_log, f"{now_iso()} {json.dumps(batt, ensure_ascii=False)}\n")
                    append_jsonl(timeline_jsonl, {
                        "ts": now_iso(),
                        "event": "battery_change",
                        "udid": udid,
                        "battery": batt,
                    })
                    log("battery change")

                lines = capture_syslog(udid, seconds=args.syslog_seconds)
                if lines:
                    summary["syslog_samples"] += 1
                    tags = syslog_tags(lines)

                    append_text(
                        syslog_log,
                        f"\n===== {now_iso()} udid={udid} =====\n" + "\n".join(lines) + "\n",
                    )
                    append_jsonl(timeline_jsonl, {
                        "ts": now_iso(),
                        "event": "syslog_sample",
                        "udid": udid,
                        "line_count": len(lines),
                        "tags": tags,
                    })
                    log("syslog sample")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log("keyboard interrupt received")

    summary["end_time_utc"] = now_iso()
    summary["artifact_dir"] = str(out_dir)

    write_json(summary_json, summary)

    log(f"summary written: {summary_json}")
    log(f"{SCRIPT_NAME} complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ------------------------------------------------------------------------------
# INSTRUCTIONS
#
# FILE NAME
# iphone_signal_watch.py
#
# RUN FROM REPO ROOT
# cd "$HOME/repos/dr-iphone" && . .venv/bin/activate && python3 iphone_signal_watch.py
#
# SHORT TEST
# cd "$HOME/repos/dr-iphone" && . .venv/bin/activate && python3 iphone_signal_watch.py --duration 30 --interval 5 --syslog-seconds 2
# ------------------------------------------------------------------------------
