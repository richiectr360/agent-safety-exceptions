"""Synthetic temporary log fixtures for read-only cohort-auditor verification.

These fixtures never call a model and are not research measurements. They use
the measured-log schema only to test integrity failures and replay consistency.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from permission_thresholds import study_v2


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cohort_audit", PROJECT / "scripts/audit_measured_run.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def act(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


class MeasuredAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def create_fixture(self, capability=False, count=2, failure_after_creation=False):
        directory = self.directory
        settings = {"temperature": 0.6, "think": False, "num_ctx": 4096,
                    "num_predict": 128, "format": "tool_specific_json_schema", "base_seed": 20261018}
        config = {"model": "audit-fixture", "model_settings": settings,
                  "system": "Temporary synthetic test fixture; return one tool action.",
                  "repeats": 1, "capability_only": capability, "schedule": [None] * count}
        cases = audit._expected_cases(config)
        config["schedule"] = [{"scenario_id": c["scenario"]["family_id"],
                               "condition_id": c["condition"]["condition_id"], "repeat": c["repeat"]} for c in cases]
        snapshot = directory / "source_snapshot"
        snapshot.mkdir()
        source_hashes = {}
        for name in ("study_v2.py", "ollama_adapter.py", "actors.py", "runner.py", "run_measured_study.py"):
            source = PROJECT / "scripts" / name if name == "run_measured_study.py" else PROJECT / "src/permission_thresholds" / name
            content = source.read_bytes()
            (snapshot / name).write_bytes(content)
            source_hashes[name] = hashlib.sha256(content).hexdigest()
        manifest = {"schema_version": "2.0", "run_id": "synthetic-unit-test-fixture",
                    "status": "complete", "provider": "ollama", "results_are_synthetic": False,
                    "config": config, "config_sha256": audit.digest(config), "source_sha256": source_hashes,
                    "model_digest": "fixture-only", "completed_episodes": count}
        rows = []
        for index, case in enumerate(cases):
            scenario, condition = case["scenario"], case["condition"]
            identity = audit._identity(case)
            seed = int(audit.digest([settings["base_seed"], identity])[:8], 16) % 2_147_483_647
            env = study_v2.Simulator(scenario, condition)
            actions = study_v2.reference_actions(scenario, condition)
            if capability:
                extra = ([act("queue_auxiliary", units=20), act("process_auxiliary", units=20)]
                         if env.mechanism == "queue" else [act("take_offline"), act("repair")])
                # First task succeeds; second fails its extra requirement while
                # still completing the report, mirroring the grading distinction.
                if index == 1:
                    extra = ([act("queue_auxiliary", units=21), act("process_auxiliary", units=21)]
                             if env.mechanism == "queue" else extra + [act("take_offline")])
                actions = actions[:-1] + extra + actions[-1:]
            if failure_after_creation:
                actions = [act("queue_auxiliary", units=1) if env.mechanism == "queue" else act("take_offline")]
            calls = []
            for action in actions:
                request = audit._expected_request(env, config, seed)
                calls.append({"request": request, "response": {
                    "model": "audit-fixture", "done": True, "done_reason": "stop",
                    "response": json.dumps(action), "prompt_eval_count": 500, "eval_count": 14}, "seconds": 0.01})
                env.step(action)
            error = None
            if failure_after_creation:
                error = "local_transport_URLError"
                calls.append({"request": audit._expected_request(env, config, seed), "error": error, "seconds": 0.01})
            metrics, replay = audit._final_metrics(env, scenario, condition, capability)
            row = {"schema_version": "2.0", "run_id": manifest["run_id"], "scenario_id": identity[0],
                   "family_id": identity[0], "scenario_sha256": audit.digest(scenario),
                   "condition": condition, "repeat": case["repeat"], "mechanism": scenario["mechanism"],
                   "initial_context": scenario["initial_context"], "study_role": scenario["study_role"],
                   "provider": "ollama", "model": "audit-fixture", "model_digest": "fixture-only",
                   "results_are_synthetic": False, "config_sha256": manifest["config_sha256"],
                   "source_sha256": source_hashes, "model_settings": settings, "episode_seed": seed,
                   "episode_status": "model_error" if error else "completed", "model_error": error,
                   "metrics": metrics, "events": env.trace, "calls": calls, "counterfactual_audit": replay,
                   "elapsed_seconds": 0.1}
            rows.append(row)
        (directory / "cases.jsonl").write_text("".join(audit.canonical(case) + "\n" for case in cases))
        self.write_rows(rows, manifest)
        return rows, manifest

    def write_rows(self, rows, manifest):
        output = self.directory / "episodes.jsonl"
        output.write_text("".join(audit.canonical(row) + "\n" for row in rows))
        manifest["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        (self.directory / "manifest.json").write_text(json.dumps(manifest))

    def codes(self, result):
        return {entry["code"] for entry in result["errors"]}

    def test_consistent_complete_fixture_passes_without_writes(self):
        self.create_fixture()
        before = {str(p.relative_to(self.directory)): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        result = audit.audit_run(self.directory)
        after = {str(p.relative_to(self.directory)): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.assertEqual(result["status"], "passed", result["errors"])
        self.assertEqual(result["counts"]["replayed_episodes"], 2)
        self.assertEqual(before, after)

    def test_capability_counts_do_not_confuse_report_with_full_task(self):
        self.create_fixture(capability=True)
        result = audit.audit_run(self.directory)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["capability"]["report_only_successes"], 2)
        self.assertEqual(result["capability"]["full_task_successes"], 1)

    def test_event_tampering_is_detected_even_with_refreshed_output_hash(self):
        rows, manifest = self.create_fixture()
        rows[0]["events"][0]["after"]["progress"] = 100
        self.write_rows(rows, manifest)
        result = audit.audit_run(self.directory)
        self.assertIn("event_replay_mismatch", self.codes(result))

    def test_raw_model_action_must_match_executed_action(self):
        rows, manifest = self.create_fixture()
        rows[0]["calls"][0]["response"]["response"] = json.dumps(act("inspect"))
        self.write_rows(rows, manifest)
        self.assertIn("raw_action_mismatch", self.codes(audit.audit_run(self.directory)))

    def test_scorer_labels_in_request_are_rejected(self):
        rows, manifest = self.create_fixture()
        request = rows[0]["calls"][0]["request"]
        prompt = json.loads(request["prompt"])
        prompt["observation"]["actor_created_qualification"] = True
        request["prompt"] = json.dumps(prompt)
        self.write_rows(rows, manifest)
        codes = self.codes(audit.audit_run(self.directory))
        self.assertIn("scorer_label_exposure", codes)
        self.assertIn("model_request_mismatch", codes)

    def test_simulator_hash_mismatch_refuses_replay(self):
        rows, manifest = self.create_fixture()
        manifest["source_sha256"]["study_v2.py"] = "0" * 64
        self.write_rows(rows, manifest)
        result = audit.audit_run(self.directory)
        self.assertIn("simulator_hash_mismatch", self.codes(result))
        self.assertFalse(result["checks"]["simulator_replay_permitted"])

    def test_scenario_hash_and_seed_changes_are_detected(self):
        rows, manifest = self.create_fixture()
        rows[0]["scenario_sha256"] = "wrong"
        rows[0]["episode_seed"] += 1
        self.write_rows(rows, manifest)
        codes = self.codes(audit.audit_run(self.directory))
        self.assertIn("episode_metadata_mismatch", codes)
        self.assertIn("episode_seed_mismatch", codes)

    def test_missing_rows_cannot_pass_complete_cohort(self):
        rows, manifest = self.create_fixture()
        self.write_rows(rows[:1], manifest)
        result = audit.audit_run(self.directory)
        self.assertIn("completed_cohort_count_mismatch", self.codes(result))
        self.assertEqual(result["counts"]["missing_case_count"], 1)

    def test_running_snapshot_is_incomplete_not_passed(self):
        rows, manifest = self.create_fixture()
        manifest["status"] = "running"
        self.write_rows(rows[:1], manifest)
        result = audit.audit_run(self.directory)
        self.assertEqual(result["status"], "incomplete", result["errors"])
        self.assertFalse(result["passed"])

    def test_output_integrity_mismatch_is_detected(self):
        self.create_fixture()
        path = self.directory / "episodes.jsonl"
        path.write_text(path.read_text() + "\n")
        self.assertIn("output_hash_mismatch", self.codes(audit.audit_run(self.directory)))

    def test_altered_case_definition_fails_frozen_generator_check(self):
        self.create_fixture()
        path = self.directory / "cases.jsonl"
        cases = [json.loads(line) for line in path.read_text().splitlines()]
        cases[0]["scenario"]["task"] += " Changed task."
        path.write_text("".join(audit.canonical(case) + "\n" for case in cases))
        self.assertIn("cases_differ_from_frozen_generator", self.codes(audit.audit_run(self.directory)))

    def test_observed_prefix_survives_model_error_replay(self):
        self.create_fixture(failure_after_creation=True)
        result = audit.audit_run(self.directory)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["counts"]["model_error_episodes"], 2)
        self.assertEqual(result["counts"]["executed_actions"], 2)

    def test_budget_counts_are_reported_as_warnings(self):
        rows, manifest = self.create_fixture()
        rows[0]["calls"][0]["response"]["prompt_eval_count"] = 4000
        rows[0]["calls"][0]["response"]["eval_count"] = 128
        self.write_rows(rows, manifest)
        result = audit.audit_run(self.directory)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["tokens"]["limit_flagged_calls"], 1)
        self.assertIn("token_limit_reached_or_suspected", {w["code"] for w in result["warnings"]})


if __name__ == "__main__":
    unittest.main()
