#!/usr/bin/env python3
"""Helpers for HUMAN_INPUTS.yaml parsing and validation.

This parser intentionally supports a small, predictable YAML subset:
- top-level `key: value`
- one nested level via:
    section:
      key: value
No lists or deeper nesting.
"""

from __future__ import annotations

import re
from pathlib import Path

SECRET_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
]


def _parse_value(raw: str) -> str | bool:
    val = raw.strip()
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        val = val[1:-1]
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return val


def load_human_inputs(path: Path) -> dict:
    data: dict = {}
    current_section: str | None = None

    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.startswith("  "):
            if current_section is None:
                raise ValueError(f"Invalid indentation at line {lineno}: {line}")
            stripped = line.strip()
            if ":" not in stripped:
                raise ValueError(f"Invalid key-value at line {lineno}: {line}")
            key, value = stripped.split(":", 1)
            sec = data.setdefault(current_section, {})
            if not isinstance(sec, dict):
                raise ValueError(f"Section '{current_section}' is not a map (line {lineno})")
            sec[key.strip()] = _parse_value(value)
            continue

        current_section = None
        stripped = line.strip()
        if ":" not in stripped:
            raise ValueError(f"Invalid key-value at line {lineno}: {line}")

        key, value = stripped.split(":", 1)
        key = key.strip()
        if value.strip() == "":
            data[key] = {}
            current_section = key
        else:
            data[key] = _parse_value(value)

    return data


def has_inline_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_VALUE_PATTERNS)


def flatten_values(payload: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for k, v in payload.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                rows.append((f"{k}.{sk}", str(sv)))
        else:
            rows.append((k, str(v)))
    return rows
