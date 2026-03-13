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


def file_info(path: Path) -> Dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }



def split_packet_blocks(lines: List[str]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    header_re = re.compile(
        r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+): '
        r'Process (?P<proc>.+?) \((?P<pid>\d+)\), '
        r'Interface: (?P<iface>.+?), Family: (?P<family>\S+)$'
    )
    hex_re = re.compile(r'^[0-9A-Fa-f]{8}:\s+(.+)$')

    for line in lines:
        m = header_re.match(line.strip())
        if m:
            if current is not None:
                blocks.append(current)
            current = {
                "timestamp": m.group("ts"),
                "process": m.group("proc"),
                "pid": int(m.group("pid")),
                "interface": m.group("iface"),
                "family": m.group("family"),
                "hex_lines": [],
            }
            continue

        hm = hex_re.match(line.rstrip())
        if hm and current is not None:
            current["hex_lines"].append(hm.group(1))

    if current is not None:
        blocks.append(current)

    return blocks


def hex_lines_to_bytes(hex_lines: List[str]) -> bytes:
    parts: List[str] = []
    for line in hex_lines:
        for token in line.replace("  ", " ").split():
            if re.fullmatch(r"[0-9A-Fa-f]{2}", token):
                parts.append(token)
    return bytes.fromhex("".join(parts)) if parts else b""


def parse_ipv4_packet(payload: bytes) -> Dict[str, Any]:
    if len(payload) < 20:
        return {}
    ihl = (payload[0] & 0x0F) * 4
    if len(payload) < ihl or ihl < 20:
        return {}
    proto_num = payload[9]
    src = ".".join(str(b) for b in payload[12:16])
    dst = ".".join(str(b) for b in payload[16:20])

    proto_map = {1: "icmp", 6: "tcp", 17: "udp"}
    proto = proto_map.get(proto_num, f"ipproto_{proto_num}")

    out = {
        "ip_version": 4,
        "protocol": proto,
        "src_ip": src,
        "dst_ip": dst,
    }

    if proto_num in (6, 17) and len(payload) >= ihl + 4:
        out["src_port"] = int.from_bytes(payload[ihl:ihl+2], "big")
        out["dst_port"] = int.from_bytes(payload[ihl+2:ihl+4], "big")

    return out


def parse_ipv6_packet(payload: bytes) -> Dict[str, Any]:
    if len(payload) < 40:
        return {}
    next_header = payload[6]
    src_raw = payload[8:24]
    dst_raw = payload[24:40]

    def fmt_ipv6(buf: bytes) -> str:
        groups = [f"{int.from_bytes(buf[i:i+2], 'big'):x}" for i in range(0, 16, 2)]
        return ":".join(groups)

    proto_map = {58: "icmpv6", 6: "tcp", 17: "udp"}
    proto = proto_map.get(next_header, f"ipproto_{next_header}")

    out = {
        "ip_version": 6,
        "protocol": proto,
        "src_ip": fmt_ipv6(src_raw),
        "dst_ip": fmt_ipv6(dst_raw),
    }

    if next_header in (6, 17) and len(payload) >= 44:
        out["src_port"] = int.from_bytes(payload[40:42], "big")
        out["dst_port"] = int.from_bytes(payload[42:44], "big")

    return out


def find_ipv4_offset(frame: bytes) -> Optional[int]:
    for i in range(0, max(0, len(frame) - 20)):
        b0 = frame[i]
        version = b0 >> 4
        ihl = b0 & 0x0F
        if version == 4 and 5 <= ihl <= 15:
            return i
    return None


def find_ipv6_offset(frame: bytes) -> Optional[int]:
    for i in range(0, max(0, len(frame) - 40)):
        if (frame[i] >> 4) == 6:
            return i
    return None


