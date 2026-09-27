"""Orquestração de turnos usando provider, contexto, sessão, memória e política."""

import re

from .context import ContextBuilder
from .memory import ConversationMemory
from .policy import ToolPolicy
from .provider import Provider, ProviderError, validate_assistant_message
from .sessions import SessionCoordinator
from .tools import TOOL_DEFINITIONS

SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Agent:
    def __init__(
        self,
        provider: Provider,
        memory: ConversationMemory,
        *,
        system_prompt: str = "",
        context_builder: ContextBuilder | None = None,
        sessions: SessionCoordinator | None = None,
        tool_policy: ToolPolicy | None = None,
    ):
        self.provider = provider
        self.memory = memory
        self.context_builder = context_builder or ContextBuilder(memory, system_prompt)
        self.sessions = sessions or SessionCoordinator()
        self.tool_policy = tool_policy or ToolPolicy()

    def respond(self, session_id: str, message: str) -> str:
        if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
            raise ValueError("Identificador de sessão inválido.")
        message = message.strip() if isinstance(message, str) else ""
        if not message:
            raise ValueError("A mensagem não pode ficar vazia.")
        if len(message) > 12_000:
            raise ValueError("A mensagem excede o limite de 12.000 caracteres.")

        with self.sessions.hold(session_id):
            return self._respond_locked(session_id, message)

    def _respond_locked(self, session_id: str, message: str) -> str:
        messages = self.context_builder.for_turn(session_id, message)
        tool_budget = 8
        for _ in range(4):
            raw_answer = self.provider.complete(messages, TOOL_DEFINITIONS)
            answer = validate_assistant_message(raw_answer, require_role=False)
            calls = answer["tool_calls"]
            if len(calls) > tool_budget:
                raise ProviderError("O agente excedeu o limite de ferramentas por resposta.")
            if not calls:
                text = answer["content"]
                if not isinstance(text, str) or not text.strip():
                    raise ProviderError("O provedor retornou uma resposta vazia.")
                text = text.strip()
                self.memory.add_exchange(session_id, message, text)
                return text

            tool_budget -= len(calls)
            messages.append({
                "role": "assistant",
                "content": answer["content"],
                "tool_calls": calls,
            })
            for call in calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": self.tool_policy.execute_call(call),
                })

        raise ProviderError("O agente atingiu o limite de chamadas de ferramentas nesta resposta.")
