#!/usr/bin/env python3
"""
README
======

Filename:
    dr_iphone.py

Project:
    Dr. iPhone

Purpose:
    Safe, read-only iPhone diagnostics from Linux using a Python-first
    orchestration model with helper tools.

Primary helper stack:
    1. python3
    2. libimobiledevice
    3. usbmuxd
    4. ifuse
    5. pymobiledevice3

Design goals:
    - Safe by default
    - Read-only by default
    - Auditable
    - Best-effort execution
    - Location independent
    - Repo friendly
    - Continue-on-failure behavior

Default behavior:
    - Checks tool availability and versions
    - Checks usbmuxd state/socket
    - Detects connected iPhone/iPad devices
    - Validates trust/pairing when possible
    - Pulls core device info using ideviceinfo
    - Pulls battery diagnostics using idevicediagnostics
    - Writes JSON + text summary report

Optional behavior:
    --syslog-seconds N   Capture a short syslog sample
    --ifuse-list-apps    List file-sharing-enabled apps via ifuse
    --pymobile-apps      List installed apps via pymobiledevice3
    --pymobile-usbmux    List devices via pymobiledevice3 usbmux

Safety notes:
    - No restore, reboot, shutdown, or write actions are performed
    - No backup is performed
    - No mount is performed by default
    - No jailbreak assumptions
    - Report-only unless you later extend it

Tested style:
    Intended to run directly from VS Code or terminal on Linux.

Author:
    OpenAI / SABLE workflow support
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================================
# CONFIG
# ============================================================================

SCRIPT_NAME = "dr_iphone.py"
APP_NAME = "Dr. iPhone"
DEFAULT_SYSLOG_SECONDS = 5


# ============================================================================
# HELPERS
# ============================================================================

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def script_root() -> Path:
    return Path(__file__).resolve().parent


def make_output_dir(custom_dir: Optional[str] = None) -> Path:
    if custom_dir:
        base = Path(custom_dir).expanduser().resolve()
    else:
        base = script_root() / "artifacts" / "dr_iphone"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = base / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def command_exists(cmd: str) -> bool:
    return which(cmd) is not None


def run_cmd(
    cmd: List[str],
    timeout: int = 30,
    allow_fail: bool = True,
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
            "stdout": proc.stdout if text else None,
            "stderr": proc.stderr if text else None,
            "duration_s": round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "cmd": cmd,
            "stdout": exc.stdout if text else None,
            "stderr": f"TIMEOUT after {timeout}s",
            "duration_s": round(time.time() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": None,
            "cmd": cmd,
            "stdout": None,
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.time() - started, 3),
        }


def shell_line(cmd: List[str]) -> str:
    return " ".join(subprocess.list2cmdline([part]) if " " in part else part for part in cmd)


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.strip()


def parse_key_value_lines(text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        result[k.strip()] = v.strip()
    return result


def safe_write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def safe_write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def first_nonempty(*values: Optional[str]) -> str:
    for v in values:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def parse_udids_from_idevice_id(output: str) -> List[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


def extract_selected_info(info: Dict[str, str]) -> Dict[str, str]:
    wanted = [
        "DeviceName",
        "ProductType",
        "ProductVersion",
        "BuildVersion",
        "CPUArchitecture",
        "UniqueDeviceID",
        "UniqueChipID",
        "SerialNumber",
        "WiFiAddress",
        "BluetoothAddress",
        "PhoneNumber",
        "InternationalMobileEquipmentIdentity",
        "MobileEquipmentIdentifier",
        "ModelNumber",
        "TimeZone",
        "RegionInfo",
        "Language",
        "TotalDiskCapacity",
        "TotalDataCapacity",
        "TotalDataAvailable",
        "BatteryCurrentCapacity",
    ]
    return {k: info[k] for k in wanted if k in info}


def parse_battery_info(text: str) -> Dict[str, str]:
    return parse_key_value_lines(text)


def command_version(cmd: str, version_args: Optional[List[str]] = None) -> Dict[str, Any]:
    args = version_args or ["--version"]
    if not command_exists(cmd):
        return {"present": False, "version": None}
    result = run_cmd([cmd] + args, timeout=15)
    version_text = clean_text(first_nonempty(result.get("stdout"), result.get("stderr")))
    version_line = version_text.splitlines()[0] if version_text else ""
    return {"present": True, "version": version_line, "raw": result}


def python_module_version(module_name: str) -> Dict[str, Any]:
    cmd = [sys.executable, "-c", f"import importlib.metadata as m; print(m.version('{module_name}'))"]
    result = run_cmd(cmd, timeout=15)
    return {
        "present": result["ok"],
        "version": clean_text(result.get("stdout")),
        "raw": result,
    }


def get_systemctl_status(unit: str) -> Dict[str, Any]:
    if not command_exists("systemctl"):
        return {"present": False, "active": None, "enabled": None}
    active = run_cmd(["systemctl", "is-active", unit], timeout=10)
    enabled = run_cmd(["systemctl", "is-enabled", unit], timeout=10)
    return {
        "present": True,
        "active": clean_text(active.get("stdout") or active.get("stderr")),
        "enabled": clean_text(enabled.get("stdout") or enabled.get("stderr")),
        "raw": {"active": active, "enabled": enabled},
    }


def collect_short_syslog(seconds: int, udid: Optional[str] = None) -> Dict[str, Any]:
    if not command_exists("idevicesyslog"):
        return {"ok": False, "reason": "idevicesyslog not found"}

    cmd = ["idevicesyslog"]
    if udid:
        cmd += ["-u", udid]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(max(1, seconds))
        proc.terminate()
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        lines = stdout.splitlines()[:400]
        return {
            "ok": True,
            "cmd": cmd,
            "captured_lines": len(lines),
            "sample": lines,
            "stderr": clean_text(stderr),
        }
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


# ============================================================================
# DIAGNOSTIC BLOCKS
# ============================================================================

def block_environment() -> Dict[str, Any]:
    return {
        "timestamp": now_iso(),
        "script": SCRIPT_NAME,
        "app": APP_NAME,
        "cwd": str(Path.cwd()),
        "script_root": str(script_root()),
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "user": os.environ.get("USER", ""),
    }


def block_tool_inventory() -> Dict[str, Any]:
    tools: Dict[str, Any] = {}

    tools["python3"] = {
        "present": command_exists("python3"),
        "which": which("python3"),
        "version": platform.python_version(),
    }

    tools["idevice_id"] = {
        "present": command_exists("idevice_id"),
        "which": which("idevice_id"),
        "version_check": command_version("idevice_id"),
    }

    tools["ideviceinfo"] = {
        "present": command_exists("ideviceinfo"),
        "which": which("ideviceinfo"),
        "version_check": command_version("ideviceinfo"),
    }

    tools["idevicepair"] = {
        "present": command_exists("idevicepair"),
        "which": which("idevicepair"),
        "version_check": command_version("idevicepair"),
    }

    tools["idevicediagnostics"] = {
        "present": command_exists("idevicediagnostics"),
        "which": which("idevicediagnostics"),
        "version_check": command_version("idevicediagnostics"),
    }

    tools["idevicesyslog"] = {
        "present": command_exists("idevicesyslog"),
        "which": which("idevicesyslog"),
        "version_check": command_version("idevicesyslog"),
    }

    tools["ifuse"] = {
        "present": command_exists("ifuse"),
        "which": which("ifuse"),
        "version_check": command_version("ifuse"),
    }

    tools["usbmuxd"] = {
        "present": command_exists("usbmuxd"),
        "which": which("usbmuxd"),
        "version_check": command_version("usbmuxd"),
    }

    tools["pymobiledevice3_cli"] = {
        "present": command_exists("pymobiledevice3"),
        "which": which("pymobiledevice3"),
        "version_check": run_cmd(["pymobiledevice3", "version"], timeout=15)
        if command_exists("pymobiledevice3") else {"ok": False}
    }

    tools["pymobiledevice3_module"] = python_module_version("pymobiledevice3")

    return tools


def block_usbmuxd() -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "socket_exists": Path("/var/run/usbmuxd").exists() or Path("/run/usbmuxd").exists(),
        "socket_path_candidates": ["/var/run/usbmuxd", "/run/usbmuxd"],
        "systemctl": {},
        "ps_grep": {},
    }

    data["systemctl"] = get_systemctl_status("usbmuxd.service")

    if command_exists("pgrep"):
        data["ps_grep"] = run_cmd(["pgrep", "-a", "usbmuxd"], timeout=10)
    else:
        data["ps_grep"] = {"ok": False, "reason": "pgrep not found"}

    return data


def block_device_discovery() -> Dict[str, Any]:
    data: Dict[str, Any] = {}

    if command_exists("idevice_id"):
        res = run_cmd(["idevice_id", "-l"], timeout=15)
        data["idevice_id"] = res
        data["udids"] = parse_udids_from_idevice_id(clean_text(res.get("stdout", ""))) if res["ok"] else []
    else:
        data["idevice_id"] = {"ok": False, "reason": "idevice_id not found"}
        data["udids"] = []

    if command_exists("pymobiledevice3"):
        data["pymobiledevice3_usbmux_list"] = run_cmd(["pymobiledevice3", "usbmux", "list"], timeout=20)
    else:
        data["pymobiledevice3_usbmux_list"] = {"ok": False, "reason": "pymobiledevice3 not found"}

    return data


def block_pairing_for_udid(udid: str) -> Dict[str, Any]:
    if not command_exists("idevicepair"):
        return {"ok": False, "reason": "idevicepair not found"}
    return run_cmd(["idevicepair", "-u", udid, "validate"], timeout=20)


def block_info_for_udid(udid: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "udid": udid,
        "pair_validate": block_pairing_for_udid(udid),
        "device_info": {},
        "selected_info": {},
        "battery_info": {},
        "storage_snapshot": {},
        "name_query": {},
    }

    if command_exists("ideviceinfo"):
        info_res = run_cmd(["ideviceinfo", "-u", udid], timeout=25)
        result["device_info_raw"] = info_res
        if info_res["ok"]:
            parsed = parse_key_value_lines(clean_text(info_res.get("stdout", "")))
            result["device_info"] = parsed
            result["selected_info"] = extract_selected_info(parsed)
            result["storage_snapshot"] = {
                k: parsed.get(k, "")
                for k in ("TotalDiskCapacity", "TotalDataCapacity", "TotalDataAvailable")
                if k in parsed
            }

        name_res = run_cmd(["ideviceinfo", "-u", udid, "-k", "DeviceName"], timeout=15)
        result["name_query"] = name_res
    else:
        result["device_info_raw"] = {"ok": False, "reason": "ideviceinfo not found"}

    if command_exists("idevicediagnostics"):
        batt_res = run_cmd(["idevicediagnostics", "-u", udid, "battery"], timeout=20)
        result["battery_raw"] = batt_res
        if batt_res["ok"]:
            result["battery_info"] = parse_battery_info(clean_text(batt_res.get("stdout", "")))
    else:
        result["battery_raw"] = {"ok": False, "reason": "idevicediagnostics not found"}

    return result


def block_ifuse_list_apps(udid: Optional[str]) -> Dict[str, Any]:
    if not command_exists("ifuse"):
        return {"ok": False, "reason": "ifuse not found"}

    cmd = ["ifuse", "--list-apps"]
    if udid:
        cmd += ["--udid", udid]

    return run_cmd(cmd, timeout=25)


def block_pymobile_apps() -> Dict[str, Any]:
    if not command_exists("pymobiledevice3"):
        return {"ok": False, "reason": "pymobiledevice3 not found"}
    return run_cmd(["pymobiledevice3", "apps", "list"], timeout=40)


def summarize(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"{APP_NAME} summary")
    lines.append("=" * 72)
    lines.append(f"Timestamp: {report['environment']['timestamp']}")
    lines.append(f"Host: {report['environment']['platform']}")
    lines.append("")

    lines.append("Tool inventory")
    lines.append("-" * 72)
    for name, item in report["tools"].items():
        present = item.get("present", False)
        which_path = item.get("which", "")
        version = ""
        if name == "python3":
            version = item.get("version", "")
        elif name == "pymobiledevice3_module":
            version = item.get("version", "")
        else:
            raw_ver = item.get("version_check", {})
            version = clean_text(raw_ver.get("stdout", "") or raw_ver.get("stderr", ""))
            if "\n" in version:
                version = version.splitlines()[0]
        lines.append(f"[{'OK' if present else 'MISS'}] {name:22} {which_path} {version}".rstrip())
    lines.append("")

    usbmuxd = report.get("usbmuxd", {})
    lines.append("usbmuxd")
    lines.append("-" * 72)
    lines.append(f"Socket exists: {usbmuxd.get('socket_exists')}")
    sysctl = usbmuxd.get("systemctl", {})
    lines.append(f"systemctl active:  {sysctl.get('active')}")
    lines.append(f"systemctl enabled: {sysctl.get('enabled')}")
    pgrep = usbmuxd.get("ps_grep", {})
    if pgrep.get("ok"):
        lines.append("Process:")
        lines.extend([f"  {line}" for line in clean_text(pgrep.get("stdout", "")).splitlines() if line.strip()])
    lines.append("")

    discovery = report.get("discovery", {})
    udids = discovery.get("udids", [])
    lines.append("Device discovery")
    lines.append("-" * 72)
    lines.append(f"UDIDs found: {len(udids)}")
    for udid in udids:
        lines.append(f"  - {udid}")
    lines.append("")

    devices = report.get("devices", [])
    for idx, dev in enumerate(devices, start=1):
        selected = dev.get("selected_info", {})
        pair = dev.get("pair_validate", {})
        battery = dev.get("battery_info", {})

        name = first_nonempty(
            selected.get("DeviceName"),
            clean_text(dev.get("name_query", {}).get("stdout")),
            dev.get("udid"),
        )

        lines.append(f"Device {idx}")
        lines.append("-" * 72)
        lines.append(f"Name:          {name}")
        lines.append(f"UDID:          {dev.get('udid')}")
        lines.append(f"ProductType:   {selected.get('ProductType', '')}")
        lines.append(f"iOS Version:   {selected.get('ProductVersion', '')}")
        lines.append(f"BuildVersion:  {selected.get('BuildVersion', '')}")
        lines.append(f"Pair validate: {'OK' if pair.get('ok') else 'FAIL'}")
        if pair.get("stdout"):
            lines.append(f"Pair output:   {clean_text(pair.get('stdout'))}")
        elif pair.get("stderr"):
            lines.append(f"Pair output:   {clean_text(pair.get('stderr'))}")

        if battery:
            for key in ("BatteryCurrentCapacity", "BatteryIsCharging", "ExternalChargeCapable", "ExternalConnected", "FullyCharged"):
                if key in battery:
                    lines.append(f"{key:14}: {battery[key]}")
        storage = dev.get("storage_snapshot", {})
        for key, value in storage.items():
            lines.append(f"{key:14}: {value}")
        lines.append("")

    ifuse_apps = report.get("ifuse_list_apps")
    if ifuse_apps:
        lines.append("ifuse --list-apps")
        lines.append("-" * 72)
        if ifuse_apps.get("ok"):
            out = clean_text(ifuse_apps.get("stdout", ""))
            lines.extend(out.splitlines()[:80] if out else ["<no output>"])
        else:
            lines.append(clean_text(ifuse_apps.get("stderr", "")) or "not run / failed")
        lines.append("")

    pymobile_apps = report.get("pymobile_apps")
    if pymobile_apps:
        lines.append("pymobiledevice3 apps list")
        lines.append("-" * 72)
        if pymobile_apps.get("ok"):
            out = clean_text(pymobile_apps.get("stdout", ""))
            preview = out.splitlines()[:120] if out else ["<no output>"]
            lines.extend(preview)
        else:
            lines.append(clean_text(pymobile_apps.get("stderr", "")) or "not run / failed")
        lines.append("")

    syslog = report.get("syslog_sample")
    if syslog:
        lines.append("Short syslog sample")
        lines.append("-" * 72)
        if syslog.get("ok"):
            lines.extend(syslog.get("sample", [])[:80])
        else:
            lines.append(syslog.get("reason", "not run / failed"))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - safe, read-only iPhone diagnostics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Base output directory. Timestamped subdirectory is created inside it.",
    )
    parser.add_argument(
        "--syslog-seconds",
        type=int,
        default=0,
        help="Capture a short idevicesyslog sample for N seconds. 0 disables.",
    )
    parser.add_argument(
        "--ifuse-list-apps",
        action="store_true",
        help="Run ifuse --list-apps for file-sharing-enabled apps.",
    )
    parser.add_argument(
        "--pymobile-apps",
        action="store_true",
        help="Run pymobiledevice3 apps list.",
    )
    parser.add_argument(
        "--pymobile-usbmux",
        action="store_true",
        help="Keep/use pymobiledevice3 usbmux list output in the report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    outdir = make_output_dir(args.output_dir or None)

    log(f"{APP_NAME} start")
    log(f"Output directory: {outdir}")

    report: Dict[str, Any] = {
        "environment": {},
        "tools": {},
        "usbmuxd": {},
        "discovery": {},
        "devices": [],
        "ifuse_list_apps": None,
        "pymobile_apps": None,
        "syslog_sample": None,
    }

    # Environment
    try:
        log("[1] environment")
        report["environment"] = block_environment()
    except Exception as exc:
        report["environment"] = {"error": f"{type(exc).__name__}: {exc}"}

    # Tool inventory
    try:
        log("[2] tool inventory")
        report["tools"] = block_tool_inventory()
    except Exception as exc:
        report["tools"] = {"error": f"{type(exc).__name__}: {exc}"}

    # usbmuxd
    try:
        log("[3] usbmuxd state")
        report["usbmuxd"] = block_usbmuxd()
    except Exception as exc:
        report["usbmuxd"] = {"error": f"{type(exc).__name__}: {exc}"}

    # Discovery
    try:
        log("[4] device discovery")
        report["discovery"] = block_device_discovery()
    except Exception as exc:
        report["discovery"] = {"error": f"{type(exc).__name__}: {exc}", "udids": []}

    udids = report.get("discovery", {}).get("udids", []) or []

    # Per-device
    for idx, udid in enumerate(udids, start=1):
        try:
            log(f"[5.{idx}] device block for {udid}")
            report["devices"].append(block_info_for_udid(udid))
        except Exception as exc:
            report["devices"].append({
                "udid": udid,
                "error": f"{type(exc).__name__}: {exc}",
            })

    first_udid = udids[0] if udids else None

    # ifuse app list
    if args.ifuse_list_apps:
        try:
            log("[6] ifuse list apps")
            report["ifuse_list_apps"] = block_ifuse_list_apps(first_udid)
        except Exception as exc:
            report["ifuse_list_apps"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    # pymobiledevice3 apps
    if args.pymobile_apps:
        try:
            log("[7] pymobiledevice3 apps list")
            report["pymobile_apps"] = block_pymobile_apps()
        except Exception as exc:
            report["pymobile_apps"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    # syslog sample
    if args.syslog_seconds and args.syslog_seconds > 0:
        try:
            log(f"[8] short syslog capture ({args.syslog_seconds}s)")
            report["syslog_sample"] = collect_short_syslog(args.syslog_seconds, first_udid)
        except Exception as exc:
            report["syslog_sample"] = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}

    # Write artifacts
    summary_text = summarize(report)
    safe_write_json(outdir / "dr_iphone_report.json", report)
    safe_write_text(outdir / "dr_iphone_summary.txt", summary_text)

    print()
    print(summary_text)
    log("Artifacts written:")
    log(f"  {outdir / 'dr_iphone_report.json'}")
    log(f"  {outdir / 'dr_iphone_summary.txt'}")
    log(f"{APP_NAME} complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   dr_iphone.py
#
# Make executable:
#   chmod +x dr_iphone.py
#
# Basic safe run:
#   ./dr_iphone.py
#
# Run with optional ifuse app listing + short syslog sample:
#   ./dr_iphone.py --ifuse-list-apps --syslog-seconds 5
#
# Run with pymobiledevice3 app list:
#   ./dr_iphone.py --pymobile-apps
#
# Run everything safe/read-only:
#   ./dr_iphone.py --ifuse-list-apps --pymobile-apps --syslog-seconds 5
#
# Notes:
#   - Plug in the iPhone first and unlock it.
#   - Tap "Trust" on the iPhone if prompted.
#   - If no device is found, check cable, trust state, and usbmuxd.
#   - ifuse app listing only reports file-sharing-enabled apps.
#   - syslog capture may include sensitive app/device messages; review locally.
#
# Signature:
#   Dr. iPhone — Python-first iPhone diagnostics for Linux
# ============================================================================
