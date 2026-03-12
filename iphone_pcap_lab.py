#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_pcap_lab.py

Project:
    Dr. iPhone

Stage:
    06 — PCAP Library P1

Purpose
-------

Perform a bounded, read-only network capture workflow for an attached
iPhone and generate first-pass evidence artifacts.

This script is designed to:

    • detect a connected iPhone
    • validate helper tools
    • attempt iPhone-side packet capture through pymobiledevice3
    • store raw capture artifacts
    • summarize endpoints, DNS-like strings, and protocols when possible
    • continue on failure without killing the full run

Design
------

    • Safe by default
    • Read-only
    • Bounded capture duration
    • Repo-friendly
    • Best-effort execution
    • Artifact-driven

Primary helper stack
--------------------

    • python3
    • usbmuxd
    • libimobiledevice-utils
    • pymobiledevice3
    • tshark (optional, for richer summaries)

Outputs
-------

Creates a timestamped artifact directory:

    artifacts/iphone_pcap_lab/<timestamp>/

Files may include:

    summary.json
    capture_stdout.txt
    capture_stderr.txt
    pcap_text.txt
    dns_candidates.json
    endpoint_candidates.json
    protocol_candidates.json
    notes.txt

Safety notes
------------

    • No device writes
    • No trust modification
    • No restore / reboot / shutdown
    • No persistent services installed by this script
    • Capture is time-bounded

Important note
--------------

pymobiledevice3 subcommands can vary between versions.
This script probes likely command forms and uses the first working path.

Author:
    OpenAI / SABLE workflow support
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# CONFIG
# ============================================================================

SCRIPT_NAME = "iphone_pcap_lab.py"
APP_NAME = "Dr. iPhone"
STAGE_NAME = "06 — PCAP Library P1"

DEFAULT_CAPTURE_SECONDS = 20
DEFAULT_MAX_LINES = 5000


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
        base = script_root() / "artifacts" / "iphone_pcap_lab"
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


