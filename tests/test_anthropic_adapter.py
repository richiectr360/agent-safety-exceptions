"""Offline adapter tests. Every HTTP transport is mocked; no provider calls."""

from copy import deepcopy
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from permission_thresholds import anthropic_adapter as adapter


def request():
    return {"protocol_version": "1.0", "model": "explicit-test-model-id",
            "system": "Follow the simulation policy.", "observation": {"state": {"load": 10}},
            "history": [], "max_output_tokens": 512}


def provider_response(text='{"tool":"inspect","arguments":{}}', **changes):
    value = {"model": "returned-test-model-id", "content": [{"type": "text", "text": text}],
             "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 8}}
    value.update(changes)
    return json.dumps(value).encode()


class AnthropicAdapterTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-never-networked"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def transport(self, content=None):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.geturl.return_value = adapter.ENDPOINT
        response.getcode.return_value = 200
        response.headers = {"request-id": "req_test123"}
        response.read.return_value = content or provider_response()
        return opener, response

    def test_request_uses_fixed_official_endpoint_top_level_system_and_redacted_metadata(self):
        opener, response = self.transport()
        with patch.object(adapter.urllib.request, "build_opener", return_value=opener) as build:
            result = adapter.get_action(request())
        sent = opener.open.call_args.args[0]
        payload = json.loads(sent.data)
        self.assertEqual(sent.full_url, adapter.ENDPOINT)
        self.assertEqual(sent.get_method(), "POST")
        self.assertEqual(sent.get_header("X-api-key"), "test-key-never-networked")
        self.assertEqual(sent.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(payload["model"], "explicit-test-model-id")
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(json.loads(payload["messages"][0]["content"])["observation"], request()["observation"])
        self.assertNotIn("tools", payload)
        self.assertIn("Follow the simulation policy.", payload["system"])
        self.assertEqual(opener.open.call_args.kwargs["timeout"], adapter.TIMEOUT_SECONDS)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], adapter.NoRedirect)
        response.read.assert_called_once_with(adapter.MAX_BYTES + 1)
        self.assertEqual(result["action"], {"tool": "inspect", "arguments": {}})
        self.assertEqual(result["metadata"]["model"], "returned-test-model-id")
        self.assertEqual(result["metadata"]["request_id"], "req_test123")
        self.assertNotIn("test-key-never-networked", json.dumps(result))

    def test_fenced_action_and_token_override(self):
        result = adapter.parse_response(provider_response('```json\n{"tool":"local_process","arguments":{}}\n```'), None, adapter.build_payload(request(), 128))
        self.assertEqual(result["action"]["tool"], "local_process")
        self.assertEqual(result["metadata"]["settings"]["max_tokens"], 128)

    def test_invalid_schemas_and_duplicate_keys_are_rejected(self):
        for value in ['{"tool":"inspect","arguments":{},"thought":"x"}', '{"tool":"inspect"}',
                      '{"tool":"inspect","arguments":[]}', '{"tool":1,"arguments":{}}',
                      '{"tool":"inspect","tool":"finish","arguments":{}}',
                      '{"tool":"reserve_resource","arguments":{"units":NaN}}',
                      'Here is the action: {"tool":"inspect","arguments":{}}']:
            with self.subTest(value=value), self.assertRaises(adapter.AdapterError):
                adapter.parse_response(provider_response(value), None, adapter.build_payload(request()))

    def test_incomplete_refused_native_tool_and_oversized_responses_are_rejected(self):
        bad = [provider_response(stop_reason=reason) for reason in ["max_tokens", "tool_use", "refusal", "pause_turn", None]]
        bad += [provider_response(content=[{"type": "tool_use", "name": "inspect"}]),
                provider_response(usage={"input_tokens": True}), b'x' * (adapter.MAX_BYTES + 1), b'\xff']
        for content in bad:
            with self.subTest(content=content[:60]), self.assertRaises(adapter.AdapterError):
                adapter.parse_response(content, None, adapter.build_payload(request()))

    def test_http_error_body_is_not_read_or_exposed(self):
        body = MagicMock()
        error = urllib.error.HTTPError(adapter.ENDPOINT, 401, "SECRET provider text", {}, body)
        opener = MagicMock()
        opener.open.side_effect = error
        with patch.object(adapter.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(adapter.AdapterError, "^provider_http_401$"):
                adapter.get_action(request())
        body.read.assert_not_called()

    def test_network_errors_are_sanitized_no_retry(self):
        for problem in [TimeoutError("SECRET"), urllib.error.URLError("SECRET")]:
            opener = MagicMock()
            opener.open.side_effect = problem
            with patch.object(adapter.urllib.request, "build_opener", return_value=opener):
                with self.assertRaisesRegex(adapter.AdapterError, "^provider_network_or_timeout_error$"):
                    adapter.get_action(request())
            opener.open.assert_called_once()

    def test_redirect_is_refused(self):
        with self.assertRaisesRegex(adapter.AdapterError, "provider_redirect_refused"):
            adapter.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.invalid")
        opener, response = self.transport()
        response.geturl.return_value = "https://elsewhere.invalid"
        with patch.object(adapter.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(adapter.AdapterError, "provider_endpoint_mismatch"):
                adapter.get_action(request())
        response.read.assert_not_called()

    def test_missing_key_and_invalid_request_never_open_network(self):
        with patch.object(adapter.urllib.request, "build_opener") as build:
            with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(adapter.AdapterError, "api_key_missing"):
                adapter.get_action(request())
            for changes in [{"model": ""}, {"protocol_version": "wrong"}, {"history": [{}]},
                            {"max_output_tokens": True}, {"max_output_tokens": 0},
                            {"max_output_tokens": 4097}, {"endpoint": "https://elsewhere.invalid"}]:
                value = deepcopy(request())
                value.update(changes)
                with self.subTest(changes=changes), self.assertRaises(adapter.AdapterError):
                    adapter.get_action(value)
            build.assert_not_called()

    def test_check_config_prints_only_presence_and_does_not_read_stdin(self):
        for present in [True, False]:
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "not-a-real-key"} if present else {}, clear=True):
                output = io.StringIO()
                with patch("sys.stdout", output), patch("sys.stdin") as stdin, patch.object(adapter.urllib.request, "build_opener") as build:
                    self.assertEqual(adapter.main(["--check-config"]), 0)
                self.assertEqual(json.loads(output.getvalue()), {"api_key_present": present})
                stdin.buffer.read.assert_not_called()
                build.assert_not_called()

    def test_cli_round_trip_and_malformed_input(self):
        opener, _ = self.transport()
        output, errors = io.StringIO(), io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(request()).encode()))
        with patch("sys.stdin", stdin), patch("sys.stdout", output), patch("sys.stderr", errors), patch.object(adapter.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(adapter.main([]), 0)
        self.assertEqual(set(json.loads(output.getvalue())), {"action", "metadata"})
        self.assertEqual(errors.getvalue(), "")
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.TextIOWrapper(io.BytesIO(b'{"secret":"PRIVATE"'))), patch("sys.stdout", output), patch("sys.stderr", errors), patch.object(adapter.urllib.request, "build_opener") as build:
            self.assertEqual(adapter.main([]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("PRIVATE", errors.getvalue())
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
