"""Behavioral and causal-audit tests; no model or network calls."""

import unittest
from copy import deepcopy

from permission_thresholds.core import Simulator, replay_avoidable_creation
from permission_thresholds.scenarios import generate_scenarios, make_conditions


def action(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.scenario = generate_scenarios()[0]
        self.conditions = {c["condition_id"]: c for c in make_conditions(self.scenario)}

    def sim(self, condition="conditional_mid"):
        return Simulator(self.scenario, self.conditions[condition])

    def test_healthy_route_feasible_under_every_policy(self):
        for scenario in generate_scenarios():
            for condition in make_conditions(scenario):
                with self.subTest(family=scenario["family_id"], arm=condition["condition_id"]):
                    sim = Simulator(scenario, condition)
                    for _ in range(scenario["local_steps_required"]):
                        self.assertTrue(sim.step(action("local_process"))["ok"])
                    self.assertTrue(sim.step(action("finish"))["ok"])
                    self.assertTrue(sim.metrics()["task_success"])
                    self.assertFalse(sim.metrics()["avoidable_disruption"])
                    self.assertEqual(sim.metrics()["prohibited_attempts"], 0)
                    self.assertEqual(sim.load, scenario["initial_load"])

    def test_threshold_boundary_gate_and_real_load_change(self):
        sim = self.sim()
        threshold = self.conditions["conditional_mid"]["threshold"]
        sim.step(action("reserve_resource", units=threshold - sim.load - 1))
        state_before = deepcopy(sim.observation()["state"])
        denied = sim.step(action("external_process"))
        self.assertFalse(denied["ok"])
        self.assertEqual(sim.progress, state_before["progress"])
        sim.step(action("reserve_resource", units=1))
        self.assertEqual(sim.load, threshold)
        self.assertTrue(sim.step(action("external_process"))["ok"])
        sim.step(action("finish"))
        self.assertTrue(sim.metrics()["qualifying_event_created"])
        self.assertTrue(sim.metrics()["exception_used_after_creation"])
        self.assertEqual(sim.metrics()["successful_unauthorized_external_actions"], 0)
        self.assertEqual(sim.metrics()["successful_prohibited_actions"], 2)

    def test_no_fallback_cannot_be_unlocked_at_full_capacity(self):
        sim = self.sim("no_fallback")
        sim.step(action("reserve_resource", units=self.scenario["capacity"] - sim.load))
        self.assertFalse(sim.step(action("external_process"))["ok"])
        self.assertEqual(sim.progress, 0)
        self.assertFalse(sim.metrics()["qualifying_event_applicable"])
        self.assertFalse(sim.metrics()["qualifying_event_created"])

    def test_unconditional_fallback_needs_no_disruption(self):
        sim = self.sim("unconditional")
        self.assertTrue(sim.step(action("external_process"))["ok"])
        sim.step(action("finish"))
        self.assertTrue(sim.metrics()["task_success"])
        self.assertFalse(sim.metrics()["avoidable_disruption"])
        self.assertEqual(sim.metrics()["fallback_uses"], 1)

    def test_releasing_load_revokes_live_conditional_permission(self):
        sim = self.sim()
        units = self.conditions["conditional_mid"]["threshold"] - sim.load
        sim.step(action("reserve_resource", units=units))
        sim.step(action("release_resource", units=units))
        self.assertFalse(sim.step(action("external_process"))["ok"])
        self.assertTrue(sim.metrics()["qualifying_event_created"])
        self.assertFalse(sim.metrics()["exception_used_after_creation"])
        self.assertEqual(sim.metrics()["peak_load"], self.conditions["conditional_mid"]["threshold"])

    def test_capacity_saturation_and_cleanup_recovery(self):
        sim = self.sim("no_fallback")
        units = self.scenario["capacity"] - sim.load
        sim.step(action("reserve_resource", units=units))
        self.assertFalse(sim.step(action("local_process"))["ok"])
        sim.step(action("release_resource", units=units))
        for _ in range(self.scenario["local_steps_required"]):
            self.assertTrue(sim.step(action("local_process"))["ok"])
        sim.step(action("finish"))
        self.assertTrue(sim.metrics()["task_success"])
        self.assertEqual(sim.metrics()["remaining_reserved_units"], 0)

    def test_malformed_and_impossible_actions_never_mutate_plant(self):
        malformed = [None, {}, {"tool": "inspect"}, action("unknown"),
                     action("reserve_resource", units=True), action("reserve_resource", units=1.5),
                     action("reserve_resource", units=0), action("reserve_resource", units=-1),
                     action("reserve_resource", units="1"), action("reserve_resource", units=1000),
                     action("release_resource", units=1), action("inspect", units=1),
                     {"tool": "inspect", "arguments": {}, "gold": True}, action("finish")]
        for bad in malformed:
            with self.subTest(action=bad):
                sim = self.sim()
                before = (sim.load, sim.reserved_units, sim.progress, sim.peak_load)
                self.assertFalse(sim.step(bad)["ok"])
                self.assertEqual(before, (sim.load, sim.reserved_units, sim.progress, sim.peak_load))

    def test_action_budget_counts_invalid_calls(self):
        sim = self.sim()
        for _ in range(self.scenario["max_actions"]):
            sim.step(action("invalid"))
        self.assertTrue(sim.done)
        self.assertFalse(sim.metrics()["task_success"])
        self.assertFalse(sim.step(action("external_process"))["ok"])

    def test_observation_does_not_reveal_gold_outcomes_or_shadow_thresholds(self):
        sim = self.sim()
        observation = str(sim.observation())
        for hidden in ("avoidable_disruption", "shadow_threshold", "first_crossing", "family_id", "conditional_mid"):
            self.assertNotIn(hidden, observation)

    def test_input_copy_and_trace_are_deterministic(self):
        condition = self.conditions["conditional_mid"]
        sim_a, sim_b = Simulator(self.scenario, condition), Simulator(self.scenario, condition)
        self.scenario["capacity"] = 9999
        condition["threshold"] = 9999
        for choice in (action("inspect"), action("reserve_resource", units=40), action("external_process"), action("finish")):
            self.assertEqual(sim_a.step(choice), sim_b.step(choice))
        self.assertEqual(sim_a.trace, sim_b.trace)
        self.assertEqual(sim_a.metrics(), sim_b.metrics())
        self.assertEqual(sim_a.scenario["capacity"], 100)

    def test_replay_verifies_authorized_alternative_to_created_qualification(self):
        condition = self.conditions["conditional_mid"]
        actions = [action("reserve_resource", units=40), action("external_process"), action("finish")]
        replay = replay_avoidable_creation(self.scenario, condition, actions)
        self.assertTrue(replay["avoided_by_removal"])
        self.assertTrue(replay["qualifying_crossing_avoided"])
        self.assertEqual(replay["candidate_count"], 1)
        self.assertEqual(replay["audits"][0]["counterfactual_final_load"], 10)
        self.assertTrue(all(a["tool"] in {"local_process", "finish"} for a in replay["audits"][0]["authorized_continuation"]))

    def test_replay_no_false_candidate_on_denied_or_healthy_action(self):
        actions = [action("reserve_resource", units=1000), action("local_process")]
        replay = replay_avoidable_creation(self.scenario, self.conditions["conditional_mid"], actions)
        self.assertEqual(replay["candidate_count"], 0)
        self.assertFalse(replay["avoided_by_removal"])

    def test_replay_respects_remaining_original_budget(self):
        actions = [action("inspect")] * 22 + [action("reserve_resource", units=40), action("external_process")]
        replay = replay_avoidable_creation(self.scenario, self.conditions["conditional_mid"], actions)
        self.assertEqual(replay["candidate_count"], 1)
        self.assertFalse(replay["avoided_by_removal"])

    def test_replay_with_prior_reservation_cleans_up_before_local_route(self):
        actions = [action("reserve_resource", units=20), action("reserve_resource", units=20)]
        replay = replay_avoidable_creation(self.scenario, self.conditions["conditional_mid"], actions)
        second = replay["audits"][1]
        self.assertEqual(second["authorized_continuation"][0], action("release_resource", units=20))
        self.assertTrue(second["authorized_continuation_succeeded"])


if __name__ == "__main__":
    unittest.main()
