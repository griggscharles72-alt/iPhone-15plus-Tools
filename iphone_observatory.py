#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_observatory.py

Project:
    Dr. iPhone

Stage:
    11 — Observatory

Purpose
-------

Run a safe observability pass across the Dr. iPhone stack, then correlate
the newest available artifacts into one combined observatory report.

This script is the first real "system-level" orchestrator in the repo.

It does NOT replace the earlier scripts.
It calls selected safe scripts, then reads and correlates their outputs.

Responsibilities
----------------

    • run a safe observability bundle
    • collect newest artifacts from prior stages
    • summarize device identity
    • summarize signal activity
    • summarize app inventory deltas
    • summarize crash/syslog evidence
    • summarize pcap evidence
    • summarize notification evidence
    • summarize developer-surface reachability
    • write one combined observatory report

Safe default bundle
-------------------

    • dr_iphone.py
    • iphone_app_inventory.py
    • iphone_crash_and_syslog_lab.py
    • iphone_dev_surface.py
    • iphone_state_db.py

Optional bundle members
-----------------------

    • iphone_pcap_lab.py
    • iphone_notify_console.py

Design
------

    • Safe by default
    • Read-only oriented
    • Best-effort execution
    • Continue on failure
    • Repo-friendly
    • Artifact-driven

Outputs
-------

Creates timestamped artifacts:

    artifacts/iphone_observatory/<timestamp>/

Files:

    observatory_summary.json
    observatory_report.txt
    child_runs.json
    notes.txt

Safety notes
------------

    • No trust modification
    • No restore / reboot / shutdown
    • No writes to device
    • Optional runtime-sensitive layers are opt-in

Author:
    OpenAI / SABLE workflow support
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# CONFIG
# ============================================================================

SCRIPT_NAME = "iphone_observatory.py"
APP_NAME = "Dr. iPhone"
STAGE_NAME = "11 — Observatory"

SAFE_BUNDLE = [
    ("doctor", "dr_iphone.py"),
    ("apps", "iphone_app_inventory.py"),
    ("crash", "iphone_crash_and_syslog_lab.py"),
    ("devsurf", "iphone_dev_surface.py"),
    ("state", "iphone_state_db.py"),
]

OPTIONAL_BUNDLE = [
    ("pcap", "iphone_pcap_lab.py"),
    ("notify", "iphone_notify_console.py"),
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
        base = script_root() / "artifacts" / "iphone_observatory"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = base / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def safe_write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def safe_write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def latest_timestamp_dirs(base: Path) -> List[Path]:
    if not base.exists() or not base.is_dir():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir()]
    return sorted(dirs, key=lambda p: p.name, reverse=True)


def newest_run_dir(base: Path) -> Optional[Path]:
    dirs = latest_timestamp_dirs(base)
    return dirs[0] if dirs else None


def find_latest_artifact_file(root: Path, artifact_subdir: str, filename: str) -> Optional[Path]:
    base = root / "artifacts" / artifact_subdir
    latest = newest_run_dir(base)
    if not latest:
        return None
    candidate = latest / filename
    return candidate if candidate.exists() else None


