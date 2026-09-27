"""Cliente mínimo para provedores compatíveis com Chat Completions."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings


class ProviderError(RuntimeError):
    """Erro seguro de comunicação com o provedor."""


class ChatProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, message: str) -> str:
        if not self.settings.api_key:
            raise ProviderError("Configure AGENT_API_KEY no ambiente antes de conversar.")

        payload = json.dumps({
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": self.settings.system_prompt},
                {"role": "user", "content": message},
            ],
        }).encode("utf-8")
        request = Request(
            f"{self.settings.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # Não propaga o corpo do provedor, que pode conter dados sensíveis.
            raise ProviderError(f"O provedor recusou a solicitação (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError("Não foi possível obter resposta do provedor; verifique rede e configuração.") from None

        try:
            answer = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("O provedor retornou uma resposta em formato inesperado.") from None
        if not isinstance(answer, str) or not answer.strip():
            raise ProviderError("O provedor retornou uma resposta vazia.")
        return answer.strip()
