"""Post hoc, scripted requirement-coverage diagnostic over saved broker evidence.

This does not rerun actors, execute fallback calls, alter collected results, or
estimate a live defense effect. It checks a veto-only gate at historical evidence
boundaries and reports hypothetical decision changes separately.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from permission_thresholds.requirement_coverage import (
    VERSION, RequirementCoverageGate, compose_outcome, load_evidence,
)


PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT / "runs/guard-policy-comparison"
NOTES = [
    "Post hoc scripted diagnostic of a new requirement-coverage gate; not a live intervention or model result, and not a novelty claim.",
    "No network, model calls, new broker execution, or changes to frozen study artifacts.",
    "Gate decisions use only immutable task requirements and trusted trace evidence available before the selected event boundary.",
    "The extra gate is veto-only: PROCEED does not grant authority, and existing DENY/DEFER decisions remain unchanged.",
    "A declared but unregistered repair requirement defers exceptional access even after repair, pending a trusted coverage correction or new job.",
    "A registered requirement proceeds only with exact broker release/count evidence of successful repair, or no initial background load.",
    "Saved repair_registered is the frozen broker configuration field, not a signed proof of arbitrary runtime enforcement.",
    "Checksums establish integrity relative to the trusted input manifest; they cannot authenticate a compromised runtime or attacker-controlled trust root.",
    "Repairs absent from the task manifest are not discovered. Unknown requirements, new scheduler events, and incomplete evidence require separate resolution.",
    "Reference-end checks concern a hypothetical later exceptional request; they do not alter historical completion or block local finish.",
    "Counterfactual suppression counts describe saved scripted requests only; changed future agent behavior, safety rates, and completion utility are unmeasured.",
]


def digest_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def checked_episode(input_dir, row):
    directory = (input_dir / row["evidence_directory"]).resolve()
    if not directory.is_relative_to(input_dir):
        raise ValueError("Evidence path escapes input directory")
    hashes = row["evidence_sha256"]
    for name in ("broker_manifest.json", "broker_trace.jsonl"):
        if digest_file(directory / name) != hashes[name]:
            raise ValueError("Episode evidence hash mismatch")
    manifest = json.loads((directory / "broker_manifest.json").read_text())
    if manifest["case"]["id"] != row["case_id"] or manifest["baseline"] != row["baseline"]:
        raise ValueError("Episode identity mismatch")
    return directory, manifest, hashes


def diagnose(input_dir, out_dir):
    input_dir, out_dir = Path(input_dir).resolve(), Path(out_dir).resolve()
    original = json.loads((input_dir / "manifest.json").read_text())
    if original.get("status") != "completed" or original.get("model_calls") != 0:
        raise ValueError("Expected a completed scripted policy-comparison run")
    for name in ("probes.jsonl", "references.jsonl", "cases.jsonl"):
        if digest_file(input_dir / name) != original["output_sha256"][name]:
            raise ValueError("Input comparison output hash mismatch")
    out_dir.mkdir(parents=True, exist_ok=False)
    snapshots = out_dir / "source_snapshot"
    snapshots.mkdir()
    source_paths = {"diagnose_requirement_coverage.py": Path(__file__).resolve(),
                    "requirement_coverage.py": PROJECT / "src/permission_thresholds/requirement_coverage.py"}
    source_hashes = {name: digest_file(path) for name, path in source_paths.items()}
    for name, path in source_paths.items():
        shutil.copyfile(path, snapshots / name)
    manifest = {"version": VERSION, "status": "running", "created_utc": datetime.now(timezone.utc).isoformat(),
                "analysis_kind": "posthoc_scripted_requirement_coverage_diagnostic", "model_calls": 0,
                "input_directory": str(input_dir), "input_manifest_sha256": digest_file(input_dir / "manifest.json"),
                "input_output_sha256": {name: original["output_sha256"][name] for name in
                                        ("probes.jsonl", "references.jsonl", "cases.jsonl")},
                "source_sha256": source_hashes, "analysis_notes": NOTES}
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    rows = []
    try:
        with (out_dir / "diagnostics.jsonl").open("x") as stream:
            for input_name, kind in (("probes.jsonl", "historical_exception_request"),
                                     ("references.jsonl", "hypothetical_exception_after_reference")):
                for line in (input_dir / input_name).read_text().splitlines():
                    prior = json.loads(line)
                    directory, episode_manifest, hashes = checked_episode(input_dir, prior)
                    events = [json.loads(line) for line in (directory / "broker_trace.jsonl").read_text().splitlines()]
                    cutoff = (next(event["sequence"] for event in events if event["kind"] == "authorization_decision")
                              if kind == "historical_exception_request" else len(events) + 1)
                    requirements, evidence = load_evidence(directory / "broker_manifest.json", directory / "broker_trace.jsonl",
                                                           expected_manifest_sha256=hashes["broker_manifest.json"],
                                                           expected_trace_sha256=hashes["broker_trace.jsonl"],
                                                           before_sequence=cutoff)
                    coverage = RequirementCoverageGate(requirements).check(evidence)
                    row = {"case_id": prior["case_id"], "baseline": prior["baseline"], "check_scope": kind,
                           "probe": prior.get("probe"), "source_evidence_directory": prior["evidence_directory"],
                           "source_evidence_sha256": {name: hashes[name] for name in
                                                      ("broker_manifest.json", "broker_trace.jsonl")},
                           "repair_required": requirements.repair_required,
                           "repair_registered_configuration": episode_manifest["case"].get("repair_registered"),
                           "gate": asdict(coverage), "evidence": asdict(evidence)}
                    if kind == "historical_exception_request":
                        existing = prior["outcome"]
                        composed = compose_outcome(existing, coverage)
                        row.update({"historical_outcome": existing, "posthoc_composed_outcome": composed,
                                    "would_suppress_prior_allowed_request": existing == "ALLOW" and composed == "DEFER",
                                    "historical_strict_oracle_violations": prior["metrics"]["strict_oracle_violations"],
                                    "remaining_strict_violations_if_vetoed": prior["metrics"]["strict_oracle_violations"]
                                                                             if composed == "ALLOW" else 0})
                    else:
                        row["historical_reference_task_success"] = prior["metrics"]["task_success"]
                    rows.append(row)
                    stream.write(canonical(row) + "\n")
        probes = [row for row in rows if row["check_scope"] == "historical_exception_request"]
        refs = [row for row in rows if row["check_scope"] == "hypothetical_exception_after_reference"]
        by_baseline = {}
        for baseline in sorted({row["baseline"] for row in probes}):
            selected = [row for row in probes if row["baseline"] == baseline]
            by_baseline[baseline] = {"requests": len(selected),
                                     "historical_outcomes": dict(Counter(row["historical_outcome"] for row in selected)),
                                     "posthoc_composed_outcomes": dict(Counter(row["posthoc_composed_outcome"] for row in selected)),
                                     "would_suppress_prior_allowed_requests": sum(row["would_suppress_prior_allowed_request"] for row in selected),
                                     "historical_strict_oracle_violations": sum(row["historical_strict_oracle_violations"] for row in selected),
                                     "remaining_strict_violations_if_vetoed": sum(row["remaining_strict_violations_if_vetoed"] for row in selected)}
        summary = {"version": VERSION, "analysis_kind": manifest["analysis_kind"], "model_calls": 0,
                   "historical_requests_checked": len(probes), "reference_end_states_checked": len(refs),
                   "request_gate_codes": dict(Counter(row["gate"]["code"] for row in probes)),
                   "reference_gate_codes": dict(Counter(row["gate"]["code"] for row in refs)),
                   "registered_completed_reference_checks_proceed": sum(row["repair_required"] is True
                        and row["repair_registered_configuration"] is True and row["gate"]["outcome"] == "PROCEED" for row in refs),
                   "no_repair_required_request_checks_proceed": sum(row["repair_required"] is False
                        and row["gate"]["outcome"] == "PROCEED" for row in probes),
                   "by_baseline": by_baseline, "analysis_notes": NOTES}
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if any(digest_file(path) != source_hashes[name] for name, path in source_paths.items()):
            raise RuntimeError("Diagnostic source changed during execution")
        manifest["status"] = "completed"
        manifest["output_sha256"] = {name: digest_file(out_dir / name) for name in ("diagnostics.jsonl", "summary.json")}
    except BaseException as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(diagnose(arguments.input_dir, arguments.out_dir), indent=2))


if __name__ == "__main__":
    main()
