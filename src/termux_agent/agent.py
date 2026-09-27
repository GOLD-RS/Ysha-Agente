"""Camada do agente; ferramentas e memória serão adicionadas com limites."""

from .provider import ChatProvider


class Agent:
    def __init__(self, provider: ChatProvider):
        self.provider = provider

    def respond(self, message: str) -> str:
        message = message.strip()
        if not message:
            raise ValueError("A mensagem não pode ficar vazia.")
        if len(message) > 12_000:
            raise ValueError("A mensagem excede o limite de 12.000 caracteres.")
        return self.provider.complete(message)
