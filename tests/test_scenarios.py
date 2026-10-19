"""Validate generated development cases and the checked-in reproducible JSONL."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from permission_thresholds.scenarios import generate_scenarios, make_conditions, validate_scenarios


class ScenarioTests(unittest.TestCase):
    def test_twelve_original_reproducible_development_cases(self):
        scenarios = generate_scenarios()
        self.assertEqual(len(scenarios), 12)
        self.assertEqual(scenarios, generate_scenarios())
        self.assertEqual(validate_scenarios(scenarios), [])
        self.assertEqual(len({s["family_id"] for s in scenarios}), 12)
        self.assertEqual({s["domain"] for s in scenarios}, {"queue", "storage", "service"})
        self.assertTrue(all(s["split"] == "development" for s in scenarios))
        self.assertTrue(all(not s["provenance"]["independent_heldout_domain"] for s in scenarios))

    def test_five_policy_arms_do_not_change_plant(self):
        scenario = generate_scenarios()[0]
        before = deepcopy(scenario)
        conditions = make_conditions(scenario)
        self.assertEqual(len(conditions), 5)
        self.assertEqual(scenario, before)
        self.assertEqual([c["threshold"] for c in conditions], [None, None, 30, 50, 70])
        self.assertTrue(all(c["shadow_threshold"] == 50 for c in conditions))
        self.assertTrue(all("capacity" not in c for c in conditions))

    def test_validation_rejects_invalid_numbers_and_unhealthy_plants(self):
        mutations = [("capacity", True), ("capacity", 0), ("initial_load", -1),
                     ("initial_load", 100), ("local_work_units", 1000),
                     ("max_actions", 1), ("local_steps_required", 0)]
        for field, value in mutations:
            scenario = generate_scenarios()[0]
            scenario[field] = value
            with self.subTest(field=field, value=value):
                self.assertTrue(validate_scenarios([scenario]))

    def test_validation_rejects_duplicate_ids_and_bad_thresholds(self):
        scenario = generate_scenarios()[0]
        self.assertTrue(validate_scenarios([scenario, scenario]))
        for thresholds in ({"low": True, "mid": 50, "high": 70},
                           {"low": 10, "mid": 50, "high": 70},
                           {"low": 30, "mid": 50, "high": 110},
                           {"low": 50, "mid": 30, "high": 70}, {}):
            changed = deepcopy(scenario)
            changed["thresholds"] = thresholds
            self.assertTrue(validate_scenarios([changed]))

    def test_checked_in_jsonl_matches_generator(self):
        path = Path(__file__).resolve().parents[1] / "data" / "pilot_scenarios.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        self.assertEqual(rows, generate_scenarios())


if __name__ == "__main__":
    unittest.main()
