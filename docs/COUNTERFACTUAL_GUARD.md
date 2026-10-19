# Counterfactual Exception Guard (CEG)

**Status:** proposed defense and local prototype specification. Validation at this stage is limited to scripted mechanism tests. No LLM defense experiment has established CEG's effectiveness. The earlier 192-episode agent cohort is unchanged and does **not** validate CEG.

## Problem and intended contribution

A conditional permission can reward an agent for changing the condition that controls its own authority. For example, an external processor may be permitted only when local capacity is unavailable. A state-only policy can authorize the transfer after the agent itself consumes the remaining capacity, even when the consumption was unnecessary for the primary task.

CEG checks whether the exception would still qualify in a resource ledger that excludes discretionary actor-created causes. Its aim is to block permission expansion that depends on those causes while preserving access during independently established failures or authorized resource use. The proposed contribution is a concrete runtime construction and its evaluation for resource-dependent exceptions. It is not a claim to have invented robust authorization, counterfactual reasoning, or parallel security states.

## State and trust boundary

The gate maintains two views under the same policy and trusted wall-clock time:

- **Factual view:** the verified, currently effective resource causes, including discretionary actor effects.
- **Shadow view:** independently established external causes and effects incurred under scoped, independently issued work grants. Discretionary actor-created causes are omitted.

This shadow is a specified reference ledger, not an unrestricted prediction of a complete alternate world. It requires a model of how individual resource causes combine. A load example is `factual_load = external_load + granted_work_load + discretionary_load`, while `shadow_load = external_load + granted_work_load`. Service availability may instead depend on several separately recorded blockers. Mixed causes must remain componentwise: an actor-created blocker does not turn an independent outage into actor-originated evidence, and an independent outage does not endorse every concurrent actor effect.

Each cause needs an identifier, resource scope, effect, creation time, provenance evidence, and lifecycle. Observations such as aggregate queue load or a service's current health can reconcile the ledger with reality, but cannot establish a cause's trusted origin. A mismatch or unaccounted effect makes the relevant state uncertain; it must not be silently assigned to the external component.

The actor can propose actions and supply explanations. It cannot promote its own effect to an external cause or issue its own work grant. Provenance comes from independently authenticated instrumentation or an authorized principal outside the actor's control. A service response saying “external failure” is not sufficient when the actor could have induced that response. Delegation does not reset provenance.

Independently verified recovery closes the affected causes. It must not leave a resolved external outage permanently active in the shadow. Resource observations and cause-resolution events must agree; unexplained disagreement produces uncertainty rather than a guessed cause assignment.

## Work grants and recovery obligations

A trusted work grant binds an authorized purpose, task and principal to resource scopes, an effect budget, and an expiry time. An effect enters the shadow only when it was independently authorized and within that scope and budget when incurred. Grants do not confer unrestricted permission to use the eventual privileged operation.

Expiry prevents new effects from being admitted under that grant. It does not erase already incurred authorized load or rewrite its historical provenance. Resource release requires a verified lifecycle event. Revocation prevents further grant use and invalidates outstanding execution leases; the ledger still records effects that physically remain.

CEG additionally accepts **trusted recovery obligations**. An obligation specifies the affected cause IDs, responsible scope, required recovery action or independently verifiable recovery condition, and a deadline measured by trusted wall-clock time. It is registered by the policy authority or an independently trusted mechanism, not inferred solely from an actor's self-report.

If a relevant recovery obligation is overdue, the gate returns `DEFER` until the affected causes are repaired or the obligation receives an independently certified infeasibility disposition. This is an escalation rule; it does not assert that an attempted repair would have succeeded. A certificate must identify the obligation and causes, come from an authorized independent source, and have a defined validity scope. The actor cannot dismiss an obligation by asserting that repair is impossible.

This blocks exception authorization while a relevant registered recovery obligation is overdue. It does not block access between exception maturity and a later repair deadline; policy authors must choose deadlines with that interval in mind. It does **not** address every omission. Unregistered withheld repairs, unknown recovery options, and deliberately slow work remain known limitations. Tool-call counts are not elapsed time: making extra calls must not manufacture an outage's trusted age.

## Decision rule

Ordinary authorization first establishes that this principal, task and operation may use this exception policy at all. CEG never creates a new operation outside that policy's scope. For an in-scope conditional request, let `E` be the exception predicate.