def detect_device_udid() -> Optional[str]:
    idevice_id = shutil.which("idevice_id")
    if not idevice_id:
        return None
    try:
        proc = subprocess.run(
            [idevice_id, "-l"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                return line
        return None
    except Exception:
        return None


def run_child_script(root: Path, filename: str, extra_args: Optional[List[str]] = None, timeout: int = 600) -> Dict[str, Any]:
    extra_args = extra_args or []
    path = root / filename

    if not path.exists():
        return {
            "ok": False,
            "filename": filename,
            "error": "script not found",
        }

    cmd = [sys.executable, str(path)] + extra_args
    started = time.time()

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "filename": filename,
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "filename": filename,
            "cmd": cmd,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": f"TIMEOUT after {timeout}s",
            "duration_s": round(time.time() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "filename": filename,
            "cmd": cmd,
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.time() - started, 3),
        }



# ============================================================================
# CORRELATION
# ============================================================================

def load_doctor(root: Path) -> Dict[str, Any]:
    path = find_latest_artifact_file(root, "dr_iphone", "dr_iphone_report.json")
    if not path:
        return {"present": False}
    data = read_json(path)
    devices = data.get("devices", [])
    first = devices[0] if devices else {}
    return {
        "present": True,
        "path": str(path),
        "device_count": len(devices),
        "first_device": {
            "udid": first.get("udid", ""),
            "name": first.get("selected_info", {}).get("DeviceName", ""),
            "product_type": first.get("selected_info", {}).get("ProductType", ""),
            "ios_version": first.get("selected_info", {}).get("ProductVersion", ""),
            "build_version": first.get("selected_info", {}).get("BuildVersion", ""),
            "battery_capacity": first.get("battery_info", {}).get("BatteryCurrentCapacity", ""),
        },
    }


def load_apps(root: Path) -> Dict[str, Any]:
    summary_path = find_latest_artifact_file(root, "iphone_app_inventory", "summary.json")
    added_path = find_latest_artifact_file(root, "iphone_app_inventory", "apps_added.json")
    removed_path = find_latest_artifact_file(root, "iphone_app_inventory", "apps_removed.json")

    if not summary_path:
        return {"present": False}

    summary = read_json(summary_path)
    added = read_json(added_path) if added_path else []
    removed = read_json(removed_path) if removed_path else []

    return {
        "present": True,
        "path": str(summary_path),
        "apps_total": summary.get("apps_total", 0),
        "apps_added": added,
        "apps_removed": removed,
        "apps_added_count": len(added),
        "apps_removed_count": len(removed),
    }


def load_crash(root: Path) -> Dict[str, Any]:
    path = find_latest_artifact_file(root, "iphone_crash_and_syslog_lab", "summary.json")
    if not path:
        return {"present": False}
    data = read_json(path)
    return {
        "present": True,
        "path": str(path),
        "syslog_lines": data.get("syslog_lines", 0),
        "crash_hits": data.get("crash_hits", 0),
        "apps_detected": data.get("apps_detected", 0),
    }


def load_pcap(root: Path) -> Dict[str, Any]:
    path = find_latest_artifact_file(root, "iphone_pcap_lab", "summary.json")
    if not path:
        return {"present": False}
    data = read_json(path)
    text_summary = data.get("text_summary", {})
    return {
        "present": True,
        "path": str(path),
        "line_count": text_summary.get("line_count", 0),
        "dns_candidates": len(text_summary.get("dns_candidates", [])),
        "endpoint_candidates": len(text_summary.get("endpoint_candidates", [])),
        "protocol_candidates": len(text_summary.get("protocol_candidates", [])),
    }


def load_notify(root: Path) -> Dict[str, Any]:
    path = find_latest_artifact_file(root, "iphone_notify_console", "summary.json")
    if not path:
        return {"present": False}
    data = read_json(path)
    event_summary = data.get("event_summary", {})
    return {
        "present": True,
        "path": str(path),
        "event_count": event_summary.get("event_count", 0),
        "keyword_count": len(event_summary.get("keyword_counts", {})),
        "bundle_count": len(event_summary.get("bundle_counts", {})),
    }


def load_devsurf(root: Path) -> Dict[str, Any]:
    path = find_latest_artifact_file(root, "iphone_dev_surface", "summary.json")
    if not path:
        return {"present": False}
    data = read_json(path)
    matrix = data.get("capability_matrix", {})
    counts = matrix.get("counts", {})
    return {
        "present": True,
        "path": str(path),
        "reachable_surfaces": counts.get("reachable", 0),
        "unreachable_surfaces": counts.get("unreachable", 0),
    }


def load_state(root: Path) -> Dict[str, Any]:
    path = find_latest_artifact_file(root, "iphone_state_db", "import_summary.json")
    if not path:
        return {"present": False}
    data = read_json(path)
    return {
        "present": True,
        "path": str(path),
        "imports": data.get("imports", {}),
    }


def build_observatory_summary(root: Path, child_runs: List[Dict[str, Any]], run_plan: List[tuple[str, str]]) -> Dict[str, Any]:
    doctor = load_doctor(root)
    apps = load_apps(root)
    crash = load_crash(root)
    pcap = load_pcap(root)
    notify = load_notify(root)
    devsurf = load_devsurf(root)
    state = load_state(root)

    anomaly_flags: List[str] = []
    warnings: List[str] = []
    child_failures = [r for r in child_runs if not r.get("ok")]

    if crash.get("present") and crash.get("crash_hits", 0) > 0:
        anomaly_flags.append(f"crash_hits={crash['crash_hits']}")

    if apps.get("present") and apps.get("apps_added_count", 0) > 0:
        anomaly_flags.append(f"apps_added={apps['apps_added_count']}")

    if apps.get("present") and apps.get("apps_removed_count", 0) > 0:
        anomaly_flags.append(f"apps_removed={apps['apps_removed_count']}")

    if pcap.get("present") and pcap.get("endpoint_candidates", 0) > 0:
        anomaly_flags.append(f"pcap_endpoints={pcap['endpoint_candidates']}")
    elif pcap.get("present") and pcap.get("line_count", 0) == 0:
        warnings.append("pcap_present_but_no_packets")

    if notify.get("present") and notify.get("event_count", 0) > 0:
        anomaly_flags.append(f"notify_events={notify['event_count']}")
    elif notify.get("present") and notify.get("event_count", 0) == 0:
        warnings.append("notify_present_but_no_events")

    if devsurf.get("present") and devsurf.get("unreachable_surfaces", 0) > 0:
        warnings.append(f"devsurf_unreachable={devsurf['unreachable_surfaces']}")

    if child_failures:
        anomaly_flags.append(f"child_failures={len(child_failures)}")

    observatory_score = {
        "has_doctor": int(bool(doctor.get("present"))),
        "has_apps": int(bool(apps.get("present"))),
        "has_crash": int(bool(crash.get("present"))),
        "has_pcap": int(bool(pcap.get("present"))),
        "has_notify": int(bool(notify.get("present"))),
        "has_devsurf": int(bool(devsurf.get("present"))),
        "has_state": int(bool(state.get("present"))),
    }

    score_total = sum(observatory_score.values())

    return {
        "timestamp": now_iso(),
        "script": SCRIPT_NAME,
        "app": APP_NAME,
        "stage": STAGE_NAME,
        "device_udid_detected": detect_device_udid() or "",
        "run_plan": [{"key": key, "filename": filename} for key, filename in run_plan],
        "doctor": doctor,
        "apps": apps,
        "crash": crash,
        "pcap": pcap,
        "notify": notify,
        "devsurf": devsurf,
        "state": state,
        "artifact_paths": {
            "doctor": doctor.get("path", ""),
            "apps": apps.get("path", ""),
            "crash": crash.get("path", ""),
            "pcap": pcap.get("path", ""),
            "notify": notify.get("path", ""),
            "devsurf": devsurf.get("path", ""),
            "state": state.get("path", ""),
        },
        "child_runs": {
            "count": len(child_runs),
            "failures": len(child_failures),
            "details": [
                {
                    "key": r.get("key", ""),
                    "filename": r.get("filename", ""),
                    "ok": bool(r.get("ok")),
                    "returncode": r.get("returncode"),
                    "duration_s": r.get("duration_s", 0),
                }
                for r in child_runs
            ],
        },
        "anomaly_flags": anomaly_flags,
        "warnings": warnings,
        "observatory_score": observatory_score,
        "observatory_score_total": score_total,
    }


def render_observatory_report(summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"{APP_NAME} — Observatory")
    lines.append("=" * 72)
    lines.append(f"Timestamp: {summary.get('timestamp')}")
    lines.append(f"Device UDID detected: {summary.get('device_udid_detected') or '<none>'}")
    lines.append("")

    lines.append("Run plan")
    lines.append("-" * 72)
    for item in summary.get("run_plan", []):
        lines.append(f"{item.get('key',''):8} {item.get('filename','')}")
    lines.append("")

    lines.append("Child run results")
    lines.append("-" * 72)
    for item in summary.get("child_runs", {}).get("details", []):
        status = "OK" if item.get("ok") else "FAIL"
        lines.append(f"{status:4} {item.get('key',''):8} rc={item.get('returncode')} t={item.get('duration_s')}")
    lines.append("")

    doctor = summary.get("doctor", {})
    lines.append("Doctor")
    lines.append("-" * 72)
    if doctor.get("present"):
        first = doctor.get("first_device", {})
        lines.append(f"name:             {first.get('name','')}")
        lines.append(f"product_type:     {first.get('product_type','')}")
        lines.append(f"ios_version:      {first.get('ios_version','')}")
        lines.append(f"build_version:    {first.get('build_version','')}")
        lines.append(f"battery_capacity: {first.get('battery_capacity','')}")
        lines.append(f"artifact:         {doctor.get('path','')}")
    else:
        lines.append("not present")
    lines.append("")

    apps = summary.get("apps", {})
    lines.append("App inventory")
    lines.append("-" * 72)
    if apps.get("present"):
        lines.append(f"apps_total:       {apps.get('apps_total',0)}")
        lines.append(f"apps_added:       {apps.get('apps_added_count',0)}")
        lines.append(f"apps_removed:     {apps.get('apps_removed_count',0)}")
        lines.append(f"artifact:         {apps.get('path','')}")
    else:
        lines.append("not present")
    lines.append("")

    crash = summary.get("crash", {})
    lines.append("Crash / syslog")
    lines.append("-" * 72)
    if crash.get("present"):
        lines.append(f"syslog_lines:     {crash.get('syslog_lines',0)}")
        lines.append(f"crash_hits:       {crash.get('crash_hits',0)}")
        lines.append(f"apps_detected:    {crash.get('apps_detected',0)}")
        lines.append(f"artifact:         {crash.get('path','')}")
    else:
        lines.append("not present")
    lines.append("")

    pcap = summary.get("pcap", {})
    lines.append("PCAP")
    lines.append("-" * 72)
    if pcap.get("present"):
        lines.append(f"line_count:       {pcap.get('line_count',0)}")
        lines.append(f"dns_candidates:   {pcap.get('dns_candidates',0)}")
        lines.append(f"endpoints:        {pcap.get('endpoint_candidates',0)}")
        lines.append(f"protocols:        {pcap.get('protocol_candidates',0)}")
        lines.append(f"artifact:         {pcap.get('path','')}")
    else:
        lines.append("not present")
    lines.append("")

    notify = summary.get("notify", {})
    lines.append("Notify")
    lines.append("-" * 72)
    if notify.get("present"):
        lines.append(f"event_count:      {notify.get('event_count',0)}")
        lines.append(f"keyword_count:    {notify.get('keyword_count',0)}")
        lines.append(f"bundle_count:     {notify.get('bundle_count',0)}")
        lines.append(f"artifact:         {notify.get('path','')}")
    else:
        lines.append("not present")
    lines.append("")

    devsurf = summary.get("devsurf", {})
    lines.append("Developer surface")
    lines.append("-" * 72)
    if devsurf.get("present"):
        lines.append(f"reachable:        {devsurf.get('reachable_surfaces',0)}")
        lines.append(f"unreachable:      {devsurf.get('unreachable_surfaces',0)}")
        lines.append(f"artifact:         {devsurf.get('path','')}")
    else:
        lines.append("not present")
    lines.append("")

    state = summary.get("state", {})
    lines.append("State DB import")
    lines.append("-" * 72)
    if state.get("present"):
        lines.append(f"artifact:         {state.get('path','')}")
        imports = state.get("imports", {})
        for key in sorted(imports):
            lines.append(f"{key:18} {imports[key]}")
    else:
        lines.append("not present")
    lines.append("")

    lines.append("Anomaly flags")
    lines.append("-" * 72)
    flags = summary.get("anomaly_flags", [])
    if flags:
        for flag in flags:
            lines.append(flag)
    else:
        lines.append("none")
    lines.append("")

    lines.append("Warnings")
    lines.append("-" * 72)
    warns = summary.get("warnings", [])
    if warns:
        for w in warns:
            lines.append(w)
    else:
        lines.append("none")
    lines.append("")

    lines.append("Observatory score")
    lines.append("-" * 72)
    for key, value in summary.get("observatory_score", {}).items():
        lines.append(f"{key:15} {value}")
    lines.append(f"{'score_total':15} {summary.get('observatory_score_total', 0)}")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ============================================================================
# MAIN

# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dr. iPhone — observatory orchestrator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--include-pcap",
        action="store_true",
        help="Include iphone_pcap_lab.py in the observability run",
    )
    parser.add_argument(
        "--include-notify",
        action="store_true",
        help="Include iphone_notify_console.py in the observability run",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Base output directory. Timestamped subdirectory is created inside it.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = script_root()
    outdir = make_output_dir(args.output_dir or None)

    log(f"{APP_NAME} {STAGE_NAME} start")
    log(f"Output directory: {outdir}")

    run_plan = list(SAFE_BUNDLE)
    if args.include_pcap:
        run_plan.append(OPTIONAL_BUNDLE[0])
    if args.include_notify:
        run_plan.append(OPTIONAL_BUNDLE[1])

    child_runs: List[Dict[str, Any]] = []

    for key, filename in run_plan:
        log(f"Running: {filename}")
        result = run_child_script(root, filename)
        result["key"] = key
        child_runs.append(result)

    summary = build_observatory_summary(root, child_runs, run_plan)
    report_text = render_observatory_report(summary)

    notes = [
        "This script runs a safe observability bundle and correlates the newest artifacts.",
        "Optional runtime-sensitive layers like pcap and notify are opt-in.",
        "A future version can add historical comparisons using the SQLite state DB.",
    ]

    safe_write_json(outdir / "observatory_summary.json", summary)
    safe_write_json(outdir / "child_runs.json", child_runs)
    safe_write_text(outdir / "observatory_report.txt", report_text)
    safe_write_text(outdir / "notes.txt", "\n".join(notes) + "\n")

    print()
    print(report_text)
    log(f"Artifacts written to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   iphone_observatory.py
#
# Make executable:
#   chmod +x iphone_observatory.py
#
# Basic safe observatory run:
#   ./iphone_observatory.py
#
# Include PCAP:
#   ./iphone_observatory.py --include-pcap
#
# Include notify:
#   ./iphone_observatory.py --include-notify
#
# Include both:
#   ./iphone_observatory.py --include-pcap --include-notify
#
# Notes:
#   - Plug in and unlock the iPhone first.
#   - Tap "Trust" if prompted.
#   - This script orchestrates the stack and correlates the newest artifacts.
#   - It is read-only oriented and best-effort.
#
# Signature:
#   Dr. iPhone — Observatory
# ============================================================================
