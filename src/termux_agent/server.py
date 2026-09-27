"""API HTTP local para conversar com o agente."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

from .agent import Agent
from .provider import ProviderError

MAX_BODY_BYTES = 64 * 1024


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
            self._send_json(200, {"status": "ok", "version": "0.1.0"})

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
            message = data.get("message") if isinstance(data, dict) else None
            if not isinstance(message, str):
                self._send_json(400, {"error": "message_must_be_a_string"})
                return
            try:
                answer = agent.respond(message)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except ProviderError as exc:
                self._send_json(502, {"error": str(exc)})
                return
            self._send_json(200, {"reply": answer})

        def log_message(self, fmt, *args):
            # Evita registrar conteúdo de conversas nos logs por padrão.
            return

    return Handler


def serve(agent: Agent, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(agent))
    server.daemon_threads = True
    print(f"Agente ativo em http://{host}:{port} (Ctrl+C para encerrar)", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nEncerrando agente...", flush=True)
    finally:
        server.server_close()
