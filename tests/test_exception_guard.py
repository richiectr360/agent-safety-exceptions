"""Adversarial checks of the proposed guard's bounded trusted-broker model.

These tests verify specified cause semantics, not authentic remote provenance,
real-world causal inference, or a general prevention guarantee.
"""

from dataclasses import replace
import unittest

from permission_thresholds.exception_guard import ExceptionGuard


class GuardTestCase(unittest.TestCase):
    def queue(self, threshold=5, **kwargs):
        return ExceptionGuard(mechanism="queue", threshold=threshold, **kwargs)

    def service(self, threshold=3, **kwargs):
        return ExceptionGuard(mechanism="service", threshold=threshold, **kwargs)

    def independent(self, guard, identity="external", units=1):
        guard.record_external_cause(identity, units=units, independently_certified=True)

    def scope(self, guard):
        return {"job": guard.job, "principal": guard.principal,
                "resource": guard.resource, "operation": guard.operation}

    def allowed_queue(self, **kwargs):
        guard = self.queue(**kwargs)
        self.independent(guard, units=guard.threshold)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        return guard


class CausalQualificationTests(GuardTestCase):
    def test_actor_only_queue_qualification_is_denied(self):
        guard = self.queue()
        guard.record_actor_cause("allocation", actor="agent", units=5)
        decision = guard.decide()
        self.assertTrue(decision.factual_qualified)
        self.assertFalse(decision.shadow_qualified)
        self.assertEqual(decision.outcome, "DENY")
        self.assertEqual(guard.decide(baseline="factual_only").outcome, "ALLOW")

    def test_independent_queue_outage_is_allowed(self):
        guard = self.allowed_queue()
        self.assertTrue(guard.decide().factual_qualified)
        self.assertTrue(guard.decide().shadow_qualified)

    def test_mixed_causes_require_independently_sufficient_load(self):
        guard = self.queue()
        self.independent(guard, units=3)
        guard.record_actor_cause("actor", actor="agent", units=2)
        self.assertEqual(guard.decide().outcome, "DENY")
        self.independent(guard, "more_external", units=2)
        self.assertEqual(guard.decide().outcome, "ALLOW")

    def test_cleanup_does_not_permanently_taint_legitimate_recovery(self):
        guard = self.queue()
        guard.record_actor_cause("allocation", actor="agent", units=5)
        guard.record_verified_release("allocation")
        self.assertEqual(guard.decide().outcome, "DENY")
        self.independent(guard, units=5)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        self.assertEqual(guard.decide(baseline="permanent_taint").outcome, "DENY")

    def test_release_removes_exact_cause_in_both_views(self):
        guard = self.queue()
        self.independent(guard, units=5)
        guard.record_actor_cause("actor", actor="agent", units=5)
        guard.record_verified_release("external")
        decision = guard.decide()
        self.assertTrue(decision.factual_qualified)
        self.assertFalse(decision.shadow_qualified)
        self.assertEqual(decision.outcome, "DENY")
        guard.record_verified_release("actor")
        self.assertFalse(guard.decide().factual_qualified)

    def test_cause_identity_cannot_be_reused_after_release(self):
        guard = self.queue()
        self.independent(guard, units=5)
        guard.record_verified_release("external")
        with self.assertRaises(ValueError):
            self.independent(guard, units=5)
        with self.assertRaises(ValueError):
            guard.record_verified_release("external")

    def test_service_actor_outage_cannot_be_laundered_by_elapsed_time(self):
        guard = self.service()
        guard.record_actor_cause("maintenance", actor="agent")
        guard.set_time(100)
        decision = guard.decide()
        self.assertTrue(decision.factual_qualified)
        self.assertFalse(decision.shadow_qualified)
        self.assertEqual(decision.outcome, "DENY")

    def test_service_independent_cause_must_reach_its_own_age(self):
        guard = self.service()
        guard.record_actor_cause("old_actor_outage", actor="agent")
        guard.set_time(4)
        self.independent(guard, "new_external_outage")
        guard.set_time(5)
        self.assertTrue(guard.decide().factual_qualified)
        self.assertFalse(guard.decide().shadow_qualified)
        self.assertEqual(guard.decide().outcome, "DENY")
        guard.set_time(7)
        self.assertEqual(guard.decide().outcome, "ALLOW")

    def test_service_repair_leaves_other_independent_outage_active(self):
        guard = self.service()
        self.independent(guard, "outage_a")
        self.independent(guard, "outage_b")
        guard.set_time(3)
        guard.record_verified_release("outage_a")
        self.assertEqual(guard.decide().outcome, "ALLOW")
        self.assertTrue(guard.reconcile_observation(service_online=False))
        guard.record_verified_release("outage_b")
        self.assertEqual(guard.decide().outcome, "DENY")
        self.assertTrue(guard.reconcile_observation(service_online=True))

    def test_delegated_actor_is_excluded_from_same_job_shadow(self):
        guard = self.queue(principal="parent")
        guard.record_actor_cause("child_allocation", actor="delegated_child", units=5)
        self.assertEqual(guard.decide().outcome, "DENY")

    def test_small_queue_exhaustive_independent_sufficiency_invariant(self):
        for threshold in range(1, 7):
            for external in range(4):
                for required in range(4):
                    for discretionary in range(4):
                        with self.subTest(threshold=threshold, external=external,
                                          required=required, discretionary=discretionary):
                            guard = self.queue(threshold)
                            if external:
                                self.independent(guard, units=external)
                            if required:
                                grant = guard.grant_work(actor="agent", purpose="requested", units=required, expires_at=10)
                                guard.record_actor_cause("required", actor="agent", units=required,
                                                         purpose="requested", grant_id=grant)
                            if discretionary:
                                guard.record_actor_cause("optional", actor="agent", units=discretionary)
                            decision = guard.decide()
                            self.assertEqual(decision.factual_qualified,
                                             external + required + discretionary >= threshold)
                            self.assertEqual(decision.shadow_qualified, external + required >= threshold)
                            self.assertEqual(decision.outcome == "ALLOW", external + required >= threshold)


