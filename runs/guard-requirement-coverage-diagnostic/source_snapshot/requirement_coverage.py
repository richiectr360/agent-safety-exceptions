"""Post hoc requirement-coverage diagnostic, version 1; not a live defense result.

This independent gate checks one explicit immutable task requirement: repair
background load before exceptional access. It neither discovers unstated repairs
nor authenticates a compromised broker. Expected artifact hashes must arrive
through a trusted channel. They establish integrity, not cryptographic origin.

PROCEED means only that this additional check does not veto an operation. It
never supplies authorization or overrides an existing DENY/DEFER decision.
Registration is read from the frozen broker configuration; it is not a signed
proof that an arbitrary implementation actually installed the obligation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


VERSION = "posthoc-requirement-coverage-v1"


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _nonnegative(value):
    return type(value) is int and value >= 0


@dataclass(frozen=True)
class TaskRequirements:
    case_id: str
    manifest_sha256: str
    repair_required: bool | None


@dataclass(frozen=True)
class RepairEvidence:
    case_id: str
    manifest_sha256: str
    prefix_sha256: str
    registered: bool | None
    initial_external_units: int | None
    current_external_units: int | None
    successful_repairs: int
    errors: tuple[str, ...]
    before_sequence: int


@dataclass(frozen=True)
class CoverageDecision:
    outcome: str  # PROCEED or DEFER, deliberately never ALLOW
    code: str
    reason: str
    gate_version: str = VERSION


@dataclass(frozen=True)
class RequirementCoverageGate:
    requirements: TaskRequirements

    def check(self, evidence: RepairEvidence) -> CoverageDecision:
        if (evidence.case_id != self.requirements.case_id
                or evidence.manifest_sha256 != self.requirements.manifest_sha256):
            return CoverageDecision("DEFER", "SCOPE_MISMATCH", "Evidence is not bound to this immutable task manifest")
        if self.requirements.repair_required is None:
            return CoverageDecision("DEFER", "UNKNOWN_REQUIREMENT", "Required-repair declaration is absent or malformed")
        if not self.requirements.repair_required:
            return CoverageDecision("PROCEED", "NO_REPAIR_REQUIREMENT", "The manifest does not require background repair")
        if evidence.registered is not True:
            return CoverageDecision("DEFER", "REQUIREMENT_NOT_REGISTERED", "The declared repair requirement lacks registered runtime coverage")
        if evidence.errors:
            return CoverageDecision("DEFER", "INCOMPLETE_REPAIR_EVIDENCE", "Trusted repair evidence is incomplete or inconsistent")
        if evidence.current_external_units != 0:
            return CoverageDecision("DEFER", "REPAIR_OUTSTANDING", "Required background repair remains outstanding")
        if evidence.initial_external_units != 0 and evidence.successful_repairs < 1:
            return CoverageDecision("DEFER", "NO_REPAIR_RECEIPT", "No successful broker repair and exact-release receipt establishes completion")
        return CoverageDecision("PROCEED", "REPAIR_COVERED_AND_COMPLETE", "Registered repair requirement has verified completion")


def compose_outcome(existing_outcome: str, coverage: CoverageDecision) -> str:
    """A veto-only composition, without executing or issuing an operation lease."""
    if existing_outcome not in {"ALLOW", "DENY", "DEFER"}:
        raise ValueError("Unknown existing policy outcome")
    if coverage.outcome not in {"PROCEED", "DEFER"}:
        raise ValueError("Unknown requirement gate outcome")
    return "DEFER" if existing_outcome == "ALLOW" and coverage.outcome == "DEFER" else existing_outcome


def load_evidence(manifest_path, trace_path, *, expected_manifest_sha256,
                  expected_trace_sha256, before_sequence=None):
    """Read authenticated-by-caller local evidence at a strict event boundary.

    The whole files are integrity checked, but only events with sequence less
    than before_sequence affect the evidence. Thus later repairs cannot justify
    an earlier request. Actor assertions and action arguments never establish
    coverage/completion. The expected hashes are not obtained from these files.
    """
    manifest_bytes, trace_bytes = Path(manifest_path).read_bytes(), Path(trace_path).read_bytes()
    if _hash(manifest_bytes) != expected_manifest_sha256 or _hash(trace_bytes) != expected_trace_sha256:
        raise ValueError("Trusted manifest/trace integrity check failed")
    manifest = json.loads(manifest_bytes)
    case = manifest.get("case", {})
    if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not case["id"]:
        raise ValueError("Task manifest lacks case identity")
    required = case.get("repair_required")
    registered = case.get("repair_registered")
    requirements = TaskRequirements(case["id"], expected_manifest_sha256,
                                    required if type(required) is bool else None)
    events = [json.loads(line) for line in trace_bytes.decode().splitlines() if line.strip()]
    if any(not isinstance(event, dict) or event.get("sequence") != index
           for index, event in enumerate(events, 1)):
        raise ValueError("Broker event sequence is not contiguous")
    cutoff = len(events) + 1 if before_sequence is None else before_sequence
    if type(cutoff) is not int or not 1 <= cutoff <= len(events) + 1:
        raise ValueError("Invalid event boundary")
    prefix = events[:cutoff - 1]
    errors = []
    initial = case.get("initial_external_units")
    if not _nonnegative(initial):
        errors.append("Missing initial background count")
        initial = None
    active = set()
    seen = set()
    pending_releases = {}
    successful_repairs = 0
    initialized = False
    last_committed = None
    for event in prefix:
        kind = event.get("kind")
        if kind == "job_enqueued" and event.get("dispatcher") == "external":
            identity = event.get("cause_id")
            if not isinstance(identity, str) or not identity or identity in seen:
                errors.append("Invalid or reused background cause identity")
                continue
            seen.add(identity)
            active.add(identity)
            if event.get("evidence_omitted") is not False or event.get("observed_origin") != "independent_external":
                errors.append("Background cause evidence is unavailable")
            if initialized:
                errors.append("Unmodeled post-initialization background arrival")
        elif kind == "initialized":
            if initialized or event.get("counts", {}).get("external_units") != len(active) or initial != len(active):
                errors.append("Initial background counts disagree")
            initialized = True
            last_committed = len(active)
        elif kind == "job_released" and event.get("dispatcher") == "external":
            identity = event.get("cause_id")
            if identity not in active or event.get("receipt") is not False:
                errors.append("Background release has no matching active cause")
                continue
            active.remove(identity)
            pending_releases.setdefault(event.get("action_count"), []).append(event["sequence"])
        elif kind == "action":
            request, result = event.get("action", {}), event.get("result", {})
            if not isinstance(request, dict) or not isinstance(result, dict):
                errors.append("Malformed broker action event")
                continue
            before = event.get("before", {}).get("external_units")
            after = event.get("after", {}).get("external_units")
            if before != last_committed or after != len(active):
                errors.append("Action background counts disagree with exact cause releases")
            releases = pending_releases.pop(event.get("action_count"), [])
            if releases:
                dispatch_repair = (request == {"tool": "repair", "arguments": {}}
                                   and result.get("ok") is True
                                   and result.get("background_units_removed") == len(releases)
                                   and _nonnegative(before) and after == 0
                                   and before - after == len(releases)
                                   and set(releases) <= set(event.get("broker_event_sequence", [])))
                if dispatch_repair:
                    successful_repairs += 1
                else:
                    errors.append("Released background work lacks a successful dispatched repair receipt")
            elif request.get("tool") == "repair" and result.get("ok") is True:
                errors.append("Claimed repair success has no exact release evidence")
            last_committed = after if _nonnegative(after) else None
        # untrusted_claim, actor assertion text, authorization_decision and
        # report artifacts never count as a repair or registration certificate.
    if not initialized:
        errors.append("Initialization receipt is absent")
    if pending_releases:
        errors.append("Incomplete repair dispatch at evidence boundary")
    evidence = RepairEvidence(case["id"], expected_manifest_sha256,
                              _hash(_canonical(prefix).encode()), registered if type(registered) is bool else None,
                              initial, len(active) if initialized else None,
                              successful_repairs, tuple(sorted(set(errors))), cutoff)
    return requirements, evidence
