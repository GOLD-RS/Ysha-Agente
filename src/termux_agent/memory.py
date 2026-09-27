"""Protocol de memória conversacional consumido pelo agente."""

from typing import Protocol


class ConversationMemory(Protocol):
    """Minimal persistence contract; implementations may be SQLite or later backends."""

    def get_recent(self, session_id: str, limit: int | None = None) -> list[dict[str, str]]:
        ...

    def add_exchange(self, session_id: str, user_message: str, assistant_message: str) -> None:
        ...

    def delete(self, session_id: str) -> int:
        ...
