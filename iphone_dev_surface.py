#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_dev_surface.py

Project:
    Dr. iPhone

Stage:
    08 — Developer Surface Capability Map

Purpose
-------

Probe advanced iPhone developer-facing capabilities from Linux and build
a capability map for the current device + host environment.

This script does not assume any advanced surface is available.
It tests safely, records outcomes, and writes artifacts.

Capabilities Probed
-------------------

    • device detection
    • helper tool validation
    • screenshot capability
    • developer-facing pymobiledevice3 surfaces
    • notification/help surface discovery
    • app/help surface discovery
    • pcap/help surface discovery
    • generic command-surface probing

Design
------

    • Safe by default
    • Read-only by default
    • Best-effort execution
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

    artifacts/iphone_dev_surface/<timestamp>/

Files may include:

    summary.json
    screenshot.png
    capability_matrix.json
    probe_results.json
    notes.txt

Safety notes
------------

    • No trust modification
    • No restore / reboot / shutdown
    • No writes to device by default
    • No location simulation by default
    • No app launch by default
    • No persistent services installed by this script

Author:
    OpenAI / SABLE workflow support
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# CONFIG
# ============================================================================

SCRIPT_NAME = "iphone_dev_surface.py"
APP_NAME = "Dr. iPhone"
STAGE_NAME = "08 — Developer Surface Capability Map"


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
        base = script_root() / "artifacts" / "iphone_dev_surface"
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
    for cmd in [
        "python3",
        "idevice_id",
        "ideviceinfo",
        "idevicescreenshot",
        "usbmuxd",
        "pymobiledevice3",
    ]:
        inv[cmd] = {
            "present": command_exists(cmd),
            "path": which(cmd) or "",
        }
    return inv


# ============================================================================
# PROBES
# ============================================================================

def probe_help(cmd: List[str], timeout: int = 12) -> Dict[str, Any]:
    return run_cmd(cmd + ["--help"], timeout=timeout)


def probe_screenshot_idevice(outdir: Path, udid: str) -> Dict[str, Any]:
    png_path = outdir / "screenshot_idevicescreenshot.png"

    if not command_exists("idevicescreenshot"):
        return {
            "surface": "idevicescreenshot",
            "available": False,
            "reason": "idevicescreenshot not found",
            "artifact": "",
        }

    # idevicescreenshot typically takes output path and can accept -u
    result = run_cmd(["idevicescreenshot", "-u", udid, str(png_path)], timeout=30)
    ok = result["ok"] and png_path.exists() and png_path.stat().st_size > 0

    return {
        "surface": "idevicescreenshot",
        "available": ok,
        "artifact": str(png_path) if png_path.exists() else "",
        "result": result,
    }


def probe_pymobiledevice_version() -> Dict[str, Any]:
    if not command_exists("pymobiledevice3"):
        return {
            "surface": "pymobiledevice3_version",
            "available": False,
            "reason": "pymobiledevice3 not found",
        }

    result = run_cmd(["pymobiledevice3", "version"], timeout=12)
    return {
        "surface": "pymobiledevice3_version",
        "available": result["ok"],
        "result": result,
    }


def probe_pymobiledevice_top_help() -> Dict[str, Any]:
    if not command_exists("pymobiledevice3"):
        return {
            "surface": "pymobiledevice3_top_help",
            "available": False,
            "reason": "pymobiledevice3 not found",
        }

    result = run_cmd(["pymobiledevice3", "--help"], timeout=12)
    return {
        "surface": "pymobiledevice3_top_help",
        "available": result["ok"],
        "result": result,
    }


def probe_command_surface(name: str, cmd: List[str]) -> Dict[str, Any]:
    if not command_exists("pymobiledevice3"):
        return {
            "surface": name,
            "available": False,
            "reason": "pymobiledevice3 not found",
        }

    result = probe_help(cmd)
    stdout = clean_text(result.get("stdout", ""))
    stderr = clean_text(result.get("stderr", ""))

    available = result["ok"] or bool(stdout)
    return {
        "surface": name,
        "available": available,
        "result": result,
        "stdout_head": stdout[:800],
        "stderr_head": stderr[:800],
    }


