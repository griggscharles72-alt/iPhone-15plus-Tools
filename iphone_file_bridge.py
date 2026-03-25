#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_file_bridge.py

Project:
    Dr. iPhone

Stage:
    03 — File Bridge

Purpose
-------
Provide controlled filesystem interaction with an attached iPhone
using ifuse and libimobiledevice.

Capabilities:
    - detect connected device
    - validate pairing
    - list file-sharing-enabled apps
    - mount app containers only when explicitly requested
    - pull artifacts from mounted container
    - unmount safely
    - write timestamped artifacts

Safety
------
    - read-only by default in workflow posture
    - mounts only when explicitly requested
    - bounded pull count
    - unmounts automatically
    - continues on failure
    - no jailbreak required

Outputs
-------
artifacts/iphone_file_bridge/<timestamp>/
    apps.json
    pull_log.txt
    summary.json
    mount_listing.txt          (only when mounted)
    pulled/                   (only when pull requested)

Usage
-----
    ./iphone_file_bridge.py
    ./iphone_file_bridge.py --bundle com.example.app
    ./iphone_file_bridge.py --bundle com.example.app --pull
    ./iphone_file_bridge.py --bundle com.example.app --pull --max-files 25
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_NAME = "iphone_file_bridge"
REPO_ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / SCRIPT_NAME


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


def list_apps(udid: str) -> list[dict[str, str]]:
    if not exists("ifuse"):
        return []

    result = run(["ifuse", "--list-apps", "--udid", udid], timeout=25)
    if not result["ok"] and not result["stdout"]:
        return []

    apps: list[dict[str, str]] = []
    for line in result["stdout"].splitlines():
        if ":" in line:
            bundle, name = line.split(":", 1)
            apps.append({"bundle": bundle.strip(), "name": name.strip()})
    return apps


def choose_unmount_command() -> str | None:
    for name in ("fusermount", "fusermount3", "umount"):
        if exists(name):
            return name
    return None


def mount_app(bundle: str, mount_dir: Path, udid: str) -> dict[str, Any]:
    mount_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ifuse",
        str(mount_dir),
        "--udid",
        udid,
        "--container",
        bundle,
    ]
    result = run(cmd, timeout=30)

    mounted = False
    listing: list[str] = []
    if result["ok"]:
        try:
            listing = sorted(p.name for p in mount_dir.iterdir())
            mounted = True
        except Exception:
            mounted = False

    return {
        "ok": result["ok"] and mounted,
        "mounted": mounted,
        "mount_dir": str(mount_dir),
        "listing": listing,
        "raw": result,
    }


