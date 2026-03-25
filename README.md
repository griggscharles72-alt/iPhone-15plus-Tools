# Dr. iPhone — Linux ↔ iPhone Observability Stack

## Overview

### Start Here

Primary daily launcher:

```bash
./dr_iphone_launcher.sh
```

Modes:

```bash
./dr_iphone_launcher.sh bench
./dr_iphone_launcher.sh bench-plus
```

Launcher responsibilities before running:

* Activates the repo virtual environment
* Checks required tools
* Verifies `usbmuxd` is active
* Waits for visible iPhone transport
* Validates pairing
* Launches the correct bench flow

> Use this as the default repo entrypoint instead of manually calling lower-level scripts.

---

## Philosophy

The Linux ↔ iPhone stack is organized as **layered scripts**, not isolated tools. Python is the orchestration layer; helper tools expose iOS device protocols. The stable base stack includes:

* `usbmuxd` — USB transport layer
* `libimobiledevice` — native iOS protocol layer
* `ifuse` — filesystem access to app containers
* `pymobiledevice3` — Python control interface for device operations

Capabilities exposed by Python scripts:

* Device discovery
* Syslog streaming
* Application inventory
* AFC file access
* Crash reports
* Network packet capture (PCAP)
* Notification listening
* Screenshots
* Developer-style features

This repository builds a **platform**, not a collection of utilities.

---

## Daily Safe Workflow

Primary daily entrypoint:

```bash
./dr_iphone_launcher.sh
```

Recommended runs:

```bash
./dr_iphone_launcher.sh
./dr_iphone_launcher.sh bench
./dr_iphone_launcher.sh bench-plus
```

Launcher tasks:

* Activates the virtual environment
* Checks required tools
* Verifies `usbmuxd` is active
* Waits for visible iPhone transport
* Validates pairing
* Launches the correct observatory flow

> Use lower-level scripts only for subsystem development.

---

## Validated Hardware Base

**Host:**

* HP ENVY TE01 Linux workstation
* VS Code + integrated terminal workflow
* Local Python virtualenv `.venv`
* `usbmuxd` active
* `libimobiledevice` helpers installed
* `pymobiledevice3` installed

**Phone:**

* iPhone 15 Plus (iPhone15,5)
* iOS 26.1, Build 23B85

**Transport / Trust State:**

* USB cable connection confirmed
* Device visibility through `lsusb` and `idevice_id`
* Pair validation through `idevicepair validate`
* Device info via `ideviceinfo`

**Primary Entry Point:**

```bash
./dr_iphone_launcher.sh
```

**Validated Run Modes:**

```bash
./dr_iphone_launcher.sh bench
./dr_iphone_launcher.sh bench-plus
```

**Known-Good Bench Behavior:**

* Launcher waits for iPhone transport
* Checks pairing before running collectors
* Bench completes: `doctor + apps + crash + devsurf + state`
* Bench-plus completes: `doctor + apps + crash + devsurf + state + pcap + notify`
* Observability artifacts: `artifacts/iphone_observatory/`
* Operator console artifacts: `artifacts/iphone_operator_console/`

**Operational Notes:**

* USB visibility in `lsusb` does not guarantee pairing
* Strong recovery: restart `usbmuxd`, clear stale lockdown cache, replug and trust device, revalidate
* Launcher is the default entrypoint

---

## Architecture

**Layered Script Organization:**

1. Environment + helper validation
2. Transport and trust
3. Static diagnostics
4. Live signal monitoring
5. File/app bridge
6. Evidence + timeline correlation
7. Advanced operator console

Each layer depends on the previous layers.

---

## Core Scripts

| Script                           | Purpose                                                       |
| -------------------------------- | ------------------------------------------------------------- |
| `dr_iphone.py`                   | Baseline diagnostics, environment and device verification     |
| `iphone_signal_watch.py`         | Live signal monitoring, battery, and syslog sampling          |
| `iphone_file_bridge.py`          | Controlled file interaction, safe mounts, artifact extraction |
| `iphone_app_inventory.py`        | Application inventory, versioning, state diffing              |
| `iphone_crash_and_syslog_lab.py` | Crash and syslog evidence extraction                          |
| `iphone_pcap_lab.py`             | Network capture and analysis, PCAP artifacts                  |
| `iphone_notify_console.py`       | Notification listening and logging                            |
| `iphone_dev_surface.py`          | Developer feature exploration, screenshots, dev surfaces      |
| `iphone_state_db.py`             | Persistent state storage (SQLite)                             |
| `iphone_operator_console.py`     | Unified operator interface, orchestrates all modules          |
| `iphone_observatory.py`          | Combines all layers into full observatory system              |

**Build Order:**

1. `dr_iphone.py`
2. `iphone_signal_watch.py`
3. `iphone_file_bridge.py`
4. `iphone_app_inventory.py`
5. `iphone_crash_and_syslog_lab.py`
6. `iphone_pcap_lab.py`
7. `iphone_notify_console.py`
8. `iphone_dev_surface.py`
9. `iphone_state_db.py`
10. `iphone_operator_console.py`

> Ordering matters: each layer relies on the previous.

**Minimal Useful Subset:**

* `dr_iphone.py`
* `iphone_signal_watch.py`
* `iphone_file_bridge.py`
* `iphone_pcap_lab.py`

---

## Repository Structure

```
dr-iphone/
├── README.md
├── requirements.txt
├── .gitignore
├── dr_iphone.py
├── iphone_signal_watch.py
├── iphone_file_bridge.py
├── iphone_app_inventory.py
├── iphone_crash_and_syslog_lab.py
├── iphone_pcap_lab.py
├── iphone_notify_console.py
├── iphone_dev_surface.py
├── iphone_state_db.py
├── iphone_operator_console.py
├── iphone_observatory.py
├── driphone_lib/
│   └── plist_utils.py
├── artifacts/
├── state/
└── docs/
```

**Directory Roles:**

* `artifacts/` — timestamped outputs per script, immutable for auditing
* `state/` — persistent data (SQLite database `dr_iphone.db`)
* `docs/` — optional documentation and research notes
* `driphone_lib/` — small helper utilities (plist parsing, shared functions)

---

## Future Extensions

After the observability stack is stable:

* Long-running monitoring daemon
* Automated anomaly detection
* Extended network traffic classification
* Richer event correlation
* Instrumentation layers (e.g., Frida integration)

> Only implement after base observability platform is stable.

---

## Project Goal

Create a **structured iPhone observability platform on Linux**, evolving from:

```text
manual command execution
```

to

```text
reproducible device intelligence
```

All scripts must fit the layered architecture; experimental scripts are not permanent components.

