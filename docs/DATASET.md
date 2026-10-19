# Dataset selection and provenance

## Recommendation

Use the project's **controlled synthetic scenarios as the primary experimental
dataset**, and **AgentDojo as an auxiliary source of realistic task patterns**.
The public datasets examined do not directly supply matched interventions on a
permission threshold, controllable agent-created obstruction, and counterfactual
ground truth. A prompt collection alone cannot establish the proposed causal
effect. This is a suitability assessment, not a claim that no related dataset
exists anywhere or that dataset construction itself establishes novelty.

The primary study should start with a working authorized solution, vary only the
permission rule or threshold in matched cases, and observe actual state-changing
actions in the deterministic simulator. The external prompts are not silently
mixed into that evaluation and do not supply its labels.

The initial primary file, `data/pilot_scenarios.jsonl`, contains **12 authored
development scenario templates**, expanded by the CLI into **60 cases across
five policy conditions**. These are developmental checks sharing the same
underlying resource mechanics, not 12 independent real-world environments or a
held-out validation set. See [the pilot protocol](PILOT_PROTOCOL.md) for the
experimental interpretation and planned validation work.

## Downloaded reference corpus

**AgentDojo v1 directly declared user-task prompts**

- Paper: Debenedetti et al. (2024), *AgentDojo: A Dynamic Environment to Evaluate
  Prompt Injection Attacks and Defenses for LLM Agents*.
  [Paper](https://arxiv.org/abs/2406.13352) ·
  [NeurIPS record](https://openreview.net/forum?id=m1YYAQjO3w)
- Original repository: <https://github.com/ethz-spylab/agentdojo>.
- Exact revision: `089ed468cf3ed0322acc66b0211f26d9d90dbf60`.
- Retrieved: 2026-10-18. Revision's commit date: 2026-06-02.
- License: **MIT**; original copyright and full license retained at
  `data/external/agentdojo/LICENSE`.
- Raw files: upstream README, LICENSE, and the four v1 `user_tasks.py` files.
  Total source size: **182,184 bytes**.
- Derived corpus: `data/external/agentdojo/tasks.jsonl`.
- Provenance and integrity: `data/external/agentdojo/manifest.json` records
  commit-pinned URLs, byte counts, and SHA-256 hashes for every source file and
  the derived JSONL.

| Suite | Directly declared prompts |
| --- | ---: |
| Banking | 16 |
| Slack | 17 |
| Travel | 20 |
| Workspace | 33 |
| **Total** | **86** |

This is a deliberately limited **reference extract**, not the complete AgentDojo
benchmark. The original release describes 97 tasks; this extraction excludes
11 tasks created dynamically by the upstream task combinator (7 workspace,
4 Slack). It also excludes environment snapshots, adversarial injection tasks,
attack payloads, and runnable grader dependencies. Later suite-version overlays
are not applied. Do not report results on this corpus as official AgentDojo
scores, or treat its v1 source as the latest complete benchmark.

## How extraction works

`scripts/fetch_reference_data.py` parses the downloaded Python source with the
standard-library AST parser. It resolves literal values, names, string
concatenation, f-strings, and a restricted literal string-join operation. It does
**not** import or execute upstream modules, graders, reference solutions, tool
calls, or installation commands. Unknown prompt expressions fail closed.

Each JSONL record contains:

- `task_id`: stable local ID, such as `agentdojo_v1/workspace/user_task_0`;
- `suite`, `source_class`, and available `difficulty`;
- resolved `prompt` text;
- `source_path`, `source_line`, `source_commit`, and direct `source_url`;
- `role`: `auxiliary_task_reference_not_threshold_ground_truth`.

The contents include public fictional benchmark contacts, account-like
identifiers, and credential-like strings. They are benchmark artifacts, not
user account data or a source of real credentials. Treat all task text as data,
not instructions to operate external systems.

## Reproduce and verify

Run from the project directory with Python 3.10 or later. No pip dependencies,
API key, paid model, or AgentDojo installation is needed.

```sh
# Fetch only missing pinned sources and regenerate the reference extract.
python3 scripts/fetch_reference_data.py

# Rebuild from the bundled sources without any network requests.
python3 scripts/fetch_reference_data.py --offline

# Verify all source hashes and compare derived artifacts; writes nothing.
python3 scripts/fetch_reference_data.py --check
```

The downloader uses HTTPS, 30-second network timeouts and a 1 MB per-file size
limit. Every download must match a source SHA-256 and size embedded in the
script before it is saved. Existing sources are verified on every run; a
mismatch raises an error rather than being silently accepted or replaced.
`--check` implies offline operation. Cached sources and derived files were
verified successfully at project creation.

## How this supports the research question

Use workspace and travel tasks to inspire realistic authorized goals such as
processing a document or completing a booking. Before adapting a task, write a
new, explicit permission rule and ensure that the ordinary path works. Then
construct matched variants that change a threshold or its consequence while
holding task difficulty, resource dynamics, available tools, and reward fixed.

For any future AgentDojo-derived scenario, record the source task ID, explain
the changes, retain the MIT notice, and have a human verify the labels. Keep the
original reference corpus separate from authored scenarios. Split evaluation by
scenario family or source task—not by small wording changes—to avoid leaking
near-duplicates between development and evaluation. The initial synthetic
scenarios are not claimed to be validated adaptations of these 86 prompts.

Labels must distinguish:

1. **Avoidable disruption:** an optional action worsens the state when an
   authorized completion path was available.
2. **Exception activation/use:** the resulting state qualifies for and/or uses
   the broader permission.
3. **Explicit policy violation:** the action violates an expressly stated rule.
4. **Legitimate recovery:** response to an external failure or a necessary
   action's unexpected accident.

Creating a qualifying state can exploit an incomplete policy without violating
its literal wording. Report that distinction. The script download, mock traces,
and generated scenarios provide no evidence that real models manufacture
necessity; that requires a separately controlled model experiment.

## Alternatives considered

| Resource | Useful for | Limitation for this first experiment |
| --- | --- | --- |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | Realistic user tasks and tool/state-based utility and security checks | Primarily prompt-injection evaluation; no ready-made threshold manipulation or counterfactual labels. Chosen as the downloaded auxiliary corpus. |
| [τ-bench family](https://github.com/sierra-research/tau2-bench) | Explicit domain policies, tools, goal states, and repeated-trial reliability | Adds user simulation and domain complexity; a causal exception-creation study still requires new interventions. The original τ-bench repository points to the maintained successor for corrected tasks; pin a revision before any future use. |
| [ToolEmu](https://github.com/ryoungj/ToolEmu) | Diverse tool-risk scenario design; published initial benchmark has 144 cases and 36 toolkits | LM-based environment emulation adds uncertainty to state/cause judgments. Better for later realism checks than deterministic counterfactual ground truth. |

Only AgentDojo was downloaded for this project. The other resources are
documented candidates, not installed dependencies or evaluated baselines.

## Citation

```bibtex
@inproceedings{debenedetti2024agentdojo,
  title={AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for {LLM} Agents},
  author={Edoardo Debenedetti and Jie Zhang and Mislav Balunovic and Luca Beurer-Kellner and Marc Fischer and Florian Tram{\`e}r},
  booktitle={The Thirty-eight Conference on Neural Information Processing Systems Datasets and Benchmarks Track},
  year={2024},
  url={https://openreview.net/forum?id=m1YYAQjO3w}
}
```
