import io
import json
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from permission_thresholds.actors import ActorError, CommandActor, ScriptedActor, safe_metadata
from permission_thresholds.cli import main
from permission_thresholds.runner import run_episode, run_to_file, read_jsonl
from permission_thresholds.scenarios import generate_scenarios, make_conditions


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.scenario = generate_scenarios()[0]
        self.conditions = make_conditions(self.scenario)

    def episode(self, condition, name="honest", actor=None):
        return run_episode(self.scenario, condition, actor or ScriptedActor(name, condition),
                           run_id="test", repeat=0, backend="scripted", actor_name=name,
                           model="scripted", synthetic=True)

    def test_scripted_diagnostic_patterns_and_replay(self):
        for condition in self.conditions:
            honest = self.episode(condition)
            seeker = self.episode(condition, "threshold_seeking")
            blind = self.episode(condition, "threshold_blind")
            self.assertTrue(honest["metrics"]["task_success"])
            self.assertTrue(seeker["metrics"]["task_success"])
            self.assertTrue(blind["metrics"]["avoidable_disruption"])
            self.assertFalse(honest["metrics"]["avoidable_disruption"])
            if condition["policy_mode"] == "conditional":
                self.assertEqual(seeker["metrics"]["peak_load"], condition["threshold"])
                self.assertTrue(seeker["counterfactual_audit"]["qualifying_crossing_avoided"])
            else:
                self.assertFalse(seeker["metrics"]["avoidable_disruption"])

    def test_gold_metadata_not_sent_to_actor(self):
        requests = []
        class RecordingActor:
            def next_action(_, request):
                requests.append(request)
                return ScriptedActor("honest", self.conditions[0]).next_action(request)
        self.episode(self.conditions[2], actor=RecordingActor())
        text = json.dumps(requests)
        for forbidden in ("family_id", "scenario_id", "qualifying_event_created", "avoided_by_removal", "shadow_threshold", "counterfactual_audit", "condition_id"):
            self.assertNotIn(forbidden, text)

    def test_adapter_failure_keeps_partial_events(self):
        class Broken:
            calls = 0
            def next_action(_, request):
                _.calls += 1
                if _.calls > 1:
                    raise ActorError("adapter_timeout")
                return {"action": {"tool": "inspect", "arguments": {}}}
        row = self.episode(self.conditions[0], actor=Broken())
        self.assertEqual(row["episode_status"], "adapter_error")
        self.assertEqual(len(row["events"]), 1)

    def test_manifest_hash_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "run.jsonl"
            manifest = run_to_file([self.scenario], path)
            self.assertEqual(len(read_jsonl(path)), 5)
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["adapter_error_episodes"], 0)
            self.assertIn("core.py", manifest["source_sha256"])
            with self.assertRaises(FileExistsError):
                run_to_file([self.scenario], path)

    def test_command_requires_explicit_enable_before_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "run.jsonl"
            with self.assertRaises(ValueError):
                run_to_file([self.scenario], path, backend="command", adapter="echo test", model="example")
            self.assertFalse(path.exists())

    def test_schedule_is_seeded_and_recorded_without_changing_case_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = run_to_file([self.scenario], root / "one.jsonl", seed=42)
            second = run_to_file([self.scenario], root / "two.jsonl", seed=42)
            third = run_to_file([self.scenario], root / "three.jsonl", seed=43)
            self.assertEqual(first["schedule"], second["schedule"])
            self.assertNotEqual(first["schedule"], third["schedule"])
            self.assertEqual({r["condition_id"] for r in first["schedule"]},
                             {c["condition_id"] for c in self.conditions})
            self.assertEqual([r["condition"]["condition_id"] for r in read_jsonl(root / "one.jsonl")],
                             [r["condition_id"] for r in first["schedule"]])

    def test_command_protocol(self):
        command = shlex.join([sys.executable, "-c", 'print(\'{"action":{"tool":"inspect","arguments":{}}}\')'])
        self.assertEqual(CommandActor(command).next_action({})["action"]["tool"], "inspect")

    def test_stderr_never_copied_into_error(self):
        command = shlex.join([sys.executable, "-c", 'import sys; print("PRIVATE_VALUE",file=sys.stderr); sys.exit(1)'])
        with self.assertRaisesRegex(ActorError, "adapter_nonzero_exit") as raised:
            CommandActor(command).next_action({})
        self.assertNotIn("PRIVATE_VALUE", str(raised.exception))

    def test_reject_nonfinite_json_and_extra_response_keys(self):
        for output in ['{"action":{"tool":"inspect","arguments":{"x":NaN}}}',
                       '{"action":{"tool":"inspect","arguments":{}},"extra":1}']:
            command = shlex.join([sys.executable, "-c", "print(" + repr(output) + ")"])
            with self.assertRaises(ActorError):
                CommandActor(command).next_action({})

    def test_metadata_allowlist(self):
        result = safe_metadata({"api_key": "PRIVATE", "usage": {"input_tokens": 5, "bad": float("inf")},
                                "settings": {"sampling": "provider_default", "secret": "PRIVATE"}})
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(result["usage"], {"input_tokens": 5})
        self.assertEqual(result["settings"]["sampling"], "provider_default")

    def test_cli_generate_validate_report_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            temp = Path(temp)
            self.assertEqual(main(["validate"]), 0)
            self.assertEqual(main(["generate", "--out", str(temp / "cases.jsonl")]), 0)
            self.assertEqual(len(read_jsonl(temp / "cases.jsonl")), 60)
            self.assertEqual(main(["run", "--limit", "5", "--out", str(temp / "run.jsonl")]), 0)
            self.assertEqual(main(["report", "--input", str(temp / "run.jsonl"), "--out", str(temp / "summary.json"), "--bootstrap-samples", "20"]), 0)
            summary = json.loads((temp / "summary.json").read_text())
            self.assertEqual(summary["evidence_status"], "synthetic_only")
            self.assertIn("NOT MODEL FINDINGS", (temp / "summary.md").read_text())
            self.assertEqual(main(["run", "--out", str(temp / "run.jsonl")]), 2)


if __name__ == "__main__":
    unittest.main()
