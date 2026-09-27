"""Configuração via ambiente, sem dependências externas."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    host: str
    port: int
    system_prompt: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_key=os.getenv("AGENT_API_KEY", "").strip(),
            base_url=os.getenv("AGENT_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            model=os.getenv("AGENT_MODEL", "gpt-4o-mini"),
            host=os.getenv("AGENT_HOST", "127.0.0.1"),
            port=int(os.getenv("AGENT_PORT", "8765")),
            system_prompt=os.getenv(
                "AGENT_SYSTEM_PROMPT",
                "Você é um assistente útil, cuidadoso e objetivo.",
            ),
        )
