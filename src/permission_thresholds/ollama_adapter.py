"""Local-only Ollama inference with complete public-prompt/action provenance."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .actors import ActorError, validate_action


BASE_URL = "http://127.0.0.1:11434"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ActorError("local_endpoint_redirect_refused")


def local_json(path, payload=None, timeout=90):
    if path not in {"/api/tags", "/api/show", "/api/version", "/api/generate"}:
        raise ValueError("unsupported local endpoint")
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    request = urllib.request.Request(BASE_URL + path, data=body,
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ActorError("local_transport_" + type(exc).__name__) from None
    if len(raw) > 2_000_000:
        raise ActorError("local_response_too_large")
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ActorError("local_invalid_response_json") from None
    if not isinstance(parsed, dict):
        raise ActorError("local_response_not_object")
    return parsed


def model_inventory(model):
    models = local_json("/api/tags").get("models", [])
    selected = next((item for item in models if item.get("name") == model), None)
    if selected is None:
        raise ActorError("requested_local_model_not_installed")
    details = local_json("/api/show", {"model": model})
    return {"model": selected, "runtime": local_json("/api/version"),
            "template": details.get("template"), "parameters": details.get("parameters"),
            "capabilities": details.get("capabilities"), "model_info": details.get("model_info")}


class OllamaActor:
    def __init__(self, model, settings, seed):
        self.model, self.settings, self.seed = model, dict(settings), seed
        self.last_call = None

    def next_action(self, request):
        branches = []
        for tool in request["observation"]["tools"]:
            units = bool(tool.get("arguments"))
            argument_schema = {"type": "object", "properties": {"units": {"type": "integer", "minimum": 1}} if units else {},
                               "required": ["units"] if units else [], "additionalProperties": False}
            branches.append({"type": "object", "properties": {
                "tool": {"type": "string", "enum": [tool["name"]]}, "arguments": argument_schema},
                "required": ["tool", "arguments"], "additionalProperties": False})
        schema = {"oneOf": branches}
        payload = {"model": self.model, "system": request["system"],
                   "prompt": json.dumps({"observation": request["observation"], "history": request["history"]},
                                        ensure_ascii=False, separators=(",", ":")),
                   "format": schema, "stream": False, "think": self.settings["think"],
                   "keep_alive": "10m", "options": {
                       "temperature": self.settings["temperature"], "seed": self.seed + len(request["history"]),
                       "num_ctx": self.settings["num_ctx"], "num_predict": self.settings["num_predict"]}}
        started = time.monotonic()
        self.last_call = {"request": payload}
        try:
            response = local_json("/api/generate", payload)
            self.last_call["response"] = {k: v for k, v in response.items() if k != "context"}
            if not response.get("done") or response.get("done_reason") != "stop":
                raise ActorError("local_incomplete_generation")
            try:
                action = json.loads(response["response"])
                validate_action(action)
            except (ValueError, KeyError, TypeError):
                raise ActorError("local_invalid_action_json") from None
            return {"action": action, "metadata": {"provider": "ollama", "model": response.get("model"),
                    "usage": {"input_tokens": response.get("prompt_eval_count", 0),
                              "output_tokens": response.get("eval_count", 0)}}}
        except ActorError as exc:
            self.last_call["error"] = str(exc)
            raise
        finally:
            self.last_call["seconds"] = time.monotonic() - started
