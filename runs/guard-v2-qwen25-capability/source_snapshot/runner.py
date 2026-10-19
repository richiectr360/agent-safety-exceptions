"""Reproducible rollout logging. No network is used by the scripted backend."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import time
from typing import Any
import uuid

from . import __version__
from .actors import ActorError, CommandActor, ScriptedActor, SYSTEM_PROMPT, safe_metadata, validate_action
from .core import Simulator, replay_avoidable_creation
from .scenarios import make_conditions, validate_scenarios


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def public_history(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Explicit allowlist. Never send labels, replay results, or condition IDs."""
    return [{"action": deepcopy(e["action"]), "result": deepcopy(e["result"])} for e in trace]


def run_episode(scenario: dict[str, Any], condition: dict[str, Any], actor: Any,
                *, run_id: str, repeat: int, backend: str, actor_name: str,
                model: str, synthetic: bool, max_output_tokens: int = 512) -> dict[str, Any]:
    env = Simulator(scenario, condition)
    calls = []
    error = None
    started = time.monotonic()
    while not env.done:
        request = {"protocol_version": "1.0", "model": model, "system": SYSTEM_PROMPT,
                   "observation": env.observation(), "history": public_history(env.trace),
                   "max_output_tokens": max_output_tokens}
        tick = time.monotonic()
        try:
            response = actor.next_action(request)
            action = validate_action(response["action"])
        except ActorError as exc:
            error = str(exc)
            calls.append({"action_index": len(env.trace), "seconds": time.monotonic() - tick,
                          "error": error})
            break
        env.step(action)
        calls.append({"action_index": len(env.trace) - 1, "seconds": time.monotonic() - tick,
                      "metadata": safe_metadata(response.get("metadata", {}))})
    actions = [deepcopy(e["action"]) for e in env.trace]
    metrics = env.metrics()
    replay = replay_avoidable_creation(scenario, condition, actions)
    metrics["avoided_by_removal"] = replay["avoided_by_removal"]
    status = "adapter_error" if error else ("completed" if metrics["task_success"] else "budget_exhausted")
    return {
        "schema_version": 1, "run_id": run_id,
        "scenario_id": scenario["family_id"], "family_id": scenario["family_id"], "domain": scenario["domain"],
        "split": scenario["split"], "scenario_sha256": digest(scenario),
        "condition": deepcopy(condition), "repeat": repeat, "backend": backend,
        "actor": actor_name, "model": model, "results_are_synthetic": synthetic,
        "episode_status": status, "adapter_error": error, "metrics": metrics,
        "actions": actions, "events": env.trace, "counterfactual_audit": replay,
        "adapter_calls": calls, "elapsed_seconds": time.monotonic() - started,
    }


def run_to_file(scenarios: list[dict[str, Any]], out: Path, *, backend: str = "scripted",
                actor_name: str = "honest", repeats: int = 1, model: str = "scripted",
                adapter: str | None = None, timeout: float = 90, allow_live: bool = False,
                adapter_is_synthetic: bool = False, limit: int | None = None,
                max_output_tokens: int = 512, seed: int = 20261018) -> dict[str, Any]:
    errors = validate_scenarios(scenarios)
    if errors or not scenarios:
        raise ValueError("; ".join(errors) if errors else "scenario list is empty")
    if repeats < 1 or (limit is not None and limit < 1) or not 1 <= max_output_tokens <= 4096:
        raise ValueError("positive repeats/limit and 1..4096 output tokens required")
    if backend not in {"scripted", "command"}:
        raise ValueError("unknown backend")
    if backend == "command" and (not allow_live or not adapter or not model or model == "scripted"):
        raise ValueError("command backend requires --allow-live, --adapter, and an explicit --model")
    if backend == "scripted":
        ScriptedActor(actor_name, {"policy_mode": "never"})  # Validate before writing.
        model = "scripted"
    cases = [(s, c, repeat) for s in scenarios for c in make_conditions(s) for repeat in range(repeats)]
    random.Random(seed).shuffle(cases)
    if limit is not None:
        cases = cases[:limit]
    # Isolated episodes plus shuffled execution reduce ordering confounds.
    manifest_path = out.with_suffix(out.suffix + ".manifest.json")
    if out.exists() or manifest_path.exists():
        raise FileExistsError("run or manifest exists; choose a new output path")
    out.parent.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(Path(__file__).parent.glob("*.py"))}
    manifest = {
        "schema_version": 1, "run_id": run_id, "project_version": __version__,
        "created_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
        "backend": backend, "actor": actor_name if backend == "scripted" else "external",
        "model": model, "results_are_synthetic": backend == "scripted" or adapter_is_synthetic,
        "planned_episodes": len(cases), "completed_episodes": 0, "adapter_error_episodes": 0,
        "scenario_sha256": digest(scenarios), "source_sha256": source_hashes,
        "system_prompt_sha256": digest(SYSTEM_PROMPT), "max_output_tokens": max_output_tokens,
        "schedule_seed": seed, "schedule": [
            {"scenario_id": s["family_id"], "condition_id": c["condition_id"], "repeat": repeat}
            for s, c, repeat in cases
        ],
        "repeats": repeats, "action_limit_per_scenario": {s["family_id"]: s["max_actions"] for s in scenarios},
        "api_calls_per_episode_bound": max(s["max_actions"] for s in scenarios),
        "notes": "Development simulator. Scripted actors are pipeline checks, not model findings. No automatic retries.",
    }
    manifest_path.write_text(canonical(manifest) + "\n")
    try:
        with out.open("x", encoding="utf-8") as stream:
            for scenario, condition, repeat in cases:
                actor = (ScriptedActor(actor_name, condition) if backend == "scripted"
                         else CommandActor(adapter, timeout=timeout))
                episode = run_episode(scenario, condition, actor, run_id=run_id, repeat=repeat,
                                      backend=backend, actor_name=manifest["actor"], model=model,
                                      synthetic=manifest["results_are_synthetic"], max_output_tokens=max_output_tokens)
                stream.write(canonical(episode) + "\n")
                stream.flush()
                manifest["completed_episodes"] += 1
                manifest["adapter_error_episodes"] += episode["episode_status"] == "adapter_error"
        manifest["status"] = "complete"
    finally:
        if manifest["status"] == "running":
            manifest["status"] = "interrupted"
        if out.exists():
            manifest["output_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
        temp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temp.write_text(canonical(manifest) + "\n")
        temp.replace(manifest_path)
    return manifest


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                raise ValueError(f"Invalid JSON at {path.name}:{number}") from None
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path.name}:{number}")
            records.append(value)
    return records
