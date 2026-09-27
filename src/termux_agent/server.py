"""API HTTP local para conversar com o agente."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import re
import uuid

from .agent import Agent
from .provider import ProviderError

MAX_BODY_BYTES = 64 * 1024
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CHAT_PAGE = Path(__file__).resolve().parents[2] / "web" / "index.html"


def authorization_valid(provided: str, token: str) -> bool:
    return not token or hmac.compare_digest(
        provided.encode("utf-8"), f"Bearer {token}".encode("utf-8")
    )


def make_handler(agent: Agent):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            return authorization_valid(
                self.headers.get("Authorization", ""),
                agent.provider.settings.access_token,
            )

        def do_GET(self):
            if self.path == "/":
                try:
                    body = CHAT_PAGE.read_bytes()
                except OSError:
                    self._send_json(503, {"error": "chat_interface_unavailable"})
                    return
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
                    self._send_json(401, {"error": "unauthorized"})
                    return
                self._send_json(200, {"messages": agent.history.get(match.group(1))})
                return
            self._send_json(404, {"error": "not_found"})

        def do_POST(self):
            if self.path != "/chat":
                self._send_json(404, {"error": "not_found"})
                return
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"error": "invalid_content_length"})
                return
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send_json(413 if length > MAX_BODY_BYTES else 400, {"error": "invalid_body_size"})
                return
            if "application/json" not in self.headers.get("Content-Type", ""):
                self._send_json(415, {"error": "content_type_must_be_json"})
                return
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"error": "invalid_json"})
                return
            if not isinstance(data, dict) or not isinstance(data.get("message"), str):
                self._send_json(400, {"error": "message_must_be_a_string"})
                return
            session_id = data.get("session_id") or uuid.uuid4().hex
            if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
                self._send_json(400, {"error": "invalid_session_id"})
                return
            try:
                answer = agent.respond(session_id, data["message"])
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except ProviderError as exc:
                self._send_json(502, {"error": str(exc)})
                return
            self._send_json(200, {"reply": answer, "session_id": session_id})

        def do_DELETE(self):
            if not self._authorized():
                self._send_json(401, {"error": "unauthorized"})
                return
            match = re.fullmatch(r"/sessions/([A-Za-z0-9_-]{1,64})", self.path)
            if not match:
                self._send_json(404, {"error": "not_found"})
                return
            deleted = agent.history.delete(match.group(1))
            self._send_json(200, {"deleted_messages": deleted})

        def log_message(self, fmt, *args):
            return

    return Handler


def serve(agent: Agent, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(agent))
    server.daemon_threads = True
    address = f"[{host}]" if ":" in host else host
    print(f"Ysha Agente ativo em http://{address}:{port}", flush=True)
    print(f"Abra http://{address}:{port}/ no navegador para conversar. Ctrl+C encerra.", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nEncerrando Ysha Agente...", flush=True)
    finally:
        server.server_close()