def run_cmd(
    cmd: List[str],
    timeout: int = 30,
    text: bool = True,
) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=text,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "cmd": cmd,
            "stdout": proc.stdout if text else "",
            "stderr": proc.stderr if text else "",
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
    for cmd in ["python3", "idevice_id", "ideviceinfo", "usbmuxd", "pymobiledevice3", "tshark"]:
        inv[cmd] = {
            "present": command_exists(cmd),
            "path": which(cmd) or "",
        }
    return inv


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
            "terminated": True,
            "returncode": proc.returncode,
        }
    except Exception as exc:
        return {
            "ok": False,
            "cmd": cmd,
            "duration_s": round(time.time() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


# ============================================================================
# PCAP / TEXT CAPTURE STRATEGY
# ============================================================================

def candidate_capture_commands(udid: str) -> List[List[str]]:
    """
    Probe likely pymobiledevice3 command forms.
    This installed CLI uses long-form device options.
    """
    return [
        ["pymobiledevice3", "pcap", "--udid", udid],
        ["pymobiledevice3", "pcap"],
        ["pymobiledevice3", "developer", "pcap", "--udid", udid],
        ["pymobiledevice3", "developer", "pcap"],
        ["pymobiledevice3", "remote", "pcap", "--udid", udid],
        ["pymobiledevice3", "remote", "pcap"],
    ]


def try_capture_text(udid: str, outdir: Path, seconds: int) -> Dict[str, Any]:
    stdout_path = outdir / "capture_stdout.txt"
    stderr_path = outdir / "capture_stderr.txt"

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
    for cmd in candidate_capture_commands(udid):
        version_probe = run_cmd(cmd + ["--help"], timeout=10)
        attempts.append({
            "probe_cmd": cmd + ["--help"],
            "probe_ok": version_probe["ok"],
            "probe_stderr": clean_text(version_probe["stderr"]),
            "probe_stdout_head": clean_text(version_probe["stdout"])[:300],
        })

        # Even if --help fails, some CLI layouts still run. Try bounded run.
        result = run_bounded_process(cmd, seconds, stdout_path, stderr_path)
        if result.get("ok"):
            result["method"] = "pymobiledevice3_text_capture"
            result["attempts"] = attempts
            return result

    return {
        "ok": False,
        "method": "none",
        "reason": "No capture command path succeeded",
        "attempts": attempts,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


# ============================================================================
# PARSING / SUMMARIZATION
# ============================================================================

DOMAIN_RE = re.compile(
    r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b"
)

IP_RE = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)

PROTO_HINTS = [
    "tcp",
    "udp",
    "dns",
    "tls",
    "ssl",
    "http",
    "https",
    "quic",
    "mdns",
    "icmp",
    "arp",
    "ntp",
]


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


def summarize_text_capture(lines: List[str]) -> Dict[str, Any]:
    domains = Counter()
    ips = Counter()
    protos = Counter()

    for line in lines:
        low = line.lower()

        for match in DOMAIN_RE.findall(line):
            domains[match] += 1

        for match in IP_RE.findall(line):
            ips[match] += 1

        for proto in PROTO_HINTS:
            if proto in low:
                protos[proto] += 1

    return {
        "line_count": len(lines),
        "dns_candidates": [{"value": k, "count": v} for k, v in domains.most_common(50)],
        "endpoint_candidates": [{"value": k, "count": v} for k, v in ips.most_common(50)],
        "protocol_candidates": [{"value": k, "count": v} for k, v in protos.most_common(50)],
    }


def tshark_text_summary(text_path: Path, outdir: Path) -> Dict[str, Any]:
    """
    Best-effort text post-processing through tshark is only possible for actual pcap files.
    Since P1 is conservative and may only get text output, we store a note here.
    """
    note = (
        "P1 currently captures and summarizes text output from pymobiledevice3 capture paths. "
        "A later P2/P3 version can be extended to emit real .pcap files and hand them to tshark "
        "for packet-level parsing."
    )
    safe_write_text(outdir / "notes.txt", note + "\n")
    return {
        "ok": command_exists("tshark"),
        "mode": "text_only_note",
        "note": note,
    }


# ============================================================================
# SUMMARY RENDER
# ============================================================================

def build_summary(
    args: argparse.Namespace,
    tools: Dict[str, Any],
    device_info: Dict[str, str],
    capture_result: Dict[str, Any],
    text_summary: Dict[str, Any],
    tshark_summary: Dict[str, Any],
) -> Dict[str, Any]:
    return {
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
        "text_summary": text_summary,
        "tshark_summary": tshark_summary,
    }


# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dr. iPhone — bounded PCAP/text capture lab",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--seconds",
        type=int,
        default=DEFAULT_CAPTURE_SECONDS,
        help="Bounded capture duration in seconds",
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

    # Attempt bounded text capture
    log(f"Starting bounded capture for {args.seconds}s")
    capture_result = try_capture_text(udid, outdir, args.seconds)

    stdout_path = outdir / "capture_stdout.txt"
    lines = read_text_lines(stdout_path, max_lines=DEFAULT_MAX_LINES)
    if lines:
        safe_write_text(outdir / "pcap_text.txt", "\n".join(lines) + "\n")

    text_summary = summarize_text_capture(lines)
    tshark_summary = tshark_text_summary(stdout_path, outdir)

    safe_write_json(outdir / "dns_candidates.json", text_summary["dns_candidates"])
    safe_write_json(outdir / "endpoint_candidates.json", text_summary["endpoint_candidates"])
    safe_write_json(outdir / "protocol_candidates.json", text_summary["protocol_candidates"])

    summary = build_summary(
        args=args,
        tools=tools,
        device_info=device_info,
        capture_result=capture_result,
        text_summary=text_summary,
        tshark_summary=tshark_summary,
    )
    safe_write_json(outdir / "summary.json", summary)

    log(f"Lines captured: {text_summary['line_count']}")
    log(f"DNS candidates: {len(text_summary['dns_candidates'])}")
    log(f"Endpoint candidates: {len(text_summary['endpoint_candidates'])}")
    log(f"Protocol candidates: {len(text_summary['protocol_candidates'])}")
    log(f"Artifacts written to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   iphone_pcap_lab.py
#
# Make executable:
#   chmod +x iphone_pcap_lab.py
#
# Basic run:
#   ./iphone_pcap_lab.py
#
# Shorter test run:
#   ./iphone_pcap_lab.py --seconds 10
#
# Custom artifact base:
#   ./iphone_pcap_lab.py --output-dir ./artifacts
#
# Notes:
#   - Plug in and unlock the iPhone first.
#   - Tap "Trust" if prompted.
#   - This P1 version is intentionally conservative and text-first.
#   - It probes likely pymobiledevice3 PCAP command paths and stores whatever
#     capture output it can safely obtain.
#   - A later P2/P3 can upgrade this to real .pcap generation and tshark parsing.
#
# Signature:
#   Dr. iPhone — PCAP Library P1
# ============================================================================
