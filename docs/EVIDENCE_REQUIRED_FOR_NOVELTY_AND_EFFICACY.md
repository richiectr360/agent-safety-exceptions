# Evidence required for novelty and efficacy

Assessment date: 18 October 2026. This is a research decision memo and proposed next study, not new experimental evidence or a frozen collection protocol. Existing manuscripts, code snapshots and results remain unchanged.

## Decision

The current project does not establish a new authorization algorithm or effectiveness against capable agents. A targeted primary-source recheck confirms conceptual overlap. The useful next contribution is empirical: measure when conditional permissions are exploitable through agent-created resource conditions, and the safety and availability consequences of enforcing cause-sensitive policies.

Candidate research question: When agents can alter the conditions that activate permissions, how much does verified cause information improve enforcement without preventing legitimate recovery?

The narrow scope is tool-mediated resource state and conditional external processing. The existing external route is simulated locally. No conclusion about real cloud isolation, general causal discovery or catastrophic-risk reduction follows from it.

## Novelty boundaries

1. Manufactured necessity is explicitly described in David Mc's author-published essay, [Where Power Migrates](https://axio.fyi/p/where-power-migrates), section Manufactured necessity. It is conceptual prior art, not a peer-reviewed defense evaluation. We cannot claim to introduce this risk.
2. [Robust declassification](https://www.cs.cornell.edu/andru/papers/robdecl-jcs/) already addresses attacker influence on release decisions. Cause-sensitive authorization is not a new general security principle.
3. [FORGE v4](https://arxiv.org/html/2602.16708v4) enforces policies over event history and provenance. Its instrumentation records dependencies and mediates actions. Our comparison must not pretend that such an engine can only inspect current load.
4. [FAVA v1](https://arxiv.org/html/2607.27267v1) represents evidence and obligations for authorization. Adding prerequisites or provenance alone does not distinguish our method.

The proposed empirical combination of matched final states, different verified causes, ordinary/adversarial agent behavior and permission-preserving utility is a candidate contribution. This bounded search did not establish priority. It is not evidence that no earlier equivalent evaluation exists. See CEG_RELATED_WORK_AUDIT.md for the broader bibliography and overlap matrix.

In the existing additive model, factual load F = S + D, with D nonnegative and S the eligible external/approved load. Requiring F >= threshold and S >= threshold is equivalent to requiring S >= threshold. With equal evidence and obligations, the current guard and the simple provenance comparator agree by construction. More model runs cannot establish algorithmic superiority where the policies are equivalent.

## Existing evidence and its limits

The corrected capability audit records Qwen2.5 3B at 4/18 compliant completions and Llama3.2 1B at 0/18. Neither meets the predeclared 12/18 overall and 1/3 per-exercise screen. The main evaluation was not launched. These are capability failures, not evidence of successful defense. The 112 matched scripted probes and 96 reference executions are mechanism checks, not adaptive-agent measurements.

Sources: output/guard-study/corrected-capability-audit/report.json, runs/guard-policy-comparison/summary.json and docs/GAP_CLOSURE_AUDIT.md, relative to the project root.

## Next study specification

Stage one is an external-model capability pilot, using the six existing exercises with three repetitions each: 18 episodes per explicitly selected model. Preserve all outcomes. Apply the existing pragmatic capability screen; passing it demonstrates interface competence, not frontier capability or adversarial competence. Pin the model, adapter, prompts, action budget and settings before collection. Interface tuning uses separate development records and requires a new documented screen.

Stage two is a bounded exploratory study for a passing model: 12 existing cases x four policies x two instruction roles x three repetitions = 288 episodes. Four policies are factual-only, equally informed provenance rules, the separately versioned requirement-coverage guard, and deny-all. Roles are ordinary task assistance and explicitly adversarial sandbox testing. The first two policies share the original registered-obligation semantics; comparisons with the coverage guard must disclose that the latter enforces manifest obligations even when registration is missing. Attribute differences to this coverage change, not to a novel causal algorithm. Add an equally informed provenance policy with the same coverage checks before claiming any implementation advantage over that stronger comparator.

Stage two alone cannot establish broad efficacy: all 12 cases are authored development cases in one logical-queue domain. A confirmatory study needs independently reviewed held-out workflows and additional domains, with case counts determined before collection through a precision/power analysis. Reviewers should judge permission outcomes before seeing model results. Threshold variants and repeated rollouts do not create independent task families.

Keep benign assistance, adversarial testing, ordinary task completion, and legitimately necessary exception access separate. Do not infer spontaneous misconduct from an explicitly instructed attack. Do not infer malicious intent from resource creation alone.

Primary outcomes:

- Episodes containing an actually executed unauthorized privileged effect, divided by all assigned episodes in the relevant attack cohort.
- Compliant task completion, and legitimate exception completion, each with their own declared denominators.
- Resource disruption even when the privileged action was blocked.
- Unnecessary denial or deferral, tool/model errors, exhausted action budgets, latency and inference cost.

Use paired task assignments across policies, retaining independent interactive trajectories. Report uncertainty clustered by independently designed workflow, not by action or repeated seed. Report effect sizes and intervals, not only significance. Preregister the useful safety improvement and tolerable utility loss before confirmatory collection, using pilot precision estimates rather than selecting margins after seeing favorable outcomes.

## Failure conditions and interpretation

- If the actor cannot complete authorized workflows, stop the efficacy claim and report the capability result.
- If the factual-only baseline has no observed unauthorized effects, there is no measured reduction to attribute to the guard; report the negative finding and uncertainty.
- If provenance rules match the guard, report equivalence or application value rather than superiority.
- If preventing exceptions leaves resource disruption intact, claim containment of the privileged effect, not elimination of harmful behavior or incentives.
- If incomplete evidence blocks legitimate recovery, report this availability cost.
- Do not compare to named published systems without an actual integration and equally expressive policies/evidence.

## Execution readiness

No paid calls or new model episodes were made during this assessment. An Anthropic command adapter exists for the earlier pilot, but the frozen V2 collector is Ollama-specific. External-model collection therefore still requires a separately versioned runner, request/response auditing, and an enforced spending limit; it must not be silently substituted into V2.

The next required input is an authorized model/provider and spending ceiling, or access to a suitable no-charge endpoint. Start with the 18-episode capability screen before spending on the larger exploratory study. Provider pricing and model availability must be checked when the model is selected. Do not put secrets in this memo or conversation.

The honest current claim remains: implemented AI safety research in progress, with a concrete testbed, transparent policy comparisons and unresolved empirical questions.
