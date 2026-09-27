"""Configuração via ambiente, sem dependências externas."""

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re
import shlex
from typing import MutableMapping
from urllib.parse import urlsplit

_ENV_ASSIGNMENT = re.compile(r"^\s*(AGENT_[A-Z0-9_]+)\s*=\s*(.*)$")


class EnvironmentFileError(ValueError):
    """Safe, user-facing error for a malformed local configuration file."""


def parse_env_text(content: str) -> dict[str, str]:
    """Parse the project's assignment format without expanding or executing it."""
    values: dict[str, str] = {}
    for line_number, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_ASSIGNMENT.fullmatch(line)
        if not match:
            raise EnvironmentFileError(f"Formato inválido em .env na linha {line_number}.")
        name, raw_value = match.groups()
        try:
            parts = shlex.split(raw_value, comments=False, posix=True)
        except ValueError:
            raise EnvironmentFileError(f"Valor malformado em .env na linha {line_number}.") from None
        if len(parts) > 1:
            raise EnvironmentFileError(f"Use um único valor citado em .env na linha {line_number}.")
        values[name] = parts[0] if parts else ""
    return values


def load_env_file(path: str | Path, environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    """Load AGENT_* settings as data; file values override inherited variables."""
    config_path = Path(path)
    if config_path.is_symlink():
        raise EnvironmentFileError("Por segurança, .env não pode ser um link simbólico.")
    try:
        content = config_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise EnvironmentFileError("Não foi possível ler o arquivo .env local.") from None
    values = parse_env_text(content)
    target = os.environ if environ is None else environ
    target.update(values)
    return values


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


def validate_settings(settings: Settings) -> None:
    if not 1 <= settings.port <= 65535:
        raise ValueError("AGENT_PORT precisa estar entre 1 e 65535.")
    if not settings.api_key:
        raise ValueError("Configure AGENT_API_KEY no arquivo .env antes de iniciar o agente.")
    validate_base_url(settings.base_url)
    if not settings.model:
        raise ValueError("Configure AGENT_MODEL com o identificador exato do modelo.")
    if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.access_token:
        raise ValueError("Defina AGENT_ACCESS_TOKEN antes de escutar em uma interface de rede.")
