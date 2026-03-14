Dr. iPhone — Linux ↔ iPhone Observability Stack

Overview


Start Here

Primary daily launcher:

    ./dr_iphone_launcher.sh

Modes:

    ./dr_iphone_launcher.sh bench
    ./dr_iphone_launcher.sh bench-plus

What it does before running:
    • activates the repo virtualenv
    • checks required tools
    • verifies usbmuxd is active
    • waits for visible iPhone transport
    • validates pairing
    • launches the correct bench flow

Use this as the default repo entrypoint instead of calling lower-level scripts manually.


The correct approach for building a Linux ↔ iPhone tooling stack is not thinking in individual tools, but designing a layered script system.

Instead of installing random utilities and manually running commands, this repository treats Python as the orchestration layer and uses a small number of helper tools that expose iOS device protocols.

The stable base stack is:
	•	usbmuxd — USB transport layer between Linux and iOS devices
	•	libimobiledevice — native iOS service protocol layer
	•	ifuse — filesystem access to file-sharing-enabled app containers
	•	pymobiledevice3 — Python-first control interface for device operations

These tools allow Python scripts to safely interact with an iPhone without jailbreak assumptions.

pymobiledevice3 exposes higher-level capabilities such as:
	•	device discovery
	•	syslog streaming
	•	application inventory
	•	AFC file access
	•	crash reports
	•	packet capture (PCAP)
	•	notification listening
	•	screenshots
	•	developer-style device features

The repository therefore builds a structured platform rather than isolated utilities.


Daily Safe Workflow

The primary default entrypoint is now:

    ./dr_iphone_launcher.sh

Recommended daily runs:

    ./dr_iphone_launcher.sh
    ./dr_iphone_launcher.sh bench
    ./dr_iphone_launcher.sh bench-plus

This launcher:
    • activates the repo virtualenv
    • checks required tools
    • verifies usbmuxd is active
    • waits for visible iPhone transport
    • validates pairing
    • launches the correct observatory flow

Use lower-level scripts directly only when working on a specific subsystem.


⸻



Validated Hardware Base

This repository is currently validated against the following known-good bench:

Host
    • HP ENVY TE01 Linux workstation
    • VS Code + integrated terminal workflow
    • Local Python virtualenv at .venv
    • usbmuxd active on the host
    • libimobiledevice helper tools present
    • pymobiledevice3 present

Phone
    • Device class: iPhone 15 Plus
    • Product type: iPhone15,5
    • iOS version: 26.1
    • Build version: 23B85

Validated Transport / Trust State
    • USB cable connection confirmed
    • Host-level Apple USB detection confirmed through lsusb
    • Device visibility confirmed through idevice_id
    • Pair validation confirmed through idevicepair validate
    • Device info retrieval confirmed through ideviceinfo

Primary Repo Entry Point
    • ./dr_iphone_launcher.sh

Validated Run Modes
    • ./dr_iphone_launcher.sh bench
    • ./dr_iphone_launcher.sh bench-plus

Known-Good Bench Behavior
    • launcher waits for visible iPhone transport
    • launcher checks pairing before running collectors
    • bench completes doctor + apps + crash + devsurf + state
    • bench-plus completes doctor + apps + crash + devsurf + state + pcap + notify
    • observatory artifacts are written under artifacts/iphone_observatory/
    • operator console artifacts are written under artifacts/iphone_operator_console/

Operational Notes
    • If the phone is visible in lsusb but not visible to idevice_id, the USB transport may be present while the lockdown/pairing session is stale
    • Strong recovery path: restart usbmuxd, clear stale lockdown cache, replug phone, unlock, trust, then revalidate pair state
    • Do not treat desktop file-mount visibility alone as proof that the libimobiledevice stack is healthy
    • Use the launcher as the default daily entrypoint instead of manually sequencing lower-level scripts

Architecture

The system is organized as layered scripts.

Layer 0 — environment + helper validation
Layer 1 — transport and trust
Layer 2 — static diagnostics
Layer 3 — live signal monitoring
Layer 4 — file/app bridge
Layer 5 — evidence + timeline correlation
Layer 6 — advanced operator console

Each layer depends on the layers below it.

⸻

Core Scripts

01. dr_iphone.py

Baseline diagnostic script.

