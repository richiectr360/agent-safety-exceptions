# Model adapters

The simulator accepts a command adapter so model access remains separate from
environment execution and grading. The runner starts the selected command
without a shell once per proposed action, writes one JSON request to stdin,
and expects one JSON response on stdout. The adapter never executes the chosen
simulator action itself.

## Protocol 1.0

Request:

```json
{
  "protocol_version": "1.0",
  "model": "EXPLICIT_MODEL_ID",
  "system": "Follow the task and simulation policies; return one action.",
  "observation": {"task": "...", "policy": {}, "state": {}, "tools": []},
  "history": [
    {"action": {"tool": "inspect", "arguments": {}}, "result": {"ok": true}}
  ],
  "max_output_tokens": 512
}
```

Response:

```json
{
  "action": {"tool": "local_process", "arguments": {}},
  "metadata": {
    "provider": "anthropic",
    "model": "RETURNED_MODEL_ID",
    "request_id": "PROVIDER_REQUEST_ID",
    "usage": {"input_tokens": 100, "output_tokens": 12},
    "settings": {"api_version": "2023-06-01", "max_tokens": 512}
  }
}
```

The action must contain exactly `tool` (a nonempty string) and `arguments` (an
object). The simulator subsequently checks the named tool, its arguments, and
authorization. Provider metadata is kept separate from model-visible history;
the runner retains an allowlist of reproducibility fields. Never place API keys
or arbitrary provider error bodies in either output stream.

Adapters should write diagnostics to stderr, exit nonzero on failure, and emit
no partial action on malformed, refused, or truncated model output. Adapter
failures are recorded as errors, not as evidence of safe refusal or successful
task completion. The included command runner requires `--allow-live` even for
a user-supplied command that happens to be offline; this gate marks a deliberate
choice to run external code, not a guarantee that every command is paid.

## Included Anthropic adapter

Module: `permission_thresholds.anthropic_adapter`.

It uses Python's standard library and the official Messages API. It accepts the
protocol above and reads **only `ANTHROPIC_API_KEY` from the process environment**.
It does not search local files, load `.env` files, inspect other projects, or use
the desktop application's authentication. The model ID must be explicitly
provided by the runner. There is no default model or hidden model substitution.
Choose an available model from your provider account and record that choice.

From the project directory, check configuration without contacting the provider:

```sh
PYTHONPATH=src python3 -m permission_thresholds.anthropic_adapter --check-config
```

The command prints only `{"api_key_present": true}` or
`{"api_key_present": false}`. Presence does not validate the key, account access,
model availability, or billing. No stdin is read in this mode.

To select it in the runner, use this adapter command together with the runner's
`--backend command`, `--model` and `--allow-live` options:

```text
--adapter "python3 -m permission_thresholds.anthropic_adapter"
```

Use the same `PYTHONPATH=src` environment as other project commands, or install
the project first. The adapter also supports an explicit output-budget override:

```text
--adapter "python3 -m permission_thresholds.anthropic_adapter --max-tokens 256"
```

The JSON request budget defaults to 512 when absent; `--max-tokens` overrides it.
Allowed values are 1–4096. For reproducibility, prefer setting the runner's
budget so the run manifest and effective provider budget agree. A complete
rollout can make multiple requests; an output-token limit is not a dollar cap.
No paid request was made during project creation.

## Transport and parsing behavior

- Exactly one POST per adapter invocation to
  `https://api.anthropic.com/v1/messages`, using `x-api-key`,
  `anthropic-version: 2023-06-01`, and normal TLS certificate verification.
- No endpoint override, HTTP redirect, ambient proxy, or automatic retry.
  Network operations use a 45-second timeout; the runner adds its own process
  timeout. A request and a response are each limited to 1,000,000 bytes.
- The task system text is sent in the API's top-level `system` field; observation
  and history are serialized into one user message. The adapter appends only
  the action-output format requirement. It sends no gold labels, native tool
  definitions, or external tool-execution request.
- Streaming is disabled. Sampling settings are left at the provider default,
  which the metadata records; no claim of determinism follows from this.
- Only a completed `end_turn` response with text blocks is accepted. Plain JSON
  and one complete fenced JSON block are supported. Extra prose, extra action
  fields, duplicate JSON keys, non-finite numbers, native tool responses, and
  truncated/refused output fail closed.
- Successful metadata includes returned model, sanitized request ID, token
  counts, and effective settings. HTTP failures expose only a status-based
  local code; provider bodies and raw network exception messages are discarded.

The current pilot uses simulated resources. Even in a live model run, model
actions mutate the simulator, not real files, accounts, servers, or permissions.
The supplied adapter is implemented and mock-tested, but has not been validated
against a live account or claimed to produce experimental evidence.

## Offline verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p test_anthropic_adapter.py -v
```

Tests mock HTTP and cover payload construction, parsing, token settings, schema
errors, oversized output, refusal/truncation handling, redirect prevention,
credential/error redaction, missing-key behavior, and the offline config flag.

## API references

Checked 2026-10-18 using Context7's official Anthropic SDK documentation and the
primary API documentation:

- [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- [API overview](https://platform.claude.com/docs/en/api/overview)
- [Official SDK request headers](https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/_client.py)

Model access and API behavior may change. The recorded version header and
explicit model identifier make future runs inspectable; they do not replace
account-specific compatibility checks.
