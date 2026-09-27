import json
import os
import secrets
import unittest
from unittest.mock import patch

from termux_agent.config import Settings
from termux_agent.provider import (
    ChatProvider,
    ProviderError,
    TransientProviderError,
    validate_assistant_message,
    validate_chat_completion,
)


def response(message, finish_reason="stop"):
    return {"choices": [{"index": 0, "message": message, "finish_reason": finish_reason}]}


def valid_tool_call(call_id="call-1", arguments='{"expression":"2+2"}'):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "calculate", "arguments": arguments},
    }


class MemoryResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self.body


class ProviderContractTests(unittest.TestCase):
    def test_valid_text_response_is_normalized(self):
        self.assertEqual(
            validate_chat_completion(response({"role": "assistant", "content": "ok"})),
            {"role": "assistant", "content": "ok", "tool_calls": []},
        )

    def test_valid_tool_call_may_have_null_content(self):
        result = validate_chat_completion(
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call()]}, "tool_calls")
        )
        self.assertEqual(result["content"], None)
        self.assertEqual(result["tool_calls"][0]["id"], "call-1")

    def test_malformed_completion_envelopes_are_rejected(self):
        malformed = [
            [],
            {},
            {"choices": []},
            {"choices": "not-a-list"},
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}, {}]},
            {"choices": [None]},
            {"choices": [{"message": {"content": "missing role"}, "finish_reason": "stop"}]},
            response({"role": "user", "content": "wrong role"}),
            response({"role": "assistant", "content": {"text": "wrong type"}}),
            response({"role": "assistant", "content": None}),
            response({"role": "assistant", "content": "", "tool_calls": []}),
            response({"role": "assistant", "content": "ok"}, []),
            response({"role": "assistant", "content": "ok"}, "unknown-reason"),
            response({"role": "assistant", "content": "ok", "tool_calls": "not-a-list"}),
            response({"role": "assistant", "content": None, "tool_calls": [3]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(None)]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call("")]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [{**valid_tool_call(), "type": "other"}]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": []}]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": {"name": "calculate"}}]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": {"arguments": "{}"}}]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": {"name": 4, "arguments": "{}"}}]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [{"id": "x", "type": "function", "function": {"name": "calculate", "arguments": {}}}]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(arguments="not-json")]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(arguments="[]")]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(arguments='{"x":1,"x":2}') ]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(arguments='{"x":NaN}') ]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(arguments='{"x":1e9999}') ]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(), valid_tool_call()]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(f"id-{i}") for i in range(9)]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call("x" * 129)]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call(arguments="x" * 65_537)]}, "tool_calls"),
            response({"role": "assistant", "content": None, "tool_calls": [valid_tool_call()]}, "length"),
            response({"role": "assistant", "content": "ok"}, "tool_calls"),
        ]
        for item in malformed:
            with self.subTest(item=item), self.assertRaises(ProviderError):
                validate_chat_completion(item)

    def test_agent_boundary_also_rejects_invalid_tool_payloads(self):
        with self.assertRaises(ProviderError):
            validate_assistant_message({
                "content": None,
                "tool_calls": [valid_tool_call(arguments='{"expression":')],
            }, require_role=False)

    def test_invalid_body_is_reported_without_echoing_provider_content(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b"internal-secret stack trace is not JSON"

        credential = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {
            "AGENT_API_KEY": credential,
            "AGENT_BASE_URL": "https://api.example.test/v1",
            "AGENT_MODEL": "test-model",
        }, clear=True):
            provider = ChatProvider(Settings.from_env())
        with patch("termux_agent.provider.urlopen", return_value=FakeResponse()):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([], [])
        self.assertNotIn(credential, str(caught.exception))
        self.assertNotIn("internal-secret", str(caught.exception))

    def test_duplicate_keys_in_http_response_are_rejected(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b'{"choices":[{"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],"choices":[]}'

        credential = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {
            "AGENT_API_KEY": credential,
            "AGENT_BASE_URL": "https://api.example.test/v1",
            "AGENT_MODEL": "test-model",
        }, clear=True):
            provider = ChatProvider(Settings.from_env())
        with patch("termux_agent.provider.urlopen", return_value=FakeResponse()):
            with self.assertRaises(ProviderError):
                provider.complete([], [])

    def test_valid_http_response_passes_through_contract_validator(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps(response({"role": "assistant", "content": "ready"})).encode()

        credential = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {
            "AGENT_API_KEY": credential,
            "AGENT_BASE_URL": "https://api.example.test/v1",
            "AGENT_MODEL": "test-model",
        }, clear=True):
            provider = ChatProvider(Settings.from_env())
        with patch("termux_agent.provider.urlopen", return_value=FakeResponse()):
            self.assertEqual(provider.complete([], []), {
                "role": "assistant", "content": "ready", "tool_calls": []
            })


class ProviderFailureClassificationTests(unittest.TestCase):
    def setUp(self):
        credential = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {
            "AGENT_API_KEY": credential,
            "AGENT_BASE_URL": "https://provider.example.test/v1",
            "AGENT_MODEL": "model",
        }, clear=True):
            self.provider = ChatProvider(Settings.from_env())

    def test_rate_limit_and_server_errors_are_transient(self):
        from urllib.error import HTTPError

        for status in (408, 425, 429, 500, 502, 503, 504):
            with self.subTest(status=status), patch(
                "termux_agent.provider.urlopen",
                side_effect=HTTPError("https://provider.example.test", status, "private body", None, None),
            ):
                with self.assertRaises(TransientProviderError):
                    self.provider.complete([], [])

    def test_auth_and_request_errors_are_permanent(self):
        from urllib.error import HTTPError

        for status in (400, 401, 403, 404, 501, 505, 511):
            with self.subTest(status=status), patch(
                "termux_agent.provider.urlopen",
                side_effect=HTTPError("https://provider.example.test", status, "private body", None, None),
            ):
                with self.assertRaises(ProviderError) as caught:
                    self.provider.complete([], [])
                self.assertFalse(caught.exception.retryable)
                self.assertNotIn("private body", str(caught.exception))

    def test_socket_timeout_is_transient_but_malformed_response_is_permanent(self):
        with patch("termux_agent.provider.urlopen", side_effect=TimeoutError):
            with self.assertRaises(TransientProviderError):
                self.provider.complete([], [])
        with patch("termux_agent.provider.urlopen", return_value=MemoryResponse(b"not-json")):
            with self.assertRaises(ProviderError) as caught:
                self.provider.complete([], [])
        self.assertFalse(caught.exception.retryable)


class ProviderSecurityTests(unittest.TestCase):
    def test_refuses_plaintext_remote_endpoint_before_sending_api_key(self):
        credential = secrets.token_urlsafe(32)
        environment = {
            "AGENT_API_KEY": credential,
            "AGENT_BASE_URL": "http://api.example.test/v1",
            "AGENT_MODEL": "test-model",
        }
        with patch.dict(os.environ, environment, clear=True):
            provider = ChatProvider(Settings.from_env())
        with patch("termux_agent.provider.urlopen") as open_url:
            with self.assertRaises(ProviderError) as caught:
                provider.complete([], [])
        open_url.assert_not_called()
        self.assertNotIn(credential, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
