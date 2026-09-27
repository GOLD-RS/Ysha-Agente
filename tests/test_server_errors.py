import json
import socket
import threading
import unittest
from types import SimpleNamespace

from termux_agent.provider import ProviderError
from termux_agent.server import make_handler


class FakeAgent:
    def __init__(self, *, response_error=None, history_error=None):
        self.provider = SimpleNamespace(settings=SimpleNamespace(access_token=""))
        self.response_error = response_error
        self.history_error = history_error
        self.history = self

    def respond(self, _session_id, _message):
        if self.response_error:
            raise self.response_error
        return "ok"

    def get_recent(self, _session_id, _limit):
        if self.history_error:
            raise self.history_error
        return []

    def delete(self, _session_id):
        if self.history_error:
            raise self.history_error
        return 0


def send_request(handler, request: bytes) -> tuple[int, dict]:
    client, server = socket.socketpair()
    def serve_one():
        try:
            handler(server, ("127.0.0.1", 1), None)
        finally:
            server.close()

    thread = threading.Thread(target=serve_one, daemon=True)
    thread.start()
    client.sendall(request)
    client.shutdown(socket.SHUT_WR)
    chunks = []
    while True:
        part = client.recv(4096)
        if not part:
            break
        chunks.append(part)
    thread.join(timeout=2)
    client.close()
    raw = b"".join(chunks)
    headers, body = raw.split(b"\r\n\r\n", 1)
    status = int(headers.split(b"\r\n", 1)[0].split()[1])
    return status, json.loads(body.decode("utf-8"))


def post_chat():
    body = b'{"message":"hello","session_id":"test"}'
    return (
        b"POST /chat HTTP/1.0\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        + body
    )


class ServerErrorTests(unittest.TestCase):
    def test_unexpected_agent_exception_returns_generic_json_without_details(self):
        handler = make_handler(FakeAgent(response_error=RuntimeError("api-secret stack trace")))
        status, payload = send_request(handler, post_chat())
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "internal_error")
        self.assertIn("message", payload)
        self.assertNotIn("api-secret", json.dumps(payload))
        self.assertNotIn("Traceback", json.dumps(payload))

    def test_provider_errors_are_mapped_to_generic_client_safe_response(self):
        handler = make_handler(FakeAgent(response_error=ProviderError("private provider response")))
        status, payload = send_request(handler, post_chat())
        self.assertEqual(status, 502)
        self.assertEqual(payload["error"], "provider_unavailable")
        self.assertNotIn("private provider response", json.dumps(payload))

    def test_history_failure_is_guarded_and_returned_as_generic_error(self):
        handler = make_handler(FakeAgent(history_error=RuntimeError("database path and secret")))
        request = b"GET /sessions/test HTTP/1.0\r\n\r\n"
        status, payload = send_request(handler, request)
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "internal_error")
        self.assertNotIn("database path", json.dumps(payload))

    def test_unsupported_method_uses_json_error_contract(self):
        handler = make_handler(FakeAgent())
        status, payload = send_request(handler, b"PATCH /chat HTTP/1.0\r\n\r\n")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"], "method_not_allowed")
        self.assertIn("message", payload)

    def test_bad_json_uses_stable_error_code_and_message(self):
        handler = make_handler(FakeAgent())
        body = b"not-json"
        request = (
            b"POST /chat HTTP/1.0\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            + body
        )
        status, payload = send_request(handler, request)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_json")
        self.assertIn("message", payload)


if __name__ == "__main__":
    unittest.main()
