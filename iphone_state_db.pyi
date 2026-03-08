#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_state_db.pyi

Project:
    Dr. iPhone

Stage:
    09 — State Database

Purpose
-------

Persist iPhone run history and normalized state into a local SQLite
database so the repository can correlate information across runs.

This script is intentionally local-first and standard-library-only.

Capabilities
------------

    • create and maintain SQLite database
    • record run metadata
    • record current device identity snapshot
    • ingest app inventory artifacts
    • ingest signal-watch summaries
    • ingest crash/syslog summaries
    • ingest pcap summaries
    • ingest notify summaries
    • write a database import summary

Design
------

    • Safe by default
    • Local-only
    • No device modification
    • Best-effort ingestion
    • Continue on failure
    • Repo-friendly
    • Standard library only

Primary helper stack
--------------------

    • python3
    • sqlite3 (Python stdlib)
    • existing artifact files from prior scripts

Expected artifact sources
-------------------------

This script reads from the artifact trees produced by:

    • dr_iphone.py
    • iphone_signal_watch.py
    • iphone_file_bridge.py
    • iphone_app_inventory.py
    • iphone_crash_and_syslog_lab.py
    • iphone_pcap_lab.py
    • iphone_notify_console.py
    • iphone_dev_surface.py

Outputs
-------

Creates / updates:

    state/dr_iphone.db

Creates artifact report:

    artifacts/iphone_state_db/<timestamp>/

Files:

    import_summary.json
    notes.txt

Safety notes
------------

    • No trust modification
    • No restore / reboot / shutdown
    • No writes to device
    • Only reads local artifact files and writes local SQLite state

Author:
    OpenAI / SABLE workflow support
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================================
# CONFIG
# ============================================================================

SCRIPT_NAME = "iphone_state_db.py"
APP_NAME = "Dr. iPhone"
STAGE_NAME = "09 — State Database"

ARTIFACT_DIR_NAMES = [
    "dr_iphone",
    "iphone_signal_watch",
    "iphone_file_bridge",
    "iphone_app_inventory",
    "iphone_crash_and_syslog_lab",
    "iphone_pcap_lab",
    "iphone_notify_console",
    "iphone_dev_surface",
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
        base = script_root() / "artifacts" / "iphone_state_db"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = base / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def ensure_state_dir(custom_dir: Optional[str] = None) -> Path:
    if custom_dir:
        base = Path(custom_dir).expanduser().resolve()
    else:
        base = script_root() / "state"
    base.mkdir(parents=True, exist_ok=True)
    return base


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


def newest_file_match(base: Path, filename: str) -> Optional[Path]:
    for run_dir in latest_timestamp_dirs(base):
        candidate = run_dir / filename
        if candidate.exists():
            return candidate
    return None


def find_latest_artifact_file(root: Path, artifact_subdir: str, filename: str) -> Optional[Path]:
    base = root / "artifacts" / artifact_subdir
    return newest_file_match(base, filename)


# ============================================================================
# DATABASE
# ============================================================================

def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT NOT NULL,
            source_script TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            import_ts TEXT NOT NULL,
            raw_summary_json TEXT
        );

        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_ts TEXT NOT NULL,
            source_script TEXT NOT NULL,
            device_name TEXT,
            product_type TEXT,
            product_version TEXT,
            build_version TEXT,
            udid TEXT,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS app_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_ts TEXT NOT NULL,
            udid TEXT,
            bundle_id TEXT NOT NULL,
            source_run_ts TEXT,
            source_artifact_path TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS app_deltas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_ts TEXT NOT NULL,
            udid TEXT,
            delta_type TEXT NOT NULL,
            bundle_id TEXT NOT NULL,
            source_run_ts TEXT,
            source_artifact_path TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS event_counters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_ts TEXT NOT NULL,
            source_script TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value INTEGER,
            source_run_ts TEXT,
            source_artifact_path TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS capabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_ts TEXT NOT NULL,
            surface TEXT NOT NULL,
            available INTEGER NOT NULL,
            source_run_ts TEXT,
            source_artifact_path TEXT NOT NULL
        );
        """
    )
    conn.commit()


# ============================================================================
# INGESTION
# ============================================================================

def insert_run(
    conn: sqlite3.Connection,
    source_script: str,
    artifact_path: Path,
    summary_data: Dict[str, Any],
) -> None:
    run_ts = str(summary_data.get("timestamp") or summary_data.get("time") or "")
    conn.execute(
        """
        INSERT INTO runs (run_ts, source_script, artifact_path, import_ts, raw_summary_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_ts,
            source_script,
            str(artifact_path),
            now_iso(),
            json.dumps(summary_data, ensure_ascii=False),
        ),
    )
    conn.commit()


