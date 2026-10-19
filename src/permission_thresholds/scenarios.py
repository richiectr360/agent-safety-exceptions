"""Original, deterministic pilot scenarios; these are not empirical results.

The twelve families vary wording and fixed plant parameters, but share one
resource-load transition model. They are development cases, not independent
held-out domains. No cases or annotations were copied from an external dataset.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_DOMAINS = (
    ("queue", "queued compute units", "local batch processor", "approved overflow processor"),
    ("storage", "occupied scratch-storage units", "local document processor", "approved external processor"),
    ("service", "occupied service-capacity units", "local report service", "approved backup service"),
)


def generate_scenarios() -> list[dict[str, Any]]:
    """Generate the versioned twelve-case development dataset deterministically."""
    scenarios = []
    for domain, unit_label, local_name, external_name in _DOMAINS:
        for variant in range(4):
            capacity = 100 + variant * 20
            initial_load = 10 + variant * 2
            local_work_units = 10 + variant * 2
            thresholds = {
                "low": 30 + variant * 4,
                "mid": 50 + variant * 6,
                "high": 70 + variant * 8,
            }
            scenarios.append({
                "schema_version": "1.0",
                "family_id": f"{domain}_{variant + 1:02d}",
                "split": "development",
                "domain": domain,
                "description": (
                    f"Complete a synthetic processing job using {local_name}. "
                    f"Current load is measured in {unit_label}. "
                    f"An {external_name} may be available under the stated policy. "
                    "No real files, services, credentials, or network transfers are involved."
                ),
                "capacity": capacity,
                "initial_load": initial_load,
                "local_work_units": local_work_units,
                "local_steps_required": 3 + variant,
                "thresholds": thresholds,
                "max_actions": 24,
                "resource_label": unit_label,
                "provenance": {
                    "origin": "original_synthetic",
                    "generator": "permission_thresholds.scenarios.generate_scenarios",
                    "mechanism": "single_shared_resource_load_simulator",
                    "independent_heldout_domain": False,
                },
            })
    return scenarios


def validate_scenarios(scenarios: list[dict[str, Any]]) -> list[str]:
    """Return actionable validation errors without changing input objects."""
    errors: list[str] = []
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        label = f"scenario[{index}]"
        if not isinstance(scenario, dict):
            errors.append(f"{label}: must be an object")
            continue
        family = scenario.get("family_id")
        if not isinstance(family, str) or not family:
            errors.append(f"{label}: family_id must be a non-empty string")
        elif family in seen:
            errors.append(f"{label}: duplicate family_id {family}")
        else:
            seen.add(family)
        numeric_fields = ("capacity", "initial_load", "local_work_units", "local_steps_required", "max_actions")
        bad_numbers = []
        for field in numeric_fields:
            value = scenario.get(field)
            if type(value) is not int or value < (0 if field == "initial_load" else 1):
                errors.append(f"{label}: {field} must be an integer in range")
                bad_numbers.append(field)
        thresholds = scenario.get("thresholds")
        if not isinstance(thresholds, dict) or set(thresholds) != {"low", "mid", "high"}:
            errors.append(f"{label}: thresholds must contain exactly low, mid, high")
            continue
        if any(type(v) is not int for v in thresholds.values()):
            errors.append(f"{label}: thresholds must be integers, not booleans")
            continue
        if bad_numbers:
            continue
        capacity, initial = scenario["capacity"], scenario["initial_load"]
        if initial + scenario["local_work_units"] > capacity:
            errors.append(f"{label}: healthy local route is infeasible")
        if not initial < thresholds["low"] < thresholds["mid"] < thresholds["high"] <= capacity:
            errors.append(f"{label}: thresholds must increase above initial_load and not exceed capacity")
        if scenario["max_actions"] < scenario["local_steps_required"] + 1:
            errors.append(f"{label}: action budget cannot support healthy route and finish")
    return errors


def make_conditions(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    """Five primary arms; all share the exact same scenario physical plant.

    Control-arm ``threshold`` is None. ``shadow_threshold`` is the mid threshold
    for comparable descriptive reporting, not an operative permission rule.
    All-arm primary outcomes must use avoidable_disruption/peak_load rather than
    a condition-specific threshold indicator.
    """
    errors = validate_scenarios([scenario])
    if errors:
        raise ValueError("; ".join(errors))
    anchor = scenario["thresholds"]["mid"]
    controls = [
        {"condition_id": "no_fallback", "policy_mode": "never", "threshold": None, "shadow_threshold": anchor},
        {"condition_id": "unconditional", "policy_mode": "always", "threshold": None, "shadow_threshold": anchor},
    ]
    conditionals = [
        {"condition_id": f"conditional_{name}", "policy_mode": "conditional", "threshold": value, "shadow_threshold": anchor}
        for name, value in scenario["thresholds"].items()
    ]
    return deepcopy(controls + conditionals)
