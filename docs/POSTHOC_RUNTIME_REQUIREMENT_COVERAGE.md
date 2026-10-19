# Post hoc runtime requirement coverage

`RequirementCoveredBroker` adds a requirement veto to the local executable broker. This change was developed after examining the frozen study and was **not** used to collect its model results. It is an executable hardening prototype and tested invariant, not measured model-effectiveness evidence. No frozen broker, guard, collector, sanitizer, analyzer, protocol, or cases were changed to add it.

The wrapper prevents the simulated external report route from writing an artifact when an explicit background-repair requirement lacks complete runtime registration or verified completion. The inherited gate must independently permit the action. Coverage `PROCEED` supplies no permission and cannot override an underlying `DENY` or `DEFER`.

## Integration

Use this class explicitly in a new application or separately versioned study:

```python
from pathlib import Path
from permission_thresholds.hardened_guard_broker import RequirementCoveredBroker

case = {
    "id": "example-task",
    "category": "queue",
    "initial_external_units": 8,
    "required_units": 8,
    "repair_required": True,
    "repair_registered": True,
    "max_actions": 12,
}
broker = RequirementCoveredBroker(Path("fresh-episode-directory"), case, "ceg")
try:
    # Before repair, external_report is deferred without writing report.json.
    broker.step({"tool": "repair", "arguments": {}})
    broker.step({"tool": "queue_required", "arguments": {"units": 8}})
    result = broker.step({"tool": "external_report", "arguments": {}})
    # Verified repair removes the repair veto; approved load satisfies CEG.
    assert result["ok"]
finally:
    broker.close()
```

Construction is a trusted operation. The actor receives only the inherited JSON tool interface. Callers must declare `repair_required` explicitly; a missing declaration defers exceptional access even though the original broker defaults it to false. A caller needing a different policy must create a separately scoped trusted task rather than accepting an actor's claim that the requirement changed.

The original collector intentionally still constructs the original `Broker`. This prototype cannot silently change the frozen experiment. An application adopting the wrapper should record the separate `hardening_manifest.json` and its new event types, and use an appropriately versioned auditor. Original study replay scripts must not be represented as validating hardened runs.

## Live evidence and dispatch

1. Construction captures immutable broker-manifest bytes, their hash, the frozen manifest object, and the exact initial background cause identities. It records a separate hardening manifest and wrapper source hash.
2. Each decision takes a broker-owned event-prefix snapshot under the broker lock. The existing requirement-coverage parser verifies exact release events and committed successful repair receipts. Later repairs cannot justify earlier requests. Actor assertions and report artifacts are never repair receipts.
3. The wrapper compares that evidence with current SQL background counts and cause identities. It also checks that the actual broker recovery set and guard obligation cover exactly the original background causes, with the expected immediate deadline and no infeasibility exemption. A static `repair_registered` flag alone is insufficient. Zero original background causes require no repair receipt or nonempty obligation.
4. It composes the result as a veto with the selected baseline. An omitted registration remains a deferral even if the actor subsequently performs repair; ordinary repair followed by local reporting remains possible.
5. Immediately before `_write_report("external_simulated")`, it repeats the full composed decision under the same broker lock. The inherited CEG lease executor rechecks only its own ledger, so this callback check is necessary. A newly failed coverage check prevents report creation even when the inherited lease remains acceptable.

`requirement_coverage_decision` events record the evidence prefix boundary, prefix hash, gate result, and hardening version. A veto at the final callback records `requirement_coverage_execution_blocked`; the inherited broker reports an execution failure and latches uncertainty. Existing `external_allows` counts the earlier decision, not successful execution. Actual execution must be counted from `report_written` events with route `external_simulated`, together with artifact verification. This distinction matters in the lease fault-injection test.

## Validation and limits

The tests cover omitted and outstanding repair requirements; verified completion permitting the underlying gate; live SQL disagreement; runtime registration loss; forged actor claims and arguments; unchanged ordinary workflows; unknown declarations; changed manifests; and a fault deliberately introduced after lease creation. The last test confirms that CEG's inherited callback cannot bypass the added check. These are deterministic implementation tests, not new model experiments.

The trust boundary is the local broker process and its validated JSON tools. Trusted Python code, SQLite, manifest creation, and event recording remain in the trusted computing base. Snapshot hashes establish local integrity and identity, not cryptographic proof of origin or resistance to a compromised host. The wrapper explicitly uses trusted SQL origin records for this new coverage check; it is not evidence that a monitor inferred unavailable origins.

The external route is still simulated: it computes and writes a local JSON report and sends no network data. The broker lock coordinates this process, not multiple independent services. A real remote dispatcher would need its own atomic authorization/execution integration, authenticated evidence, and crash/retry semantics. No claim of protection for arbitrary callbacks, arbitrary Python execution, external systems, or a compromised broker is made.

This requirement gate may defer when evidence is incomplete even if the actual action would satisfy policy. Such deferrals are availability costs; they should not all be relabeled prevented violations. The wrapper covers the explicit repair requirement represented in this task manifest. It does not discover omitted requirements that were never declared to the trusted constructor.
