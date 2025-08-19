"""
Main module for Scanner CLI.

This module provides the command-line interface for reading barcodes via stdin and routing them to REST endpoints based on configurable modes. It supports mode switching, input prompts, logging, and idle timeouts.

Functions:
    _eval_mathops(expr: str):
        Safely evaluates mathematical expressions from user input, restricting allowed operations and values.

    parse_args(argv=None):
        Parses command-line arguments for the Scanner CLI.

    configure_logging(log_file: str | None, verbosity: int):
        Configures logging handlers and verbosity levels.

    log_event(event: str, **fields):
        Logs structured events as JSON records.

    list_modes(modes: Dict[str, Mode]):
        Displays available modes in a formatted table.

    main(argv=None):
        Entry point for the CLI. Handles mode management, barcode scanning, input prompts, API requests, and logging.

Usage:
    Run as a script to start the Scanner CLI. Use command-line arguments to configure modes, logging, and timeouts.

(c) Passlick Development 2025. All rights reserved.
"""


from __future__ import annotations

import argparse
import sys
import json
import logging
import re
from pathlib import Path
import threading
from typing import Dict
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich import box

from .config import load_modes, find_mode, Mode
from . import __version__
from .client import ApiClient
import ast


def _eval_mathops(expr: str):
    expr = expr.strip()
    if not expr:
        raise ValueError("empty expression")
    if any(c in expr for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_[]{};:\\'"):
        raise ValueError("disallowed characters")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError("syntax error") from e

    base_allowed = [
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Load,
    ]
    if hasattr(ast, 'Paren'):
        base_allowed.append(
            ast.Paren)
    allowed_nodes = tuple(base_allowed)

    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"disallowed node {type(node).__name__}")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, int) and abs(node.value) > 10**12:
                raise ValueError("integer too large")
            if isinstance(node.value, float) and abs(node.value) > 10**12:
                raise ValueError("float too large")
    value = eval(compile(tree, filename="<expr>", mode="eval"),
                 {"__builtins__": {}}, {})
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value


console = Console()


_ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def sanitize_input(value: str) -> str:
    if not value:
        return value
    cleaned = _ANSI_CSI_RE.sub("", value)
    cleaned = cleaned.replace("\x1b", "")
    return cleaned


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Scanner CLI - Tool to read barcodes via stdin and route them to REST endpoints based on configurable modes")
    parser.add_argument("--modes-dir", default="modes",
                        help="Set directory containing mode definition files")
    parser.add_argument("--default-mode", default="DEFAULT",
                        help="Set default mode")
    parser.add_argument("--list-modes", action="store_true",
                        help="List available modes")
    parser.add_argument("--log-file", default=None,
                        help="Set path to log file")
    parser.add_argument("-v", "--verbose", action="count",
                        default=0, help="Verbose output")
    parser.add_argument("--idle-timeout", type=int, default=None,
                        help="Set idle timeout (in seconds; disabled if omitted)")
    return parser.parse_args(argv)


