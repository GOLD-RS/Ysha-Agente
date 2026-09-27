"""Cliente e contrato estrito para provedores OpenAI Chat Completions."""

import http.client
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings, validate_base_url

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOOL_CALLS = 8
MAX_TOOL_NAME_LENGTH = 128
MAX_TOOL_ARGUMENTS_LENGTH = 65_536


class ProviderError(RuntimeError):
    """Erro seguro de comunicação ou de contrato do provedor."""


def _reject_non_json_constant(_value: str):
    raise ValueError("non-standard JSON constant")


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_tool_arguments(raw: str) -> dict:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_non_json_constant,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        raise ProviderError("O provedor retornou argumentos de ferramenta inválidos.") from None
    if not isinstance(value, dict):
        raise ProviderError("Os argumentos da ferramenta precisam ser um objeto JSON.")
    return value


def validate_assistant_message(message, *, require_role: bool = True) -> dict:
    """Validate and normalize one assistant message before agent/tool dispatch."""
    if not isinstance(message, dict):
        raise ProviderError("O provedor retornou uma mensagem em formato incompatível.")
    role = message.get("role")
    if role is None and not require_role:
        role = "assistant"
    if role != "assistant":
        raise ProviderError("O provedor retornou uma mensagem com papel incompatível.")

    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ProviderError("O provedor retornou conteúdo em formato incompatível.")

    raw_calls = message.get("tool_calls", [])
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list) or len(raw_calls) > MAX_TOOL_CALLS:
        raise ProviderError("O provedor retornou chamadas de ferramenta inválidas.")

    calls = []
    seen_ids = set()
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ProviderError("O provedor retornou chamadas de ferramenta inválidas.")
        call_id = raw_call.get("id")
        if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 128 or call_id in seen_ids:
            raise ProviderError("O provedor retornou um identificador de ferramenta inválido.")
        seen_ids.add(call_id)
        if raw_call.get("type") != "function":
            raise ProviderError("O provedor retornou um tipo de ferramenta incompatível.")
        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise ProviderError("O provedor retornou uma função em formato incompatível.")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_TOOL_NAME_LENGTH:
            raise ProviderError("O provedor retornou uma função sem nome válido.")
        raw_arguments = function.get("arguments")
        if not isinstance(raw_arguments, str) or len(raw_arguments) > MAX_TOOL_ARGUMENTS_LENGTH:
            raise ProviderError("O provedor retornou argumentos em formato incompatível.")
        _parse_tool_arguments(raw_arguments)
        calls.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": raw_arguments},
        })

    if not calls and (not isinstance(content, str) or not content.strip()):
        raise ProviderError("O provedor retornou uma resposta sem conteúdo.")
    return {"role": "assistant", "content": content, "tool_calls": calls}


def validate_chat_completion(payload) -> dict:
    """Validate the documented Chat Completions envelope and return its message."""
    if not isinstance(payload, dict):
        raise ProviderError("O provedor retornou uma resposta em formato incompatível.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderError("O provedor retornou uma resposta em formato incompatível.")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and (not isinstance(finish_reason, str) or finish_reason not in {
        "stop", "tool_calls", "function_call", "length", "content_filter"
    }):
        raise ProviderError("O provedor retornou um motivo de conclusão incompatível.")
    message = validate_assistant_message(choice.get("message"), require_role=True)
    has_calls = bool(message["tool_calls"])
    if finish_reason in ("tool_calls", "function_call") and not has_calls:
        raise ProviderError("O provedor indicou ferramentas sem fornecer chamadas válidas.")
    if finish_reason in ("length", "content_filter") and has_calls:
        raise ProviderError("A resposta do provedor foi interrompida durante uma chamada de ferramenta.")
    return message


class ChatProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        if not self.settings.api_key:
            raise ProviderError("Configure AGENT_API_KEY no ambiente antes de conversar.")
        try:
            validate_base_url(self.settings.base_url)
        except ValueError as exc:
            raise ProviderError(str(exc)) from None

        payload = json.dumps({
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
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
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if not isinstance(body, bytes):
                    raise ProviderError("O provedor retornou um corpo de resposta inválido.")
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProviderError("A resposta do provedor excedeu o limite de tamanho permitido.")
                payload = json.loads(body.decode("utf-8"))
        except ProviderError:
            raise
        except HTTPError as exc:
            raise ProviderError(f"O provedor recusou a solicitação (HTTP {exc.code}).") from None
        except (URLError, TimeoutError, OSError, http.client.HTTPException, json.JSONDecodeError, UnicodeDecodeError):
            raise ProviderError("Não foi possível obter resposta do provedor; verifique rede e configuração.") from None

        return validate_chat_completion(payload)
