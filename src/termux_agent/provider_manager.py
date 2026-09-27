"""Seleção e política limitada de retry/fallback para providers configurados."""

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging
import math
import re
import time
from typing import Protocol

from .config import ProviderConfig, Settings
from .provider import (
    ChatProvider,
    ProviderConfigurationError,
    ProviderError,
)

logger = logging.getLogger(__name__)


class ProviderManagerError(ProviderError):
    """Falha pública estável do manager; nunca inclui dados do adapter."""

    def __init__(self, error_code: str, http_status: int, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.http_status = http_status


class _TimedAdapter(Protocol):
    def complete(self, messages: list[dict], tools: list[dict], *, timeout: float) -> dict:
        ...


@dataclass
class _RequestBudget:
    deadline: float
    attempts: int = 0


class ProviderManager:
    BACKOFF_BASE_SECONDS = 0.25
    BACKOFF_MAX_SECONDS = 1.0

    def __init__(
        self,
        settings: Settings,
        *,
        adapter_factories: Mapping[str, Callable[[ProviderConfig], _TimedAdapter]] | None = None,
    ):
        profiles = settings.provider_profiles
        if not profiles:
            profiles = (ProviderConfig(
                name="default",
                adapter="chat_completions",
                api_key=settings.api_key,
                base_url=settings.base_url,
                model=settings.model,
            ),)
        by_name = {profile.name: profile for profile in profiles}
        if len(profiles) > 8 or len(by_name) != len(profiles):
            raise ProviderConfigurationError("Há IDs de provider repetidos ou acima do limite.")
        for profile in profiles:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", profile.name):
                raise ProviderConfigurationError("Há um ID de provider inválido na configuração.")
            if (
                not isinstance(profile.timeout_seconds, (int, float))
                or isinstance(profile.timeout_seconds, bool)
                or not math.isfinite(profile.timeout_seconds)
                or not 0.1 <= profile.timeout_seconds <= 90
                or type(profile.max_retries) is not int
                or not 0 <= profile.max_retries <= 2
            ):
                raise ProviderConfigurationError("Timeout ou limite de retry de provider inválido.")
        selected = settings.selected_provider if settings.provider_profiles else "default"
        if selected not in by_name:
            raise ProviderConfigurationError("O provider selecionado não está configurado.")
        fallbacks = settings.fallback_providers
        if (
            len(set(fallbacks)) != len(fallbacks)
            or selected in fallbacks
            or any(name not in by_name for name in fallbacks)
        ):
            raise ProviderConfigurationError("A lista de fallback referencia providers inválidos.")
        total_timeout = settings.provider_total_timeout_seconds
        if (
            not isinstance(total_timeout, (int, float))
            or isinstance(total_timeout, bool)
            or not math.isfinite(total_timeout)
            or not 0.1 <= total_timeout <= 180
        ):
            raise ProviderConfigurationError("O limite total de tempo está inválido.")
        max_attempts = settings.provider_max_attempts_per_response
        if type(max_attempts) is not int or not 1 <= max_attempts <= 24:
            raise ProviderConfigurationError("O limite total de tentativas está inválido.")

        factories: dict[str, Callable[[ProviderConfig], _TimedAdapter]] = {
            "chat_completions": ChatProvider,
        }
        if adapter_factories:
            factories.update(adapter_factories)
        adapters: dict[str, _TimedAdapter] = {}
        for profile in profiles:
            factory = factories.get(profile.adapter)
            if factory is None:
                raise ProviderConfigurationError("A configuração seleciona um tipo de provider não suportado.")
            try:
                adapter = factory(profile)
            except Exception:
                raise ProviderConfigurationError("Não foi possível criar o adapter do provider configurado.") from None
            if not callable(getattr(adapter, "complete", None)):
                raise ProviderConfigurationError("O adapter do provider não implementa a operação de conclusão.")
            adapters[profile.name] = adapter

        self._profiles = by_name
        self._adapters = adapters
        self._selected = selected
        self._fallbacks = fallbacks
        self._total_timeout = total_timeout
        self._max_attempts = max_attempts
        self._request_budget: ContextVar[_RequestBudget | None] = ContextVar(
            f"provider_request_budget_{id(self)}",
            default=None,
        )

    @property
    def selected_provider(self) -> str:
        return self._selected

    @contextmanager
    def response_scope(self):
        """Share one deadline/attempt budget across a full Agent turn, including tool calls."""
        current = self._request_budget.get()
        if current is not None:
            yield current
            return
        token = self._request_budget.set(
            _RequestBudget(deadline=time.monotonic() + self._total_timeout)
        )
        try:
            yield self._request_budget.get()
        finally:
            self._request_budget.reset(token)

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        if self._request_budget.get() is None:
            with self.response_scope():
                return self.complete(messages, tools)
        return self._complete_in_scope(messages, tools, self._request_budget.get())

    def _complete_in_scope(self, messages, tools, budget: _RequestBudget) -> dict:
        sequence = (self._selected, *self._fallbacks)
        for provider_index, provider_id in enumerate(sequence):
            profile = self._profiles[provider_id]
            adapter = self._adapters[provider_id]
            for attempt_index in range(profile.max_retries + 1):
                remaining = budget.deadline - time.monotonic()
                if remaining <= 0:
                    raise self._timeout_error()
                if budget.attempts >= self._max_attempts:
                    raise self._attempt_limit_error()
                budget.attempts += 1
                timeout = min(profile.timeout_seconds, remaining)
                try:
                    result = adapter.complete(messages, tools, timeout=timeout)
                except ProviderError as exc:
                    retryable = bool(getattr(exc, "retryable", False))
                    self._log_failure(provider_id, attempt_index + 1, retryable)
                    if not retryable:
                        raise self._failure_error() from None
                except (TimeoutError, ConnectionError):
                    retryable = True
                    self._log_failure(provider_id, attempt_index + 1, True)
                except Exception:
                    # An unclassified adapter/programming error is permanent; do not hide it with fallback.
                    self._log_failure(provider_id, attempt_index + 1, False)
                    raise self._failure_error() from None
                else:
                    if time.monotonic() >= budget.deadline:
                        self._log_failure(provider_id, attempt_index + 1, True)
                        raise self._timeout_error()
                    if provider_id != self._selected:
                        logger.warning("provider_fallback_succeeded provider_id=%s", provider_id)
                    return result

                if attempt_index < profile.max_retries:
                    if budget.attempts >= self._max_attempts:
                        raise self._attempt_limit_error()
                    remaining = budget.deadline - time.monotonic()
                    delay = min(
                        self.BACKOFF_BASE_SECONDS * (2 ** attempt_index),
                        self.BACKOFF_MAX_SECONDS,
                        remaining,
                    )
                    if delay <= 0:
                        raise self._timeout_error()
                    time.sleep(delay)
                    if time.monotonic() >= budget.deadline:
                        raise self._timeout_error()
                    continue
                # Only an exhausted transient failure can advance to the configured fallback.
                break

            if provider_index < len(sequence) - 1:
                if budget.attempts >= self._max_attempts:
                    raise self._attempt_limit_error()
                logger.warning(
                    "provider_fallback_started provider_id=%s next_provider_id=%s",
                    provider_id,
                    sequence[provider_index + 1],
                )

        raise ProviderManagerError(
            "providers_unavailable",
            503,
            "Todos os providers configurados estão temporariamente indisponíveis.",
        )

    @staticmethod
    def _log_failure(provider_id: str, attempt: int, retryable: bool) -> None:
        logger.warning(
            "provider_attempt_failed provider_id=%s attempt=%d category=%s",
            provider_id,
            attempt,
            "transient" if retryable else "permanent",
        )

    @staticmethod
    def _failure_error() -> ProviderManagerError:
        return ProviderManagerError(
            "provider_failure",
            502,
            "O provider selecionado falhou ao processar a solicitação.",
        )

    @staticmethod
    def _attempt_limit_error() -> ProviderManagerError:
        return ProviderManagerError(
            "provider_attempt_limit",
            503,
            "O limite total de tentativas de provider para esta resposta foi atingido.",
        )

    @staticmethod
    def _timeout_error() -> ProviderManagerError:
        return ProviderManagerError(
            "provider_timeout",
            504,
            "O tempo limite total para obter uma resposta foi excedido.",
        )
