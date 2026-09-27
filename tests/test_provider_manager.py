import json
import os
import secrets
import socket
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch

from termux_agent.agent import Agent
from termux_agent.config import Settings
from termux_agent.history import HistoryStore
from termux_agent.provider import (
    ChatProvider,
    ProviderConfigurationError,
    ProviderContractError,
    ProviderError,
    TransientProviderError,
)
from termux_agent.provider_manager import ProviderManager, ProviderManagerError
from termux_agent.server import make_handler


class ScriptedAdapter:
    def __init__(self, *actions):
        self.actions = list(actions)
        self.calls = 0
        self.timeouts = []

    def complete(self, messages, tools, *, timeout=None):
        self.calls += 1
        self.timeouts.append(timeout)
        if not self.actions:
            raise AssertionError("unexpected provider call")
        action = self.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            return action(timeout)
        return action


class MemoryResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount):
        chunk, self.body = self.body[:amount], self.body[amount:]
        return chunk


def configured_settings(
    ids=("primary",),
    *,
    selected=None,
    fallbacks=(),
    retries=1,
    timeout="30",
    total_timeout="90",
    max_attempts=8,
    api_key="",
):
    environment = {
        "AGENT_PROVIDER_IDS": ",".join(ids),
        "AGENT_PROVIDER_SELECTED": selected or ids[0],
        "AGENT_PROVIDER_FALLBACKS": ",".join(fallbacks),
        "AGENT_PROVIDER_TOTAL_TIMEOUT_SECONDS": total_timeout,
        "AGENT_PROVIDER_MAX_ATTEMPTS_PER_RESPONSE": str(max_attempts),
    }
    for name in ids:
        prefix = f"AGENT_PROVIDER_{name.upper()}_"
        environment[prefix + "TYPE"] = "chat_completions"
        environment[prefix + "API_KEY"] = api_key
        environment[prefix + "BASE_URL"] = f"https://{name}.example.test/v1"
        environment[prefix + "MODEL"] = f"model-{name}"
        environment[prefix + "TIMEOUT_SECONDS"] = timeout
        environment[prefix + "MAX_RETRIES"] = str(retries)
    with patch.dict(os.environ, environment, clear=True):
        return Settings.from_env()


def build_manager(settings, adapters):
    def factory(profile):
        return adapters[profile.name]

    return ProviderManager(settings, adapter_factories={"chat_completions": factory})


def send_request(handler, request):
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
        chunk = client.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
    client.close()
    thread.join(timeout=2)
    raw = b"".join(chunks)
    headers, body = raw.split(b"\r\n\r\n", 1)
    status = int(headers.split(b"\r\n", 1)[0].split()[1])
    return status, json.loads(body)


