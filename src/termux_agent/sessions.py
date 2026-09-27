"""Coordenação e serialização de operações por sessão."""

from contextlib import contextmanager
import threading


class SessionCoordinator:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[str, tuple[threading.Lock, int]] = {}

    @property
    def active_sessions(self) -> int:
        with self._guard:
            return len(self._locks)

    @contextmanager
    def hold(self, session_id: str):
        # Mesma sessão fica em ordem; sessões distintas podem avançar em paralelo.
        with self._guard:
            entry = self._locks.get(session_id)
            lock = entry[0] if entry else threading.Lock()
            users = entry[1] + 1 if entry else 1
            self._locks[session_id] = (lock, users)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._guard:
                current_lock, users = self._locks[session_id]
                if users <= 1:
                    del self._locks[session_id]
                else:
                    self._locks[session_id] = (current_lock, users - 1)
