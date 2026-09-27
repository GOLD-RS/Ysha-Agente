"""Adapter síncrono para a API OpenAI Chat Completions."""

import http.client
import json
import math
import socket
import ssl
import time
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ProviderConfig, Settings, validate_base_url

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOOL_CALLS = 8
MAX_TOOL_NAME_LENGTH = 128
MAX_TOOL_ARGUMENTS_LENGTH = 65_536
READ_CHUNK_BYTES = 64 * 1024
TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class ProviderError(RuntimeError):
    """Erro seguro; subclasses indicam se a falha pode ser transitória."""

    retryable = False


class TransientProviderError(ProviderError):
    retryable = True


class ProviderConfigurationError(ProviderError):
    """Falha permanente de configuração/credenciais, sem dados sensíveis."""


class ProviderContractError(ProviderError):
    """Falha permanente no formato/conteúdo devolvido pelo provider."""


class Provider(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        ...


def _reject_non_json_constant(_value: str):
    raise ValueError("non-standard JSON constant")


def _finite_json_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


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
            parse_float=_finite_json_float,
        )
    except (json.JSONDecodeError, ValueError, TypeError, RecursionError):
        raise ProviderContractError("O provider retornou argumentos de ferramenta inválidos.") from None
    if not isinstance(value, dict):
        raise ProviderContractError("Os argumentos da ferramenta precisam ser um objeto JSON.")
    return value


def validate_assistant_message(message, *, require_role: bool = True) -> dict:
    """Validate and normalize one assistant message before agent/tool dispatch."""
    if not isinstance(message, dict):
        raise ProviderContractError("O provider retornou uma mensagem em formato incompatível.")
    role = message.get("role")
    if role is None and not require_role:
        role = "assistant"
    if role != "assistant":
        raise ProviderContractError("O provider retornou uma mensagem com papel incompatível.")

    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ProviderContractError("O provider retornou conteúdo em formato incompatível.")

    raw_calls = message.get("tool_calls", [])
    if raw_calls is None:
        raw_calls = []
    if not isinstance(raw_calls, list) or len(raw_calls) > MAX_TOOL_CALLS:
        raise ProviderContractError("O provider retornou chamadas de ferramenta inválidas.")

    calls = []
    seen_ids = set()
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            raise ProviderContractError("O provider retornou chamadas de ferramenta inválidas.")
        call_id = raw_call.get("id")
        if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 128 or call_id in seen_ids:
            raise ProviderContractError("O provider retornou um identificador de ferramenta inválido.")
        seen_ids.add(call_id)
        if raw_call.get("type") != "function":
            raise ProviderContractError("O provider retornou um tipo de ferramenta incompatível.")
        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise ProviderContractError("O provider retornou uma função em formato incompatível.")
        name = function.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_TOOL_NAME_LENGTH:
            raise ProviderContractError("O provider retornou uma função sem nome válido.")
        raw_arguments = function.get("arguments")
        if not isinstance(raw_arguments, str) or len(raw_arguments) > MAX_TOOL_ARGUMENTS_LENGTH:
            raise ProviderContractError("O provider retornou argumentos em formato incompatível.")
        _parse_tool_arguments(raw_arguments)
        calls.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": raw_arguments},
        })

    if not calls and (not isinstance(content, str) or not content.strip()):
        raise ProviderContractError("O provider retornou uma resposta sem conteúdo.")
    return {"role": "assistant", "content": content, "tool_calls": calls}


def validate_chat_completion(payload) -> dict:
    """Validate the Chat Completions envelope and return its assistant message."""
    if not isinstance(payload, dict):
        raise ProviderContractError("O provider retornou uma resposta em formato incompatível.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderContractError("O provider retornou uma resposta em formato incompatível.")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and (not isinstance(finish_reason, str) or finish_reason not in {
        "stop", "tool_calls", "function_call", "length", "content_filter"
    }):
        raise ProviderContractError("O provider retornou um motivo de conclusão incompatível.")
    message = validate_assistant_message(choice.get("message"), require_role=True)
    has_calls = bool(message["tool_calls"])
    if finish_reason in ("tool_calls", "function_call") and not has_calls:
        raise ProviderContractError("O provider indicou ferramentas sem fornecer chamadas válidas.")
    if finish_reason in ("length", "content_filter") and has_calls:
        raise ProviderContractError("A resposta do provider foi interrompida durante uma chamada de ferramenta.")
    return message


