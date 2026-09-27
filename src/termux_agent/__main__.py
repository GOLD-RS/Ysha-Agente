"""Ponto de entrada: python -m termux_agent"""

from .agent import Agent
from .config import Settings
from .provider import ChatProvider
from .server import serve


def main() -> None:
    settings = Settings.from_env()
    if not 1 <= settings.port <= 65535:
        raise SystemExit("AGENT_PORT precisa estar entre 1 e 65535.")
    serve(Agent(ChatProvider(settings)), settings.host, settings.port)


if __name__ == "__main__":
    main()