class ProviderManagerTests(unittest.TestCase):
    def test_legacy_single_provider_configuration_remains_supported(self):
        with patch.dict(os.environ, {
            "AGENT_API_KEY": "",
            "AGENT_BASE_URL": "https://legacy.example.test/v1",
            "AGENT_MODEL": "legacy-model",
        }, clear=True):
            settings = Settings.from_env()
        adapter = ScriptedAdapter({"content": "ok", "tool_calls": []})
        manager = build_manager(settings, {"default": adapter})
        self.assertEqual(manager.selected_provider, "default")
        self.assertEqual(settings.provider_profiles[0].timeout_seconds, 90)
        self.assertEqual(manager.complete([], []), {"content": "ok", "tool_calls": []})
        self.assertEqual(adapter.calls, 1)

    def test_selection_uses_configured_provider_without_fallback(self):
        settings = configured_settings(("primary", "secondary"), selected="secondary")
        first = ScriptedAdapter({"content": "wrong", "tool_calls": []})
        second = ScriptedAdapter({"content": "selected", "tool_calls": []})
        manager = build_manager(settings, {"primary": first, "secondary": second})
        self.assertEqual(manager.selected_provider, "secondary")
        self.assertEqual(manager.complete([], []) ["content"], "selected")
        self.assertEqual(first.calls, 0)
        self.assertEqual(second.calls, 1)

    def test_unknown_selected_provider_is_rejected(self):
        settings = configured_settings(("primary",))
        with self.assertRaises(ProviderConfigurationError):
            ProviderManager(replace(settings, selected_provider="missing"))

    def test_transient_failure_retries_then_succeeds(self):
        settings = configured_settings(retries=1)
        adapter = ScriptedAdapter(
            TransientProviderError("private response must not escape"),
            {"content": "recovered", "tool_calls": []},
        )
        manager = build_manager(settings, {"primary": adapter})
        self.assertEqual(manager.complete([], []) ["content"], "recovered")
        self.assertEqual(adapter.calls, 2)

    def test_retry_count_is_limited_by_profile_configuration(self):
        settings = configured_settings(retries=2)
        adapter = ScriptedAdapter(*[TransientProviderError("temporary") for _ in range(4)])
        manager = build_manager(settings, {"primary": adapter})
        with self.assertRaises(ProviderManagerError) as caught:
            manager.complete([], [])
        self.assertEqual(adapter.calls, 3)
        self.assertEqual(caught.exception.error_code, "providers_unavailable")

    def test_backoff_delays_are_exponential_and_bounded(self):
        settings = configured_settings(retries=2, total_timeout="10")
        adapter = ScriptedAdapter(*[TransientProviderError("temporary") for _ in range(3)])
        manager = build_manager(settings, {"primary": adapter})
        clock = [0.0]
        delays = []

        def monotonic():
            return clock[0]

        def sleep(delay):
            delays.append(delay)
            clock[0] += delay

        with patch("termux_agent.provider_manager.time.monotonic", side_effect=monotonic), \
             patch("termux_agent.provider_manager.time.sleep", side_effect=sleep):
            with self.assertRaises(ProviderManagerError):
                manager.complete([], [])
        self.assertEqual(delays, [0.25, 0.5])
        self.assertTrue(all(delay <= manager.BACKOFF_MAX_SECONDS for delay in delays))

    def test_fallback_runs_only_after_selected_provider_transient_retries_exhaust(self):
        settings = configured_settings(
            ("primary", "backup"), fallbacks=("backup",), retries=1,
        )
        primary = ScriptedAdapter(TransientProviderError("network"), TransientProviderError("network"))
        backup = ScriptedAdapter({"content": "fallback", "tool_calls": []})
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        self.assertEqual(manager.complete([], []) ["content"], "fallback")
        self.assertEqual(primary.calls, 2)
        self.assertEqual(backup.calls, 1)

    def test_permanent_failure_does_not_retry_or_fallback(self):
        settings = configured_settings(("primary", "backup"), fallbacks=("backup",), retries=2)
        primary = ScriptedAdapter(ProviderContractError("raw contract content"))
        backup = ScriptedAdapter({"content": "must not run", "tool_calls": []})
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        with self.assertRaises(ProviderManagerError) as caught:
            manager.complete([], [])
        self.assertEqual(caught.exception.error_code, "provider_failure")
        self.assertNotIn("raw contract content", str(caught.exception))
        self.assertEqual(primary.calls, 1)
        self.assertEqual(backup.calls, 0)

    def test_deadline_is_passed_to_adapter_and_total_timeout_is_enforced(self):
        settings = configured_settings(("primary", "backup"), fallbacks=("backup",), total_timeout="1")
        clock = [0.0]
        primary = ScriptedAdapter(lambda _timeout: (clock.__setitem__(0, 1.0) or {"content": "late"}))
        backup = ScriptedAdapter({"content": "must not run"})
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        with patch("termux_agent.provider_manager.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(ProviderManagerError) as caught:
                manager.complete([], [])
        self.assertEqual(caught.exception.error_code, "provider_timeout")
        self.assertEqual(primary.timeouts, [1.0])
        self.assertEqual(backup.calls, 0)

    def test_all_transiently_unavailable_providers_return_one_safe_error(self):
        settings = configured_settings(("primary", "backup"), fallbacks=("backup",), retries=0)
        primary = ScriptedAdapter(TransientProviderError("first raw body"))
        backup = ScriptedAdapter(TransientProviderError("second raw body"))
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        with self.assertRaises(ProviderManagerError) as caught:
            manager.complete([], [])
        self.assertEqual(caught.exception.error_code, "providers_unavailable")
        self.assertNotIn("raw body", str(caught.exception))

    def test_credentials_and_raw_adapter_errors_never_appear_in_errors_or_logs(self):
        dynamic_credential = secrets.token_urlsafe(32)
        settings = configured_settings(api_key=dynamic_credential, retries=0)
        self.assertNotIn(dynamic_credential, repr(settings))
        self.assertNotIn(dynamic_credential, repr(settings.provider_profiles))
        adapter = ScriptedAdapter(TransientProviderError(f"raw response {dynamic_credential}"))
        manager = build_manager(settings, {"primary": adapter})
        with self.assertLogs("termux_agent.provider_manager", level="WARNING") as captured:
            with self.assertRaises(ProviderManagerError) as caught:
                manager.complete([], [])
        combined = str(caught.exception) + "\n".join(captured.output)
        self.assertNotIn(dynamic_credential, combined)
        self.assertNotIn("raw response", combined)

    def test_contract_error_from_agent_does_not_trigger_manager_fallback(self):
        settings = configured_settings(("primary", "backup"), fallbacks=("backup",), retries=1)
        invalid_answer = {"content": None, "tool_calls": [{
            "id": "bad-call", "type": "function",
            "function": {"name": "calculate", "arguments": "not-json"},
        }]}
        primary = ScriptedAdapter(invalid_answer)
        backup = ScriptedAdapter({"content": "must not run", "tool_calls": []})
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        memory = HistoryStore(":memory:")
        try:
            agent = Agent(manager, memory, system_prompt="test")
            with self.assertRaises(ProviderError):
                agent.respond("test", "hello")
        finally:
            memory.close()
        self.assertEqual(primary.calls, 1)
        self.assertEqual(backup.calls, 0)

    def test_invalid_tool_schema_is_permanent_and_never_uses_fallback(self):
        settings = configured_settings(("primary", "backup"), fallbacks=("backup",), retries=2)
        invalid_tool_call = {"content": None, "tool_calls": [{
            "id": "call-1", "type": "function",
            "function": {"name": "calculate", "arguments": "{}"},
        }]}
        primary = ScriptedAdapter(invalid_tool_call)
        backup = ScriptedAdapter({"content": "must not run", "tool_calls": []})
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        memory = HistoryStore(":memory:")
        try:
            agent = Agent(manager, memory, system_prompt="test")
            with self.assertRaises(ProviderContractError):
                agent.respond("invalid-tool", "calculate")
            self.assertEqual(memory.get("invalid-tool"), [])
        finally:
            memory.close()
        self.assertEqual(primary.calls, 1)
        self.assertEqual(backup.calls, 0)

    def test_attempt_budget_is_shared_across_the_full_agent_tool_cycle(self):
        settings = configured_settings(
            ("primary", "backup"), fallbacks=("backup",), retries=2, max_attempts=2,
        )
        tool_call = {"content": None, "tool_calls": [{
            "id": "call-1", "type": "function",
            "function": {"name": "calculate", "arguments": '{"expression":"1+1"}'},
        }]}
        primary = ScriptedAdapter(tool_call, TransientProviderError("temporary"))
        backup = ScriptedAdapter({"content": "must not run", "tool_calls": []})
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        memory = HistoryStore(":memory:")
        try:
            agent = Agent(manager, memory, system_prompt="test")
            with self.assertRaises(ProviderManagerError) as caught:
                agent.respond("budget", "calculate")
        finally:
            memory.close()
        self.assertEqual(caught.exception.error_code, "provider_attempt_limit")
        self.assertEqual(primary.calls, 2)
        self.assertEqual(backup.calls, 0)

    def test_total_deadline_is_shared_across_agent_tool_cycles(self):
        settings = configured_settings(
            ("primary", "backup"), fallbacks=("backup",), retries=0,
            total_timeout="1", max_attempts=4,
        )
        tool_call = {"content": None, "tool_calls": [{
            "id": "call-1", "type": "function",
            "function": {"name": "calculate", "arguments": '{"expression":"1+1"}'},
        }]}
        clock = [0.0]
        primary = ScriptedAdapter(
            tool_call,
            lambda _timeout: (clock.__setitem__(0, 1.0) or {"content": "late", "tool_calls": []}),
        )
        backup = ScriptedAdapter({"content": "must not run", "tool_calls": []})
        manager = build_manager(settings, {"primary": primary, "backup": backup})
        memory = HistoryStore(":memory:")
        try:
            agent = Agent(manager, memory, system_prompt="test")
            with patch("termux_agent.provider_manager.time.monotonic", side_effect=lambda: clock[0]):
                with self.assertRaises(ProviderManagerError) as caught:
                    agent.respond("deadline", "calculate")
        finally:
            memory.close()
        self.assertEqual(caught.exception.error_code, "provider_timeout")
        self.assertEqual(primary.calls, 2)
        self.assertEqual(backup.calls, 0)

    def test_chat_completions_adapter_is_created_and_remains_compatible(self):
        credential = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {
            "AGENT_API_KEY": credential,
            "AGENT_BASE_URL": "https://adapter.example.test/v1",
            "AGENT_MODEL": "adapter-model",
        }, clear=True):
            settings = Settings.from_env()
        body = json.dumps({"choices": [{
            "message": {"role": "assistant", "content": "adapter ok"},
            "finish_reason": "stop",
        }]}).encode()
        with patch("termux_agent.provider.urlopen", return_value=MemoryResponse(body)):
            manager = ProviderManager(settings)
            self.assertEqual(manager.complete([], [])["content"], "adapter ok")
        direct = ChatProvider(settings)
        self.assertTrue(callable(direct.complete))

    def test_agent_and_existing_chat_endpoint_remain_compatible(self):
        settings = configured_settings()
        adapter = ScriptedAdapter({"content": "chat response", "tool_calls": []})
        manager = build_manager(settings, {"primary": adapter})
        memory = HistoryStore(":memory:")
        try:
            agent = Agent(manager, memory, system_prompt="test")
            handler = make_handler(agent)
            body = json.dumps({"message": "hello", "session_id": "compat"}).encode()
            request = (
                b"POST /chat HTTP/1.0\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                + body
            )
            status, payload = send_request(handler, request)
        finally:
            memory.close()
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"reply": "chat response", "session_id": "compat"})
        self.assertEqual(adapter.calls, 1)

    def test_manager_errors_use_stable_safe_http_contract(self):
        settings = configured_settings(retries=0)
        adapter = ScriptedAdapter(TransientProviderError("body with sensitive content"))
        manager = build_manager(settings, {"primary": adapter})
        memory = HistoryStore(":memory:")
        try:
            handler = make_handler(Agent(manager, memory, system_prompt="test"))
            body = json.dumps({"message": "hello", "session_id": "compat"}).encode()
            request = (
                b"POST /chat HTTP/1.0\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                + body
            )
            status, payload = send_request(handler, request)
        finally:
            memory.close()
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "providers_unavailable")
        self.assertEqual(payload["message"], "Todos os providers configurados estão temporariamente indisponíveis.")
        self.assertNotIn("sensitive content", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
