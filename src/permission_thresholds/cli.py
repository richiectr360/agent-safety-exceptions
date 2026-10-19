"""Command-line workflow for local pilot development and later model evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .analysis import render_markdown, summarize
from .core import Simulator
from .runner import canonical, read_jsonl, run_to_file
from .scenarios import generate_scenarios, make_conditions, validate_scenarios


def load_scenarios(path: Path | None):
    scenarios = read_jsonl(path) if path else generate_scenarios()
    errors = validate_scenarios(scenarios)
    if errors or not scenarios:
        raise ValueError("; ".join(errors) if errors else "scenario list is empty")
    return scenarios


def write_report(inputs: list[Path], out: Path, bootstrap_samples: int = 2000):
    md = out.with_suffix(".md")
    if md == out or out.exists() or md.exists():
        raise FileExistsError("report path must be a new JSON file with an unused .md sibling")
    records = [row for path in inputs for row in read_jsonl(path)]
    summary = summarize(records, bootstrap_samples=bootstrap_samples)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    with md.open("x", encoding="utf-8") as stream:
        stream.write(render_markdown(summary))
    return {"episodes": len(records), "evidence_status": summary["evidence_status"],
            "json_report": str(out), "markdown_report": str(md)}


def build_parser():
    parser = argparse.ArgumentParser(description="Permission-threshold research pilot. Scripted runs are not empirical findings.")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate scenarios and all ordinary authorized routes")
    validate.add_argument("--scenarios", type=Path)
    generate = commands.add_parser("generate", help="Materialize all five policy conditions per scenario")
    generate.add_argument("--scenarios", type=Path)
    generate.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("run", help="Run scripted actors or an explicitly enabled external adapter")
    run.add_argument("--scenarios", type=Path)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--backend", choices=["scripted", "command"], default="scripted")
    run.add_argument("--actor", choices=["honest", "threshold_seeking", "threshold_blind"], default="honest")
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--seed", type=int, default=20261018, help="Seed for shuffling the independent episode schedule")
    run.add_argument("--model", default="scripted")
    run.add_argument("--adapter")
    run.add_argument("--timeout", type=float, default=90)
    run.add_argument("--limit", type=int)
    run.add_argument("--max-output-tokens", type=int, default=512)
    run.add_argument("--allow-live", action="store_true", help="Permit executing the adapter; it may incur provider charges")
    run.add_argument("--adapter-is-synthetic", action="store_true", help="Label a custom mock adapter as synthetic")
    report = commands.add_parser("report", help="Produce JSON and Markdown reports, keeping actors/models separate")
    report.add_argument("--input", nargs="+", type=Path, required=True)
    report.add_argument("--out", type=Path, required=True)
    report.add_argument("--bootstrap-samples", type=int, default=2000)
    demo = commands.add_parser("demo", help="Run three fully offline scripted actors and produce a report")
    demo.add_argument("--out-dir", type=Path, required=True)
    demo.add_argument("--bootstrap-samples", type=int, default=2000)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"validate", "generate", "run"}:
            scenarios = load_scenarios(args.scenarios)
        if args.command == "validate":
            count = 0
            for scenario in scenarios:
                for condition in make_conditions(scenario):
                    env = Simulator(scenario, condition)
                    for _ in range(scenario["local_steps_required"]):
                        env.step({"tool": "local_process", "arguments": {}})
                    env.step({"tool": "finish", "arguments": {}})
                    if not env.metrics()["task_success"]:
                        raise ValueError("reference authorized route failed")
                    count += 1
            print(json.dumps({"valid": True, "scenarios": len(scenarios), "verified_authorized_routes": count,
                              "split": "development", "independent_heldout_domains": False}))
        elif args.command == "generate":
            if args.out.exists():
                raise FileExistsError("output exists; choose a new path")
            args.out.parent.mkdir(parents=True, exist_ok=True)
            count = 0
            with args.out.open("x", encoding="utf-8") as stream:
                for scenario in scenarios:
                    for condition in make_conditions(scenario):
                        stream.write(canonical({"schema_version": 1,
                                                "case_id": scenario["family_id"] + "/" + condition["condition_id"],
                                                "scenario": scenario, "condition": condition,
                                                "role": "development_case_not_model_request"}) + "\n")
                        count += 1
            print(json.dumps({"cases": count, "output": str(args.out)}))
        elif args.command == "run":
            result = run_to_file(scenarios, args.out, backend=args.backend, actor_name=args.actor,
                                 repeats=args.repeats, model=args.model, adapter=args.adapter,
                                 timeout=args.timeout, allow_live=args.allow_live,
                                 adapter_is_synthetic=args.adapter_is_synthetic, limit=args.limit,
                                 max_output_tokens=args.max_output_tokens, seed=args.seed)
            print(json.dumps({"output": str(args.out), "episodes": result["completed_episodes"],
                              "adapter_errors": result["adapter_error_episodes"],
                              "results_are_synthetic": result["results_are_synthetic"]}))
            return 2 if result["adapter_error_episodes"] else 0
        elif args.command == "report":
            print(json.dumps(write_report(args.input, args.out, args.bootstrap_samples)))
        elif args.command == "demo":
            if args.out_dir.exists():
                raise FileExistsError("demo output directory exists; choose a new path")
            args.out_dir.mkdir(parents=True)
            outputs = []
            for name in ("honest", "threshold_seeking", "threshold_blind"):
                out = args.out_dir / (name + ".jsonl")
                run_to_file(generate_scenarios(), out, actor_name=name)
                outputs.append(out)
            print(json.dumps(write_report(outputs, args.out_dir / "summary.json", args.bootstrap_samples)))
        return 0
    except (ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