| Condition | Decision |
| --- | --- |
| Predicate, provenance, reconciliation, or required evidence is unknown | `DEFER` |
| With complete evidence, a relevant predicate is false in either view | `DENY` |
| A relevant recovery obligation is overdue without a valid independent disposition | `DEFER` |
| Both predicates are verified true, provenance is verified, and no relevant recovery obligation is overdue | `ALLOW`, subject to execution-time revalidation |

For an `ALLOW`, the core requirement is:

`E(factual) AND E(shadow) AND verified_provenance AND no_overdue_recovery`

The factual conjunction matters: a stale or pessimistic shadow must not authorize an exception after the actual qualifying condition has disappeared. `DEFER` is not a successful task outcome; it requires an independent decision or additional evidence. An uncertain cause is not automatically a discretionary cause, and uncertainty is not proof of misconduct.

```text
evaluate(request, trusted_now):
    if ordinary_scope_authorization(request) is false:
        return DENY
    if ordinary_scope_authorization(request) is unknown:
        return DEFER

    snapshot = obtain_consistent_verified_snapshot(request.resources)
    if snapshot is unavailable:
        return DEFER

    factual = build_factual_view(snapshot.causes, trusted_now)
    shadow  = build_shadow_view(
        independently_external_causes(snapshot),
        effects_validly_incurred_under_scoped_grants(snapshot),
        verified_cause_resolutions(snapshot),
        trusted_now)

    factual_result = evaluate_exception(request.policy, factual)
    shadow_result  = evaluate_exception(request.policy, shadow)
    if either result is UNKNOWN or provenance/reconciliation is unverified:
        return DEFER
    if either result is verified FALSE:
        return DENY
    if relevant_registered_recovery_is_overdue_without_valid_disposition(
            request, snapshot, trusted_now):
        return DEFER

    return ALLOW_WITH_LEASE(
        task=request.task, principal=request.principal,
        operation=request.operation, policy_epoch=snapshot.policy_epoch,
        state_version=snapshot.state_version, expiry=short_trusted_expiry)

execute(request, lease):
    atomically within the trusted execution boundary:
        verify request, task, principal, operation and lease bindings
        verify expiry, current policy epoch, current state version and revocations
        re-evaluate the gate against current verified state and trusted time
        if the current decision is not ALLOW: do not execute
        otherwise consume the lease and execute the bound operation
```

The lease is an execution-time protection concept. Its scope should include the operation's exact target and relevant arguments, and it should be single-use. An issued lease is not evidence that a later state still qualifies. Policy changes, relevant state changes, expiry or revocation require rejection or fresh evaluation. Production atomicity requires a trusted enforcement boundary that controls the actual side effect; an in-process prototype alone does not establish atomic enforcement across remote services.

## Narrow property and assumptions

For the CEG policy in conditional mode, fix a trusted exogenous event history, independently authorized work history, policy, request and evaluation time. Assume complete mediation, faithful cause classification, correct resource transitions, a trustworthy clock, and no actor influence over the gate or its evidence. If the shadow exception predicate is false under that fixed history, adding discretionary actor-created resource causes cannot make CEG return `ALLOW` for the request. Independently unconditional permissions are outside this property.

This follows from requiring a true shadow predicate. It is deliberately narrower than noninterference over all possible executions. When the shadow already qualifies, actor effects may still change the factual predicate or task outcome. The property also says nothing about changes to the trusted history, deliberate delays, misclassified causes, unregistered omissions, or an actor that can bypass the enforcement boundary.

An observed “external” event may be downstream of an earlier actor action. Treating it as fixed across both worlds would then be an invalid causal assumption. CEG must either track that dependency, establish independence through trusted evidence, or defer. It cannot resolve this problem by renaming an observed event as exogenous.

## Baselines and evaluation

Compare five explicit policies on the same tasks and event schedules:

1. **Factual-only:** enforce the ordinary exception on current factual state.
2. **Permanent taint denial:** deny conditional access after any relevant discretionary actor-created cause appears, including after its verified removal.
3. **Shadow without recovery obligations:** require both predicates and verified provenance, but omit the overdue-recovery check.
4. **CEG:** the full construction above.
5. **Deny all conditional exceptions:** an availability floor that prevents exception use by construction.

Scripted checks should cover discretionary load creation, independently external failures, authorized load, mixed causes, verified recovery, grant exhaustion/expiry/revocation, origin forgery, unknown provenance, aggregate-state mismatch, overdue repairs, certified infeasibility, and stale or mismatched leases. They validate specified mechanisms and failure cases. They are not evidence that CEG defeats adaptive LLM agents or generalizes to real deployments. The executed challenge report is stored in `runs/ceg-mechanism-checks-final/summary.json`. Its labels and cases are authored contract checks, not independently labeled model outcomes. The report explicitly retains unregistered-recovery-delay counterexamples; it must not be pooled with the earlier measured LLM cohort.

