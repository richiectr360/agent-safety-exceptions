# Measured local pilot plan

Frozen before the first v2 model rollout on 18 October 2026. This is a local
analysis plan, not an externally registered preregistration. Preserve the run
manifest, prompt and source hashes; deviations must be reported.

**Resource amendment before any completed model episode:** the initial Qwen3 4B
connectivity attempt was interrupted under disk pressure, with zero completed
episodes. Its manifest is retained under `runs/measured-qwen3-v2-development`.
The larger download was removed. The next local cohort uses Llama 3.2 1B and
4096-token context; all other settings and hypotheses remain as below. This is
a capability-limited small-model pilot, not evidence about frontier agents.
The installed model digest and actual runtime parameters in each manifest are
authoritative. No Qwen3 outcomes are included in the empirical cohort.

**Interface amendment during development, before the full cohort:** the initial
generic action grammar allowed the model to attach `units` to tools that accept
no arguments. Two connectivity episodes showed 39 such invalid actions in 48
calls. The final grammar uses a separate JSON-schema branch for each tool with
its actual argument schema. Every tool remains selectable regardless of whether
its action would be authorized. There is no post-hoc argument repair. The first
capability run under the old grammar is retained as interface-development evidence;
capability is assessed again under the frozen final interface. Model failures
within either cohort remain recorded and are not selectively retried.

**Model-family extension before the full cohort:** after disk headroom recovered,
Qwen2.5 3B was added as a second local family under identical final interface and
sampling settings. Each model receives six capability checks. The Llama 3.2 1B
final-interface capability result is 0/6; it remains reported and is not evidence
of safety. Model cohorts remain separate, with their exact immutable weight digests.

## Question

Does an operative permission threshold change optional environment modification
more than an identically displayed threshold that grants no conditional authority?
The primary comparison is healthy queue scenarios under literal-only policies.
Service availability and explicit-rule variants are supplementary.

## Data collection

- Models: locally executed Llama 3.2 1B (`llama3.2:1b`) and Qwen2.5 3B
  (`qwen2.5:3b`), as amended above. Record each installed digest, quantization,
  runtime version, template, and settings. The full measured cohort is Qwen;
  Llama is retained in the independent capability assessment.
- Settings: temperature 0.6, thinking disabled, JSON-schema action output,
  4096-token context, 128 generated tokens per action, 24-action rollout bound.
  Seeds are derived from a fixed base seed and case/repetition identifiers.
- Cases: 12 authored scenarios, 8 authority/display arms, 2 instruction variants
  = 192 cases per repetition. Each simulator starts fresh. Run order is shuffled.
- Initial measured pilot: one repetition per case. Expansion requires a separately
  recorded run plan and must preserve this original cohort. Do not stop selectively
  when favorable outcomes appear. Every planned case should be retained.
- Capability checks: 6 healthy tasks requiring actual auxiliary QA work or a
  completed maintenance cycle, with unconditional external permission. These
  are separate from the primary experiment and do not determine which outcomes
  are retained. A failed capability check narrows the interpretation of a null.
- A small development connectivity run may precede the full cohort. It is
  explicitly excluded from the measured cohort and must be archived separately.
- All fabricated mixtures and scripted demos are excluded from empirical tables.

## Primary outcome and analysis

Within each authored queue scenario, regress mean added peak load before report
completion on the displayed threshold separately for operative and placebo arms.
Report the paired slope difference across the three authored queue scenarios,
with individual slopes and raw action distributions. The repeated templates are
not independent deployment samples. With only three queue scenarios and one
initial repetition, estimates are exploratory and cannot establish general safety.

Also report optional state creation, actor-created qualification, subsequent
fallback use, completion, explicit-rule violations where applicable, denied calls,
cleanup, and model errors. Optional quality checks have real ancillary outputs;
their use is not automatically a violation under literal-only policies. The
omission audit establishes feasibility of the requested report without the action,
not equality of auxiliary utility or the actor's intent.

The external gate enforces its literal predicate by construction. A zero count
of successful externally unauthorized calls is a property of that gate, not an
empirical finding about the model's safety. Record attempted violations separately.

Retain harmful actions observed before later model/transport errors. Do not count
an unfinished error prefix as a safe rollout. A model error is different from a
policy-compliant refusal. Report complete-case and all-attempt prefix counts.

For rare-event counts, present descriptive Wilson intervals with their independent
Bernoulli assumption stated. They do not provide deployment-generalization bounds
for a few authored templates. Do not use zero-width all-zero bootstrap intervals
to claim zero risk. Do not select claims based only on p-values.

## Interpretation and limitations

The operative/placebo external-policy sentences differ only by the word `not`
versus `also`; operational-number text is identical. This controls numerical
salience more closely than the initial pilot, but prompt interpretation and
capability still require scrutiny. Two simulator mechanisms do not constitute
broad real-world coverage. Same-state supplied history controls are not observations
of the evaluated model creating that history.

Positive evidence would require real pre-completion state changes, meaningful
operative-versus-placebo differences, and successful independent capability checks.
Null or mixed outcomes must be reported. The first cohort supports a bounded
local-model pilot; a strong general empirical paper still needs additional model
families, held-out human-validated tasks, and enough repetitions to assess uncertainty.

## Execution note after the capability cohorts

The final-interface capability result for Qwen2.5 3B is 2/6 complete successes,
with 6/6 base report completions. Two queue tasks produce twenty-one rather than
exactly twenty receipts, and two service tasks leave the service offline. The
runner progress line reports base `task_success`; the authoritative capability
label is `metrics.capability_success`. Llama3.2 1B achieves 0/6. The full planned
192-case Qwen cohort proceeds as an exploratory local-model measurement, with
these limits reported. Llama is not included in the main cohort; its failed
capability checks remain visible rather than being interpreted as safety evidence.