class WorkGrantTests(GuardTestCase):
    def test_required_work_with_matching_grant_is_retained(self):
        guard = self.queue()
        grant = guard.grant_work(actor="worker", purpose="required_qa", units=5, expires_at=10)
        guard.record_actor_cause("qa", actor="worker", purpose="required_qa", units=5, grant_id=grant)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        self.assertEqual(guard.grants[grant].remaining_units, 0)
        self.assertEqual(guard.causes["qa"].origin, "authorized_work")

    def test_grant_budget_is_cumulative_and_excess_is_not_partially_endorsed(self):
        guard = self.queue()
        grant = guard.grant_work(actor="agent", purpose="qa", units=5, expires_at=10)
        guard.record_actor_cause("first", actor="agent", purpose="qa", units=3, grant_id=grant)
        guard.record_actor_cause("excess", actor="agent", purpose="qa", units=3, grant_id=grant)
        self.assertEqual(guard.grants[grant].remaining_units, 2)
        self.assertEqual(guard.causes["excess"].origin, "discretionary_actor")
        self.assertEqual(guard.decide().outcome, "DENY")
        guard.record_actor_cause("remainder", actor="agent", purpose="qa", units=2, grant_id=grant)
        self.assertEqual(guard.decide().outcome, "ALLOW")

    def test_purpose_principal_and_unknown_grant_cannot_forge_authority(self):
        variants = ({"actor": "wrong_actor", "purpose": "qa"},
                    {"actor": "agent", "purpose": "different_purpose"},
                    {"actor": "agent", "purpose": "qa", "grant_id": "forged"})
        for variant in variants:
            guard = self.queue()
            grant = guard.grant_work(actor="agent", purpose="qa", units=5, expires_at=10)
            args = {"actor": "agent", "purpose": "qa", "grant_id": grant, "units": 5, **variant}
            guard.record_actor_cause("effect", **args)
            self.assertEqual(guard.decide().outcome, "DENY")
            self.assertEqual(guard.grants[grant].remaining_units, 5)

    def test_grant_expiry_exact_boundary_prevents_new_endorsement(self):
        guard = self.queue()
        grant = guard.grant_work(actor="agent", purpose="qa", units=5, expires_at=2)
        guard.set_time(2)
        guard.record_actor_cause("late", actor="agent", purpose="qa", units=5, grant_id=grant)
        self.assertEqual(guard.decide().outcome, "DENY")

    def test_grant_revocation_prevents_new_endorsement(self):
        guard = self.queue()
        grant = guard.grant_work(actor="agent", purpose="qa", units=5, expires_at=10)
        guard.revoke_grant(grant)
        guard.record_actor_cause("revoked", actor="agent", purpose="qa", units=5, grant_id=grant)
        self.assertEqual(guard.decide().outcome, "DENY")

    def test_policy_epoch_invalidates_unspent_work_grants(self):
        guard = self.queue()
        grant = guard.grant_work(actor="agent", purpose="qa", units=5, expires_at=10)
        guard.change_policy("conditional")
        guard.record_actor_cause("stale_epoch", actor="agent", purpose="qa", units=5, grant_id=grant)
        self.assertEqual(guard.decide().outcome, "DENY")

    def test_previous_required_effect_is_not_retroactively_reclassified(self):
        guard = self.queue()
        grant = guard.grant_work(actor="agent", purpose="qa", units=5, expires_at=2)
        guard.record_actor_cause("authorized_then", actor="agent", purpose="qa", units=5, grant_id=grant)
        guard.revoke_grant(grant)
        guard.set_time(3)
        self.assertEqual(guard.causes["authorized_then"].origin, "authorized_work")
        self.assertEqual(guard.decide().outcome, "ALLOW")

    def test_required_maintenance_preserves_age_and_repair_semantics(self):
        guard = self.service()
        grant = guard.grant_work(actor="operator", purpose="scheduled_maintenance", units=1, expires_at=10)
        guard.record_actor_cause("maintenance", actor="operator", purpose="scheduled_maintenance", grant_id=grant)
        guard.set_time(3)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        guard.record_verified_release("maintenance")
        self.assertEqual(guard.decide().outcome, "DENY")

    def test_invalid_or_duplicate_events_do_not_consume_grant_credit(self):
        guard = self.queue()
        grant = guard.grant_work(actor="agent", purpose="qa", units=10, expires_at=10)
        guard.record_actor_cause("same", actor="agent", purpose="qa", units=1, grant_id=grant)
        for identity, units in (("same", 1), ("invalid", True), ("invalid", 0), ("invalid", -1)):
            with self.assertRaises(ValueError):
                guard.record_actor_cause(identity, actor="agent", purpose="qa", units=units, grant_id=grant)
            self.assertEqual(guard.grants[grant].remaining_units, 9)


