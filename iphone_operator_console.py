#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_operator_console.py

Project:
    Dr. iPhone

Stage:
    10 — Operator Console

Purpose
-------

Provide a single operator-facing entrypoint for the Dr. iPhone repository.

This script:

    • discovers available Dr. iPhone scripts
    • exposes safe subcommands
    • runs child scripts on demand
    • shows latest artifact status
    • reports state database presence
    • centralizes basic operator workflow

Design
------

    • Safe by default
    • No device modification by default
    • Repo-friendly
    • Best-effort execution
    • Continue on failure
    • Artifact-driven

Managed scripts
---------------

    01 dr_iphone.py
    02 iphone_signal_watch.py
    03 iphone_file_bridge.py
    04 iphone_app_inventory.py
    05 iphone_crash_and_syslog_lab.py
    06 iphone_pcap_lab.py
    07 iphone_notify_console.py
    08 iphone_dev_surface.py
    09 iphone_state_db.py
    11 iphone_observatory.py

Outputs
-------

Creates timestamped operator artifacts:

    artifacts/iphone_operator_console/<timestamp>/

Files:

    summary.json
    child_runs.json
    notes.txt

Safety notes
------------

    • No trust modification
    • No restore / reboot / shutdown
    • Default actions are read-only
    • Child scripts control their own safety boundaries
    • This console only orchestrates them

Author:
    OpenAI / SABLE workflow support
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================================
# CONFIG
# ============================================================================

SCRIPT_NAME = "iphone_operator_console.py"
APP_NAME = "Dr. iPhone"
STAGE_NAME = "10 — Operator Console"

MANAGED_SCRIPTS = [
    ("doctor", "dr_iphone.py"),
    ("watch", "iphone_signal_watch.py"),
    ("bridge", "iphone_file_bridge.py"),
    ("apps", "iphone_app_inventory.py"),
    ("crash", "iphone_crash_and_syslog_lab.py"),
    ("pcap", "iphone_pcap_lab.py"),
    ("notify", "iphone_notify_console.py"),
    ("devsurf", "iphone_dev_surface.py"),
    ("state", "iphone_state_db.py"),
    ("observatory", "iphone_observatory.py"),
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
        base = script_root() / "artifacts" / "iphone_operator_console"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = base / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def safe_write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def safe_write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def latest_timestamp_dirs(base: Path) -> List[Path]:
    if not base.exists() or not base.is_dir():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir()]
    return sorted(
        dirs,
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )


def newest_run_dir(base: Path) -> Optional[Path]:
    dirs = latest_timestamp_dirs(base)
    return dirs[0] if dirs else None


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


# ============================================================================
# STATUS / DISCOVERY
# ============================================================================