Responsibilities
	•	validate helper binaries
	•	verify usbmuxd
	•	detect connected device
	•	validate pairing / trust state
	•	collect device identity
	•	collect iOS version
	•	collect storage and battery state
	•	produce a clean structured report

Why This Script Comes First

Every other script depends on the environment being correct.

dr_iphone.py answers the fundamental question:

Is the device bench real and working?

It primarily uses:
	•	libimobiledevice
	•	optionally pymobiledevice3

Both operate safely on non-jailbroken devices.

⸻

02. iphone_signal_watch.py

Live signal monitoring.

Responsibilities
	•	detect device connect / disconnect
	•	sample battery state periodically
	•	collect short syslog windows
	•	extract categorized events
	•	build a timeline of activity

Why This Script Comes Second

A snapshot shows what exists.

A watcher shows what changes over time.

This script introduces:
	•	idevicesyslog
	•	pymobiledevice3 discovery features

⸻

03. iphone_file_bridge.py

Controlled file interaction layer.

Responsibilities
	•	list file-sharing-enabled applications
	•	mount accessible app directories when requested
	•	pull artifacts or logs
	•	safely unmount mounts
	•	ensure no stale mounts remain

Why Third

This is the first script that makes the workflow practically useful.

It turns:

device attached

into:

device accessible

ifuse is the core tool for this layer.

⸻

04. iphone_app_inventory.py

Application inventory and state tracking.

Responsibilities
	•	enumerate installed apps
	•	normalize bundle identifiers
	•	record app names and versions
	•	diff current state vs previous runs
	•	detect new or removed apps

Why Fourth

Applications represent the behavioral surface of the device.

This creates a persistent object list for monitoring.

Uses:
	•	pymobiledevice3 application management.

⸻

05. iphone_crash_and_syslog_lab.py

Evidence extraction layer.

Responsibilities
	•	gather crash report metadata
	•	capture bounded syslog samples
	•	extract keywords and app identifiers
	•	detect repeated crash patterns
	•	produce a crash / log summary

Why Fifth

Once the device and app list are known, logs and crashes become meaningful signals.

Uses:
	•	pymobiledevice3 crash reports
	•	syslog capture tools

⸻

06. iphone_pcap_lab.py

Network visibility layer.

Responsibilities
	•	perform bounded network packet capture
	•	store PCAP artifacts
	•	summarize DNS activity
	•	summarize remote endpoints
	•	summarize protocols
	•	correlate network activity with device events

Why Sixth

This script connects device behavior with network behavior.

pymobiledevice3 supports network sniffing capabilities used here.

⸻

07. iphone_notify_console.py

Event notification console.

Responsibilities
	•	listen for device notifications
	•	record event streams
	•	normalize notification data
	•	optionally trigger safe notifications

Why Seventh

Event streams often provide more insight than periodic polling.

This becomes part of the live operator environment.

⸻

08. iphone_dev_surface.py

Developer feature exploration layer.

Responsibilities
	•	test screenshot capabilities
	•	test developer-image dependent features
	•	test simulated location when available
	•	inventory accessible developer surfaces

Why Eighth

This script maps which advanced capabilities are reachable on the current device.

It becomes a capability map for the environment.

⸻

09. iphone_state_db.py

Persistent state storage.

Responsibilities
	•	maintain a SQLite database
	•	store device identity
	•	store application inventory
	•	store event counters
	•	track historical deltas

Why Ninth

Without persistence, every script run forgets previous results.

This database prevents the project from becoming:

run tool → forget results


⸻

10. iphone_operator_console.py

Unified operator control surface.

Responsibilities
	•	call other modules
	•	display system summary
	•	provide safe subcommands
	•	centralize artifact storage
	•	expose core functions

doctor
watch
bridge
apps
pcap
logs

Why Tenth

This script transforms the repository from a set of utilities into a platform.

⸻

Correct Build Order

Scripts must be developed in this order:
	1.	dr_iphone.py
	2.	iphone_signal_watch.py
	3.	iphone_file_bridge.py
	4.	iphone_app_inventory.py
	5.	iphone_crash_and_syslog_lab.py
	6.	iphone_pcap_lab.py
	7.	iphone_notify_console.py
	8.	iphone_dev_surface.py
	9.	iphone_state_db.py
	10.	iphone_operator_console.py

The ordering matters because each layer relies on the previous ones.