def run_all_probes(outdir: Path, udid: str) -> List[Dict[str, Any]]:
    probes: List[Dict[str, Any]] = []

    # Basic screenshot path
    probes.append(probe_screenshot_idevice(outdir, udid))

    # Top-level pymobiledevice3 surfaces
    probes.append(probe_pymobiledevice_version())
    probes.append(probe_pymobiledevice_top_help())

    # Known/likely command families
    surface_commands = [
        ("pymobile_apps", ["pymobiledevice3", "apps"]),
        ("pymobile_notifications", ["pymobiledevice3", "notifications"]),
        ("pymobile_notification", ["pymobiledevice3", "notification"]),
        ("pymobile_pcap", ["pymobiledevice3", "pcap"]),
        ("pymobile_developer", ["pymobiledevice3", "developer"]),
        ("pymobile_usbmux", ["pymobiledevice3", "usbmux"]),
        ("pymobile_crash", ["pymobiledevice3", "crash"]),
        ("pymobile_afc", ["pymobiledevice3", "afc"]),
        ("pymobile_syslog", ["pymobiledevice3", "syslog"]),
        ("pymobile_mounter", ["pymobiledevice3", "mounter"]),
        ("pymobile_backup2", ["pymobiledevice3", "backup2"]),
        ("pymobile_lockdown", ["pymobiledevice3", "lockdown"]),
    ]

    for name, cmd in surface_commands:
        probes.append(probe_command_surface(name, cmd))

    return probes


def build_capability_matrix(probes: List[Dict[str, Any]]) -> Dict[str, Any]:
    matrix: Dict[str, Any] = {
        "reachable_surfaces": [],
        "unreachable_surfaces": [],
        "artifacts": [],
        "counts": {
            "reachable": 0,
            "unreachable": 0,
        },
    }

    for probe in probes:
        surface = probe.get("surface", "unknown")
        available = bool(probe.get("available"))
        artifact = probe.get("artifact", "")

        entry = {
            "surface": surface,
            "available": available,
        }

        if available:
            matrix["reachable_surfaces"].append(entry)
            matrix["counts"]["reachable"] += 1
        else:
            matrix["unreachable_surfaces"].append(entry)
            matrix["counts"]["unreachable"] += 1

        if artifact:
            matrix["artifacts"].append(artifact)

    return matrix


# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dr. iPhone — developer surface capability mapper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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

    probes = run_all_probes(outdir, udid)
    capability_matrix = build_capability_matrix(probes)

    safe_write_json(outdir / "probe_results.json", probes)
    safe_write_json(outdir / "capability_matrix.json", capability_matrix)

    notes = [
        "This script maps surfaces; it does not assume they are functional in full depth.",
        "A surface marked reachable means the command/help path or artifact test responded.",
        "A later version can add controlled opt-in probes for location simulation or app launch testing.",
        "Default behavior remains read-only and report-first.",
    ]
    safe_write_text(outdir / "notes.txt", "\n".join(notes) + "\n")

    summary = {
        "timestamp": now_iso(),
        "script": SCRIPT_NAME,
        "app": APP_NAME,
        "stage": STAGE_NAME,
        "tools": tools,
        "device": {
            "DeviceName": device_info.get("DeviceName", ""),
            "ProductType": device_info.get("ProductType", ""),
            "ProductVersion": device_info.get("ProductVersion", ""),
            "BuildVersion": device_info.get("BuildVersion", ""),
            "UniqueDeviceID": device_info.get("UniqueDeviceID", ""),
        },
        "capability_matrix": capability_matrix,
    }

    safe_write_json(outdir / "summary.json", summary)

    log(f"Reachable surfaces: {capability_matrix['counts']['reachable']}")
    log(f"Unreachable surfaces: {capability_matrix['counts']['unreachable']}")
    log(f"Artifacts written to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   iphone_dev_surface.py
#
# Make executable:
#   chmod +x iphone_dev_surface.py
#
# Basic run:
#   ./iphone_dev_surface.py
#
# Custom artifact base:
#   ./iphone_dev_surface.py --output-dir ./artifacts
#
# Notes:
#   - Plug in and unlock the iPhone first.
#   - Tap "Trust" if prompted.
#   - This version is read-only by default.
#   - It probes command/help surfaces and screenshot capability.
#   - It does not attempt location simulation or app launching.
#
# Signature:
#   Dr. iPhone — Developer Surface Capability Map
# ============================================================================