def discover_scripts(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key, filename in MANAGED_SCRIPTS:
        path = root / filename
        rows.append({
            "key": key,
            "filename": filename,
            "path": str(path),
            "exists": path.exists(),
            "executable": path.exists() and path.stat().st_mode & 0o111 != 0,
        })
    return rows


def artifact_status(root: Path) -> Dict[str, Any]:
    status: Dict[str, Any] = {}

    for key, filename in MANAGED_SCRIPTS:
        base = root / "artifacts" / filename.replace(".py", "")
        latest = newest_run_dir(base)
        status[key] = {
            "artifact_dir": str(base),
            "latest_run_dir": str(latest) if latest else "",
            "present": latest is not None,
        }

    console_base = root / "artifacts" / "iphone_operator_console"
    latest_console = newest_run_dir(console_base)
    status["console"] = {
        "artifact_dir": str(console_base),
        "latest_run_dir": str(latest_console) if latest_console else "",
        "present": latest_console is not None,
    }

    return status


def db_status(root: Path) -> Dict[str, Any]:
    db_path = root / "state" / "dr_iphone.db"
    result: Dict[str, Any] = {
        "present": db_path.exists(),
        "path": str(db_path),
        "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "table_counts": {},
    }

    if not db_path.exists():
        return result

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        tables = [
            "runs",
            "devices",
            "app_inventory",
            "app_deltas",
            "event_counters",
            "capabilities",
        ]

        for table in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                result["table_counts"][table] = count
            except Exception:
                result["table_counts"][table] = None

        conn.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def render_status_text(
    root: Path,
    scripts: List[Dict[str, Any]],
    artifacts: Dict[str, Any],
    db: Dict[str, Any],
    udid: Optional[str],
) -> str:
    lines: List[str] = []
    lines.append(f"{APP_NAME} — Operator Console")
    lines.append("=" * 72)
    lines.append(f"Timestamp: {now_iso()}")
    lines.append(f"Repo root:  {root}")
    lines.append(f"Device UDID detected: {udid or '<none>'}")
    lines.append("")

    lines.append("Managed scripts")
    lines.append("-" * 72)
    for row in scripts:
        lines.append(
            f"[{'OK' if row['exists'] else 'MISS'}] "
            f"{row['key']:8}  {row['filename']}"
        )
    lines.append("")

    lines.append("Latest artifacts")
    lines.append("-" * 72)
    for key, meta in artifacts.items():
        present = "YES" if meta.get("present") else "NO"
        latest = meta.get("latest_run_dir", "")
        lines.append(f"{key:8} present={present:3} latest={latest}")
    lines.append("")

    lines.append("State DB")
    lines.append("-" * 72)
    lines.append(f"present:    {db.get('present')}")
    lines.append(f"path:       {db.get('path')}")
    lines.append(f"size_bytes: {db.get('size_bytes')}")
    for table, count in db.get("table_counts", {}).items():
        lines.append(f"{table:14} {count}")
    lines.append("")

    lines.append("Common commands")
    lines.append("-" * 72)
    lines.append("./iphone_operator_console.py bench")
    lines.append("./iphone_operator_console.py bench-plus")
    lines.append("./iphone_operator_console.py status")
    lines.append("./iphone_operator_console.py run observatory")
    lines.append("./iphone_operator_console.py run doctor")
    lines.append("./iphone_operator_console.py run apps")
    lines.append("./iphone_operator_console.py run crash")
    lines.append("./iphone_operator_console.py run pcap -- --seconds 10")
    lines.append("./iphone_operator_console.py run-all-safe")
    lines.append("./iphone_operator_console.py db-status")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ============================================================================
# CHILD SCRIPT EXECUTION
# ============================================================================

def resolve_script(root: Path, key: str) -> Optional[Path]:
    for script_key, filename in MANAGED_SCRIPTS:
        if script_key == key:
            path = root / filename
            return path if path.exists() else None
    return None


def run_child_script(
    root: Path,
    key: str,
    extra_args: Optional[List[str]] = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    extra_args = extra_args or []
    path = resolve_script(root, key)

    if not path:
        return {
            "ok": False,
            "key": key,
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
            "key": key,
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": round(time.time() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "key": key,
            "cmd": cmd,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": f"TIMEOUT after {timeout}s",
            "duration_s": round(time.time() - started, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "key": key,
            "cmd": cmd,
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "duration_s": round(time.time() - started, 3),
        }


def run_all_safe(root: Path) -> List[Dict[str, Any]]:
    """
    Conservative safe bundle:
      doctor -> apps -> crash -> devsurf -> state
    Observatory is the preferred daily runner, but this bundle remains useful
    as a lower-level conservative control path.
    Excludes watch/bridge/pcap/notify because those are more runtime-specific.
    """
    ordered_keys = ["doctor", "apps", "crash", "devsurf", "state"]
    results: List[Dict[str, Any]] = []

    for key in ordered_keys:
        log(f"Running child script: {key}")
        result = run_child_script(root, key)
        results.append(result)

    return results


# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dr. iPhone — operator console",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show repo, artifact, and DB status")
    sub.add_parser("db-status", help="Show SQLite state DB status")
    sub.add_parser("list-scripts", help="List managed scripts")
    sub.add_parser("bench", help="Run the primary daily bench pass (observatory)")
    sub.add_parser("bench-plus", help="Run observatory with optional pcap and notify layers")
    sub.add_parser("run-all-safe", help="Run a conservative safe script bundle")

    run_p = sub.add_parser("run", help="Run a managed child script")
    run_p.add_argument("script_key", help="doctor | watch | bridge | apps | crash | pcap | notify | devsurf | state | observatory")
    run_p.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through after --",
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

    scripts = discover_scripts(root)
    artifacts = artifact_status(root)
    db = db_status(root)
    udid = detect_device_udid()

    child_runs: List[Dict[str, Any]] = []

    if args.command == "status":
        text = render_status_text(root, scripts, artifacts, db, udid)
        print()
        print(text)
        safe_write_text(outdir / "status.txt", text)

    elif args.command == "db-status":
        text = json.dumps(db, indent=2, ensure_ascii=False)
        print(text)
        safe_write_text(outdir / "db_status.json", text + "\n")

    elif args.command == "list-scripts":
        text_lines = [
            f"{row['key']:8} {row['filename']} {'OK' if row['exists'] else 'MISS'}"
            for row in scripts
        ]
        text = "\n".join(text_lines) + "\n"
        print(text, end="")
        safe_write_text(outdir / "managed_scripts.txt", text)

    elif args.command == "bench":
        result = run_child_script(root, "observatory")
        child_runs.append(result)

        print(result.get("stdout", ""), end="")
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr, end="")

        safe_write_json(outdir / "child_runs.json", child_runs)

        artifacts = artifact_status(root)
        db = db_status(root)
        udid = detect_device_udid()

    elif args.command == "bench-plus":
        result = run_child_script(
            root,
            "observatory",
            extra_args=["--include-pcap", "--include-notify"],
        )
        child_runs.append(result)

        print(result.get("stdout", ""), end="")
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr, end="")

        safe_write_json(outdir / "child_runs.json", child_runs)

        artifacts = artifact_status(root)
        db = db_status(root)
        udid = detect_device_udid()

    elif args.command == "run":
        extra_args = list(args.script_args or [])
        if extra_args and extra_args[0] == "--":
            extra_args = extra_args[1:]

        result = run_child_script(root, args.script_key, extra_args=extra_args)
        child_runs.append(result)

        print(result.get("stdout", ""), end="")
        if result.get("stderr"):
            print(result["stderr"], file=sys.stderr, end="")

        safe_write_json(outdir / "child_runs.json", child_runs)

        artifacts = artifact_status(root)
        db = db_status(root)
        udid = detect_device_udid()

    elif args.command == "run-all-safe":
        child_runs = run_all_safe(root)
        safe_write_json(outdir / "child_runs.json", child_runs)

        print()
        print("Run-all-safe results")
        print("-" * 72)
        for item in child_runs:
            status = "OK" if item.get("ok") else "FAIL"
            print(
                f"{status:4} "
                f"{item.get('key',''):8} "
                f"rc={item.get('returncode')} "
                f"t={item.get('duration_s')}"
            )

        artifacts = artifact_status(root)
        db = db_status(root)
        udid = detect_device_udid()

    summary = {
        "timestamp": now_iso(),
        "script": SCRIPT_NAME,
        "app": APP_NAME,
        "stage": STAGE_NAME,
        "command": args.command,
        "repo_root": str(root),
        "device_udid": udid or "",
        "scripts": scripts,
        "artifacts": artifacts,
        "db": db,
        "child_run_count": len(child_runs),
    }

    notes = [
        "This console is the front door for the Dr. iPhone repo.",
        "Default posture is report-first and read-only oriented.",
        "run-all-safe intentionally excludes longer or more runtime-sensitive operations like watch and some capture modes.",
        "Use 'run <key> -- <args>' to pass arguments to child scripts.",
    ]

    safe_write_json(outdir / "summary.json", summary)
    if child_runs:
        safe_write_json(outdir / "child_runs.json", child_runs)
    safe_write_text(outdir / "notes.txt", "\n".join(notes) + "\n")

    log(f"Artifacts written to {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   iphone_operator_console.py
#
# Make executable:
#   chmod +x iphone_operator_console.py
#
# Bench:
#   ./iphone_operator_console.py bench
#
# Bench plus:
#   ./iphone_operator_console.py bench-plus
#
# Status:
#   ./iphone_operator_console.py status
#
# List managed scripts:
#   ./iphone_operator_console.py list-scripts
#
# Show DB status:
#   ./iphone_operator_console.py db-status
#
# Run one child script:
#   ./iphone_operator_console.py run observatory
#   ./iphone_operator_console.py run doctor
#
# Run one child script with extra args:
#   ./iphone_operator_console.py run pcap -- --seconds 10
#   ./iphone_operator_console.py run bridge -- --bundle com.example.app --pull yes
#
# Run conservative safe bundle:
#   ./iphone_operator_console.py run-all-safe
#
# Notes:
#   - Plug in and unlock the iPhone first when running device-dependent commands.
#   - Tap "Trust" if prompted.
#   - This console orchestrates child scripts; each child script defines its own safety boundary.
#
# Signature:
#   Dr. iPhone — Operator Console
# ============================================================================