def unmount(path: Path) -> dict[str, Any]:
    tool = choose_unmount_command()
    if not tool:
        return {"ok": False, "stderr": "no unmount tool found", "cmd": []}

    if tool in ("fusermount", "fusermount3"):
        cmd = [tool, "-u", str(path)]
    else:
        cmd = [tool, str(path)]

    return run(cmd, timeout=20)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def pull_files(src_dir: Path, dest_dir: Path, max_files: int) -> dict[str, Any]:
    dest_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    count = 0

    try:
        items = sorted(src_dir.rglob("*"))
    except Exception as exc:
        return {"count": 0, "copied": [], "skipped": [], "errors": [str(exc)]}

    for item in items:
        if count >= max_files:
            break
        try:
            if item.is_symlink():
                skipped.append(f"symlink:{safe_rel(item, src_dir)}")
                continue
            if item.is_dir():
                continue
            rel = item.relative_to(src_dir)
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())
            copied.append(str(rel))
            count += 1
        except Exception as exc:
            errors.append(f"{safe_rel(item, src_dir)} :: {exc}")

    return {
        "count": count,
        "copied": copied,
        "skipped": skipped,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Controlled iPhone file bridge")
    p.add_argument("--bundle", help="bundle id to mount")
    p.add_argument("--pull", action="store_true", help="copy files from mounted container")
    p.add_argument("--max-files", type=int, default=25, help="maximum files to copy when --pull is used")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = ensure_dir(ARTIFACT_ROOT / stamp())

    apps_json = out_dir / "apps.json"
    pull_log = out_dir / "pull_log.txt"
    summary_json = out_dir / "summary.json"
    mount_listing = out_dir / "mount_listing.txt"

    summary: dict[str, Any] = {
        "script": SCRIPT_NAME,
        "start_time_utc": now_iso(),
        "device": None,
        "pair_valid": False,
        "apps_found": 0,
        "bundle_requested": args.bundle,
        "mount_attempted": bool(args.bundle),
        "mount_ok": False,
        "pull_requested": args.pull,
        "files_pulled": 0,
        "max_files": args.max_files,
        "artifacts_dir": str(out_dir),
        "helper_inventory": {
            "idevice_id": exists("idevice_id"),
            "idevicepair": exists("idevicepair"),
            "ifuse": exists("ifuse"),
            "fusermount": exists("fusermount"),
            "fusermount3": exists("fusermount3"),
            "umount": exists("umount"),
        },
    }

    log("starting file bridge")

    udid = detect_device()
    if not udid:
        log("no device detected")
        summary["end_time_utc"] = now_iso()
        write_text(summary_json, json.dumps(summary, indent=2))
        return 1

    summary["device"] = udid
    log(f"device detected {udid}")

    pair = validate_pairing(udid)
    summary["pair_valid"] = pair.get("paired", False)
    summary["pair_validate_raw"] = pair
    if not pair.get("paired", False):
        log("pair validation failed")
        summary["end_time_utc"] = now_iso()
        write_text(summary_json, json.dumps(summary, indent=2))
        return 2

    apps = list_apps(udid)
    summary["apps_found"] = len(apps)
    apps_json.write_text(json.dumps(apps, indent=2), encoding="utf-8")
    log(f"{len(apps)} file-sharing apps found")

    mount_result: dict[str, Any] | None = None
    unmount_result: dict[str, Any] | None = None
    pull_result: dict[str, Any] | None = None
    mount_point = out_dir / "mount"

    try:
        if args.bundle:
            log(f"mounting {args.bundle}")
            mount_result = mount_app(args.bundle, mount_point, udid)
            summary["mount_ok"] = bool(mount_result.get("ok"))
            summary["mount_result"] = mount_result

            if mount_result.get("listing") is not None:
                write_text(mount_listing, "\n".join(mount_result.get("listing", [])) + "\n")

            if mount_result.get("ok"):
                log("mount successful")
                if args.pull:
                    log(f"pulling up to {args.max_files} files")
                    pull_result = pull_files(mount_point, out_dir / "pulled", args.max_files)
                    summary["files_pulled"] = pull_result["count"]
                    summary["pull_result"] = pull_result
                    write_text(
                        pull_log,
                        json.dumps(
                            {
                                "files_pulled": pull_result["count"],
                                "copied": pull_result["copied"],
                                "skipped": pull_result["skipped"],
                                "errors": pull_result["errors"],
                            },
                            indent=2,
                        ),
                    )
            else:
                log("mount failed")
    finally:
        if args.bundle and mount_point.exists():
            log("unmounting")
            unmount_result = unmount(mount_point)
            summary["unmount_result"] = unmount_result

    summary["end_time_utc"] = now_iso()
    write_text(summary_json, json.dumps(summary, indent=2))

    print("\nFile Bridge summary")
    print("=" * 72)
    print(f"Device:         {summary['device']}")
    print(f"Pair valid:     {summary['pair_valid']}")
    print(f"Apps found:     {summary['apps_found']}")
    print(f"Bundle request: {summary['bundle_requested']}")
    print(f"Mount ok:       {summary['mount_ok']}")
    print(f"Files pulled:   {summary['files_pulled']}")
    print(f"Summary file:   {summary_json}")

    log("iphone_file_bridge complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ----------------------------------------------------------------------------
# chmod +x iphone_file_bridge.py
# . .venv/bin/activate
# ./iphone_file_bridge.py
# ./iphone_file_bridge.py --bundle com.example.app
# ./iphone_file_bridge.py --bundle com.example.app --pull --max-files 25
# ============================================================================
