"""Configuração via ambiente, sem dependências externas."""

from dataclasses import dataclass, field
import ipaddress
import math
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
class ProviderConfig:
    """Private configuration for one provider/model profile."""

    name: str
    adapter: str
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout_seconds: float = 30.0
    max_retries: int = 1


def _provider_ids(raw: str, variable: str) -> tuple[str, ...]:
    if not raw.strip():
        return ()
    names = tuple(item.strip() for item in raw.split(","))
    if (
        len(names) > 8
        or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name) for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError(f"{variable} precisa conter até oito IDs únicos em minúsculas.")
    return names


def _read_float(variable: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(variable, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{variable} precisa ser um número válido.") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{variable} precisa estar entre {minimum} e {maximum} segundos.")
    return value


def _read_int(variable: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(variable, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{variable} precisa ser um número inteiro.") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{variable} precisa estar entre {minimum} e {maximum}.")
    return value


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    access_token: str = field(repr=False)
    base_url: str
    model: str
    host: str
    port: int
    system_prompt: str
    database_path: str
    history_limit: int
    provider_profiles: tuple[ProviderConfig, ...] = ()
    selected_provider: str = "default"
    fallback_providers: tuple[str, ...] = ()
    provider_total_timeout_seconds: float = 90.0
    provider_max_attempts_per_response: int = 8

    @classmethod
    def from_env(cls) -> "Settings":
        history_limit = max(2, min(100, int(os.getenv("AGENT_HISTORY_LIMIT", "20"))))
        history_limit -= history_limit % 2

        ids = _provider_ids(os.getenv("AGENT_PROVIDER_IDS", ""), "AGENT_PROVIDER_IDS")
        selected = os.getenv("AGENT_PROVIDER_SELECTED", "").strip()
        fallbacks = _provider_ids(os.getenv("AGENT_PROVIDER_FALLBACKS", ""), "AGENT_PROVIDER_FALLBACKS")
        total_timeout = _read_float("AGENT_PROVIDER_TOTAL_TIMEOUT_SECONDS", 90.0, 0.1, 180.0)
        max_attempts = _read_int("AGENT_PROVIDER_MAX_ATTEMPTS_PER_RESPONSE", 8, 1, 24)
        if ids:
            selected = selected or ids[0]
            if selected not in ids or selected in fallbacks or any(item not in ids for item in fallbacks):
                raise ValueError("Seleção/fallback deve referenciar IDs configurados e distintos.")
            profiles = []
            for name in ids:
                prefix = f"AGENT_PROVIDER_{name.upper()}_"
                profiles.append(ProviderConfig(
                    name=name,
                    adapter=os.getenv(prefix + "TYPE", "chat_completions").strip(),
                    api_key=os.getenv(prefix + "API_KEY", "").strip(),
                    base_url=os.getenv(prefix + "BASE_URL", "").strip().rstrip("/"),
                    model=os.getenv(prefix + "MODEL", "").strip(),
                    timeout_seconds=_read_float(prefix + "TIMEOUT_SECONDS", 30.0, 0.1, 90.0),
                    max_retries=_read_int(prefix + "MAX_RETRIES", 1, 0, 2),
                ))
            selected_profile = next(item for item in profiles if item.name == selected)
            provider_profiles = tuple(profiles)
        else:
            if selected or fallbacks:
                raise ValueError("Defina AGENT_PROVIDER_IDS antes de selecionar ou configurar fallbacks.")
            legacy = ProviderConfig(
                name="default",
                adapter="chat_completions",
                api_key=os.getenv("AGENT_API_KEY", "").strip(),
                base_url=os.getenv("AGENT_BASE_URL", "").strip().rstrip("/"),
                model=os.getenv("AGENT_MODEL", "").strip(),
                timeout_seconds=_read_float("AGENT_PROVIDER_TIMEOUT_SECONDS", 90.0, 0.1, 90.0),
                max_retries=_read_int("AGENT_PROVIDER_MAX_RETRIES", 1, 0, 2),
            )
            provider_profiles = (legacy,)
            selected = "default"
            selected_profile = legacy

        return cls(
            api_key=selected_profile.api_key,
            access_token=os.getenv("AGENT_ACCESS_TOKEN", "").strip(),
            base_url=selected_profile.base_url,
            model=selected_profile.model,
            host=os.getenv("AGENT_HOST", "127.0.0.1"),
            port=int(os.getenv("AGENT_PORT", "8765")),
            system_prompt=os.getenv(
                "AGENT_SYSTEM_PROMPT",
                "Você é Ysha Agente, um assistente útil, cuidadoso e objetivo. "
                "Peça confirmação antes de ações externas ou irreversíveis.",
            ),
            database_path=os.getenv("AGENT_DB_PATH", "data/ysha-agent.sqlite3"),
            history_limit=history_limit,
            provider_profiles=provider_profiles,
            selected_provider=selected,
            fallback_providers=fallbacks,
            provider_total_timeout_seconds=total_timeout,
            provider_max_attempts_per_response=max_attempts,
        )


def validate_settings(settings: Settings) -> None:
    if not 1 <= settings.port <= 65535:
        raise ValueError("AGENT_PORT precisa estar entre 1 e 65535.")
    if type(settings.provider_max_attempts_per_response) is not int or not 1 <= settings.provider_max_attempts_per_response <= 24:
        raise ValueError("AGENT_PROVIDER_MAX_ATTEMPTS_PER_RESPONSE precisa estar entre 1 e 24.")
    profiles = settings.provider_profiles
    if not profiles:
        if not settings.api_key:
            raise ValueError("Configure AGENT_API_KEY no arquivo .env antes de iniciar o agente.")
        validate_base_url(settings.base_url)
        if not settings.model:
            raise ValueError("Configure AGENT_MODEL com o identificador exato do modelo.")
    else:
        names = [profile.name for profile in profiles]
        if len(names) > 8 or len(set(names)) != len(names):
            raise ValueError("Configure até oito IDs de provider únicos.")
        if settings.selected_provider not in names:
            raise ValueError("AGENT_PROVIDER_SELECTED não corresponde a um provider configurado.")
        if (
            len(set(settings.fallback_providers)) != len(settings.fallback_providers)
            or settings.selected_provider in settings.fallback_providers
            or any(name not in names for name in settings.fallback_providers)
        ):
            raise ValueError("AGENT_PROVIDER_FALLBACKS contém IDs ausentes ou repetidos.")
        if (
            not isinstance(settings.provider_total_timeout_seconds, (int, float))
            or isinstance(settings.provider_total_timeout_seconds, bool)
            or not math.isfinite(settings.provider_total_timeout_seconds)
            or not 0.1 <= settings.provider_total_timeout_seconds <= 180
        ):
            raise ValueError("AGENT_PROVIDER_TOTAL_TIMEOUT_SECONDS está fora do intervalo permitido.")
        for profile in profiles:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", profile.name):
                raise ValueError("ID de provider inválido.")
            if profile.adapter != "chat_completions":
                raise ValueError(f"Tipo de adapter não suportado para provider {profile.name}.")
            if not profile.api_key:
                variable = "AGENT_API_KEY" if profile.name == "default" and len(profiles) == 1 else f"AGENT_PROVIDER_{profile.name.upper()}_API_KEY"
                raise ValueError(f"Configure {variable} para o provider {profile.name}.")
            validate_base_url(profile.base_url)
            if not profile.model:
                raise ValueError(f"Configure o modelo para o provider {profile.name}.")
            if (
                not isinstance(profile.timeout_seconds, (int, float))
                or isinstance(profile.timeout_seconds, bool)
                or not math.isfinite(profile.timeout_seconds)
                or not 0.1 <= profile.timeout_seconds <= 90
            ):
                raise ValueError(f"Timeout inválido para o provider {profile.name}.")
            if type(profile.max_retries) is not int or not 0 <= profile.max_retries <= 2:
                raise ValueError(f"Número de tentativas inválido para o provider {profile.name}.")
    if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.access_token:
        raise ValueError("Defina AGENT_ACCESS_TOKEN antes de escutar em uma interface de rede.")
