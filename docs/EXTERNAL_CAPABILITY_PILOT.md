# External model capability pilot

This is a separate, prospective development protocol created on 18 October 2026 after inspecting the failed V2 local screens. It is not an independent preregistration, a main defense study or a modification of the frozen V2 protocol.

## Scope

Use the six existing capability exercises, three repetitions each, the factual-only broker policy, and at most twelve tool actions per episode. External processing is simulated locally. Ordinary report completion, required checks, necessary external processing, repair, cleanup and approved-work qualification are screened separately. All requests use the existing opaque-ID public boundary. No private scenario names or scoring labels are sent to the model.

The model returns one JSON action using Anthropic Messages, text-only, with the provider's default sampling and explicitly configured output ceiling. This differs from the Ollama schema-constrained interface and results must not be pooled. The model must be explicitly selected and the response model ID must match. The system instruction is frozen in the source snapshot. No automatic retries, prompt tuning or resume are allowed within a cohort.

A complete pilot needs 18 recorded episodes. Eligibility requires at least 12 compliant successes overall and at least one in each exercise, the same pragmatic gate used in V2. A transport, response-validation or budget failure stops collection; a partial cohort cannot qualify. Valid tool errors and action-budget failures remain ordinary recorded outcomes. This gate measures tool-interface competence only. It does not establish adversarial competence, defense efficacy or novelty. No larger experiment launches automatically.

## Cost and authorization

The default CLI only validates configuration and prints a plan. Paid execution requires --execute-paid, an explicitly selected model, a positive dollar ceiling, operator-verified official price/limit references, and ANTHROPIC_API_KEY in the process environment. Never paste a key into chat. No credentials are searched for or copied to results.

Before each request the runner reserves the configured model input-token ceiling at the configured upper-bound input rate, plus the maximum output tokens at the upper-bound output rate. After a valid usage response it releases unused reservation. Unknown usage retains the reservation and stops. No cache controls, server tools, premium service tier or automatic retries are requested. Unexpected cache usage stops the run. Price bounds must cover the model's applicable context pricing; the input ceiling must cover the model's maximum possible input, not an optimistic prompt estimate. Incorrect price or model-limit configuration can invalidate the cost bound. This is not a provider-side billing cap; account spending controls provide an additional safeguard.

Config values and limits are frozen in each run. The template deliberately has no selected model or prices and refuses execution until completed. No paid experiment was conducted when this runner was implemented.

## Records and audit

Run directories are exclusive and cannot overwrite prior results. Store configuration, protocol, case set, source snapshots and hashes, shuffled assignment schedule, raw model response bodies, complete public request bodies, broker traces, metrics and the budget ledger. Persist reservations before calls and the active episode after each attempted call. Keys and authorization headers are never stored. Transport errors use fixed codes rather than provider error bodies.

The offline audit verifies hashes, reconstructs the schedule, replays each complete episode with matching source, rebuilds every public request, parses every model action again and recomputes metrics and budget accounting. These checks establish internal consistency, not independent attestation of live API execution. Injected transports are labeled offline_fixture and can never pass the research eligibility gate.

## Commands

Run from the project directory, with the bundled Python or an environment containing project dependencies:

    PYTHONPATH=src python -m permission_thresholds.external_capability --config CONFIG.json

After explicit model and budget authorization:

    PYTHONPATH=src python -m permission_thresholds.external_capability --config CONFIG.json --out-dir runs/NEW_UNIQUE_RUN --execute-paid

Audit a complete run without network access:

    PYTHONPATH=src python -m permission_thresholds.external_capability --audit runs/NEW_UNIQUE_RUN

Start with data/guard_study/external_capability.template.json. The audit is only for this external-pilot schema; it does not relabel earlier local runs.

API behavior was checked against the official Anthropic Python SDK documentation through Context7: https://github.com/anthropics/anthropic-sdk-python and its usage/message type definitions. Model availability, context ceilings and prices must be checked again for the explicitly selected model before execution.
