#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_app_inventory.py

Project:
    Dr. iPhone

Stage:
    04 — App Inventory

Purpose
-------
Enumerate installed iPhone applications and maintain historical
state so changes between runs can be detected.

Capabilities
------------
- detect connected device
- validate pairing
- enumerate installed apps through pymobiledevice3
- normalize bundle identifiers
- persist current inventory
- diff current vs previous state
- write timestamped artifacts

Outputs
-------
artifacts/iphone_app_inventory/<timestamp>/
    apps_current.json
    apps_previous.json
    apps_added.json
    apps_removed.json
    summary.json

state/iphone_app_inventory/
    apps_previous.json

Safe operation
--------------
- read-only
- no jailbreak assumptions
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_NAME = "iphone_app_inventory"
REPO_ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / SCRIPT_NAME
STATE_ROOT = REPO_ROOT / "state" / SCRIPT_NAME


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return utc_now().strftime("%Y%m%d_%H%M%SZ")


def now_iso() -> str:
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], timeout: int = 30) -> dict[str, Any]:
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
            "cmd": cmd,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": 124,
            "stdout": "",
            "stderr": f"timeout after {timeout}s",
            "cmd": cmd,
        }
    except Exception as exc:
        return {
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": f"{type(exc).__name__}: {exc}",
            "cmd": cmd,
        }


def detect_device() -> str | None:
    if not exists("idevice_id"):
        return None
    result = run(["idevice_id", "-l"], timeout=15)
    if not result["ok"]:
        return None
    for line in result["stdout"].splitlines():
        if line.strip():
            return line.strip()
    return None


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


def parse_app_lines(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except Exception:
        return []

    if not isinstance(payload, dict):
        return []

    apps: list[dict[str, Any]] = []

    for bundle, meta in payload.items():
        if not isinstance(bundle, str):
            continue
        if not isinstance(meta, dict):
            meta = {}

        app = {
            "bundle": bundle,
            "name": meta.get("CFBundleDisplayName") or meta.get("CFBundleName") or bundle,
            "version": meta.get("CFBundleShortVersionString"),
            "build": meta.get("CFBundleVersion"),
            "type": meta.get("ApplicationType"),
            "path": meta.get("Path"),
            "container": meta.get("Container"),
            "minimum_os": meta.get("MinimumOSVersion"),
        }
        apps.append(app)

    apps.sort(key=lambda x: x["bundle"])
    return apps


def enumerate_apps_with_pymobiledevice3() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cli = None
    for candidate in ("pymobiledevice3",):
        if exists(candidate):
            cli = candidate
            break

    if not cli:
        return [], {"ok": False, "reason": "pymobiledevice3 cli missing"}

    attempts = [
        [cli, "apps", "list"],
        [cli, "apps", "list", "--help"],
    ]

    first = run(attempts[0], timeout=60)
    apps = parse_app_lines(first["stdout"])
    meta: dict[str, Any] = {
        "command": attempts[0],
        "ok": first["ok"],
        "stderr": first["stderr"],
        "returncode": first["returncode"],
        "parsed_count": len(apps),
    }

    return apps, meta


def load_previous(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            out = []
            for item in data:
                if isinstance(item, dict) and "bundle" in item:
                    out.append(item)
            return sorted(out, key=lambda x: x["bundle"])
    except Exception:
        return []
    return []


def diff_apps(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    curr_set = {a["bundle"] for a in current}
    prev_set = {a["bundle"] for a in previous}
    added = sorted(curr_set - prev_set)
    removed = sorted(prev_set - curr_set)
    return added, removed


def main() -> int:
    out_dir = ensure_dir(ARTIFACT_ROOT / stamp())
    state_dir = ensure_dir(STATE_ROOT)

    current_path = out_dir / "apps_current.json"
    previous_path_art = out_dir / "apps_previous.json"
    added_path = out_dir / "apps_added.json"
    removed_path = out_dir / "apps_removed.json"
    summary_path = out_dir / "summary.json"
    previous_state_path = state_dir / "apps_previous.json"

    summary: dict[str, Any] = {
        "script": SCRIPT_NAME,
        "start_time_utc": now_iso(),
        "device": None,
        "pair_valid": False,
        "apps_total": 0,
        "apps_added": 0,
        "apps_removed": 0,
        "artifacts_dir": str(out_dir),
        "state_file": str(previous_state_path),
        "helper_inventory": {
            "idevice_id": exists("idevice_id"),
            "idevicepair": exists("idevicepair"),
            "pymobiledevice3": exists("pymobiledevice3"),
        },
    }

    log("starting app inventory")

    udid = detect_device()
    if not udid:
        log("no device detected")
        summary["end_time_utc"] = now_iso()
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 1

    summary["device"] = udid
    log(f"device {udid}")

    pair = validate_pairing(udid)
    summary["pair_valid"] = pair.get("paired", False)
    summary["pair_validate_raw"] = pair
    if not pair.get("paired", False):
        log("pair validation failed")
        summary["end_time_utc"] = now_iso()
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 2

    apps, enum_meta = enumerate_apps_with_pymobiledevice3()
    summary["enumeration_meta"] = enum_meta
    summary["apps_total"] = len(apps)

    current_path.write_text(json.dumps(apps, indent=2), encoding="utf-8")
    log(f"{len(apps)} apps found")

    previous = load_previous(previous_state_path)
    previous_path_art.write_text(json.dumps(previous, indent=2), encoding="utf-8")

    added, removed = diff_apps(apps, previous)
    summary["apps_added"] = len(added)
    summary["apps_removed"] = len(removed)

    added_path.write_text(json.dumps(added, indent=2), encoding="utf-8")
    removed_path.write_text(json.dumps(removed, indent=2), encoding="utf-8")

    previous_state_path.write_text(json.dumps(apps, indent=2), encoding="utf-8")

    summary["end_time_utc"] = now_iso()
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\nApp Inventory summary")
    print("=" * 72)
    print(f"Device:       {summary['device']}")
    print(f"Pair valid:   {summary['pair_valid']}")
    print(f"Apps total:   {summary['apps_total']}")
    print(f"Apps added:   {summary['apps_added']}")
    print(f"Apps removed: {summary['apps_removed']}")
    print(f"Summary file: {summary_path}")

    log("iphone_app_inventory complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ----------------------------------------------------------------------------
# chmod +x iphone_app_inventory.py
# . .venv/bin/activate
# ./iphone_app_inventory.py
# ============================================================================
