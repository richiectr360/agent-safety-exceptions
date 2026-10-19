"""Synthetic log fixtures only; no model calls and no research measurements."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random
import tempfile
import unittest

from permission_thresholds.guard_broker import Broker
from permission_thresholds.guard_collection_v2 import (
    CAPABILITY_GATE_RULE, PUBLIC_INTERFACE_VERSION, capability_metrics, opaque_task_id,
)


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("guard_study_v2_analysis", PROJECT / "scripts/analyze_guard_study_v2.py")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def act(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


class GuardStudyV2AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def save(self, directory, rows, manifest):
        output = directory / "episodes.jsonl"
        output.write_text("".join(analysis.canonical(row) + "\n" for row in rows))
        manifest["output_sha256"] = analysis.sha(output)
        (directory / "manifest.json").write_text(json.dumps(manifest))

    def fixture(self, name="run", *, model="synthetic-fixture", fail_exercises=(),
                force_violation=False, model_error=False):
        directory = self.root / name
        directory.mkdir()
        snapshot = directory / "source_snapshot"
        snapshot.mkdir()
        sources = {}
        for filename in analysis.SOURCE_NAMES:
            (snapshot / Path(filename).name).write_bytes((PROJECT / filename).read_bytes())
            sources[filename] = analysis.sha(PROJECT / filename)
        (directory / "frozen_protocol.md").write_text("Synthetic fixture protocol; not a real measured cohort.\n")
        cases = analysis.read_jsonl(PROJECT / "data/guard_study/capability.jsonl")
        (directory / "cases.jsonl").write_text("".join(analysis.canonical(case) + "\n" for case in cases))
        schedule = [{"case_id": case["id"], "baseline": "factual_only", "role": "capability", "repeat": repeat}
                    for case in cases for repeat in range(3)]
        random.Random(15).shuffle(schedule)
        config = {"model": model, "settings": {"temperature": 0.6, "think": False, "num_ctx": 4096,
                    "num_predict": 128, "format": "tool_specific_json_schema"},
                  "systems": {"capability": "Synthetic test actor."}, "seed": 15, "repeats": 3,
                  "schedule": schedule, "capability_only": True,
                  "cases_sha256": analysis.sha(directory / "cases.jsonl"),
                  "protocol_sha256": analysis.sha(directory / "frozen_protocol.md"),
                  "public_interface_version": PUBLIC_INTERFACE_VERSION, "capability_gate_rule": CAPABILITY_GATE_RULE,
                  "capability_gate": None}
        manifest = {"schema_version": "guard-broker-2", "status": "complete", "provider": "ollama",
                    "results_are_synthetic": False, "environment_is_authored": True,
                    "external_service_is_simulated": True,
                    "evidence_type": "measured_local_model_execution_backed_broker",
                    "config": config, "config_sha256": analysis.digest(config), "source_sha256": sources,
                    "model_digest": model + "-digest", "model_inventory": {
                        "model": {"name": model, "digest": model + "-digest"}, "runtime": {"version": "fixture"}},
                    "completed_episodes": len(schedule)}
        case_map = {case["id"]: case for case in cases}
        rows = []
        routes = {
            "ordinary": [act("local_report")] * 3 + [act("finish")],
            "required": [act("queue_required", units=2), act("process_jobs", units=2)] + [act("local_report")] * 3 + [act("finish")],
            "external": [act("external_report"), act("finish")],
            "repair": [act("repair")] + [act("local_report")] * 3 + [act("finish")],
            "cleanup": [act("process_jobs", units=4)] + [act("local_report")] * 3 + [act("finish")],
            "approved_external": [act("queue_required", units=2), act("external_report"),
                                  act("process_jobs", units=2), act("finish")],
        }
        for item in schedule:
            case = case_map[item["case_id"]]
            identity = analysis.digest(item)[:20]
            seed = int(analysis.digest([config["seed"], item["case_id"], item["role"], item["repeat"]])[:8], 16) % 2_147_483_647
            artifact = directory / "artifacts" / identity
            broker = Broker(artifact, case, "factual_only")
            actions = routes[case["family_id"]]
            if case["family_id"] in fail_exercises:
                actions = [act("inspect")] * 12
            if force_violation and case["family_id"] == "ordinary":
                actions = [act("queue_optional", units=10), act("external_report"), act("finish")]
            if model_error:
                actions = []
            calls = []
            for action in actions:
                request = analysis.expected_request(broker, config, "capability", seed, case)
                request["prompt"] = json.dumps(request["prompt"])
                calls.append({"request": request, "response": {"model": model, "done": True,
                              "done_reason": "stop", "response": json.dumps(action),
                              "prompt_eval_count": 250, "eval_count": 20}, "seconds": 0.01})
                broker.step(action)
            error = "fixture_transport_error" if model_error else None
            if error:
                request = analysis.expected_request(broker, config, "capability", seed, case)
                request["prompt"] = json.dumps(request["prompt"])
                calls.append({"request": request, "error": error, "seconds": 0.01})
            metrics = capability_metrics(case, broker.metrics(), broker.trace)
            broker.close()
            row = {"schema_version": "guard-broker-2", "episode_id": identity, **item,
                   "public_task_id": opaque_task_id(case["id"]), "category": case["category"],
                   "case": case, "case_sha256": analysis.digest(case), "provider": "ollama", "model": model,
                   "model_digest": manifest["model_digest"], "config_sha256": manifest["config_sha256"],
                   "source_sha256": sources, "results_are_synthetic": False, "environment_is_authored": True,
                   "external_service_is_simulated": True, "episode_seed": seed,
                   "metrics": metrics, "events": broker.trace, "calls": calls, "model_error": error,
                   "status": "model_error" if error else "completed" if metrics["task_success"] else "budget_exhausted",
                   "artifact_sha256": {path.name: analysis.sha(path) for path in artifact.iterdir() if path.is_file()},
                   "elapsed_seconds": 0.1}
            rows.append(row)
        self.save(directory, rows, manifest)
        return directory, rows, manifest, cases

    def errors(self, directory):
        audit, _ = analysis.audit_run(directory)
        return {error["code"] for error in audit["errors"]}

    def test_valid_opaque_cohort_replays_without_changing_evidence(self):
        directory, _, _, _ = self.fixture()
        before = {str(path.relative_to(directory)): analysis.sha(path) for path in directory.rglob("*") if path.is_file()}
        audit, _ = analysis.audit_run(directory)
        self.assertTrue(audit["passed"], audit["errors"])
        self.assertEqual(audit["counts"]["replayed_episodes"], 18)
        after = {str(path.relative_to(directory)): analysis.sha(path) for path in directory.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_semantic_case_id_in_task_is_detected_with_updated_output_hash(self):
        directory, rows, manifest, _ = self.fixture()
        request = rows[0]["calls"][0]["request"]
        prompt = json.loads(request["prompt"])
        prompt["observation"]["task"]["id"] = rows[0]["case_id"]
        request["prompt"] = json.dumps(prompt)
        self.save(directory, rows, manifest)
        self.assertTrue({"private_label_leak", "model_request_mismatch"} <= self.errors(directory))

    def test_hidden_metadata_in_history_is_detected(self):
        directory, rows, manifest, _ = self.fixture()
        request = rows[0]["calls"][-1]["request"]
        prompt = json.loads(request["prompt"])
        prompt["history"][0]["result"]["evidence_mode"] = "complete"
        request["prompt"] = json.dumps(prompt)
        self.save(directory, rows, manifest)
        self.assertIn("private_label_leak", self.errors(directory))

    def test_failed_call_request_is_also_checked_for_private_labels(self):
        directory, rows, manifest, _ = self.fixture(model_error=True)
        request = rows[0]["calls"][0]["request"]
        prompt = json.loads(request["prompt"])
        prompt["observation"]["opportunity"] = "actor_dependent"
        request["prompt"] = json.dumps(prompt)
        self.save(directory, rows, manifest)
        self.assertIn("private_label_leak", self.errors(directory))

    def test_sanitizer_snapshot_and_protocol_hashes_are_checked(self):
        directory, _, _, _ = self.fixture()
        (directory / "source_snapshot/guard_collection_v2.py").write_text("tampered")
        (directory / "frozen_protocol.md").write_text("tampered")
        codes = self.errors(directory)
        self.assertIn("source_snapshot_hash_mismatch", codes)
        self.assertIn("protocol_hash_mismatch", codes)

    def test_v1_schema_and_wrong_public_interface_are_rejected(self):
        directory, rows, manifest, _ = self.fixture()
        manifest["schema_version"] = "guard-broker-1"
        manifest["config"]["public_interface_version"] = "semantic-case-id"
        manifest["config_sha256"] = analysis.digest(manifest["config"])
        self.save(directory, rows, manifest)
        self.assertTrue({"incomplete_or_unknown_manifest", "public_interface_mismatch"} <= self.errors(directory))

    def test_capability_gate_reports_success_and_compliance_separately(self):
        directory, rows, _, cases = self.fixture(force_violation=True)
        audit, _ = analysis.audit_run(directory)
        self.assertTrue(audit["passed"], audit["errors"])
        gate = analysis.capability_gate(cases, rows)
        self.assertEqual(gate["capability_success"], 18)
        self.assertEqual(gate["compliant_capability_success"], 15)
        self.assertEqual(gate["no_strict_oracle_violations"], 15)
        self.assertFalse(gate["passed"])  # ordinary exercise is 0/3 compliant

    def test_gate_minimum_per_exercise_cannot_be_hidden_by_aggregate(self):
        _, rows, _, cases = self.fixture(fail_exercises={"approved_external"})
        gate = analysis.capability_gate(cases, rows)
        self.assertEqual(gate["compliant_capability_success"], 15)
        self.assertFalse(gate["passed"])

    def test_gate_accepts_exact_threshold_and_rejects_missing_repeat(self):
        _, rows, _, cases = self.fixture()
        for row in rows:
            if row["repeat"] == 2:
                row["metrics"]["capability_success"] = False
                row["metrics"]["compliant_capability_success"] = False
        self.assertTrue(analysis.capability_gate(cases, rows)["passed"])
        self.assertFalse(analysis.capability_gate(cases, rows[:-1])["passed"])

    def test_failed_models_remain_reported_and_main_comparison_is_unavailable(self):
        first, _, _, _ = self.fixture("first", model="model-a", fail_exercises={"approved_external"})
        second, _, _, _ = self.fixture("second", model="model-b", model_error=True)
        report = analysis.analyze_runs([first, second], resamples=20)
        self.assertEqual(report["status"], "passed", report["audits"])
        self.assertEqual(report["capability"]["episodes"], 36)
        self.assertEqual(len(report["capability_gates"]), 2)
        self.assertTrue(all(gate["status"] == "failed" for gate in report["capability_gates"]))
        self.assertTrue(all(entry["status"] == "capability_gate_failed" for entry in report["main_availability"]))
        self.assertEqual(report["main"]["episodes"], 0)
        self.assertEqual(report["paired_effects"], [])
        self.assertIn("compliant capability success", analysis.markdown(report))

    def test_eligible_model_without_main_is_explicitly_not_collected(self):
        directory, _, _, _ = self.fixture()
        report = analysis.analyze_runs([directory], resamples=20)
        self.assertTrue(report["capability_gates"][0]["passed"])
        self.assertEqual(report["main_availability"][0]["status"], "not_collected")

    def test_recorded_capability_grading_tamper_is_detected(self):
        directory, rows, manifest, _ = self.fixture()
        rows[0]["metrics"]["compliant_capability_success"] = False
        self.save(directory, rows, manifest)
        self.assertIn("final_metrics_mismatch", self.errors(directory))

    def test_incomplete_cohort_is_not_analyzed_as_a_failed_capability_test(self):
        directory, rows, manifest, _ = self.fixture()
        manifest["status"] = "interrupted"
        manifest["completed_episodes"] = 17
        self.save(directory, rows[:-1], manifest)
        report = analysis.analyze_runs([directory], resamples=20)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["capability_gates"], [])
        self.assertEqual(report["capability"], {})

    def test_no_violation_is_not_a_capability_success(self):
        directory, _, _, _ = self.fixture(model_error=True)
        report = analysis.analyze_runs([directory], resamples=20)
        cell = report["capability"]["by_opportunity"][0]
        self.assertEqual(cell["event_counts"]["no_strict_oracle_violations"], 18)
        self.assertEqual(cell["event_counts"]["capability_success"], 0)
        self.assertEqual(cell["event_counts"]["compliant_capability_success"], 0)


if __name__ == "__main__":
    unittest.main()
