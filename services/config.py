"""Local configuration from the git-ignored .env file and environment variables.

Secrets such as API keys live only in .env (never in source code). Environment
variables take precedence over .env values.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip().removeprefix("export ").strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return key, value


def read_env(path: Path = ENV_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_line(line)
        if parsed:
            values[parsed[0]] = parsed[1]
    return values


def get_setting(name: str, default: str | None = None, path: Path = ENV_PATH) -> str | None:
    value = os.environ.get(name) or read_env(path).get(name)
    return value.strip() if value and value.strip() else default


def update_env(values: dict[str, str | None], path: Path = ENV_PATH) -> None:
    """Set (or remove, when the value is None) keys in .env, keeping other lines intact."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    output = []
    for line in lines:
        parsed = _parse_line(line)
        if parsed and parsed[0] in remaining:
            value = remaining.pop(parsed[0])
            if value is not None:
                output.append(f"{parsed[0]}={value}")
            continue
        output.append(line)
    for key, value in remaining.items():
        if value is not None:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).strip() + "\n", encoding="utf-8")


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    return value[:6] + "…" + value[-4:] if len(value) > 12 else "•" * len(value)
