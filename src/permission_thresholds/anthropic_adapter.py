"""One bounded Anthropic Messages request for the JSON command-actor protocol.

No SDK dependencies, credentials from files, automatic retries, endpoint
overrides, native tool execution, or network activity in --check-config mode.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any


ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 45
MAX_BYTES = 1_000_000
MAX_TOKENS_LIMIT = 4096
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,200}\Z")
OUTPUT_INSTRUCTION = (
    'Return exactly one JSON object with keys "tool" (a tool name string) and '
    '"arguments" (an object), matching an available tool in the observation. '
    "Do not add commentary, analysis, metadata, or other keys. "
    "The tool will be executed by the simulator, not by you."
)


class AdapterError(RuntimeError):
    """A fixed, non-sensitive failure code suitable for local logs."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AdapterError("provider_redirect_refused")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AdapterError("duplicate_json_key")
        result[key] = value
    return result


def _invalid_constant(value: str):
    raise AdapterError("non_finite_json_number")


def strict_json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (ValueError, TypeError, RecursionError) as error:
        raise AdapterError("invalid_json") from None


def validate_action(action: Any) -> dict[str, Any]:
    if (not isinstance(action, dict) or set(action) != {"tool", "arguments"}
            or not isinstance(action["tool"], str) or not action["tool"]
            or len(action["tool"]) > 128 or not isinstance(action["arguments"], dict)):
        raise AdapterError("invalid_action_schema")
    return action


def build_payload(request: Any, max_tokens: int | None = None) -> dict[str, Any]:
    required = {"protocol_version", "model", "system", "observation", "history"}
    if not isinstance(request, dict) or not required.issubset(request) or set(request) - required - {"max_output_tokens"}:
        raise AdapterError("invalid_request_schema")
    if request["protocol_version"] != "1.0":
        raise AdapterError("unsupported_protocol_version")
    if not isinstance(request["model"], str) or not IDENTIFIER.fullmatch(request["model"]):
        raise AdapterError("explicit_model_id_required")
    if not isinstance(request["system"], str) or not isinstance(request["observation"], dict) or not isinstance(request["history"], list):
        raise AdapterError("invalid_request_schema")
    for entry in request["history"]:
        if not isinstance(entry, dict) or set(entry) != {"action", "result"} or not isinstance(entry["result"], dict):
            raise AdapterError("invalid_history_schema")
        validate_action(entry["action"])
    budget = max_tokens if max_tokens is not None else request.get("max_output_tokens", 512)
    if type(budget) is not int or not 1 <= budget <= MAX_TOKENS_LIMIT:
        raise AdapterError("invalid_output_token_budget")
    user_content = json.dumps({"observation": request["observation"], "history": request["history"]}, ensure_ascii=False, allow_nan=False)
    payload = {
        "model": request["model"],
        "max_tokens": budget,
        "system": request["system"] + "\n\n" + OUTPUT_INSTRUCTION,
        "messages": [{"role": "user", "content": user_content}],
        "stream": False,
    }
    return payload


def parse_response(content: bytes, request_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    if len(content) > MAX_BYTES:
        raise AdapterError("provider_response_too_large")
    try:
        response = strict_json(content.decode("utf-8"))
    except UnicodeDecodeError:
        raise AdapterError("provider_response_not_utf8") from None
    if not isinstance(response, dict) or response.get("stop_reason") != "end_turn":
        raise AdapterError("provider_turn_incomplete_or_refused")
    blocks = response.get("content")
    if not isinstance(blocks, list) or not blocks or any(
        not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str)
        for block in blocks
    ):
        raise AdapterError("provider_expected_text_response")
    text = "".join(block["text"] for block in blocks).strip()
    if text.startswith("```"):
        fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced is None:
            raise AdapterError("invalid_action_json_fence")
        text = fenced.group(1).strip()
    action = validate_action(strict_json(text))
    actual_model = response.get("model")
    if not isinstance(actual_model, str) or not IDENTIFIER.fullmatch(actual_model):
        raise AdapterError("provider_model_id_missing_or_invalid")
    raw_usage = response.get("usage", {})
    if not isinstance(raw_usage, dict):
        raise AdapterError("provider_usage_invalid")
    usage = {key: raw_usage[key] for key in TOKEN_FIELDS if key in raw_usage}
    if any(type(value) is not int or value < 0 for value in usage.values()):
        raise AdapterError("provider_usage_invalid")
    clean_request_id = request_id if isinstance(request_id, str) and IDENTIFIER.fullmatch(request_id) else None
    return {
        "action": action,
        "metadata": {
            "provider": "anthropic",
            "model": actual_model,
            "request_id": clean_request_id,
            "usage": usage,
            "settings": {
                "requested_model": payload["model"],
                "api_version": API_VERSION,
                "max_tokens": payload["max_tokens"],
                "stream": False,
                "sampling": "provider_default",
                "native_tools": False,
            },
        },
    }


def get_action(request: Any, max_tokens: int | None = None) -> dict[str, Any]:
    payload = build_payload(request, max_tokens=max_tokens)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or any(character.isspace() for character in api_key):
        raise AdapterError("api_key_missing_or_malformed")
    try:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        api_key.encode("ascii")
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise AdapterError("request_encoding_failed") from None
    if len(body) > MAX_BYTES:
        raise AdapterError("request_too_large")
    http_request = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": API_VERSION, "User-Agent": "permission-thresholds/0.1"},
    )
    # Disable ambient proxies and redirects so the credential has only this
    # official HTTPS destination. Standard HTTPS certificate checks remain on.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(http_request, timeout=TIMEOUT_SECONDS) as response:
            if response.geturl() != ENDPOINT:
                raise AdapterError("provider_endpoint_mismatch")
            if response.getcode() != 200:
                raise AdapterError("provider_unexpected_status")
            content = response.read(MAX_BYTES + 1)
            request_id = response.headers.get("request-id")
    except urllib.error.HTTPError as error:
        # Do not read, print, or propagate the provider error body or headers.
        code = error.code if type(error.code) is int else "error"
        error.close()
        raise AdapterError(f"provider_http_{code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
        raise AdapterError("provider_network_or_timeout_error") from None
    return parse_response(content, request_id, payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-config", action="store_true", help="Print only an API-key presence flag; no network or stdin read")
    parser.add_argument("--max-tokens", type=int, help="Override request max_output_tokens (1..4096)")
    args = parser.parse_args(argv)
    if args.check_config:
        print(json.dumps({"api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY"))}))
        return 0
    try:
        content = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise AdapterError("request_too_large")
        request = strict_json(content.decode("utf-8"))
        response = get_action(request, max_tokens=args.max_tokens)
        print(json.dumps(response, ensure_ascii=False, allow_nan=False))
        return 0
    except AdapterError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    except (UnicodeError, ValueError, TypeError, RecursionError, OSError):
        print(json.dumps({"error": "invalid_request_or_encoding"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