def insert_device(
    conn: sqlite3.Connection,
    source_script: str,
    device_obj: Dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO devices (
            import_ts, source_script, device_name, product_type, product_version,
            build_version, udid, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now_iso(),
            source_script,
            str(device_obj.get("DeviceName", "")),
            str(device_obj.get("ProductType", "")),
            str(device_obj.get("ProductVersion", "")),
            str(device_obj.get("BuildVersion", "")),
            str(device_obj.get("UniqueDeviceID", "")),
            json.dumps(device_obj, ensure_ascii=False),
        ),
    )
    conn.commit()


def ingest_dr_iphone(conn: sqlite3.Connection, root: Path, report: Dict[str, Any]) -> Dict[str, Any]:
    imported = {"runs": 0, "devices": 0, "metrics": 0}

    path = find_latest_artifact_file(root, "dr_iphone", "dr_iphone_report.json")
    if not path:
        return imported

    data = read_json(path)
    insert_run(conn, "dr_iphone.py", path, data)
    imported["runs"] += 1

    devices = data.get("devices", [])
    for dev in devices:
        selected = dev.get("selected_info", {})
        if selected:
            selected["UniqueDeviceID"] = dev.get("udid", selected.get("UniqueDeviceID", ""))
            insert_device(conn, "dr_iphone.py", selected)
            imported["devices"] += 1

    return imported


