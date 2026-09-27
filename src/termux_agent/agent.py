"""Agente com histórico por sessão e execução limitada de ferramentas."""

import json

from .history import HistoryStore
from .provider import ChatProvider, ProviderError
from .tools import TOOL_DEFINITIONS, ToolError, run_tool


class Agent:
    def __init__(self, provider: ChatProvider, history: HistoryStore):
        self.provider = provider
        self.history = history

    def respond(self, session_id: str, message: str) -> str:
        message = message.strip()
        if not message:
            raise ValueError("A mensagem não pode ficar vazia.")
        if len(message) > 12_000:
            raise ValueError("A mensagem excede o limite de 12.000 caracteres.")

        messages = [{"role": "system", "content": self.provider.settings.system_prompt}]
        messages.extend(self.history.get(session_id))
        messages.append({"role": "user", "content": message})

        tool_budget = 8
        for _ in range(4):
            answer = self.provider.complete(messages, TOOL_DEFINITIONS)
            calls = answer.get("tool_calls") or []
            if not isinstance(calls, list):
                raise ProviderError("O provedor retornou chamadas de ferramentas inválidas.")
            if len(calls) > tool_budget:
                raise ProviderError("O agente excedeu o limite de ferramentas por resposta.")
            if not calls:
                text = answer.get("content")
                if not isinstance(text, str) or not text.strip():
                    raise ProviderError("O provedor retornou uma resposta vazia.")
                text = text.strip()
                self.history.add_exchange(session_id, message, text)
                return text

            if any(not isinstance(call, dict) for call in calls):
                raise ProviderError("O provedor retornou chamadas de ferramentas inválidas.")
            tool_budget -= len(calls)
            messages.append({
                "role": "assistant",
                "content": answer.get("content"),
                "tool_calls": calls,
            })
            for call in calls:
                call_id = call.get("id", "")
                function = call.get("function", {})
                if not isinstance(function, dict) or not isinstance(call_id, str):
                    raise ProviderError("O provedor retornou chamadas de ferramentas inválidas.")
                name = function.get("name", "")
                try:
                    arguments = json.loads(function.get("arguments", "{}"))
                    if not isinstance(arguments, dict):
                        raise ToolError("Argumentos inválidos.")
                    result = run_tool(name, arguments)
                except (json.JSONDecodeError, ToolError, TypeError):
                    result = "Erro: argumentos inválidos ou ferramenta não permitida."
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})

        raise ProviderError("O agente atingiu o limite de chamadas de ferramentas nesta resposta.")