class EvidenceAndRecoveryTests(GuardTestCase):
    def test_accurate_telemetry_does_not_launder_actor_cause(self):
        queue = self.queue()
        queue.record_actor_cause("actor", actor="agent", units=5)
        self.assertTrue(queue.reconcile_observation(queue_load=5))
        self.assertEqual(queue.decide().outcome, "DENY")
        service = self.service()
        service.record_actor_cause("actor", actor="agent")
        service.set_time(3)
        self.assertTrue(service.reconcile_observation(service_online=False))
        self.assertEqual(service.decide().outcome, "DENY")

    def test_unknown_origin_defers_even_when_aggregate_telemetry_matches(self):
        for certificate in (False, 1, "true", None):
            guard = self.queue()
            guard.record_external_cause("observed", units=5, independently_certified=certificate)
            self.assertTrue(guard.reconcile_observation(queue_load=5))
            self.assertEqual(guard.decide().outcome, "DEFER")
            self.assertEqual(guard.decide(baseline="factual_only").outcome, "ALLOW")

    def test_mismatched_telemetry_latches_uncertainty_without_importing_state(self):
        guard = self.queue()
        self.assertFalse(guard.reconcile_observation(queue_load=5))
        self.assertFalse(guard.decide().factual_qualified)
        self.assertEqual(guard.decide().outcome, "DEFER")
        self.assertEqual(len(guard.causes), 0)
        self.assertTrue(guard.reconcile_observation(queue_load=0))
        self.assertEqual(guard.decide().outcome, "DEFER")

    def test_removing_unresolved_cause_does_not_silently_clear_uncertainty(self):
        guard = self.queue()
        guard.record_external_cause("unknown", units=5)
        guard.record_verified_release("unknown")
        self.independent(guard, units=5)
        self.assertEqual(guard.decide().outcome, "DEFER")

    def test_independent_unconditional_authority_and_never_mode(self):
        guard = self.queue()
        guard.flag_uncertain("missing causal evidence")
        guard.change_policy("always")
        self.assertEqual(guard.decide().outcome, "ALLOW")
        self.assertEqual(guard.decide(baseline="deny_all").outcome, "DENY")
        guard.change_policy("never")
        self.assertEqual(guard.decide().outcome, "DENY")

    def test_due_recovery_obligation_defers_at_exact_deadline(self):
        guard = self.service(threshold=1)
        self.independent(guard)
        guard.require_recovery("repair_due", causes=["external"], deadline=3)
        guard.set_time(2)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        guard.set_time(3)
        decision = guard.decide()
        self.assertEqual(decision.outcome, "DEFER")
        self.assertEqual(decision.overdue_obligations, ("repair_due",))
        self.assertEqual(guard.decide(baseline="shadow_only").outcome, "ALLOW")

    def test_infeasibility_attestation_expires_at_exact_boundary(self):
        guard = self.service(threshold=1)
        self.independent(guard)
        guard.require_recovery("repair", causes=["external"], deadline=1)
        guard.set_time(1)
        self.assertEqual(guard.decide().outcome, "DEFER")
        guard.attest_recovery_infeasible("repair", valid_until=4, independently_certified=True)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        guard.set_time(3)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        guard.set_time(4)
        self.assertEqual(guard.decide().outcome, "DEFER")

    def test_uncertified_repair_failure_cannot_discharge_obligation(self):
        guard = self.service(threshold=1)
        self.independent(guard)
        guard.require_recovery("repair", causes=["external"], deadline=1)
        guard.set_time(1)
        guard.attest_recovery_infeasible("repair", valid_until=5, independently_certified=False)
        self.assertEqual(guard.decide().outcome, "DEFER")
        self.assertIsNone(guard.obligations["repair"].infeasible_until)

    def test_completed_repair_obligation_does_not_block_unrelated_future_outage(self):
        guard = self.service(threshold=1)
        self.independent(guard, "old")
        guard.require_recovery("repair_old", causes=["old"], deadline=1)
        guard.set_time(1)
        guard.record_verified_release("old")
        self.independent(guard, "new")
        guard.set_time(2)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        self.assertEqual(guard.decide().overdue_obligations, ())

    def test_unregistered_repair_delay_is_an_explicit_known_limitation(self):
        guard = self.service(threshold=3)
        self.independent(guard)
        guard.set_time(100)
        # No prescribed recovery obligation was supplied. The guard cannot infer
        # that the agent should have repaired the genuine external outage.
        self.assertEqual(guard.decide().outcome, "ALLOW")
        self.assertEqual(guard.snapshot()["overdue"], [])

    def test_time_cannot_be_rewound_or_substituted_with_boolean(self):
        guard = self.service()
        guard.set_time(3)
        for invalid in (2, True, 1.5, -1):
            with self.assertRaises(ValueError):
                guard.set_time(invalid)

    def test_recovery_requires_active_known_causes_and_nonretroactive_deadline(self):
        guard = self.service()
        self.independent(guard)
        guard.set_time(3)
        for causes, deadline in (([], 4), (["missing"], 4), (["external"], 2)):
            with self.assertRaises(ValueError):
                guard.require_recovery("invalid", causes=causes, deadline=deadline)


