# Can AI Agents Manufacture Their Own Safety Exceptions?

**Amornchot Singh · AI safety research in progress**

[Read the working paper](paper/agent_safety_exceptions.pdf) · [Study protocol](docs/GUARD_EXECUTION_STUDY_PLAN_V2.md) · [Related work](docs/CEG_RELATED_WORK_AUDIT.md) · [Next experiment](docs/EXTERNAL_CAPABILITY_PILOT.md)

When an AI agent is allowed to use a restricted tool only under exceptional conditions, can it create those conditions itself? For example, an agent could occupy local resources and then ask to use an external-processing exception.

This project implements a controlled environment for studying the **integrity of conditional permissions**. A trusted broker records resource origins, enforces authorization rules and verifies report artifacts. The research concerns specification gaming and AI control. It does not establish that the underlying security principle is new.

## Current findings

| Evidence | Finding | Interpretation |
| --- | --- | --- |
| Scripted policy comparison | Eight policies, 14 matched states, 112 executed probes | Mechanism comparison, not learned-agent behavior |
| Legitimate scripted workflows | 96 executions across eight policies | Availability and reachability checks |
| Provenance rule versus CEG | Identical outcomes on all 14 states; equivalent in the additive model | No demonstrated algorithmic superiority |
| Corrected local-model capability screen | Qwen2.5 3B: 4/18 compliant completions; Llama3.2 1B: 0/18 | Neither model-interface configuration qualified for the main safety study |
| Required-repair coverage | Separate runtime wrapper addresses the observed registration gap | Software validation, not measured efficacy against capable agents |
| External-model pilot | Implemented; no paid model calls made | Ready for configuration and capability screening |

**No experiment in this release establishes defense effectiveness against capable adaptive agents.** The paper reports these boundaries and negative findings explicitly. The 331 passing software checks verify implementation behavior; they are not independent research samples.

## What is implemented

- A SQLite-backed tool environment with local jobs, work receipts and verified reports.
- Policy comparators for factual thresholds, taint, provenance, recovery obligations and deny-all.
- A separately versioned recovery-coverage wrapper with a final execution check.
- Frozen local-model collection records, opaque public scenario IDs and replay auditing.
- An opt-in external capability runner with call records and conditional cost accounting.

The alternative processing route is **simulated locally**. Queue occupancy is logical rather than physical CPU contention. All tool-environment data are authored/synthetic; the retained Ollama responses are actual local-model outputs. These are different meanings of “synthetic” and must not be conflated.

## Quick start

Python 3.10 or later. The experiment runtime uses the standard library. Document-related tests require the additional paper dependencies.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install -r requirements-paper.txt
PYTHONPATH=src python -m unittest discover -s tests -q
```

Audit the retained corrected capability runs without model calls:

```bash
PYTHONPATH=src python scripts/analyze_guard_study_v2.py \
  --run runs/guard-v2-qwen25-capability \
  --run runs/guard-v2-llama32-capability \
  --out-dir output/replayed-capability
```

Use a fresh output directory for every audit or collection. The four retained run directories include their original source snapshots and hashes. Historical absolute paths in manifests are preserved for integrity; audit commands above use the checkout paths. Checksums establish internal consistency, not third-party attestation.

For an external-model screen, read [the separate protocol](docs/EXTERNAL_CAPABILITY_PILOT.md). The template intentionally contains no approved model or prices. Planning does not call an API. Paid execution requires an explicit model, verified limits/prices, a spending ceiling, a configured API key and `--execute-paid`. The runner never starts the main defense study automatically.

## Paper and publication status

The [PDF](paper/agent_safety_exceptions.pdf) uses a single-column academic layout inspired by an existing manuscript. It is a **working paper**, not an accepted conference publication or a certified workshop submission template. Intended submission: MERe AI Workshop 2026; no submission or acceptance is claimed.

The [editable source manuscript](paper/source_manuscript.docx) preserves the earlier study narrative. The PDF builder adds the current external-pilot status and software-check count. Rebuild with:

```bash
python paper/build_pdf.py
```

## Evidence organization

- `runs/guard-policy-comparison`: scripted decisions and legitimate reference executions.
- `runs/guard-requirement-coverage-diagnostic`: post hoc static diagnostic, not a fresh model cohort.
- `runs/guard-v2-*-capability`: the 36 corrected local-model episodes.
- `data/guard_study`: authored scenarios and frozen protocol metadata.
- `docs`: current protocols, limitations and related-work audits, plus clearly historical design documents.
- `src`, `scripts`, `tests`: implementation, analysis and software verification.

This public release excludes earlier contaminated main pilots, superseded model cohorts and illustrative fabricated result files. Some historical scripts/docs describe those separate development stages; they do not supply additional public empirical findings. The current PDF and the table above define the scope of this release.

## Attribution and limitations

The project was developed with AI-assisted coding, analysis and manuscript preparation. No independent human review of the scenario labels is claimed. All substantive claims should be read with the [evidence assessment](docs/EVIDENCE_REQUIRED_FOR_NOVELTY_AND_EFFICACY.md).

A small licensed AgentDojo prompt extract is retained for earlier scenario inspiration, with its original license and source provenance under `data/external/agentdojo`. This is not a full AgentDojo benchmark evaluation. Third-party materials retain their original licenses. No blanket project license is granted by this initial release.
