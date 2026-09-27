"""Ponto de entrada: python -m termux_agent"""

from .agent import Agent
from .config import Settings
from .history import HistoryStore
from .provider import ChatProvider
from .server import serve


def main() -> None:
    settings = Settings.from_env()
    if not 1 <= settings.port <= 65535:
        raise SystemExit("AGENT_PORT precisa estar entre 1 e 65535.")
    if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.access_token:
        raise SystemExit("Defina AGENT_ACCESS_TOKEN antes de escutar em uma interface de rede.")
    history = HistoryStore(settings.database_path, settings.history_limit)
    serve(Agent(ChatProvider(settings), history), settings.host, settings.port)


if __name__ == "__main__":
    main()
