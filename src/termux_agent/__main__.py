"""Ponto de entrada: python -m termux_agent"""

from urllib.parse import urlsplit

from .agent import Agent
from .config import Settings
from .history import HistoryStore
from .provider import ChatProvider
from .server import serve


def main() -> None:
    settings = Settings.from_env()
    if not 1 <= settings.port <= 65535:
        raise SystemExit("AGENT_PORT precisa estar entre 1 e 65535.")
    if not settings.api_key:
        raise SystemExit("Configure AGENT_API_KEY no arquivo .env antes de iniciar o agente.")
    endpoint = urlsplit(settings.base_url)
    if endpoint.scheme not in ("https", "http") or not endpoint.netloc:
        raise SystemExit("Configure AGENT_BASE_URL com o endpoint documentado pelo seu provedor.")
    if not settings.model:
        raise SystemExit("Configure AGENT_MODEL com o identificador exato do modelo.")
    if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.access_token:
        raise SystemExit("Defina AGENT_ACCESS_TOKEN antes de escutar em uma interface de rede.")
    history = HistoryStore(settings.database_path, settings.history_limit)
    serve(Agent(ChatProvider(settings), history), settings.host, settings.port)


if __name__ == "__main__":
    main()