def _response_socket(response):
    file_obj = getattr(response, "fp", None)
    raw = getattr(file_obj, "raw", None)
    return getattr(raw, "_sock", None)


def _read_bounded_body(response, deadline: float) -> bytes:
    sock = _response_socket(response)
    if sock is None and not hasattr(response, "read1"):
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if not isinstance(body, bytes):
            raise ProviderContractError("O provider retornou um corpo de resposta inválido.")
        if len(body) > MAX_RESPONSE_BYTES:
            raise ProviderContractError("A resposta do provider excedeu o limite de tamanho permitido.")
        return body
    body = bytearray()
    while len(body) <= MAX_RESPONSE_BYTES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransientProviderError("O provider excedeu o tempo limite da solicitação.")
        if sock is not None:
            sock.settimeout(remaining)
        reader = getattr(response, "read1", response.read)
        chunk = reader(min(READ_CHUNK_BYTES, MAX_RESPONSE_BYTES + 1 - len(body)))
        if not isinstance(chunk, bytes):
            raise ProviderContractError("O provider retornou um corpo de resposta inválido.")
        if not chunk:
            break
        body.extend(chunk)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProviderContractError("A resposta do provider excedeu o limite de tamanho permitido.")
    return bytes(body)


class ChatProvider:
    """Adapter compatível com a configuração antiga e com perfis ProviderConfig."""

    def __init__(self, settings: Settings | ProviderConfig):
        self.settings = settings
        if isinstance(settings, Settings) and settings.provider_profiles:
            selected_profile = next(
                (item for item in settings.provider_profiles if item.name == settings.selected_provider),
                settings.provider_profiles[0],
            )
            self.timeout_seconds = selected_profile.timeout_seconds
        else:
            self.timeout_seconds = getattr(settings, "timeout_seconds", 30.0)

    def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout: float | None = None,
    ) -> dict:
        if not self.settings.api_key:
            raise ProviderConfigurationError("O provider selecionado não tem credencial configurada.")
        try:
            validate_base_url(self.settings.base_url)
        except ValueError:
            raise ProviderConfigurationError("A URL do provider não passou na validação de segurança.") from None

        call_timeout = self.timeout_seconds if timeout is None else min(self.timeout_seconds, timeout)
        if not math.isfinite(call_timeout) or call_timeout <= 0:
            raise TransientProviderError("O tempo disponível para consultar o provider terminou.")
        deadline = time.monotonic() + call_timeout
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
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransientProviderError("O tempo disponível para consultar o provider terminou.")
        try:
            with urlopen(request, timeout=remaining) as response:
                body = _read_bounded_body(response, deadline)
        except ProviderError:
            raise
        except HTTPError as exc:
            if exc.code in TRANSIENT_HTTP_STATUS:
                raise TransientProviderError("O provider está temporariamente indisponível.") from None
            raise ProviderError("O provider recusou a solicitação.") from None
        except URLError as exc:
            if isinstance(exc.reason, ssl.SSLError):
                raise ProviderConfigurationError("A conexão segura com o provider não pôde ser validada.") from None
            if (
                isinstance(exc.reason, socket.gaierror)
                and getattr(socket, "EAI_NONAME", None) is not None
                and exc.reason.errno == socket.EAI_NONAME
            ):
                raise ProviderConfigurationError("O host configurado para o provider não foi encontrado.") from None
            raise TransientProviderError("Não foi possível conectar ao provider.") from None
        except ssl.SSLError:
            raise ProviderConfigurationError("A conexão segura com o provider não pôde ser validada.") from None
        except (socket.timeout, TimeoutError):
            raise TransientProviderError("O provider excedeu o tempo limite da solicitação.") from None
        except (OSError, http.client.HTTPException):
            raise TransientProviderError("A conexão com o provider foi interrompida.") from None

        try:
            response_payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_non_json_constant,
                parse_float=_finite_json_float,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError, RecursionError):
            raise ProviderContractError("O provider retornou uma resposta JSON incompatível.") from None
        return validate_chat_completion(response_payload)