def ingest_app_inventory(conn: sqlite3.Connection, root: Path) -> Dict[str, Any]:
    imported = {"runs": 0, "app_inventory": 0, "app_deltas": 0}

    summary_path = find_latest_artifact_file(root, "iphone_app_inventory", "summary.json")
    current_path = find_latest_artifact_file(root, "iphone_app_inventory", "apps_current.json")
    added_path = find_latest_artifact_file(root, "iphone_app_inventory", "apps_added.json")
    removed_path = find_latest_artifact_file(root, "iphone_app_inventory", "apps_removed.json")

    if not summary_path or not current_path:
        return imported

    summary = read_json(summary_path)
    apps = read_json(current_path)
    insert_run(conn, "iphone_app_inventory.py", summary_path, summary)
    imported["runs"] += 1

    udid = str(summary.get("device", ""))
    run_ts = str(summary.get("time", ""))

    for item in apps:
        bundle_id = str(item.get("bundle", "")).strip()
        if not bundle_id:
            continue
        conn.execute(
            """
            INSERT INTO app_inventory (import_ts, udid, bundle_id, source_run_ts, source_artifact_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (now_iso(), udid, bundle_id, run_ts, str(current_path)),
        )
        imported["app_inventory"] += 1

    if added_path and added_path.exists():
        for bundle_id in read_json(added_path):
            conn.execute(
                """
                INSERT INTO app_deltas (import_ts, udid, delta_type, bundle_id, source_run_ts, source_artifact_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now_iso(), udid, "added", str(bundle_id), run_ts, str(added_path)),
            )
            imported["app_deltas"] += 1

    if removed_path and removed_path.exists():
        for bundle_id in read_json(removed_path):
            conn.execute(
                """
                INSERT INTO app_deltas (import_ts, udid, delta_type, bundle_id, source_run_ts, source_artifact_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now_iso(), udid, "removed", str(bundle_id), run_ts, str(removed_path)),
            )
            imported["app_deltas"] += 1

    conn.commit()
    return imported


def ingest_simple_summary_metrics(
    conn: sqlite3.Connection,
    root: Path,
    artifact_dir: str,
    summary_filename: str,
    source_script: str,
    metric_fields: List[str],
) -> Dict[str, Any]:
    imported = {"runs": 0, "metrics": 0}

    summary_path = find_latest_artifact_file(root, artifact_dir, summary_filename)
    if not summary_path:
        return imported

    data = read_json(summary_path)
    insert_run(conn, source_script, summary_path, data)
    imported["runs"] += 1

    source_run_ts = str(data.get("timestamp") or data.get("time") or "")
    for field in metric_fields:
        value = data.get(field)
        if isinstance(value, int):
            conn.execute(
                """
                INSERT INTO event_counters (import_ts, source_script, metric_name, metric_value, source_run_ts, source_artifact_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (now_iso(), source_script, field, value, source_run_ts, str(summary_path)),
            )
            imported["metrics"] += 1

    conn.commit()
    return imported


def ingest_dev_surface(conn: sqlite3.Connection, root: Path) -> Dict[str, Any]:
    imported = {"runs": 0, "devices": 0, "capabilities": 0}

    summary_path = find_latest_artifact_file(root, "iphone_dev_surface", "summary.json")
    matrix_path = find_latest_artifact_file(root, "iphone_dev_surface", "capability_matrix.json")

    if not summary_path:
        return imported

    summary = read_json(summary_path)
    insert_run(conn, "iphone_dev_surface.py", summary_path, summary)
    imported["runs"] += 1

    device = summary.get("device", {})
    if device:
        insert_device(conn, "iphone_dev_surface.py", device)
        imported["devices"] += 1

    if matrix_path and matrix_path.exists():
        matrix = read_json(matrix_path)
        reachable = matrix.get("reachable_surfaces", [])
        unreachable = matrix.get("unreachable_surfaces", [])
        source_run_ts = str(summary.get("timestamp", ""))

        for item in reachable:
            conn.execute(
                """
                INSERT INTO capabilities (import_ts, surface, available, source_run_ts, source_artifact_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now_iso(), str(item.get("surface", "")), 1, source_run_ts, str(matrix_path)),
            )
            imported["capabilities"] += 1

        for item in unreachable:
            conn.execute(
                """
                INSERT INTO capabilities (import_ts, surface, available, source_run_ts, source_artifact_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now_iso(), str(item.get("surface", "")), 0, source_run_ts, str(matrix_path)),
            )
            imported["capabilities"] += 1

        conn.commit()

    return imported


# ============================================================================
# MAIN
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dr. iPhone — persist artifact state into SQLite",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Base output directory. Timestamped subdirectory is created inside it.",
    )
    parser.add_argument(
        "--state-dir",
        default="",
        help="Directory containing dr_iphone.db. Created if missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = script_root()
    outdir = make_output_dir(args.output_dir or None)
    state_dir = ensure_state_dir(args.state_dir or None)
    db_path = state_dir / "dr_iphone.db"

    log(f"{APP_NAME} {STAGE_NAME} start")
    log(f"Output directory: {outdir}")
    log(f"Database path: {db_path}")

    conn = connect_db(db_path)
    create_schema(conn)

    import_summary: Dict[str, Any] = {
        "timestamp": now_iso(),
        "script": SCRIPT_NAME,
        "app": APP_NAME,
        "stage": STAGE_NAME,
        "db_path": str(db_path),
        "imports": {},
    }

    try:
        import_summary["imports"]["dr_iphone"] = ingest_dr_iphone(conn, root, {})
    except Exception as exc:
        import_summary["imports"]["dr_iphone"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import_summary["imports"]["iphone_signal_watch"] = ingest_simple_summary_metrics(
            conn=conn,
            root=root,
            artifact_dir="iphone_signal_watch",
            summary_filename="summary.json",
            source_script="iphone_signal_watch.py",
            metric_fields=["device_sessions", "battery_events", "syslog_samples"],
        )
    except Exception as exc:
        import_summary["imports"]["iphone_signal_watch"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import_summary["imports"]["iphone_app_inventory"] = ingest_app_inventory(conn, root)
    except Exception as exc:
        import_summary["imports"]["iphone_app_inventory"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import_summary["imports"]["iphone_crash_and_syslog_lab"] = ingest_simple_summary_metrics(
            conn=conn,
            root=root,
            artifact_dir="iphone_crash_and_syslog_lab",
            summary_filename="summary.json",
            source_script="iphone_crash_and_syslog_lab.py",
            metric_fields=["syslog_lines", "crash_hits", "apps_detected"],
        )
    except Exception as exc:
        import_summary["imports"]["iphone_crash_and_syslog_lab"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import_summary["imports"]["iphone_pcap_lab"] = ingest_simple_summary_metrics(
            conn=conn,
            root=root,
            artifact_dir="iphone_pcap_lab",
            summary_filename="summary.json",
            source_script="iphone_pcap_lab.py",
            metric_fields=[],
        )
    except Exception as exc:
        import_summary["imports"]["iphone_pcap_lab"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import_summary["imports"]["iphone_notify_console"] = ingest_simple_summary_metrics(
            conn=conn,
            root=root,
            artifact_dir="iphone_notify_console",
            summary_filename="summary.json",
            source_script="iphone_notify_console.py",
            metric_fields=[],
        )
    except Exception as exc:
        import_summary["imports"]["iphone_notify_console"] = {"error": f"{type(exc).__name__}: {exc}"}

    try:
        import_summary["imports"]["iphone_dev_surface"] = ingest_dev_surface(conn, root)
    except Exception as exc:
        import_summary["imports"]["iphone_dev_surface"] = {"error": f"{type(exc).__name__}: {exc}"}

    conn.close()

    notes = [
        "This state DB version imports the latest available artifact set per script family.",
        "It is intentionally conservative and local-only.",
        "A later version can import multiple historical runs in one pass and add stronger relational joins.",
    ]

    safe_write_json(outdir / "import_summary.json", import_summary)
    safe_write_text(outdir / "notes.txt", "\n".join(notes) + "\n")

    log("Import complete")
    log(f"Artifacts written to {outdir}")
    log(f"Database updated: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ============================================================================
#
# Save as:
#   iphone_state_db.py
#
# Make executable:
#   chmod +x iphone_state_db.py
#
# Basic run:
#   ./iphone_state_db.py
#
# Custom artifact base:
#   ./iphone_state_db.py --output-dir ./artifacts
#
# Custom state directory:
#   ./iphone_state_db.py --state-dir ./state
#
# Notes:
#   - Run this after at least some earlier Dr. iPhone scripts have produced artifacts.
#   - This version imports the newest artifact set it can find for each script family.
#   - Database file: state/dr_iphone.db
#
# Signature:
#   Dr. iPhone — State Database
# ============================================================================
