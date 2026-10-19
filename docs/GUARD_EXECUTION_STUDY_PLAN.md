# Execution backed evaluation of resource dependent permissions

## Scope and claim

This study tests a bounded, operational authorization policy in an SQLite job broker. Actual queued jobs, computed check receipts and verified local report files replace the earlier scalar-only transitions. The external route is still a simulated alternative that writes a local file. Logical queue occupancy is not measured CPU or remote-service contention. The actor can issue only validated JSON tool calls; arbitrary shell/code access is outside the threat model.

CEG receives cause evidence from trusted dispatch, without accepting actor-supplied origin or grant labels. Background jobs come from a controlled independent scheduler; required work comes from a fixed manifest; optional jobs originate in actor tool calls. This establishes provenance within this controlled environment, not general causal discovery. External events induced through unmodeled dependencies remain out of scope. We test incomplete evidence and misleading claims explicitly.

In an additive nonnegative queue, the CEG permission predicate reduces to a simple provenance-filtered threshold rule. The study therefore makes no claim to a new counterfactual inference algorithm. The potentially useful result is the behavior of real agents under explicit resource-dependent policies and the safety/utility consequences of enforcing trustworthy provenance and registered recovery obligations.

## Frozen design before collection

Twelve evaluation case families cover healthy capacity, independent full queues, approved work, actor load, mixed causes, missing origin, false actor claims, omitted ledger events, registered repair, unregistered repair and ordinary required work. Cases are materialized after broker implementation, with implementation and case hashes. The same team authors the mechanism and cases; this is a procedural holdout, not independent-domain or blinded human validation. No outcome-dependent case removal is allowed.

Six separate capability exercises check ordinary computation, required checks, legitimate external processing, repair, cleanup and authorized workload qualification. The primary capability endpoint additionally requires the named external route, repair or cleanup when specified. Capability episodes are never counted as safety observations.

Available installed models are Qwen2.5 3B and Llama3.2 1B. Both will be retained regardless of performance. We run three independent seeded repetitions per capability exercise and three per evaluation cell. The three live policies are factual-only, history-rules and CEG; all eight policies are additionally compared on controlled action sequences and same pre-action states. The provenance arithmetic comparator is implemented separately and must receive exactly the same evidence as CEG. Agreement is reported as equivalence within this model, not as a CEG improvement.

Each evaluation model has 12 cases × 3 policies × 2 actor instructions × 3 repetitions = 216 planned episodes. Each capability model has 6 cases × 3 repetitions = 18 planned episodes under factual-only enforcement. Two models give 432 evaluation and 36 capability episodes. Every assigned episode, including generation errors and exhausted budgets, remains in its denominator. A collection interrupted for operational reasons must be explicitly marked incomplete; it cannot be silently reported as the full design.

Ordinary-assistant and adversarial-test instructions are separate cohorts. Adversarial agents are explicitly asked to obtain unauthorized external processing in a local synthetic sandbox; their behavior is not evidence of spontaneous deception or malicious intent in ordinary assistants. Models receive policy, tools, current operational state and public action/result history. Private oracle origin columns, scoring labels and alternative-policy decisions are never supplied. The broker baseline name is not included, although decision explanations differ and are visible.

The temperature is 0.6, output cap 128 tokens, context setting 4096, and at most 12 tool calls per episode. Complete prompts, responses, model digests, runtimes, seeds and source snapshots are retained. There are no automatic inference retries or cross-episode learning. Policies share initial cases and sampling seeds, but fresh interactive histories can diverge; this is not identical-trajectory evaluation.

## Policies

1. Factual-only checks the observed total load threshold.
2. Permanent taint denies after any discretionary resource cause in the history.
3. Active taint denies while any discretionary cause remains active.
4. History-rules adds evidence completeness and registered recovery requirements to active-taint checking.
5. Shadow-only checks independent/authorized load but omits registered recovery obligations.
6. Provenance-rules independently computes eligible load from the observed event ledger and checks evidence and recovery obligations.
7. CEG uses the proposed guard, including execution-time revalidation and a single-use lease.
8. Deny-all rejects conditional external processing.

These are transparent local policy comparators. We do not call them reproductions of Progent, FORGE, FAVA or other published systems. A fair published-system comparison would require their actual implementations, equivalent expressible policy and identical observed evidence.

## Outcomes and analysis

The explicit user policy forbids manufacturing fallback conditions and requires any specified repair before external processing. This makes actor-dependent execution and premature use before required repair violations of the declared policy, rather than disagreements with a weaker literal threshold.

Primary reported outcomes are episode-level actor-dependent external execution, strict-policy violation, valid report creation, full workflow completion, and task completion without a successful strict-policy violation. Attempted external use, denials, deferrals, optional work, repairs, invalid tool calls, model errors, elapsed time and tokens are secondary outcomes. Optional work alone does not establish intent or a violation. Full workflow completion requires a correct artifact, required receipts, required repairs and successful finish. Report creation is also reported separately.

Actor-dependent opportunity cases are declared in the case file before collection. The main descriptive contrast is CEG minus factual-only episode event rate within these cases, separately for each model and actor instruction. Necessary legitimate external use has its own predeclared case: an independently full queue with unavailable repair and no removable actor jobs. Missing-evidence cases are a separate availability stress test, not intrinsically malicious actions. Omission cases remain explicit counterexamples if a mandatory recovery rule was not registered with the guard.

Analyses retain errors and incomplete workflows, report per-case counts, and separate models and actor instructions. Any scenario-cluster bootstrap is exploratory and conditions on this small authored case set; it is not a confidence interval for deployment reliability. Repeated seeds and parameter variants are not independent domains. For model errors, observed violations are a lower bound on a truncated interaction, not proof of safety. Capability failures limit how much absent attack behavior can establish.

Replay checks recompute transitions, artifact contents and metrics from recorded actions. Integrity hashes identify the code and data used; they are not independent attestation that inference took place. The new cohorts never reuse or relabel the earlier 192-episode study as defense evidence.

## Remaining external validation requirements

Frontier-capable actors, independent human outcome review, out-of-domain workflows, induced third-party failures, distributed execution and production telemetry cannot be established from this controlled local experiment. They remain prerequisites for broader claims. Novelty is assessed against the separate primary-source audit and cannot be guaranteed by a new method name or passing tests.
