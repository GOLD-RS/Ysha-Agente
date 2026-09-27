"""API HTTP local para conversar com o agente."""

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import math
from pathlib import Path
import re
import socket
import threading
import time
import uuid

from .agent import Agent
from .provider import ProviderError
from .provider_manager import ProviderManagerError

MAX_BODY_BYTES = 64 * 1024
UI_HISTORY_LIMIT = 200
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CHAT_PAGE = Path(__file__).resolve().parents[2] / "web" / "index.html"


class SlidingWindowRateLimiter:
    """Bound request bursts and remember a fixed number of client addresses."""

    def __init__(self, limit: int = 30, window_seconds: int = 60, max_clients: int = 128, clock=time.monotonic):
        self.limit = max(1, int(limit))
        self.window = max(1, int(window_seconds))
        self.max_clients = max(1, int(max_clients))
        self.clock = clock
        self._events: dict[str, tuple[deque[float], float]] = {}
        self._lock = threading.Lock()

    def allow(self, client: str) -> tuple[bool, int]:
        now = self.clock()
        with self._lock:
            if client not in self._events and len(self._events) >= self.max_clients:
                oldest = min(self._events, key=lambda key: self._events[key][1])
                del self._events[oldest]
            events, _ = self._events.get(client, (deque(), now))
            cutoff = now - self.window
            while events and events[0] <= cutoff:
                events.popleft()
            self._events[client] = (events, now)
            if len(events) >= self.limit:
                retry_after = max(1, math.ceil(self.window - (now - events[0])))
                return False, retry_after
            events.append(now)
            return True, 0


def authorization_valid(provided: str, token: str) -> bool:
    return not token or hmac.compare_digest(
        provided.encode("utf-8"), f"Bearer {token}".encode("utf-8")
    )


def _guard_handler(method):
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            if not getattr(self, "_response_started", False):
                try:
                    self._send_error_response(500, "internal_error", "Ocorreu um erro interno. Tente novamente.")
                except Exception:
                    pass
    return guarded


