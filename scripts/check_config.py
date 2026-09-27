#!/usr/bin/env python3
"""Valida .env como dados antes do supervisor Termux entrar no loop."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from termux_agent.config import Settings, load_env_file, validate_settings  # noqa: E402


def main() -> int:
    try:
        load_env_file(ROOT / ".env")
        validate_settings(Settings.from_env())
    except (OSError, ValueError):
        print("Configuração ausente ou inválida; revise .env e rode ./setup-termux.sh.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