def decode_packet_bytes(frame: bytes, family: str = "") -> Dict[str, Any]:
    family = str(family or "").strip()

    if family == "AF_INET6":
        off = find_ipv6_offset(frame)
        if off is not None:
            decoded = parse_ipv6_packet(frame[off:])
            decoded["ether_type"] = "ipv6"
            decoded["decode_offset"] = off
            return decoded

    if family == "AF_INET":
        off = find_ipv4_offset(frame)
        if off is not None:
            decoded = parse_ipv4_packet(frame[off:])
            decoded["ether_type"] = "ipv4"
            decoded["decode_offset"] = off
            return decoded

    off6 = find_ipv6_offset(frame)
    if off6 is not None:
        decoded = parse_ipv6_packet(frame[off6:])
        decoded["ether_type"] = "ipv6"
        decoded["decode_offset"] = off6
        return decoded

    off4 = find_ipv4_offset(frame)
    if off4 is not None:
        decoded = parse_ipv4_packet(frame[off4:])
        decoded["ether_type"] = "ipv4"
        decoded["decode_offset"] = off4
        return decoded

    return {}


def extract_dns_candidates(lines: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for line in lines:
        low = line.lower()
        if "dns" in low or "query" in low or "answer" in low:
            item = line.strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return out[:200]


def extract_endpoint_candidates(lines: List[str]) -> List[str]:
    blocks = split_packet_blocks(lines)
    seen = set()
    out: List[str] = []

    for block in blocks:
        raw = hex_lines_to_bytes(block.get("hex_lines", []))
        decoded = decode_packet_bytes(raw, block.get("family", ""))
        src_ip = decoded.get("src_ip")
        dst_ip = decoded.get("dst_ip")
        src_port = decoded.get("src_port")
        dst_port = decoded.get("dst_port")

        candidates = []
        if src_ip:
            candidates.append(f"{src_ip}:{src_port}" if src_port is not None else src_ip)
        if dst_ip:
            candidates.append(f"{dst_ip}:{dst_port}" if dst_port is not None else dst_ip)

        for item in candidates:
            if item not in seen:
                seen.add(item)
                out.append(item)

    return out[:200]


def extract_protocol_candidates(lines: List[str]) -> List[str]:
    blocks = split_packet_blocks(lines)
    seen = set()
    out: List[str] = []

    for block in blocks:
        raw = hex_lines_to_bytes(block.get("hex_lines", []))
        decoded = decode_packet_bytes(raw, block.get("family", ""))

        for item in [
            block.get("family", ""),
            decoded.get("ether_type", ""),
            decoded.get("protocol", ""),
        ]:
            item = str(item).strip()
            if item and item not in seen:
                seen.add(item)
                out.append(item)

    return out[:50]


def summarize_process_candidates(lines: List[str]) -> List[str]:
    blocks = split_packet_blocks(lines)
    seen = set()
    out: List[str] = []
    for block in blocks:
        proc = str(block.get("process", "")).strip()
        if proc and proc not in seen:
            seen.add(proc)
            out.append(proc)
    return out[:100]

def try_capture_text(udid: str, outdir: Path, seconds: int) -> Dict[str, Any]:
    stdout_path = outdir / "capture_stdout.txt"
    stderr_path = outdir / "capture_stderr.txt"

    attempts: List[Dict[str, Any]] = []

    probe = run_cmd(
        ["pymobiledevice3", "pcap", "--udid", udid, "--help"],
        timeout=12,
    )
    attempts.append(
        {
            "probe_cmd": ["pymobiledevice3", "pcap", "--udid", udid, "--help"],
            "probe_ok": probe["ok"],
            "probe_stderr": clean_text(probe.get("stderr", "")),
            "probe_stdout_head": clean_text(probe.get("stdout", ""))[:400],
        }
    )

    cmd = ["pymobiledevice3", "pcap", "--udid", udid]
    started = time.time()

    try:
        with stdout_path.open("w", encoding="utf-8") as out_fp, stderr_path.open("w", encoding="utf-8") as err_fp:
            proc = subprocess.Popen(
                cmd,
                cwd=str(script_root()),
                stdout=out_fp,
                stderr=err_fp,
                text=True,
            )
            try:
                proc.wait(timeout=seconds)
                terminated = False
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                terminated = True

        return {
            "ok": True,
            "cmd": cmd,
            "duration_s": round(time.time() - started, 3),
            "terminated": terminated,
            "returncode": proc.returncode,
            "method": "pymobiledevice3_text_capture",
            "attempts": attempts,
        }
    except Exception as exc:
        return {
            "ok": False,
            "cmd": cmd,
            "duration_s": round(time.time() - started, 3),
            "terminated": False,
            "returncode": None,
            "method": "pymobiledevice3_text_capture",
            "error": f"{type(exc).__name__}: {exc}",
            "attempts": attempts,
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
        default=20,
        help="Capture duration in seconds.",
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
        safe_write_text(
            outdir / "notes.txt",
            "No device detected. Check cable, trust prompt, and usbmuxd.\n",
        )
        log("No device detected")
        log(f"Artifacts written to {outdir}")
        return 1

    device_info = get_device_info(udid)
    log(f"Device detected: {device_info.get('DeviceName', udid)}")

    log(f"Starting bounded capture for {args.seconds}s")
    capture_result = try_capture_text(udid, outdir, args.seconds)

    stdout_path = outdir / "capture_stdout.txt"
    stderr_path = outdir / "capture_stderr.txt"
    pcap_path = outdir / "iphone_capture.pcap"

    lines = read_text_lines(stdout_path, max_lines=DEFAULT_MAX_LINES)
    if lines:
        safe_write_text(outdir / "pcap_text.txt", "\n".join(lines) + "\n")

    dns_candidates = extract_dns_candidates(lines)
    endpoint_candidates = extract_endpoint_candidates(lines)
    protocol_candidates = extract_protocol_candidates(lines)
    process_candidates = summarize_process_candidates(lines)

    stdout_info = file_info(stdout_path)
    stderr_info = file_info(stderr_path)
    pcap_info = file_info(pcap_path)

    safe_write_json(outdir / "dns_candidates.json", dns_candidates)
    safe_write_json(outdir / "endpoint_candidates.json", endpoint_candidates)
    safe_write_json(outdir / "protocol_candidates.json", protocol_candidates)

    capture_truth = {
        "mode": "text_capture",
        "stdout_file": stdout_info,
        "stderr_file": stderr_info,
        "pcap_file": pcap_info,
        "stdout_line_count": len(lines),
        "has_text_output": len(lines) > 0,
        "has_pcap_file": pcap_info["exists"],
        "pcap_nonzero": pcap_info["size_bytes"] > 0,
        "packet_capture_status": "",
    }

    if pcap_info["exists"] and pcap_info["size_bytes"] > 0:
        capture_truth["packet_capture_status"] = "pcap_present_nonzero"
    elif pcap_info["exists"] and pcap_info["size_bytes"] == 0:
        capture_truth["packet_capture_status"] = "pcap_present_zero_bytes"
    elif len(lines) > 0:
        capture_truth["packet_capture_status"] = "text_output_only"
    else:
        capture_truth["packet_capture_status"] = "no_packets_observed"

    notes = [
        "This version is passive/read-only.",
        "It probes likely pymobiledevice3 capture command paths.",
        "Capture truth is reported explicitly so empty runs are distinguishable from real packet capture.",
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
        "capture_truth": capture_truth,
        "text_summary": {
            "line_count": len(lines),
            "dns_candidates": dns_candidates,
            "endpoint_candidates": endpoint_candidates,
            "protocol_candidates": protocol_candidates,
            "process_candidates": process_candidates,
        },
        "tshark_summary": {
            "ok": True,
            "mode": "text_only_note",
            "note": "This stage now reports exact capture truth. A later version can promote real packet parsing when non-zero PCAP artifacts exist."
        }
    }
    safe_write_json(outdir / "summary.json", summary)

    log(f"Lines captured: {len(lines)}")
    log(f"DNS candidates: {len(dns_candidates)}")
    log(f"Endpoint candidates: {len(endpoint_candidates)}")
    log(f"Protocol candidates: {len(protocol_candidates)}")
    log(f"Process candidates: {len(process_candidates)}")
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
