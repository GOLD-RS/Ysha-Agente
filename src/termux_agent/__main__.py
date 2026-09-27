"""Ponto de entrada: python -m termux_agent"""

from pathlib import Path

from .agent import Agent
from .config import Settings, load_env_file, validate_settings
from .db_maintenance import DatabaseLock
from .history import HistoryStore
from .provider import ChatProvider
from .server import serve


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    try:
        load_env_file(root / ".env")
        settings = Settings.from_env()
        validate_settings(settings)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    with DatabaseLock(settings.database_path):
        history = HistoryStore(settings.database_path, settings.history_limit)
        try:
            serve(Agent(ChatProvider(settings), history), settings.host, settings.port)
        finally:
            history.close()


if __name__ == "__main__":
    main()
