#!/usr/bin/env python3
"""
README
======

Filename:
    iphone_crash_and_syslog_lab.py

Project:
    Dr. iPhone

Stage:
    05 — Crash + Syslog Evidence Lab

Purpose
-------
Collect bounded syslog samples and crash-report metadata from an attached
iPhone to build a structured evidence layer.

Capabilities
------------
- detect connected device
- validate pairing
- capture short syslog windows
- categorize crash/error indicators
- extract likely app identifiers from syslog
- collect crash-report metadata when available
- persist timestamped evidence artifacts

Safety
------
- read-only
- bounded capture
- no device modification
- no jailbreak required

Outputs
-------
artifacts/iphone_crash_and_syslog_lab/<timestamp>/
    syslog_sample.log
    crash_keywords.log
    crash_apps.json
    crash_report_meta.json
    summary.json
"""

from __future__ import annotations

import json
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_NAME = "iphone_crash_and_syslog_lab"
REPO_ROOT = Path(__file__).resolve().parent
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / SCRIPT_NAME

CRASH_WORDS = [
    "crash",
    "exception",
    "fault",
    "panic",
    "abort",
    "segmentation",
    "killed",
    "termination",
    "assertion",
    "watchdog",
    "jetsam",
    "thermal",
    "reset",
]

BUNDLE_RE = re.compile(r"\b(?:[A-Za-z0-9_-]+\.)+[A-Za-z0-9_-]+\b")


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


def capture_syslog(udid: str, seconds: int = 8, line_cap: int = 500) -> list[str]:
    if not exists("idevicesyslog"):
        return []

    proc = None
    try:
        proc = subprocess.Popen(
            ["idevicesyslog", "-u", udid],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        start = time.time()
        lines: list[str] = []

        if proc.stdout is not None:
            for line in proc.stdout:
                lines.append(line.rstrip("\n"))
                if len(lines) >= line_cap:
                    break
                if time.time() - start >= seconds:
                    break

        return lines
    except Exception:
        return []
    finally:
        if proc is not None:
            try:
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def detect_keywords(lines: list[str]) -> tuple[list[str], dict[str, int]]:
    hits: list[str] = []
    counts = {word: 0 for word in CRASH_WORDS}

    for line in lines:
        low = line.lower()
        matched = False
        for word in CRASH_WORDS:
            if word in low:
                counts[word] += 1
                matched = True
        if matched:
            hits.append(line)

    return hits, counts


def extract_apps(lines: list[str]) -> list[str]:
    apps: set[str] = set()

    for line in lines:
        for match in BUNDLE_RE.findall(line):
            if "/" in match or ":" in match:
                continue
            if match.startswith("com.apple.") or match.startswith("com.") or match.startswith("net.") or match.startswith("org.") or match.startswith("io.") or match.startswith("ch."):
                apps.add(match)

    return sorted(apps)


def collect_crash_report_meta() -> dict[str, Any]:
    """
    Best-effort metadata collection using pymobiledevice3 if present.
    We keep this bounded and non-fatal.
    """
    meta: dict[str, Any] = {
        "source": None,
        "ok": False,
        "items": [],
        "error": None,
    }

    if not exists("pymobiledevice3"):
        meta["error"] = "pymobiledevice3 missing"
        return meta

    attempts = [
        ["pymobiledevice3", "crash", "ls"],
        ["pymobiledevice3", "crash", "list"],
    ]

    for cmd in attempts:
        result = run(cmd, timeout=30)
        if result["ok"] and result["stdout"]:
            meta["source"] = cmd
            meta["ok"] = True
            items = [line.strip() for line in result["stdout"].splitlines() if line.strip()]
            meta["items"] = items[:200]
            return meta

    meta["source"] = attempts
    meta["error"] = "no supported crash listing command succeeded"
    return meta


def main() -> int:
    out_dir = ensure_dir(ARTIFACT_ROOT / stamp())

    syslog_file = out_dir / "syslog_sample.log"
    keywords_file = out_dir / "crash_keywords.log"
    crash_apps_file = out_dir / "crash_apps.json"
    crash_meta_file = out_dir / "crash_report_meta.json"
    summary_file = out_dir / "summary.json"

    summary: dict[str, Any] = {
        "script": SCRIPT_NAME,
        "start_time_utc": now_iso(),
        "device": None,
        "pair_valid": False,
        "syslog_lines": 0,
        "crash_hits": 0,
        "apps_detected": 0,
        "artifacts_dir": str(out_dir),
        "helper_inventory": {
            "idevice_id": exists("idevice_id"),
            "idevicepair": exists("idevicepair"),
            "idevicesyslog": exists("idevicesyslog"),
            "pymobiledevice3": exists("pymobiledevice3"),
        },
    }

    log("starting crash/syslog lab")

    udid = detect_device()
    if not udid:
        log("no device detected")
        summary["end_time_utc"] = now_iso()
        summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 1

    summary["device"] = udid
    log(f"device detected {udid}")

    pair = validate_pairing(udid)
    summary["pair_valid"] = pair.get("paired", False)
    summary["pair_validate_raw"] = pair
    if not pair.get("paired", False):
        log("pair validation failed")
        summary["end_time_utc"] = now_iso()
        summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 2

    lines = capture_syslog(udid, seconds=8, line_cap=500)
    summary["syslog_lines"] = len(lines)
    syslog_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    log(f"{len(lines)} syslog lines captured")

    hits, keyword_counts = detect_keywords(lines)
    summary["crash_hits"] = len(hits)
    summary["keyword_counts"] = keyword_counts
    keywords_file.write_text("\n".join(hits) + ("\n" if hits else ""), encoding="utf-8")

    apps = extract_apps(lines)
    summary["apps_detected"] = len(apps)
    crash_apps_file.write_text(json.dumps(apps, indent=2), encoding="utf-8")

    crash_meta = collect_crash_report_meta()
    summary["crash_report_meta_ok"] = crash_meta.get("ok", False)
    summary["crash_report_meta_count"] = len(crash_meta.get("items", []))
    crash_meta_file.write_text(json.dumps(crash_meta, indent=2), encoding="utf-8")

    summary["end_time_utc"] = now_iso()
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\nCrash + Syslog Lab summary")
    print("=" * 72)
    print(f"Device:              {summary['device']}")
    print(f"Pair valid:          {summary['pair_valid']}")
    print(f"Syslog lines:        {summary['syslog_lines']}")
    print(f"Crash keyword hits:  {summary['crash_hits']}")
    print(f"Apps detected:       {summary['apps_detected']}")
    print(f"Crash meta entries:  {summary['crash_report_meta_count']}")
    print(f"Summary file:        {summary_file}")

    log("iphone_crash_and_syslog_lab complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# ============================================================================
# INSTRUCTIONS
# ----------------------------------------------------------------------------
# chmod +x iphone_crash_and_syslog_lab.py
# . .venv/bin/activate
# ./iphone_crash_and_syslog_lab.py
# ============================================================================
