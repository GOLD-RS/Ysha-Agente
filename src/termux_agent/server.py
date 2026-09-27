"""API HTTP local para conversar com o agente."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import uuid

from .agent import Agent
from .provider import ProviderError

MAX_BODY_BYTES = 64 * 1024
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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

        def do_GET(self):
            if self.path != "/health":
                self._send_json(404, {"error": "not_found"})
                return
            self._send_json(200, {"status": "ok", "version": "0.2.0", "memory": "sqlite"})

        def do_POST(self):
            if self.path != "/chat":
                self._send_json(404, {"error": "not_found"})
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
    print(f"Ysha Agente ativo em http://{host}:{port} (Ctrl+C para encerrar)", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nEncerrando Ysha Agente...", flush=True)
    finally:
        server.server_close()
