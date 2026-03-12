#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_notify_console.py

Project:
    Dr. iPhone

Stage:
    07 — Notify Console

Purpose
-------

Collect bounded iPhone notification / event output and normalize it into
structured artifacts for later correlation.

This is an event-intake layer, not a modification layer.

Capabilities:

    • detect attached iPhone
    • validate helper tools
    • probe pymobiledevice3 notification-related command paths
    • capture bounded event output
    • normalize event lines
    • extract event keywords
    • write structured artifacts

Design
------

    • Safe by default
    • Read-only
    • Bounded capture window
    • Continue on failure
    • Repo-friendly
    • Artifact-driven

Primary helper stack
--------------------

    • python3
    • usbmuxd
    • libimobiledevice-utils
    • pymobiledevice3

Outputs
-------

Creates a timestamped artifact directory:

    artifacts/iphone_notify_console/<timestamp>/

Files may include:

    summary.json
    notify_stdout.txt
    notify_stderr.txt
    normalized_events.json
    keyword_counts.json
    notes.txt

Safety notes
------------

    • No trust modification
    • No restore / reboot / shutdown
    • No writes to the device
    • No triggering by default in this version
    • Capture is time-bounded

Important note
--------------

pymobiledevice3 command layouts can vary by version.
This script probes likely notification command forms and uses the first
working path it finds.

Author:
    OpenAI / SABLE workflow support
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# CONFIG
# ============================================================================

SCRIPT_NAME = "iphone_notify_console.py"
APP_NAME = "Dr. iPhone"
STAGE_NAME = "07 — Notify Console"

DEFAULT_SECONDS = 20
DEFAULT_MAX_LINES = 5000

EVENT_KEYWORDS = [
    "notify",
    "notification",
    "event",
    "state",
    "battery",
    "power",
    "lock",
    "unlock",
    "network",
    "wifi",
    "cellular",
    "data",
    "app",
    "launch",
    "terminate",
    "crash",
    "disconnect",
    "connect",
    "thermal",
    "memory",
]


# ============================================================================
# HELPERS
# ============================================================================

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def script_root() -> Path:
    return Path(__file__).resolve().parent


def make_output_dir(custom_dir: Optional[str] = None) -> Path:
    if custom_dir:
        base = Path(custom_dir).expanduser().resolve()
    else:
        base = script_root() / "artifacts" / "iphone_notify_console"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = base / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def safe_write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def safe_write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def command_exists(cmd: str) -> bool:
    return which(cmd) is not None


def run_cmd(cmd: List[str], timeout: int = 20) -> Dict[str, Any]:
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
            "cmd": cmd,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "cmd": cmd,
            "stdout": exc.stdout or "",
            "stderr": f"TIMEOUT after {timeout}s",
            "duration_s": round(time.time() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": None,
            "cmd": cmd,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.time() - started, 3),
        }


def clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def detect_device_udid() -> Optional[str]:
    if not command_exists("idevice_id"):
        return None
    res = run_cmd(["idevice_id", "-l"], timeout=15)
    if not res["ok"]:
        return None
    for line in clean_text(res["stdout"]).splitlines():
        line = line.strip()
        if line:
            return line
    return None


def get_device_info(udid: str) -> Dict[str, str]:
    if not command_exists("ideviceinfo"):
        return {}
    res = run_cmd(["ideviceinfo", "-u", udid], timeout=25)
    if not res["ok"]:
        return {}
    info: Dict[str, str] = {}
    for line in clean_text(res["stdout"]).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return info


def get_tool_inventory() -> Dict[str, Any]:
    inv: Dict[str, Any] = {}
    for cmd in ["python3", "idevice_id", "ideviceinfo", "usbmuxd", "pymobiledevice3"]:
        inv[cmd] = {
            "present": command_exists(cmd),
            "path": which(cmd) or "",
        }
    return inv


