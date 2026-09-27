"""Montagem isolada do contexto enviado ao provider."""

from .memory import ConversationMemory


class ContextBuilder:
    def __init__(self, memory: ConversationMemory, system_prompt: str):
        self.memory = memory
        self.system_prompt = system_prompt

    def for_turn(self, session_id: str, user_message: str) -> list[dict[str, str]]:
        recent = self.memory.get_recent(session_id)
        if not isinstance(recent, list):
            raise RuntimeError("A memória retornou um contexto incompatível.")
        context = [{"role": "system", "content": self.system_prompt}]
        for item in recent:
            if (
                not isinstance(item, dict)
                or item.get("role") not in ("user", "assistant")
                or not isinstance(item.get("content"), str)
            ):
                raise RuntimeError("A memória retornou uma mensagem incompatível.")
            context.append({"role": item["role"], "content": item["content"]})
        context.append({"role": "user", "content": user_message})
        return context