def configure_logging(log_file: str | None, verbosity: int):
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        handlers.append(fh)
    logging.basicConfig(level=level, handlers=handlers, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log_event(event: str, **fields):
    record = {"event": event, **fields}
    logging.getLogger(__name__).info(json.dumps(record, ensure_ascii=False))


def list_modes(modes: Dict[str, Mode]):
    table = Table(title="AVAILABLE MODES", box=box.SIMPLE_HEAVY)
    table.add_column("NAME")
    table.add_column("ENDPOINT")
    table.add_column("TRIGGER")
    table.add_column("PREFIXES")
    for m in modes.values():
        table.add_row(m.name, m.endpoint, ",".join(
            m.trigger or []), ",".join(m.prefix_trigger or []))
    console.print(table)


def main(argv=None):
    args = parse_args(argv)
    console.print(
        f"*** SCANNER CLI v{__version__} ***", style="yellow3", markup=False, highlight=False)
    console.print(
        "(c) Passlick Development 2025. All rights reserved.\n", style="white", highlight=False)
    modes_dir = Path(args.modes_dir)
    if not modes_dir.exists():
        console.print(f"[red]Modes directory {modes_dir} does not exist[/red]")
        return 1
    modes = load_modes(modes_dir)
    configure_logging(args.log_file, args.verbose)
    if args.list_modes:
        list_modes(modes)
        return 0
    if args.default_mode not in modes:
        console.print(
            f"[red]Default mode {args.default_mode} not found. Available: {list(modes)}[/red]")
        return 1

    default_mode = modes[args.default_mode]
    current_mode = default_mode
    mode_lock = threading.Lock()
    idle_timer: threading.Timer | None = None

    def cancel_timer():
        nonlocal idle_timer
        if idle_timer is not None:
            idle_timer.cancel()
            idle_timer = None

    def _do_timeout(reason: str):
        nonlocal current_mode
        with mode_lock:
            if current_mode.name != default_mode.name:
                current_mode = default_mode
                console.print(
                    f"[yellow]Mode auto-reverted to {default_mode.name} ({reason})[/yellow]")
                log_event("mode_auto_revert",
                          to_mode=default_mode.name, reason=reason)

    def schedule_timeout():
        nonlocal idle_timer
        if not args.idle_timeout:
            return
        if current_mode.name == default_mode.name:
            cancel_timer()
            return
        cancel_timer()
        idle_timer = threading.Timer(
            args.idle_timeout, lambda: _do_timeout("inactivity"))
        idle_timer.daemon = True
        idle_timer.start()
    console.print(
        f"Starting in mode [bold]{current_mode.name}[/bold]. Ready for scans (Ctrl+C to exit)...")
    log_event("startup", current_mode=current_mode.name, modes=list(modes))

    with ApiClient() as api:
        while True:
            try:
                try:
                    console.print("[", end="")
                    console.print(current_mode.name, style="green", end="")
                    console.print("] ", end="")
                except Exception:
                    pass
                line = sys.stdin.readline()
                if line == '':
                    log_event("stdin_eof")
                    break
                barcode = sanitize_input(line.strip())
                if not barcode:
                    continue

                triggered_mode = find_mode(modes, barcode)
                effective_mode = current_mode
                ephemeral = False
                raw_barcode = barcode
                if triggered_mode:
                    if triggered_mode.trigger and barcode in triggered_mode.trigger:
                        with mode_lock:
                            current_mode = triggered_mode
                            effective_mode = current_mode
                        console.print(
                            f"Switched mode to [green]{current_mode.name}[/green]")
                        log_event(
                            "mode_switch", new_mode=current_mode.name, trigger=raw_barcode)
                        schedule_timeout()
                        if not triggered_mode.enable_trigger_req:
                            continue
                        payload = {
                            "barcode": raw_barcode, "mode": effective_mode.name, "action": "mode"}
                        try:
                            resp = api.send(
                                effective_mode.method,
                                effective_mode.endpoint,
                                payload,
                                timeout=effective_mode.timeout,
                                headers=effective_mode.header,
                            )
                            if resp.is_success:
                                console.print(
                                    f"[green]{effective_mode.method} {resp.status_code}[/green] -> {effective_mode.endpoint} {payload}")
                                log_event("sent", mode=effective_mode.name, endpoint=effective_mode.endpoint,
                                          status=resp.status_code, method=effective_mode.method, payload=payload)
                            else:
                                console.print(
                                    f"[red]{effective_mode.method} {resp.status_code}[/red] {payload}: {resp.text}")
                                log_event("error", mode=effective_mode.name, endpoint=effective_mode.endpoint,
                                          status=resp.status_code, method=effective_mode.method, response=resp.text)
                        except Exception as e:
                            console.print(f"[red]Request failed[/red]: {e}")
                            log_event("exception", mode=effective_mode.name,
                                      method=effective_mode.method, error=str(e))
                        continue
                    if triggered_mode.prefix_trigger:
                        for pref in triggered_mode.prefix_trigger:
                            if barcode.startswith(pref):
                                effective_mode = triggered_mode
                                ephemeral = True
                                if triggered_mode.strip_prefix:
                                    barcode = barcode[len(pref):]
                                break

                payload = {"barcode": barcode,
                           "mode": effective_mode.name, "action": "scan"}
                if raw_barcode != barcode:
                    payload["raw_barcode"] = raw_barcode
                if effective_mode.enable_input:
                    base_prompt = ">>> INPUT"
                    try:
                        extra = Prompt.ask(
                            base_prompt, default="", show_default=False) or ""
                    except TypeError:
                        extra = Prompt.ask(base_prompt, default="") or ""
                    if extra:
                        if effective_mode.eval_mathops:
                            try:
                                evaluated = _eval_mathops(extra)
                            except Exception:
                                evaluated = extra
                        else:
                            evaluated = extra
                        payload["input"] = sanitize_input(str(evaluated))
                        payload["action"] = "scan+input"

                try:
                    resp = api.send(
                        effective_mode.method,
                        effective_mode.endpoint,
                        payload,
                        timeout=effective_mode.timeout,
                        headers=effective_mode.header,
                    )
                    if resp.is_success:
                        console.print(
                            f"[green]{effective_mode.method} {resp.status_code}[/green] -> {effective_mode.endpoint} {payload}")
                        log_event("sent", mode=effective_mode.name, endpoint=effective_mode.endpoint,
                                  status=resp.status_code, method=effective_mode.method, payload=payload)
                    else:
                        console.print(
                            f"[red]{effective_mode.method} {resp.status_code}[/red] {payload}: {resp.text}")
                        log_event("error", mode=effective_mode.name, endpoint=effective_mode.endpoint,
                                  status=resp.status_code, method=effective_mode.method, response=resp.text)
                except Exception as e:
                    console.print(f"[red]Request failed[/red]: {e}")
                    log_event("exception", mode=effective_mode.name,
                              method=effective_mode.method, error=str(e))

                if ephemeral:
                    pass
                else:
                    schedule_timeout()
            except KeyboardInterrupt:
                console.print("\nExiting.")
                log_event("shutdown", current_mode=current_mode.name)
                break
            except Exception as e:
                console.print(f"[red]Unexpected error[/red]: {e}")

    cancel_timer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