def make_handler(agent: Agent, access_token: str = ""):
    rate_limiter = SlidingWindowRateLimiter()

    class Handler(BaseHTTPRequestHandler):
        timeout = 15
        server_version = "Ysha"
        sys_version = ""

        def _send_json(self, status: int, payload: dict, extra_headers: dict[str, str] | None = None) -> None:
            self._response_started = True
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _send_error_response(
            self,
            status: int,
            code: str,
            message: str,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self._send_json(status, {"error": code, "message": message}, extra_headers)

        def send_error(self, code, message=None, explain=None):
            if getattr(self, "_response_started", False):
                return
            if code == 501:
                self._send_error_response(405, "method_not_allowed", "Método não permitido.")
            elif code == 414:
                self._send_error_response(414, "request_target_too_long", "Caminho da solicitação muito longo.")
            else:
                self._send_error_response(400, "bad_request", "Solicitação inválida.")

        def _authorized(self) -> bool:
            return authorization_valid(
                self.headers.get("Authorization", ""),
                access_token,
            )

        @_guard_handler
        def do_GET(self):
            if self.path == "/":
                try:
                    body = CHAT_PAGE.read_bytes()
                except OSError:
                    self._send_error_response(503, "chat_interface_unavailable", "A interface local não está disponível.")
                    return
                self._response_started = True
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "memory": "sqlite"})
                return
            match = re.fullmatch(r"/sessions/([A-Za-z0-9_-]{1,64})", self.path)
            if match:
                if not self._authorized():
                    self._send_error_response(401, "unauthorized", "Acesso não autorizado.")
                    return
                recent = agent.memory.get_recent(match.group(1), UI_HISTORY_LIMIT + 1)
                truncated = len(recent) > UI_HISTORY_LIMIT
                self._send_json(200, {
                    "messages": recent[-UI_HISTORY_LIMIT:],
                    "history_is_truncated": truncated,
                })
                return
            self._send_error_response(404, "not_found", "Rota não encontrada.")

        @_guard_handler
        def do_POST(self):
            if self.path != "/chat":
                self._send_error_response(404, "not_found", "Rota não encontrada.")
                return
            if not self._authorized():
                self._send_error_response(401, "unauthorized", "Acesso não autorizado.")
                return
            allowed, retry_after = rate_limiter.allow(self.client_address[0])
            if not allowed:
                self._send_error_response(429, "rate_limited", "Muitas solicitações; aguarde antes de tentar novamente.", {"Retry-After": str(retry_after)})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_error_response(400, "invalid_content_length", "Tamanho da solicitação inválido.")
                return
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send_error_response(413 if length > MAX_BODY_BYTES else 400, "invalid_body_size", "Tamanho do corpo inválido.")
                return
            if "application/json" not in self.headers.get("Content-Type", ""):
                self._send_error_response(415, "unsupported_media_type", "Envie o corpo no formato JSON.")
                return
            try:
                raw_body = self.rfile.read(length)
            except (socket.timeout, TimeoutError):
                self._send_error_response(408, "request_timeout", "A solicitação demorou demais.")
                return
            try:
                data = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_error_response(400, "invalid_json", "O corpo JSON é inválido.")
                return
            if not isinstance(data, dict) or not isinstance(data.get("message"), str):
                self._send_error_response(400, "invalid_message", "A mensagem precisa ser texto.")
                return
            session_id = data.get("session_id") or uuid.uuid4().hex
            if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
                self._send_error_response(400, "invalid_session_id", "Identificador de sessão inválido.")
                return
            try:
                answer = agent.respond(session_id, data["message"])
            except ValueError:
                self._send_error_response(400, "invalid_message", "Confira a mensagem e tente novamente.")
                return
            except ProviderManagerError as exc:
                self._send_error_response(exc.http_status, exc.error_code, str(exc))
                return
            except ProviderError:
                self._send_error_response(502, "provider_unavailable", "O provedor não respondeu em um formato utilizável.")
                return
            self._send_json(200, {"reply": answer, "session_id": session_id})

        @_guard_handler
        def do_DELETE(self):
            if not self._authorized():
                self._send_error_response(401, "unauthorized", "Acesso não autorizado.")
                return
            match = re.fullmatch(r"/sessions/([A-Za-z0-9_-]{1,64})", self.path)
            if not match:
                self._send_error_response(404, "not_found", "Rota não encontrada.")
                return
            deleted = agent.memory.delete(match.group(1))
            self._send_json(200, {"deleted_messages": deleted})

        def log_message(self, fmt, *args):
            return

    return Handler


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Cap worker threads so local clients cannot grow memory without bound."""

    daemon_threads = True
    request_queue_size = 16

    def __init__(self, server_address, request_handler, max_workers: int = 8):
        self._worker_slots = threading.BoundedSemaphore(max(1, max_workers))
        super().__init__(server_address, request_handler)

    def process_request(self, request, client_address):
        if not self._worker_slots.acquire(blocking=False):
            body = b'{"error":"server_busy"}'
            response = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\n".encode("ascii")
                + b"Connection: close\r\n\r\n"
                + body
            )
            try:
                request.settimeout(1)
                request.sendall(response)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()

    def handle_error(self, request, client_address):
        # Standard library's default prints tracebacks that may contain request data.
        return


def serve(agent: Agent, host: str, port: int, access_token: str = "") -> None:
    server = BoundedThreadingHTTPServer((host, port), make_handler(agent, access_token))
    address = f"[{host}]" if ":" in host else host
    print(f"Ysha Agente ativo em http://{address}:{port}", flush=True)
    print(f"Abra http://{address}:{port}/ no navegador para conversar. Ctrl+C encerra.", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nEncerrando Ysha Agente...", flush=True)
    finally:
        server.server_close()
