"""Configuração via ambiente, sem dependências externas."""

from dataclasses import dataclass
import ipaddress
import os
from urllib.parse import urlsplit


def validate_base_url(value: str) -> None:
    """Reject malformed endpoints and plaintext remote credential transport."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("AGENT_BASE_URL está malformada.") from None
    if parsed.scheme not in ("https", "http") or not host:
        raise ValueError("AGENT_BASE_URL precisa usar http:// ou https:// e conter um host.")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise ValueError("AGENT_BASE_URL não pode incluir credenciais, query ou fragmento.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("A porta de AGENT_BASE_URL está fora do intervalo válido.")
    if parsed.scheme == "http":
        is_loopback = host.lower() == "localhost"
        try:
            is_loopback = is_loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if not is_loopback:
            raise ValueError("Use HTTPS para provedores remotos; HTTP só é permitido em localhost.")


@dataclass(frozen=True)
class Settings:
    api_key: str
    access_token: str
    base_url: str
    model: str
    host: str
    port: int
    system_prompt: str
    database_path: str
    history_limit: int

    @classmethod
    def from_env(cls) -> "Settings":
        history_limit = max(2, min(100, int(os.getenv("AGENT_HISTORY_LIMIT", "20"))))
        history_limit -= history_limit % 2
        return cls(
            api_key=os.getenv("AGENT_API_KEY", "").strip(),
            access_token=os.getenv("AGENT_ACCESS_TOKEN", "").strip(),
            base_url=os.getenv("AGENT_BASE_URL", "").strip().rstrip("/"),
            model=os.getenv("AGENT_MODEL", "").strip(),
            host=os.getenv("AGENT_HOST", "127.0.0.1"),
            port=int(os.getenv("AGENT_PORT", "8765")),
            system_prompt=os.getenv(
                "AGENT_SYSTEM_PROMPT",
                "Você é Ysha Agente, um assistente útil, cuidadoso e objetivo. "
                "Peça confirmação antes de ações externas ou irreversíveis.",
            ),
            database_path=os.getenv("AGENT_DB_PATH", "data/ysha-agent.sqlite3"),
            history_limit=history_limit,
        )