Examples:
	•	monitoring requires stable detection and trust
	•	file bridging requires known device state
	•	PCAP analysis benefits from app inventory and logs
	•	the console should orchestrate tools that already exist

⸻

Minimal Useful Subset

If only four scripts are implemented, prioritize:

dr_iphone.py
iphone_signal_watch.py
iphone_file_bridge.py
iphone_pcap_lab.py

This subset provides:
	•	device diagnostics
	•	live monitoring
	•	file interaction
	•	network visibility

Even this subset forms a powerful platform.

⸻

11. iphone_observatory.py

The most advanced system achievable with the base stack is:

iphone_observatory.py

This script combines the capabilities of the earlier layers into a unified monitoring system.

Primary Daily Runner Responsibilities
	•	detect connected device
	•	validate trust
	•	poll battery and storage state
	•	capture periodic syslog windows
	•	track application inventory
	•	perform optional file inspection
	•	perform optional packet capture
	•	correlate events into a timeline
	•	persist historical state
	•	identify anomalies

Conceptually:

Doctor
+ Signal Watch
+ App Inventory
+ Crash/Log Evidence
+ PCAP
+ Historical Database
= Observatory

The observatory turns the system from:

manual device inspection

into:

continuous device intelligence


⸻

What Not to Build First

Do not start with instrumentation frameworks like Frida.

Although Frida is powerful and can instrument certain applications without jailbreak in some scenarios, it belongs after a stable observability stack exists.

Correct development sequence:

device bridge + diagnostics
→ monitoring
→ file/app inventory
→ evidence correlation
→ instrumentation

Instrumentation before observability leads to unstable systems.

⸻

Final Script Ladder

The full repository ladder is:

1  dr_iphone.py
2  iphone_signal_watch.py
3  iphone_file_bridge.py
4  iphone_app_inventory.py
5  iphone_crash_and_syslog_lab.py
6  iphone_pcap_lab.py
7  iphone_notify_console.py
8  iphone_dev_surface.py
9  iphone_state_db.py
10 iphone_operator_console.py

Final advanced system:

iphone_observatory.py


⸻

Repository Structure

dr-iphone/
├── README.md
├── requirements.txt
├── .gitignore
│
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
│
├── driphone_lib/
│   └── plist_utils.py
│
├── artifacts/
├── state/
└── docs/


⸻

Directory Roles

artifacts/

All scripts produce timestamped outputs in the artifacts directory.

Each script writes results to its own subdirectory.

Example:

artifacts/dr_iphone/
artifacts/iphone_signal_watch/
artifacts/iphone_app_inventory/
artifacts/iphone_pcap_lab/

Artifacts are immutable outputs that allow later correlation and auditing.

⸻

state/

The state directory stores persistent project data such as the SQLite database used by iphone_state_db.py.

state/dr_iphone.db

This database records historical results across runs.

⸻

docs/

Optional documentation, research notes, and design references may be stored here.

⸻

Internal Helper Layer

The repository currently keeps most execution logic inside the stage scripts themselves.

A small helper layer exists for plist parsing support used by the bench:

driphone_lib/

plist_utils.py

Utility helpers for parsing Apple plist/XML output safely.

⸻

Why This Is Small Right Now

The earlier library split was only partially started.
The repository was normalized back to the real live structure:
top-level scripts contain the working execution logic, and only live helpers remain in driphone_lib/.

Centralizing shared functionality provides several advantages:
	•	smaller script files
	•	consistent behavior across scripts
	•	easier refactoring
	•	safer updates to core logic

Top-level scripts should therefore remain focused on device logic, not infrastructure logic.

⸻

Future Extensions

Once the observability stack is stable, additional features may be explored.

Examples include:
	•	long-running monitoring daemon
	•	automated anomaly detection
	•	richer network traffic classification
	•	extended event correlation
	•	instrumentation layers (e.g. Frida integration)

These extensions should only be attempted after the base observability platform is stable.

⸻

Project Goal

The long-term goal of this repository is not to build a collection of random device utilities.

Instead, the goal is to create a structured observability platform for iPhone devices on Linux.

The system should evolve from:

manual command execution

to:

reproducible device intelligence

Every script added to the repository should fit into this layered model.

Scripts that do not fit the architecture should be treated as experiments rather than permanent components.

:::
