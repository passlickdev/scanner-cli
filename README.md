# Scanner CLI

CLI tool to read (barcode) tokens from standard input and route them as HTTP requests to configurable REST endpoints. Modes let you dynamically change where (and how) scans are sent, either persistently (keyword trigger) or ephemerally (prefix trigger). Designed for wedge / USB scanners that just type into stdin, but works with any newline-delimited input source.

## Highlights

* Zero‑state: just run the command and start scanning
* YAML mode definitions (one file per mode)
* Persistent mode switching (exact trigger) & ephemeral prefix triggers
* Optional per‑scan supplemental user input with safe math evaluation
* Structured JSON logging (suitable for ingestion / auditing)
* Idle timeout auto‑reverts to a safe default mode

## Installation

```bash
pip install git+https://github.com/passlickdev/scanner-cli@master
```

Python 3.12+ is required.

## Quick Start

1. Create a directory `modes/` on your system
2. Create a mode definition file, for example `modes/DEFAULT.yaml`
3. Copy the example content from `modes/DEFAULT.yaml.example` to your mode definition file
4. Edit the mode definition file to your needs
4. Run:
	 ```bash
	 scanner-cli
	 ```
5. Scan a barcode or enter a value

Press Ctrl+C to exit. EOF on stdin (e.g. piping a file) ends the session cleanly.

## CLI Usage

```bash
scanner-cli [--modes-dir DIR] [--default-mode NAME] [--list-modes] \
						[--log-file PATH] [-v|-vv|-vvv] [--idle-timeout SECONDS]
```

Option | Description | Default
-------|-------------|--------
`--modes-dir DIR` | Directory containing YAML mode definition files (`*.yml` / `*.yaml`). | `modes`
`--default-mode NAME` | Mode to start in and to revert to after idle timeout. Must match a `name` in a YAML file. | `DEFAULT`
`--list-modes` | List parsed modes and exit. | (off)
`--log-file PATH` | Append JSON log events to a file (stderr still used for console output). | (none)
`-v` / `-vv` / `-vvv` | Increase log verbosity (INFO / DEBUG). | WARN
`--idle-timeout SECONDS` | If set, revert to default mode after this many seconds of no successful scan (only when in a non‑default mode). | (disabled)

Exit codes: `0` success / normal exit, `1` configuration or runtime error.

## Mode Definition (YAML)

Each `*.yaml` file in the modes directory describes one mode. Minimal example:

```yaml
name: DEFAULT
endpoint: "https://example.com/api/v1/scan"
method: POST            # Optional (default POST). Anything httpx supports.
timeout: 10             # Seconds (optional)
header:                 # Optional headers merged with default Content-Type
	Authorization: Bearer XXXXX

# Optional triggers:
trigger:                # Exact match => persistent mode switch
	- MODE1
prefix_trigger:         # Prefix match => ephemeral use for that scan only
	- M1;
strip_prefix: false     # If true, remove the matched prefix before sending barcode

enable_input: false     # If true, prompt user for an extra value after each scan
eval_mathops: true      # If enable_input and true: safe evaluation of math expressions
enable_trigger_req: false  # If true, also send a request for the trigger barcode itself when switching
```

### Field Reference

Key | Type | Purpose
----|------|--------
`name` | str | Mode identifier (must be unique). Filename does not have to match but recommended.
`endpoint` | str | Full URL to send requests to.
`method` | str | HTTP method (default `POST`). For non body methods (GET, etc.) payload is sent as query params.
`header` | dict | Extra headers (merged over `Content-Type: application/json`).
`timeout` | int | Per-request timeout override (seconds). Falls back to client default (10s).
`trigger` | list[str] | Exact tokens that, when scanned, persistently switch modes.
`enable_trigger_req` | bool | When switching via trigger, also fire a request carrying the trigger (action `mode`).
`prefix_trigger` | list[str] | Prefixes that cause an ephemeral mode for that scan only.
`strip_prefix` | bool | Remove matched prefix from the barcode before sending.
`enable_input` | bool | Prompt user for an extra input line (e.g., quantity) after scanning.
`eval_mathops` | bool | If extra input looks like a math expression, safely evaluate (`1+2*3`).

### Mode Switching Semantics

* Persistent switch: If a scanned token exactly equals a configured `trigger`, the current mode changes until another switch happens or idle timeout reverts it. Optionally a request is sent (`enable_trigger_req: true`) with `action: "mode"`.
* Ephemeral switch: If a token starts with a `prefix_trigger`, that scan uses the target mode (optionally stripping the prefix), then control returns to the previous mode immediately after.

### Payload Structure

Standard scan request JSON (POST body or query string for non-body methods):

```json
{
	"barcode": "1234567890",
	"mode": "DEFAULT",
	"action": "scan"
}
```

Additional fields that may appear:

Field | Added When
------|-----------
`raw_barcode` | Prefix stripping occurred
`input` | Extra user input captured (may be evaluated math result)
`action: scan+input` | Extra input present
`action: mode` | Trigger request on mode switch (if enabled)

### Extra Input & Math Evaluation

When `enable_input` is true, the prompt `>>> INPUT` appears after a barcode. If `eval_mathops` is true the tool safely evaluates simple arithmetic (`+ - * / // % **`, integers & floats) with size limits. Invalid or disallowed expressions fall back to raw text.

## Logging & Observability

Console output is human friendly; structured events (INFO level) are emitted as single-line JSON objects to the log stream (and to `--log-file` if provided). Representative events:

Event | When | Sample Fields
------|------|--------------
`startup` | Program start | `current_mode`, `modes`
`mode_switch` | Persistent trigger switch | `new_mode`, `trigger`
`mode_auto_revert` | Idle timeout revert | `to_mode`, `reason`
`sent` | Successful request | `mode`, `endpoint`, `status`, `payload`
`error` | Non-success HTTP status | `status`, `response`
`exception` | Request failure | `error`
`stdin_eof` | End of input stream | —
`shutdown` | Graceful exit | `current_mode`

Use `-v` or `-vv` for INFO / DEBUG verbosity; DEBUG logs add internal details.

## Idle Timeout

If `--idle-timeout N` is supplied and you are in a non-default mode, a timer is (re)started after each scan or switch. When it expires with no further scans, the mode automatically reverts to the default and a `mode_auto_revert` event is logged.


## Troubleshooting

Problem | Resolution
--------|-----------
Modes directory missing | Create `modes/` or pass `--modes-dir`.
Default mode not found | Ensure YAML has `name:` matching `--default-mode`.
No requests sent | Confirm scanner sends newline, check `-v` logs, verify endpoint reachable.
Unexpected mode switches | Check for overlapping prefixes, inspect `trigger` lists.
Timeouts | Increase `timeout` in mode or use more robust endpoint.

## License

AGPLv3.0. See `LICENSE` for full text.
(c) Passlick Development 2025. All rights reserved.
