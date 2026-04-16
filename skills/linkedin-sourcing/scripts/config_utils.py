#!/usr/bin/env python3
"""Shared utilities for parsing shell-style config files.

Provides a single, permissive config parser used across the linkedin-sourcing
scripts. Handles quoted and unquoted values, ignores comments and empty lines.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union


def _parse_config_value(raw_value: str) -> str | None:
    """Parse a shell-style config value from the right-hand side of KEY=VALUE."""
    value = raw_value.strip()
    if not value:
        return ""

    if value[0] in ('"', "'"):
        quote = value[0]
        closing_index = value.find(quote, 1)
        if closing_index == -1:
            return value[1:]
        return value[1:closing_index]

    return value.split("#", 1)[0].strip()


def parse_config_file(config_path: Union[str, Path]) -> dict[str, str]:
    """Parse a shell config file and extract key-value pairs.

    Handles:
    - Double-quoted values: VAR="value"
    - Single-quoted values: VAR='value'
    - Unquoted values: VAR=value
    - Ignores comments (lines starting with #)
    - Ignores empty lines

    Args:
        config_path: Path to the config file (string or Path)

    Returns:
        Dict of config key-value pairs. Returns empty dict if file doesn't exist.
    """
    config: dict[str, str] = {}
    path = Path(config_path)

    if not path.exists():
        return config

    try:
        content = path.read_text()
    except (OSError, IOError):
        return config

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" in line:
            key, value = line.split("=", 1)
            key = key.strip()
            parsed_value = _parse_config_value(value)
            if key and parsed_value is not None:
                config[key] = parsed_value

    return config