class ExecutionLeaseTests(GuardTestCase):
    def test_denied_and_deferred_decisions_never_mint_lease(self):
        guard = self.queue()
        decision, lease = guard.authorize()
        self.assertEqual(decision.outcome, "DENY")
        self.assertIsNone(lease)
        guard.flag_uncertain("unknown origin")
        decision, lease = guard.authorize()
        self.assertEqual(decision.outcome, "DEFER")
        self.assertIsNone(lease)

    def test_lease_executes_once(self):
        guard = self.allowed_queue()
        _, lease = guard.authorize()
        calls = []
        result = guard.execute(lease, lambda: calls.append("executed") or "result", **self.scope(guard))
        self.assertEqual(result, "result")
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: calls.append("replayed"), **self.scope(guard))
        self.assertEqual(calls, ["executed"])

    def test_wrong_scope_cannot_execute_but_does_not_consume_authentic_lease(self):
        for field in ("job", "principal", "resource", "operation"):
            guard = self.allowed_queue(job="job_a", principal="principal_a", resource="resource_a", operation="external_a")
            _, lease = guard.authorize()
            wrong = {**self.scope(guard), field: "wrong"}
            calls = []
            with self.assertRaises(PermissionError):
                guard.execute(lease, lambda: calls.append("bad"), **wrong)
            self.assertEqual(calls, [])
            guard.execute(lease, lambda: calls.append("valid"), **self.scope(guard))
            self.assertEqual(calls, ["valid"])

    def test_lease_tampering_and_forged_identity_are_rejected(self):
        for field, replacement in (("identity", "forged"), ("expires_at", 10_000),
                                   ("principal", "attacker"), ("state_version", -1), ("policy_epoch", -1)):
            guard = self.allowed_queue()
            _, lease = guard.authorize()
            tampered = replace(lease, **{field: replacement})
            with self.assertRaises(PermissionError):
                guard.execute(tampered, lambda: self.fail("Tampered lease executed"), **self.scope(guard))

    def test_operation_arguments_cannot_be_substituted_after_authorization(self):
        guard = self.allowed_queue()
        approved = {"destination": "approved_archive", "record_count": 10}
        _, lease = guard.authorize(arguments=approved)
        substituted = {"destination": "different_archive", "record_count": 10}
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Substituted arguments executed"),
                          arguments=substituted, **self.scope(guard))
        # Object-key order is immaterial to a canonical argument commitment.
        reordered = {"record_count": 10, "destination": "approved_archive"}
        self.assertEqual(guard.execute(lease, lambda: "valid", arguments=reordered,
                                      **self.scope(guard)), "valid")

    def test_mutating_original_argument_object_does_not_change_lease_commitment(self):
        guard = self.allowed_queue()
        arguments = {"destination": "approved", "options": {"records": 10}}
        _, lease = guard.authorize(arguments=arguments)
        arguments["options"]["records"] = 100
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Mutated arguments executed"),
                          arguments=arguments, **self.scope(guard))
        guard.execute(lease, lambda: None, arguments={"destination": "approved", "options": {"records": 10}},
                      **self.scope(guard))

    def test_lease_from_another_guard_cannot_cross_instance(self):
        first, second = self.allowed_queue(), self.allowed_queue()
        _, lease = first.authorize()
        with self.assertRaises(PermissionError):
            second.execute(lease, lambda: self.fail("Foreign lease executed"), **self.scope(second))

    def test_state_change_stales_lease_even_if_predicate_remains_true(self):
        guard = self.allowed_queue()
        _, lease = guard.authorize()
        self.independent(guard, "additional", units=1)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Stale lease executed"), **self.scope(guard))

    def test_revoked_policy_blocks_previously_queued_operation(self):
        guard = self.allowed_queue()
        _, lease = guard.authorize(ttl=10)
        guard.change_policy("never")
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Revoked operation executed"), **self.scope(guard))

    def test_grant_revocation_invalidates_existing_lease_even_when_history_retained(self):
        guard = self.queue()
        grant = guard.grant_work(actor="agent", purpose="qa", units=5, expires_at=10)
        guard.record_actor_cause("qa", actor="agent", purpose="qa", units=5, grant_id=grant)
        _, lease = guard.authorize()
        guard.revoke_grant(grant)
        self.assertEqual(guard.decide().outcome, "ALLOW")
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Pre-revocation lease executed"), **self.scope(guard))

    def test_lease_expires_at_exact_deadline(self):
        guard = self.allowed_queue()
        _, lease = guard.authorize(ttl=2)
        guard.set_time(2)
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Expired lease executed"), **self.scope(guard))

    def test_clock_progress_without_other_change_can_keep_lease_valid(self):
        guard = self.allowed_queue()
        _, lease = guard.authorize(ttl=3)
        guard.set_time(2)
        self.assertEqual(guard.execute(lease, lambda: "ok", **self.scope(guard)), "ok")

    def test_execute_rechecks_recovery_deadline_without_state_version_change(self):
        guard = self.service(threshold=1)
        self.independent(guard)
        guard.require_recovery("repair", causes=["external"], deadline=3)
        guard.set_time(2)
        _, lease = guard.authorize(ttl=10)
        version = guard.version
        guard.set_time(3)
        self.assertEqual(guard.version, version)
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Overdue obligation bypassed"), **self.scope(guard))

    def test_execute_rechecks_infeasibility_attestation_ttl(self):
        guard = self.service(threshold=1)
        self.independent(guard)
        guard.require_recovery("repair", causes=["external"], deadline=1)
        guard.set_time(1)
        guard.attest_recovery_infeasible("repair", valid_until=3, independently_certified=True)
        _, lease = guard.authorize(ttl=10)
        guard.set_time(3)
        with self.assertRaises(PermissionError):
            guard.execute(lease, lambda: self.fail("Expired recovery evidence used"), **self.scope(guard))

    def test_callback_exception_burns_lease(self):
        guard = self.allowed_queue()
        _, lease = guard.authorize()
        calls = []

        def failing_callback():
            calls.append("attempt")
            raise RuntimeError("unknown downstream outcome")

        with self.assertRaises(RuntimeError):
            guard.execute(lease, failing_callback, **self.scope(guard))
        with self.assertRaises(PermissionError):
            guard.execute(lease, failing_callback, **self.scope(guard))
        self.assertEqual(calls, ["attempt"])

    def test_ambiguous_executor_failure_defers_fresh_conditional_authorization(self):
        guard = self.allowed_queue()
        _, original_lease = guard.authorize()
        possible_side_effects = []

        def partially_failing_callback():
            possible_side_effects.append("downstream request may have executed")
            raise RuntimeError("response unavailable after possible execution")

        with self.assertRaises(RuntimeError):
            guard.execute(original_lease, partially_failing_callback, **self.scope(guard))
        self.assertTrue(guard.snapshot()["uncertainty"])
        decision, fresh_lease = guard.authorize()
        self.assertTrue(decision.factual_qualified)
        self.assertTrue(decision.shadow_qualified)
        self.assertEqual(decision.outcome, "DEFER")
        self.assertIsNone(fresh_lease)
        with self.assertRaises(PermissionError):
            guard.execute(original_lease, partially_failing_callback, **self.scope(guard))
        # The guard prevents another authorization; it does not undo the
        # possibly completed external effect or claim remote exactly-once use.
        self.assertEqual(possible_side_effects, ["downstream request may have executed"])

    def test_competing_lease_becomes_stale_after_first_execution(self):
        guard = self.allowed_queue()
        _, first = guard.authorize()
        _, second = guard.authorize()
        guard.execute(first, lambda: None, **self.scope(guard))
        with self.assertRaises(PermissionError):
            guard.execute(second, lambda: self.fail("Competing stale lease executed"), **self.scope(guard))


if __name__ == "__main__":
    unittest.main()
