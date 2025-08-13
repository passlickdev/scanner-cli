"""
This module provides configuration management for scanner modes.

Classes:
    Mode: Represents a scanner mode configuration, including endpoint, method, triggers, and other options.

Functions:
    load_modes(directory: Path) -> Dict[str, Mode]:
        Loads mode configurations from YAML files in the specified directory.

    find_mode(modes: Dict[str, Mode], barcode: str) -> Optional[Mode]:
        Finds and returns a Mode matching the given barcode, either by trigger or prefix.

(c) Passlick Development 2025. All rights reserved.
"""


from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
import yaml
import sys


@dataclass
class Mode:
    name: str
    endpoint: str
    method: str = "POST"
    enable_input: bool = False
    trigger: List[str] | None = None
    prefix_trigger: List[str] | None = None
    strip_prefix: bool = False
    timeout: int | None = None
    header: Dict[str, str] | None = None
    eval_mathops: bool = True
    enable_trigger_req: bool = False

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Mode":
        prefixes = data.get("prefix_trigger")
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        return Mode(
            name=data["name"],
            endpoint=data["endpoint"],
            method=(data.get("method") or "POST").upper(),
            enable_input=data.get("enable_input", False),
            trigger=data.get("trigger"),
            prefix_trigger=prefixes,
            strip_prefix=data.get("strip_prefix", False),
            timeout=data.get("timeout"),
            header=data.get("header"),
            eval_mathops=data.get("eval_mathops", True),
            enable_trigger_req=data.get("enable_trigger_req", False),
        )


def load_modes(directory: Path) -> Dict[str, Mode]:
    modes: Dict[str, Mode] = {}
    for path in directory.glob("*.y*ml"):
        try:
            with path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            print(f"[LOAD MODES] Failed to parse {path}: {e}", file=sys.stderr)
            continue
        try:
            mode = Mode.from_dict(raw)
        except KeyError as ke:
            print(f"[LOAD MODES] Missing key {ke} in {path}", file=sys.stderr)
            continue
        modes[mode.name] = mode
    return modes


def find_mode(modes: Dict[str, Mode], barcode: str) -> Optional[Mode]:
    for mode in modes.values():
        if mode.trigger and barcode in mode.trigger:
            return mode
    for mode in modes.values():
        if mode.prefix_trigger:
            for pref in mode.prefix_trigger:
                if barcode.startswith(pref):
                    return mode
    return None