def read_text_lines(path: Path, max_lines: int = DEFAULT_MAX_LINES) -> List[str]:
    if not path.exists():
        return []
    lines: List[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fp:
        for i, line in enumerate(fp):
            if i >= max_lines:
                break
            lines.append(line.rstrip("\n"))
    return lines


def run_bounded_process(
    cmd: List[str],
    seconds: int,
    stdout_path: Path,
    stderr_path: Path,
) -> Dict[str, Any]:
    started = time.time()
    try:
        with stdout_path.open("w", encoding="utf-8") as out_fp, stderr_path.open("w", encoding="utf-8") as err_fp:
            proc = subprocess.Popen(
                cmd,
                stdout=out_fp,
                stderr=err_fp,
                text=True,
            )
            try:
                time.sleep(max(1, seconds))
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            except KeyboardInterrupt:
                proc.terminate()
                raise

        return {
            "ok": True,
            "cmd": cmd,
            "duration_s": round(time.time() - started, 3),
            "returncode": proc.returncode,
            "terminated": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "cmd": cmd,
            "duration_s": round(time.time() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


# ============================================================================
# NOTIFICATION COMMAND PROBES
# ============================================================================

def candidate_notify_commands(udid: str) -> List[List[str]]:
    return [
        ["pymobiledevice3", "developer", "accessibility", "notifications", "--udid", udid],
        ["pymobiledevice3", "developer", "accessibility", "notifications"],
        ["pymobiledevice3", "developer", "dvt", "notifications", "--udid", udid],
        ["pymobiledevice3", "developer", "dvt", "notifications"],
    ]


def try_notify_capture(udid: str, outdir: Path, seconds: int) -> Dict[str, Any]:
    stdout_path = outdir / "notify_stdout.txt"
    stderr_path = outdir / "notify_stderr.txt"

    if not command_exists("pymobiledevice3"):
        safe_write_text(stderr_path, "pymobiledevice3 not found\n")
        safe_write_text(stdout_path, "")
        return {
            "ok": False,
            "method": "none",
            "reason": "pymobiledevice3 not found",
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }

    attempts: List[Dict[str, Any]] = []

    for cmd in candidate_notify_commands(udid):
        probe = run_cmd(cmd + ["--help"], timeout=10)
        attempts.append({
            "probe_cmd": cmd + ["--help"],
            "probe_ok": probe["ok"],
            "probe_stdout_head": clean_text(probe["stdout"])[:300],
            "probe_stderr_head": clean_text(probe["stderr"])[:300],
        })

        result = run_bounded_process(cmd, seconds, stdout_path, stderr_path)
        if result.get("ok"):
            result["method"] = "pymobiledevice3_notify_capture"
            result["attempts"] = attempts
            return result

    return {
        "ok": False,
        "method": "none",
        "reason": "No notification command path succeeded",
        "attempts": attempts,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


# ============================================================================
# NORMALIZATION / SUMMARIZATION
# ============================================================================

BUNDLE_RE = re.compile(r"\b(?:[A-Za-z0-9_-]+\.)+[A-Za-z0-9_-]+\b")


def normalize_event_lines(lines: List[str]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        lowered = stripped.lower()
        matched_keywords = [kw for kw in EVENT_KEYWORDS if kw in lowered]
        bundles = BUNDLE_RE.findall(stripped)

        normalized.append({
            "line_number": idx,
            "raw": stripped,
            "keywords": matched_keywords,
            "bundles": bundles,
            "has_bundle": bool(bundles),
        })

    return normalized


def summarize_events(normalized_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    keyword_counter = Counter()
    bundle_counter = Counter()

    for event in normalized_events:
        for kw in event.get("keywords", []):
            keyword_counter[kw] += 1
        for bundle in event.get("bundles", []):
            bundle_counter[bundle] += 1

    return {
        "event_count": len(normalized_events),
        "keyword_counts": dict(keyword_counter.most_common(100)),
        "bundle_counts": dict(bundle_counter.most_common(100)),
    }


# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dr. iPhone — bounded notification/event intake",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=DEFAULT_SECONDS,
        help="Bounded notification capture duration in seconds",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Base output directory. Timestamped subdirectory is created inside it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outdir = make_output_dir(args.output_dir or None)

    log(f"{APP_NAME} {STAGE_NAME} start")
    log(f"Output directory: {outdir}")

    tools = get_tool_inventory()
    udid = detect_device_udid()

    if not udid:
        summary = {
            "timestamp": now_iso(),
            "script": SCRIPT_NAME,
            "app": APP_NAME,
            "stage": STAGE_NAME,
            "error": "No iPhone detected",
            "tools": tools,
        }
        safe_write_json(outdir / "summary.json", summary)
        safe_write_text(outdir / "notes.txt", "No device detected. Check cable, trust prompt, and usbmuxd.\n")
        log("No device detected")
        log(f"Artifacts written to {outdir}")
        return 1

    device_info = get_device_info(udid)
    log(f"Device detected: {device_info.get('DeviceName', udid)}")

    log(f"Starting bounded notification capture for {args.seconds}s")
    capture_result = try_notify_capture(udid, outdir, args.seconds)

    stdout_path = outdir / "notify_stdout.txt"
    lines = read_text_lines(stdout_path, max_lines=DEFAULT_MAX_LINES)

    normalized_events = normalize_event_lines(lines)
    event_summary = summarize_events(normalized_events)

    safe_write_json(outdir / "normalized_events.json", normalized_events)
    safe_write_json(outdir / "keyword_counts.json", event_summary["keyword_counts"])
    safe_write_json(outdir / "bundle_counts.json", event_summary["bundle_counts"])

    notes = [
        "This version is passive/read-only.",
        "It probes likely pymobiledevice3 notification command paths.",
        "A later version can add explicit safe filtering profiles and optional known-notification subscriptions.",
    ]
    safe_write_text(outdir / "notes.txt", "\n".join(notes) + "\n")

    summary = {
        "timestamp": now_iso(),
        "script": SCRIPT_NAME,
        "app": APP_NAME,
        "stage": STAGE_NAME,
        "capture_seconds": args.seconds,
        "tools": tools,
        "device": {
            "DeviceName": device_info.get("DeviceName", ""),
            "ProductType": device_info.get("ProductType", ""),
            "ProductVersion": device_info.get("ProductVersion", ""),
            "BuildVersion": device_info.get("BuildVersion", ""),
            "UniqueDeviceID": device_info.get("UniqueDeviceID", ""),
        },
        "capture_result": capture_result,
        "event_summary": event_summary,
    }

    safe_write_json(outdir / "summary.json", summary)

    log(f"Event lines captured: {event_summary['event_count']}")
    log(f"Keywords found: {len(event_summary['keyword_counts'])}")
    log(f"Bundles found: {len(event_summary['bundle_counts'])}")
    log(f"Artifacts written to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   iphone_notify_console.py
#
# Make executable:
#   chmod +x iphone_notify_console.py
#
# Basic run:
#   ./iphone_notify_console.py
#
# Shorter run:
#   ./iphone_notify_console.py --seconds 10
#
# Custom artifact base:
#   ./iphone_notify_console.py --output-dir ./artifacts
#
# Notes:
#   - Plug in and unlock the iPhone first.
#   - Tap "Trust" if prompted.
#   - This version is passive and does not trigger notifications.
#   - It captures bounded output, normalizes it, and stores artifacts.
#
# Signature:
#   Dr. iPhone — Notify Console
# ============================================================================
