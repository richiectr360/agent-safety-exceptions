"""Artificial unit-test fixtures only; nothing here is empirical evidence."""

from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from permission_thresholds.runner import canonical, digest
from permission_thresholds.study_v2 import Simulator, generate_scenarios, make_conditions, reference_actions


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_empirical_paper.py"
SPEC = importlib.util.spec_from_file_location("empirical_paper", SCRIPT)
paper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(paper)


def fixture(directory, capability=False, model="fixture-model", success=True):
    """Write a small internally consistent fixture to a temporary directory."""
    scenario = generate_scenarios()[0]
    scenario = deepcopy(scenario)
    if capability:
        scenario["family_id"] += "_capability"
        scenario["study_role"] = "authorized_capability_check"
    condition = next(c for c in make_conditions(scenario) if c["condition_id"] == "unconditional__literal_only")
    env = Simulator(scenario, condition)
    for action in reference_actions(scenario, condition):
        env.step(action)
    metrics = env.metrics()
    if capability:
        metrics.update({"capability_success": success, "safety_metrics_applicable": False,
                        "optional_state_creation": None, "actor_created_qualification": None,
                        "exception_used_after_creation": None})
    source = {name: b"test fixture source\n" for name in ("study_v2.py", "ollama_adapter.py", "run_measured_study.py")}
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in source.items()}
    schedule = [{"scenario_id": scenario["family_id"], "condition_id": condition["condition_id"], "repeat": 0}]
    config = {"model": model, "model_settings": {"temperature": 0.6, "num_ctx": 4096, "num_predict": 128},
              "system": "fixture system", "capability_only": capability, "repeats": 1, "schedule": schedule}
    manifest = {"schema_version": "2.0", "run_id": directory.name, "status": "complete",
                "results_are_synthetic": False, "provider": "ollama", "config": config,
                "config_sha256": digest(config), "source_sha256": hashes, "model_digest": model + "-digest",
                "model_inventory": {"model": {"name": model, "digest": model + "-digest", "details": {}},
                                    "runtime": {"version": "fixture"}}, "completed_episodes": 1}
    row = {key: manifest[key] for key in ("schema_version", "run_id", "results_are_synthetic", "provider",
                                       "config_sha256", "source_sha256", "model_digest")}
    row.update({"scenario_id": scenario["family_id"], "family_id": scenario["family_id"],
                "mechanism": "queue", "initial_context": "healthy", "study_role": scenario["study_role"],
                "scenario_sha256": digest(scenario), "condition": condition, "repeat": 0,
                "model": model, "model_settings": config["model_settings"], "episode_status": "completed",
                "metrics": metrics, "events": env.trace, "calls": [{"fixture_only": True}]})
    directory.mkdir()
    snapshot = directory / "source_snapshot"
    snapshot.mkdir()
    for name, content in source.items():
        (snapshot / name).write_bytes(content)
    (directory / "cases.jsonl").write_text(canonical({"scenario": scenario, "condition": condition, "repeat": 0}) + "\n")
    save(directory, manifest, row)
    return manifest, row


def save(directory, manifest, row):
    content = (canonical(row) + "\n").encode()
    (directory / "episodes.jsonl").write_bytes(content)
    manifest["output_sha256"] = hashlib.sha256(content).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest))


class EmpiricalPaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_load_main_and_capability_and_matching_profiles(self):
        fixture(self.root / "main")
        fixture(self.root / "cap", capability=True)
        main = paper.load_run(self.root / "main", capability_only=False)
        cap = paper.load_run(self.root / "cap", capability_only=True)
        paper.validate_collections([main], [cap])

    def test_roles_cannot_be_swapped(self):
        fixture(self.root / "main")
        fixture(self.root / "cap", capability=True)
        for name, requested in (("main", True), ("cap", False)):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "role"):
                paper.load_run(self.root / name, capability_only=requested)

    def test_tampered_episode_bytes_are_rejected(self):
        fixture(self.root / "main")
        with (self.root / "main/episodes.jsonl").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "integrity-verified"):
            paper.load_run(self.root / "main", capability_only=False)

    def test_config_hash_is_checked(self):
        manifest, row = fixture(self.root / "main")
        manifest["config"]["model_settings"]["temperature"] = 0
        save(self.root / "main", manifest, row)
        with self.assertRaisesRegex(ValueError, "Configuration integrity"):
            paper.load_run(self.root / "main", capability_only=False)

    def test_source_snapshot_bytes_are_checked(self):
        fixture(self.root / "main")
        (self.root / "main/source_snapshot/ollama_adapter.py").write_text("changed")
        with self.assertRaisesRegex(ValueError, "Source snapshot"):
            paper.load_run(self.root / "main", capability_only=False)

    def test_each_row_metadata_must_agree_with_manifest(self):
        for field in ("run_id", "model_digest", "config_sha256", "source_sha256"):
            path = self.root / field
            manifest, row = fixture(path)
            row[field] = {"bad": "hash"} if field == "source_sha256" else "wrong"
            save(path, manifest, row)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "disagrees with manifest"):
                paper.load_run(path, capability_only=False)

    def test_frozen_scenario_hash_is_checked(self):
        manifest, row = fixture(self.root / "main")
        row["scenario_sha256"] = "wrong"
        save(self.root / "main", manifest, row)
        with self.assertRaisesRegex(ValueError, "frozen cases"):
            paper.load_run(self.root / "main", capability_only=False)

    def test_capability_metric_must_exist_not_default_false(self):
        manifest, row = fixture(self.root / "cap", capability=True)
        del row["metrics"]["capability_success"]
        save(self.root / "cap", manifest, row)
        with self.assertRaisesRegex(ValueError, "Capability labels"):
            paper.load_run(self.root / "cap", capability_only=True)

    def test_capability_cannot_assign_safety_labels(self):
        manifest, row = fixture(self.root / "cap", capability=True)
        row["metrics"]["optional_state_creation"] = True
        save(self.root / "cap", manifest, row)
        with self.assertRaisesRegex(ValueError, "must not be scored"):
            paper.load_run(self.root / "cap", capability_only=True)

    def test_main_requires_matching_capability_and_no_duplicate_runs(self):
        fixture(self.root / "main")
        fixture(self.root / "cap", capability=True)
        main = paper.load_run(self.root / "main", capability_only=False)
        cap = paper.load_run(self.root / "cap", capability_only=True)
        with self.assertRaisesRegex(ValueError, "matching capability"):
            paper.validate_collections([main], [])
        with self.assertRaisesRegex(ValueError, "Duplicate run"):
            paper.validate_collections([main], [cap, cap])

    def test_main_and_capability_different_interfaces_cannot_be_pooled(self):
        fixture(self.root / "main")
        fixture(self.root / "cap", capability=True)
        main = paper.load_run(self.root / "main", capability_only=False)
        cap = paper.load_run(self.root / "cap", capability_only=True)
        cap[0]["model_inventory"]["runtime"]["version"] = "different"
        with self.assertRaisesRegex(ValueError, "profile mismatch"):
            paper.validate_collections([main], [cap])

    def test_observed_bounds_retain_error_events_and_unknown_suffix(self):
        _, base = fixture(self.root / "main")
        rows = [deepcopy(base) for _ in range(3)]
        rows[0]["episode_status"] = "budget_exhausted"
        rows[1]["episode_status"] = "model_error"
        rows[1]["metrics"]["optional_state_creation"] = True
        rows[2]["episode_status"] = "model_error"
        counts = paper.observed_counts(rows, "optional_state_creation")
        self.assertEqual(counts["complete_case"], "0/1")
        self.assertEqual(counts["possible_count_bounds"], [1, 2])
        self.assertEqual(counts["unknown_error_continuations"], 1)
        self.assertEqual(counts["budget_exhausted"], 1)

    def test_abstract_uses_capability_not_report_success_and_labels_cap_only(self):
        _, main = fixture(self.root / "main", model="qwen")
        _, cap = fixture(self.root / "cap", capability=True, model="qwen", success=False)
        _, other = fixture(self.root / "other", capability=True, model="llama", success=False)
        self.assertTrue(cap["metrics"]["task_success"])
        abstract = paper.build_abstract([main], [cap, other])
        self.assertIn("qwen 0/1 (main-cohort model)", abstract)
        self.assertIn("llama 0/1 (capability-only model)", abstract)
        self.assertIn("Capability failures limit", abstract)
        self.assertIn("covering queue environments", abstract)
        self.assertNotIn("two tool environments", abstract)

    def test_primary_filter_excludes_service_and_explicit_rules(self):
        _, base = fixture(self.root / "main")
        base["condition"].update({"arm": "conditional_low", "policy_mode": "conditional"})
        service, explicit = deepcopy(base), deepcopy(base)
        service["mechanism"] = "service"
        explicit["condition"]["instruction_ablation"] = "explicit_resource_rule"
        service["metrics"]["actor_created_qualification"] = True
        explicit["metrics"]["actor_created_qualification"] = True
        selected = paper.primary_rows([base, service, explicit])
        self.assertEqual(selected, [base])
        abstract = paper.build_abstract([base, service, explicit], [])
        self.assertIn("0/1 attempts show actor-created qualification", abstract)

    def test_builder_writes_traceable_document_from_temporary_test_fixtures(self):
        fixture(self.root / "main")
        fixture(self.root / "cap", capability=True, success=False)
        output = self.root / "output/test-fixture-not-evidence.docx"
        argv = [str(SCRIPT), "--run", str(self.root / "main"), "--capability", str(self.root / "cap"),
                "--out", str(output)]
        with patch("sys.argv", argv), redirect_stdout(io.StringIO()):
            paper.main()
        self.assertTrue(output.exists())
        document = paper.Document(output)
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Capability failures limit interpretation", text)
        self.assertIn("Missing continuations are not safety negatives", text)
        self.assertIn("Table 3", text)
        report = json.loads((output.parent / "measured_results.json").read_text())
        self.assertEqual(report["episodes"], 1)
        provenance = json.loads((output.parent / "manuscript_provenance.json").read_text())
        self.assertEqual(provenance["manuscript_sha256"], hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
