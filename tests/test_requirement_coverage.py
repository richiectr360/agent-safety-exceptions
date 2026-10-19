"""Post hoc requirement gate tests; these are scripted checks, not model results."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from permission_thresholds.guard_broker import Broker
from permission_thresholds.requirement_coverage import (
    CoverageDecision, RequirementCoverageGate, compose_outcome, load_evidence,
)


class RequirementCoverageTests(unittest.TestCase):
    def episode(self, *, repair_required=True, repair_registered=True, actions=(), **kwargs):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        case = {"id": "coverage-test", "category": "coverage", "initial_external_units": 8,
                "repair_required": repair_required, "repair_registered": repair_registered,
                "max_actions": 12, **kwargs}
        broker = Broker(directory, case, "ceg")
        for tool in actions:
            broker.step({"tool": tool, "arguments": {}})
        broker.close()
        return directory

    def load(self, directory, cutoff=None):
        manifest, trace = directory / "broker_manifest.json", directory / "broker_trace.jsonl"
        return load_evidence(manifest, trace,
                             expected_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                             expected_trace_sha256=hashlib.sha256(trace.read_bytes()).hexdigest(),
                             before_sequence=cutoff)

    def check(self, directory, cutoff=None):
        requirements, evidence = self.load(directory, cutoff)
        return RequirementCoverageGate(requirements).check(evidence)

    def edit_events(self, directory, transform):
        path = directory / "broker_trace.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        transform(events)
        path.write_text("".join(json.dumps(event) + "\n" for event in events))

    def test_unregistered_declared_requirement_defers(self):
        decision = self.check(self.episode(repair_registered=False))
        self.assertEqual((decision.outcome, decision.code), ("DEFER", "REQUIREMENT_NOT_REGISTERED"))

    def test_registered_repair_outstanding_defers(self):
        decision = self.check(self.episode())
        self.assertEqual((decision.outcome, decision.code), ("DEFER", "REPAIR_OUTSTANDING"))

    def test_registered_repair_exact_release_receipts_allow_gate_to_proceed(self):
        directory = self.episode(actions=("repair",))
        requirements, evidence = self.load(directory)
        self.assertEqual(evidence.current_external_units, 0)
        self.assertEqual(evidence.successful_repairs, 1)
        self.assertEqual(evidence.errors, ())
        self.assertEqual(RequirementCoverageGate(requirements).check(evidence).outcome, "PROCEED")

    def test_absent_required_repair_does_not_veto_useful_external_route(self):
        directory = self.episode(repair_required=False, repair_registered=False,
                                 initial_external_units=10, repair_available=False)
        self.assertEqual(self.check(directory).outcome, "PROCEED")

    def test_unregistered_completion_remains_conservatively_uncovered(self):
        directory = self.episode(repair_registered=False, actions=("repair",))
        self.assertEqual(self.load(directory)[1].successful_repairs, 1)
        self.assertEqual(self.check(directory).code, "REQUIREMENT_NOT_REGISTERED")

    def test_actor_claim_cannot_register_requirement_or_complete_repair(self):
        for registered in (False, True):
            with self.subTest(registered=registered):
                directory = self.episode(repair_registered=registered, actions=("claim_external",))
                self.assertEqual(self.load(directory)[1].successful_repairs, 0)
                self.assertEqual(self.check(directory).outcome, "DEFER")

    def test_future_repair_does_not_justify_earlier_request(self):
        directory = self.episode(actions=("external_report", "repair"))
        events = [json.loads(line) for line in (directory / "broker_trace.jsonl").read_text().splitlines()]
        cutoff = next(event["sequence"] for event in events if event["kind"] == "authorization_decision")
        self.assertEqual(self.check(directory, cutoff).code, "REPAIR_OUTSTANDING")
        self.assertEqual(self.check(directory).outcome, "PROCEED")

    def test_partial_release_before_dispatch_receipt_defers(self):
        directory = self.episode(actions=("repair",))
        events = [json.loads(line) for line in (directory / "broker_trace.jsonl").read_text().splitlines()]
        cutoff = next(event["sequence"] for event in events if event["kind"] == "action")
        self.assertEqual(self.check(directory, cutoff).code, "INCOMPLETE_REPAIR_EVIDENCE")

    def test_malformed_claimed_repair_receipt_is_not_completion(self):
        directory = self.episode(actions=("repair",))
        def mutate(events):
            next(event for event in events if event["kind"] == "action")["result"]["background_units_removed"] = 999
        self.edit_events(directory, mutate)
        # Recomputed caller-trusted digest models a faulty trusted event producer,
        # not an attacker who can authenticate arbitrary events.
        self.assertEqual(self.check(directory).code, "INCOMPLETE_REPAIR_EVIDENCE")

    def test_non_repair_action_cannot_claim_external_release(self):
        directory = self.episode(actions=("repair",))
        def mutate(events):
            next(event for event in events if event["kind"] == "action")["action"] = {"tool": "claim_external", "arguments": {}}
        self.edit_events(directory, mutate)
        self.assertEqual(self.check(directory).code, "INCOMPLETE_REPAIR_EVIDENCE")

    def test_mismatched_task_binding_defers(self):
        requirements, evidence = self.load(self.episode(actions=("repair",)))
        gate = RequirementCoverageGate(requirements)
        self.assertEqual(gate.check(replace(evidence, case_id="other-job")).code, "SCOPE_MISMATCH")
        self.assertEqual(gate.check(replace(evidence, manifest_sha256="other-hash")).code, "SCOPE_MISMATCH")

    def test_unknown_declaration_defers_but_cannot_discover_unknown_repairs(self):
        requirements, evidence = self.load(self.episode(actions=("repair",)))
        gate = RequirementCoverageGate(replace(requirements, repair_required=None))
        self.assertEqual(gate.check(evidence).code, "UNKNOWN_REQUIREMENT")

    def test_hidden_or_missing_origin_cannot_supply_repair_evidence(self):
        for mode in ("hidden_external_effect", "missing_origin"):
            with self.subTest(mode=mode):
                directory = self.episode(evidence_mode=mode, actions=("repair",))
                self.assertEqual(self.check(directory).code, "INCOMPLETE_REPAIR_EVIDENCE")

    def test_unavailable_repair_does_not_override_obligation(self):
        directory = self.episode(repair_available=False, actions=("repair",))
        self.assertEqual(self.check(directory).code, "REPAIR_OUTSTANDING")

    def test_zero_initial_background_is_vacuously_complete_when_covered(self):
        self.assertEqual(self.check(self.episode(initial_external_units=0)).outcome, "PROCEED")

    def test_hash_verification_fails_closed(self):
        directory = self.episode()
        with self.assertRaisesRegex(ValueError, "integrity"):
            load_evidence(directory / "broker_manifest.json", directory / "broker_trace.jsonl",
                          expected_manifest_sha256="bad", expected_trace_sha256="bad")

    def test_sequence_gaps_are_rejected(self):
        directory = self.episode()
        self.edit_events(directory, lambda events: events[0].update(sequence=99))
        with self.assertRaisesRegex(ValueError, "sequence"):
            self.load(directory)

    def test_requirements_and_evidence_are_immutable(self):
        requirements, evidence = self.load(self.episode())
        with self.assertRaises(FrozenInstanceError):
            requirements.repair_required = False
        with self.assertRaises(FrozenInstanceError):
            evidence.registered = True

    def test_composition_never_grants_new_authority(self):
        proceed = CoverageDecision("PROCEED", "test", "test")
        defer = CoverageDecision("DEFER", "test", "test")
        for existing in ("ALLOW", "DENY", "DEFER"):
            self.assertEqual(compose_outcome(existing, proceed), existing)
            self.assertEqual(compose_outcome(existing, defer), "DEFER" if existing == "ALLOW" else existing)


if __name__ == "__main__":
    unittest.main()
