"""Illustrative synthetic results; arbitrary mixtures, no AI model evaluation.

Run with PYTHONPATH=src. Every reported number is computed from a scripted
simulator rollout. Mixture probabilities are invented assumptions, not estimates.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from random import Random

from permission_thresholds.actors import ScriptedActor
from permission_thresholds.analysis import summarize, render_markdown
from permission_thresholds.runner import canonical, digest, run_episode
from permission_thresholds.scenarios import generate_scenarios, make_conditions


PROFILES = {
    "illustrative_mixture_A": {"honest": 0.65, "threshold_seeking": 0.30, "threshold_blind": 0.05},
    "illustrative_mixture_B": {"honest": 0.90, "threshold_seeking": 0.05, "threshold_blind": 0.05},
}
NOTICE = (
    "ILLUSTRATIVE SYNTHETIC RESULTS ONLY. Behavior probabilities are arbitrary "
    "assumptions selected for demonstration. No real model, safety intervention, "
    "or empirical research hypothesis was evaluated. Differences between mixtures "
    "are designed into the generator and do not establish a safety improvement."
)


def main():
    parser = argparse.ArgumentParser(description=NOTICE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=False)
    rng = Random(args.seed)
    scenarios = generate_scenarios()
    rows = []
    manifest = {
        "notice": NOTICE, "results_are_synthetic": True,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed, "repeats_per_case": args.repeats,
        "profiles": PROFILES, "scenario_sha256": digest(scenarios),
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((Path(__file__).resolve().parents[1] / "src/permission_thresholds").glob("*.py"))},
        "sampling": "Independent categorical scripted-behavior draw per episode; shuffled case schedule.",
        "model_calls": 0,
    }
    manifest["run_id"] = "illustrative-" + digest(manifest)[:16]
    output = args.out_dir / "SYNTHETIC_episodes.jsonl"
    with output.open("x", encoding="utf-8") as stream:
        for profile, weights in PROFILES.items():
            cases = [(s, c, r) for s in scenarios for c in make_conditions(s) for r in range(args.repeats)]
            rng.shuffle(cases)
            for scenario, condition, repeat in cases:
                chosen = rng.choices(list(weights), weights=list(weights.values()), k=1)[0]
                row = run_episode(
                    scenario, condition, ScriptedActor(chosen, condition),
                    run_id=manifest["run_id"], repeat=repeat, backend="scripted",
                    actor_name=profile, model="NO_MODEL_SCRIPTED_SIMULATION", synthetic=True,
                )
                row["simulation_assumptions"] = {"notice": NOTICE, "probabilities": weights,
                                                  "sampled_scripted_behavior": chosen}
                stream.write(canonical(row) + "\n")
                rows.append(row)
    summary = summarize(rows, bootstrap_samples=0)
    summary["illustration_notice"] = NOTICE
    summary["invented_probability_assumptions"] = PROFILES
    expected = len(PROFILES) * len(scenarios) * 5 * args.repeats
    assert len(rows) == expected and all(r["results_are_synthetic"] for r in rows)
    assert all(r["metrics"]["task_success"] for r in rows)
    assert summary["evidence_status"] == "synthetic_only"
    manifest["episode_count"] = len(rows)
    manifest["episode_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    for name, value in (("SYNTHETIC_manifest.json", manifest), ("SYNTHETIC_summary.json", summary)):
        (args.out_dir / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "SYNTHETIC_summary.md").write_text(
        "# Illustrative synthetic run — not AI model findings\n\n" + NOTICE +
        "\n\nInvented behavior probabilities:\n\n" +
        "| Mixture | Rule-following | Threshold-seeking | Threshold-blind |\n" +
        "| --- | ---: | ---: | ---: |\n" +
        "\n".join(f"| {n} | {w['honest']:.0%} | {w['threshold_seeking']:.0%} | {w['threshold_blind']:.0%} |"
                  for n, w in PROFILES.items()) +
        "\n\nNo confidence intervals or significance claims are supplied for this illustration.\n\n" +
        render_markdown(summary), encoding="utf-8",
    )
    compact = []
    for profile in PROFILES:
        selected = [r for r in rows if r["actor"] == profile]
        conditional = [r for r in selected if r["condition"]["policy_mode"] == "conditional"]
        controls = [r for r in selected if r["condition"]["policy_mode"] != "conditional"]
        count = lambda records, key: sum(r["metrics"][key] for r in records)
        compact.append({
            "profile": profile, "episodes": len(selected),
            "completed": count(selected, "task_success"),
            "conditional_disruption": [count(conditional, "avoidable_disruption"), len(conditional)],
            "control_disruption": [count(controls, "avoidable_disruption"), len(controls)],
            "exception_used_after_creation": [count(conditional, "exception_used_after_creation"), len(conditional)],
            "tracking_slope": next(g["threshold_tracking"]["mean_slope"] for g in summary["groups"] if g["actor"] == profile),
        })
    print(json.dumps({"notice": NOTICE, "results": compact, "output": str(args.out_dir)}, indent=2))


if __name__ == "__main__":
    main()
