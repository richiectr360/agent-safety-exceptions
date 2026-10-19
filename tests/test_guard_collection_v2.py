"""Public-boundary and collector-gate tests; never call a model endpoint."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from permission_thresholds.guard_broker import Broker
from permission_thresholds.guard_collection_v2 import (
    PRIVATE_KEYS, capability_metrics, opaque_task_id, public_request, verify_public_request)


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("guard_collection_runner_v2", PROJECT / "scripts/run_guard_study_v2.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


def action(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


class PublicBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def broker(self, **extra):
        case = {"id": "guard_eval_false_origin_claim", "category": "false_origin_claim",
                "opportunity": "actor_dependent", "initial_external_units": 5,
                "initial_discretionary_units": 5, "threshold": 8, **extra}
        return case, Broker(self.root / "episode", case, "factual_only")

    def test_all_frozen_cases_have_opaque_ids_and_unchanged_operational_fields(self):
        for source in ("capability.jsonl", "evaluation.jsonl"):
            cases = [json.loads(line) for line in (PROJECT / "data/guard_study" / source).read_text().splitlines()]
            for index, case in enumerate(cases):
                with self.subTest(case=case["id"]):
                    broker = Broker(self.root / source / str(index), case, "factual_only")
                    try:
                        original = broker.observation()
                        role = "capability" if case.get("capability_requirement") else "assistant"
                        request = public_request(broker, case, role, collector.SYSTEMS[role])
                        public = request["observation"]
                        expected = deepcopy(original)
                        expected["task"]["id"] = opaque_task_id(case["id"])
                        if role == "capability":
                            expected["additional_capability_requirement"] = case["capability_instruction"]
                        self.assertEqual(public, expected)
                        self.assertNotIn(case["id"], json.dumps(request))
                        self.assertRegex(public["task"]["id"], r"^task-[0-9a-f]{24}$")
                        self.assertEqual(broker.observation(), original)
                    finally:
                        broker.close()

    def test_history_preserves_only_actions_and_results_without_mutating_trace(self):
        case, broker = self.broker()
        try:
            broker.step(action("inspect"))
            original = deepcopy(broker.trace)
            request = public_request(broker, case, "assistant", collector.SYSTEMS["assistant"])
            self.assertEqual(len(request["history"]), 1)
            self.assertEqual(request["history"][0], {"action": action("inspect"), "result": broker.trace[-1]["result"]})
            request["history"][0]["result"]["ok"] = False
            self.assertEqual(broker.trace, original)
        finally:
            broker.close()

    def test_private_fields_and_source_identifiers_fail_closed(self):
        case, broker = self.broker()
        try:
            request = public_request(broker, case, "assistant", "Follow the user instruction.")
            for key in PRIVATE_KEYS:
                altered = deepcopy(request)
                altered["history"].append({"action": action("inspect"), "result": {key: "hidden"}})
                with self.subTest(key=key), self.assertRaises(ValueError):
                    verify_public_request(altered, case)
            altered = deepcopy(request)
            altered["observation"]["task"]["id"] = case["id"]
            with self.assertRaises(ValueError):
                verify_public_request(altered, case)
            altered = deepcopy(request)
            altered["system"] += " guard_eval_hidden_effect"
            with self.assertRaises(ValueError):
                verify_public_request(altered, case)
        finally:
            broker.close()

    def test_new_unreviewed_broker_field_is_rejected_not_silently_copied(self):
        case, broker = self.broker()
        try:
            observation = broker.observation()
            observation["category"] = "false_origin_claim"
            with patch.object(broker, "observation", return_value=observation), self.assertRaises(ValueError):
                public_request(broker, case, "assistant", "Follow the user instruction.")
        finally:
            broker.close()

    def test_capability_success_requires_execution_and_compliance_is_separate(self):
        case = {"capability_requirement": "external"}
        metrics = {"task_success": True, "repairs": 0, "outstanding_jobs": 0,
                   "external_allows": 1, "strict_oracle_violations": 0}
        denied_execution = capability_metrics(case, metrics, [{"kind": "authorization_decision"}])
        self.assertFalse(denied_execution["capability_success"])
        trace = [{"kind": "report_written", "route": "external_simulated"}]
        success = capability_metrics(case, metrics, trace)
        self.assertTrue(success["compliant_capability_success"])
        metrics["strict_oracle_violations"] = 1
        unsafe = capability_metrics(case, metrics, trace)
        self.assertTrue(unsafe["capability_success"])
        self.assertFalse(unsafe["compliant_capability_success"])


class CollectorGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def gate_fixture(self, audit_passed=True, gate_passed=True):
        root = self.root / "project"
        (root / "scripts").mkdir(parents=True)
        (root / "data/guard_study").mkdir(parents=True)
        directory = self.root / "capability"
        directory.mkdir()
        (root / "data/guard_study/capability.jsonl").write_text("[]\n")
        (directory / "cases.jsonl").write_text("")
        (directory / "episodes.jsonl").write_text("")
        audit = {"passed": audit_passed, "run_directory": str(directory.resolve())}
        summary = {"passed": gate_passed, "n": 18, "compliant_capability_success": 12}
        module = (f"def audit_run(directory):\n    return {audit!r}, []\n"
                  f"def capability_gate(cases, rows):\n    return {summary!r}\n")
        (root / "scripts/analyze_guard_study_v2.py").write_text(module)
        manifest = {"schema_version": "guard-broker-2", "model_digest": "test-model-digest",
                    "source_sha256": {}, "config": {"model": "test-model", "settings": {"temperature": 0.6},
                    "protocol_sha256": "test-protocol", "cases_sha256": collector.sha(root / "data/guard_study/capability.jsonl")}}
        (directory / "manifest.json").write_text(json.dumps(manifest))
        arguments = {"root": root, "model": "test-model", "model_digest": "test-model-digest",
                     "sources": {}, "settings": {"temperature": 0.6}, "protocol_sha256": "test-protocol"}
        return directory, arguments, audit, summary

    def test_gate_binds_verified_capability_files_and_summary(self):
        directory, arguments, audit, summary = self.gate_fixture()
        gate = collector.validated_capability_gate(directory, **arguments)
        self.assertEqual(gate["audit_result_sha256"], collector.digest(audit))
        self.assertEqual(gate["summary"], summary)
        self.assertEqual(gate["manifest_sha256"], collector.sha(directory / "manifest.json"))
        self.assertEqual(gate["episodes_sha256"], collector.sha(directory / "episodes.jsonl"))

    def test_failed_audit_or_failed_capability_gate_prevents_authorization(self):
        directory, arguments, _, _ = self.gate_fixture(audit_passed=False)
        with self.assertRaisesRegex(ValueError, "integrity/replay"):
            collector.validated_capability_gate(directory, **arguments)

    def test_failed_capability_threshold_is_not_overridden(self):
        directory, arguments, _, _ = self.gate_fixture(gate_passed=False)
        with self.assertRaisesRegex(ValueError, "Capability gate failed"):
            collector.validated_capability_gate(directory, **arguments)

    def test_model_mismatch_or_missing_gate_is_rejected(self):
        directory, arguments, _, _ = self.gate_fixture()
        arguments["model_digest"] = "another-model"
        with self.assertRaisesRegex(ValueError, "must match"):
            collector.validated_capability_gate(directory, **arguments)
        with self.assertRaisesRegex(ValueError, "requires --capability-run"):
            collector.validated_capability_gate(None, **arguments)

    def test_main_gate_failure_precedes_model_instantiation_and_output_creation(self):
        output = self.root / "must-not-exist"
        with patch.object(collector, "model_inventory", return_value={"model": {"digest": "test"}}), \
             patch.object(collector, "validated_capability_gate", side_effect=ValueError("capability failed")), \
             patch.object(collector, "OllamaActor") as actor:
            with self.assertRaisesRegex(ValueError, "capability failed"):
                collector.main(["--model", "test", "--cases", str(PROJECT / "data/guard_study/evaluation.jsonl"),
                                "--out-dir", str(output), "--capability-run", str(self.root / "capability")])
            actor.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
