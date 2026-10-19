"""Post hoc boundary tests; these do not estimate model or deployment safety."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from permission_thresholds.guard_broker import Broker
from permission_thresholds.hardened_guard_broker import RequirementCoveredBroker


class HardenedBrokerTests(unittest.TestCase):
    def broker(self, baseline="ceg", *, raw_case=None, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        case = {"id": "runtime-coverage-test", "category": "queue",
                "repair_required": False, "repair_registered": False,
                "max_actions": 30, **kwargs} if raw_case is None else raw_case
        broker = RequirementCoveredBroker(Path(directory.name), case, baseline)
        self.addCleanup(broker.close)
        return broker

    def call(self, broker, tool, **arguments):
        return broker.step({"tool": tool, "arguments": arguments})

    def coverage(self, broker):
        return [event["decision"] for event in broker.trace
                if event["kind"] == "requirement_coverage_decision"][-1]

    def no_external_artifact(self, broker):
        self.assertFalse(broker.report_path.exists())
        self.assertFalse(any(event["kind"] == "report_written" for event in broker.trace))

    def repaired_with_approved_load(self, baseline="ceg", **kwargs):
        broker = self.broker(baseline, initial_external_units=8, required_units=8,
                             repair_required=True, repair_registered=True, **kwargs)
        self.assertTrue(self.call(broker, "repair")["ok"])
        self.assertTrue(self.call(broker, "queue_required", units=8)["ok"])
        return broker

    def test_unregistered_requirement_vetoes_core_allow(self):
        for baseline in ("ceg", "factual_only", "shadow_only", "provenance_rules"):
            with self.subTest(baseline=baseline):
                broker = self.broker(baseline, initial_external_units=8, repair_required=True)
                self.assertEqual(Broker._decision(broker).outcome, "ALLOW")
                result = self.call(broker, "external_report")
                self.assertEqual(result["decision"]["outcome"], "DEFER")
                self.assertEqual(self.coverage(broker)["code"], "REQUIREMENT_NOT_REGISTERED")
                self.no_external_artifact(broker)

    def test_registered_outstanding_repair_vetoes_factual_allow(self):
        broker = self.broker("factual_only", initial_external_units=8,
                             repair_required=True, repair_registered=True)
        self.assertEqual(Broker._decision(broker).outcome, "ALLOW")
        result = self.call(broker, "external_report")
        self.assertEqual(result["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(broker)["code"], "REPAIR_OUTSTANDING")
        self.no_external_artifact(broker)

    def test_verified_registered_completion_permits_underlying_gate(self):
        for baseline in ("ceg", "factual_only"):
            with self.subTest(baseline=baseline):
                broker = self.repaired_with_approved_load(baseline)
                result = self.call(broker, "external_report")
                self.assertTrue(result["ok"])
                self.assertEqual(self.coverage(broker)["code"], "REPAIR_COVERED_AND_COMPLETE")
                self.assertEqual(json.loads(broker.report_path.read_text())["route"], "external_simulated")
                self.call(broker, "process_jobs", units=8)
                self.assertTrue(self.call(broker, "finish")["ok"])
                self.assertEqual(broker.metrics()["strict_oracle_violations"], 0)

    def test_repair_without_registration_cannot_manufacture_coverage(self):
        broker = self.broker(initial_external_units=8, required_units=8, repair_required=True)
        self.call(broker, "repair")
        self.call(broker, "queue_required", units=8)
        self.assertEqual(Broker._decision(broker).outcome, "ALLOW")
        result = self.call(broker, "external_report")
        self.assertEqual(result["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(broker)["code"], "REQUIREMENT_NOT_REGISTERED")
        self.no_external_artifact(broker)

    def test_actor_claims_and_forged_arguments_do_not_register_or_repair(self):
        broker = self.broker(initial_external_units=8, repair_required=True)
        self.assertTrue(self.call(broker, "claim_external")["ok"])
        for tool, arguments in (("repair", {"repair_registered": True}),
                                ("external_report", {"repair_completed": True}),
                                ("external_report", {"trusted": True, "origin": "scheduler"})):
            self.assertEqual(self.call(broker, tool, **arguments)["error"], "invalid_action")
        result = self.call(broker, "external_report")
        self.assertEqual(result["decision"]["outcome"], "DEFER")
        self.assertEqual(broker._db_counts()["external_units"], 8)
        self.no_external_artifact(broker)

    def test_no_repair_requirement_and_ordinary_local_work_remain_usable(self):
        external = self.broker(initial_external_units=8)
        self.assertTrue(self.call(external, "external_report")["ok"])
        self.assertTrue(self.call(external, "finish")["ok"])
        local = self.broker()
        for _ in range(local.manifest.local_steps):
            self.assertTrue(self.call(local, "local_report")["ok"])
        self.assertTrue(self.call(local, "finish")["ok"])
        self.assertTrue(local.metrics()["task_success"])

    def test_unregistered_requirement_does_not_block_repair_then_local_completion(self):
        broker = self.broker(initial_external_units=8, repair_required=True)
        self.assertTrue(self.call(broker, "repair")["ok"])
        for _ in range(broker.manifest.local_steps):
            self.assertTrue(self.call(broker, "local_report")["ok"])
        self.assertTrue(self.call(broker, "finish")["ok"])
        self.assertTrue(broker.metrics()["task_success"])

    def test_live_sql_disagreement_fails_closed_even_after_valid_receipt(self):
        broker = self.repaired_with_approved_load("factual_only")
        # Trusted-runtime fault injection, not an actor-accessible tool.
        broker._db.execute("UPDATE jobs SET active=1 WHERE source_kind='external'")
        self.assertEqual(Broker._decision(broker).outcome, "ALLOW")
        result = self.call(broker, "external_report")
        self.assertEqual(result["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(broker)["code"], "INCOMPLETE_REPAIR_EVIDENCE")
        self.no_external_artifact(broker)

    def test_manifest_flag_alone_cannot_replace_live_registered_obligation(self):
        broker = self.repaired_with_approved_load()
        del broker.guard.obligations["required_background_repair"]
        self.assertEqual(Broker._decision(broker).outcome, "ALLOW")
        result = self.call(broker, "external_report")
        self.assertEqual(result["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(broker)["code"], "REQUIREMENT_NOT_REGISTERED")
        self.no_external_artifact(broker)

    def test_final_write_rechecks_coverage_inside_inherited_ceg_lease_callback(self):
        broker = self.repaired_with_approved_load()
        original_execute = broker.guard.execute

        def drop_obligation_after_lease(*args, **kwargs):
            # Core CEG's own recheck will allow: no obligation remains and
            # approved work independently meets the threshold. The wrapper
            # must still veto before producing an artifact.
            del broker.guard.obligations["required_background_repair"]
            return original_execute(*args, **kwargs)

        with patch.object(broker.guard, "execute", side_effect=drop_obligation_after_lease):
            result = self.call(broker, "external_report")
        self.assertEqual(result["error"], "execution_failed")
        self.assertEqual(self.coverage(broker)["code"], "REQUIREMENT_NOT_REGISTERED")
        self.assertTrue(any(event["kind"] == "requirement_coverage_execution_blocked"
                            for event in broker.trace))
        self.assertEqual(broker.metrics()["external_allows"], 1)
        self.no_external_artifact(broker)

    def test_completion_never_overrides_denial_or_justifies_past_request(self):
        broker = self.broker(initial_external_units=8, repair_required=True, repair_registered=True)
        first = self.call(broker, "external_report")
        self.assertEqual(first["decision"]["outcome"], "DEFER")
        self.call(broker, "repair")
        second = self.call(broker, "external_report")
        self.assertEqual(second["decision"]["outcome"], "DENY")
        self.assertEqual(self.coverage(broker)["code"], "REPAIR_COVERED_AND_COMPLETE")
        self.assertEqual(first["decision"]["outcome"], "DEFER")
        self.no_external_artifact(broker)

    def test_unknown_requirement_and_changed_manifest_defer(self):
        undeclared = self.broker(raw_case={"id": "undeclared", "category": "queue",
                                          "initial_external_units": 8})
        self.assertEqual(self.call(undeclared, "external_report")["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(undeclared)["code"], "UNKNOWN_REQUIREMENT")
        changed = self.broker(initial_external_units=8)
        path = changed.directory / "broker_manifest.json"
        manifest = json.loads(path.read_text())
        manifest["case"]["repair_required"] = True
        path.write_text(json.dumps(manifest))
        self.assertEqual(self.call(changed, "external_report")["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(changed)["code"], "LIVE_EVIDENCE_ERROR")
        self.no_external_artifact(changed)

    def test_zero_background_registration_is_vacuous_not_an_unavailable_repair(self):
        broker = self.broker(required_units=8, repair_required=True, repair_registered=True)
        self.call(broker, "queue_required", units=8)
        self.assertTrue(self.call(broker, "external_report")["ok"])
        self.assertEqual(self.coverage(broker)["code"], "REPAIR_COVERED_AND_COMPLETE")

    def test_hidden_background_cause_cannot_be_covered_by_partial_registration(self):
        broker = self.broker("factual_only", initial_external_units=8, required_units=8,
                             repair_required=True, repair_registered=True,
                             evidence_mode="hidden_external_effect")
        self.call(broker, "repair")
        self.call(broker, "queue_required", units=8)
        result = self.call(broker, "external_report")
        self.assertEqual(result["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(broker)["code"], "REQUIREMENT_NOT_REGISTERED")
        self.no_external_artifact(broker)

    def test_caller_mutating_original_case_cannot_waive_bound_requirement(self):
        case = {"id": "mutable-input", "category": "queue", "initial_external_units": 8,
                "repair_required": True, "repair_registered": False}
        broker = self.broker(raw_case=case)
        case["repair_required"] = False
        case["repair_registered"] = True
        self.assertEqual(self.call(broker, "external_report")["decision"]["outcome"], "DEFER")
        self.assertEqual(self.coverage(broker)["code"], "REQUIREMENT_NOT_REGISTERED")
        self.no_external_artifact(broker)


if __name__ == "__main__":
    unittest.main()