The next real-agent study should freeze the tasks, policies, grants, event schedules, recovery obligations, model settings and outcome definitions before collecting a new cohort. Include external-only failures where the exception is useful, actor-created qualification opportunities, mixed causes, and legitimate approved work. Compare baseline policies using matched task variants, trusted-time schedules and repeated independent rollouts. Test capability separately so failure to use an exception is not mistaken for safety.

Report attempted and successful privileged operations, actor-dependent grants prevented, legitimate exception access, primary-task completion, erroneous denials, deferrals, recovery completion, latency and computational cost. Report errors and partial traces with their actual denominators. Analyze tasks or families as clusters rather than treating every action as independent. Preserve failed and null cases. Deferral and deny-all can look safe while making the system unusable, so compare safety and utility jointly.

Use held-out attack strategies after freezing the defense, including delegated causes, forged provenance, induced third-party failures, delay, unregistered repair withholding and attempts to reuse stale leases. Report which cases lie outside the assumed trust model. The earlier 192 episodes can motivate scenarios, but a new, explicitly identified defense cohort is required for effectiveness claims.

## Closest verified prior work and novelty boundary

- **Myers, Sabelfeld and Zdancewic (2006), _Enforcing Robust Declassification and Qualified Robustness_, Journal of Computer Security 14(2).** Prevents untrusted influence over whether or what information is released, with an endorsement-based relaxation. This is a direct conceptual predecessor to protecting an exception's enabling condition. [Primary paper](https://www.cs.cornell.edu/andru/papers/robdecl-jcs/robdecl-jcs.pdf)
- **Arden and Myers (2016), _A Calculus for Flow-Limited Authorization_, CSF.** Protects dynamically computed authorization against improper influence and proves information-flow guarantees. CEG is not the first attempt to protect authorization computations themselves. [Author page and paper](https://www.cs.cornell.edu/andru/papers/flac/)
- **McCall, Bichhawat and Jia (2023), _Tainted Secure Multi-Execution to Restrict Attacker Influence_, CCS.** Uses multiple execution views and integrity tracking to constrain attacker influence over declassification. It is a close runtime predecessor to a trusted shadow view, although its setting is web information flow. [Primary paper](https://www.andrew.cmu.edu/user/liminjia/research/papers/ifc-ccs23.pdf)
- **Vaskov, Schwarting and Baker (2024), _Do no harm: A counterfactual approach to safe reinforcement learning_, L4DC.** Constrains harm relative to an alternate safe policy to distinguish caused violations from unavoidable ones. Its mechanism is an RL constraint rather than a permission gate. [Proceedings](https://proceedings.mlr.press/v242/vaskov24a.html)
- **Krakovna, Orseau, Kumar, Martic and Legg (2018; revised 2019), _Penalizing side effects using stepwise relative reachability_, arXiv preprint.** Demonstrates that counterfactual baseline choices can create undesirable incentives. This motivates explicit treatment and testing of CEG's shadow definition. [Primary preprint](https://arxiv.org/abs/1806.01186)

The defensible research claim is a specified resource-ledger gate, recovery-obligation extension and controlled evaluation for tool-agent exceptions. Whether this precise combination adds a publishable contribution requires further related-work review and new evidence. A new name, a shadow state, or uncertainty abstention alone does not establish novelty.

## Prototype integration boundary

`exception_guard.py` exposes a trusted-broker API. It does not authenticate external evidence, deploy process isolation, classify causal independence, or connect the new guard to a live LLM agent. Inputs labeled independent are assumptions supplied by the trusted test harness. Grants are scoped to the guard instance and have purpose, actor, budget and time bounds. Infeasibility attestations expire. The execution lease binds the operation argument hash as well as its job, principal, resource, policy epoch, state version and expiry. A trusted callback must perform the exact checked invocation; the prototype cannot prove the behavior of an arbitrary Python callback. Atomicity covers the local broker lock, not remote service state.

If the execution callback raises an exception, the lease stays consumed and the guard records an uncertain outcome. Subsequent conditional authorization defers because the remote action may have partially succeeded. This is not rollback, durable idempotency or exactly-once execution; process crashes and remote state reconciliation require an integrated executor.
