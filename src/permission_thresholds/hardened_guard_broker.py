"""Post hoc runtime requirement coverage for the local JSON broker boundary.

This wrapper was not used in the frozen model study. The external route still
writes only a local artifact; this is not a remote-service security integration.
Actor JSON actions cannot create evidence or install repair obligations.
"""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from .exception_guard import Decision
from .guard_broker import Broker
from .requirement_coverage import (CoverageDecision, RequirementCoverageGate,
                                   TaskRequirements, compose_outcome, load_evidence)


VERSION = "posthoc-runtime-requirement-coverage-v1"


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class RequirementCoveredBroker(Broker):
    """Compose a veto with any existing baseline, including its execution path.

    Construction and Python internals are trusted. The attacker interface is
    inherited ``step`` with validated JSON tools, not arbitrary Python or SQL.
    Runtime registration must cover exactly the manifest's background causes.
    A missing explicit repair declaration defers exceptional access.
    """

    def __init__(self, directory: Path, case: dict, baseline: str = "ceg"):
        if (Path(directory) / "hardening_manifest.json").exists():
            raise FileExistsError("Hardening evidence directory must be fresh")
        declaration = case.get("repair_required")
        super().__init__(directory, case, baseline)
        self._coverage_manifest = self.manifest
        self._coverage_manifest_bytes = (self.directory / "broker_manifest.json").read_bytes()
        self._coverage_manifest_hash = _hash(self._coverage_manifest_bytes)
        self._coverage_gate = RequirementCoverageGate(TaskRequirements(
            self.manifest.id, self._coverage_manifest_hash,
            declaration if type(declaration) is bool else None))
        self._coverage_initial_causes = frozenset(row[0] for row in self._db.execute(
            "SELECT cause_id FROM jobs WHERE source_kind='external'"))
        document = {"version": VERSION, "post_hoc": True, "frozen_study_defense": False,
                    "baseline": baseline, "broker_manifest_sha256": self._coverage_manifest_hash,
                    "requirements": asdict(self._coverage_gate.requirements),
                    "wrapper_source_sha256": _hash(Path(__file__).read_bytes()),
                    "external_route": "simulated authorization route; local JSON output only"}
        (self.directory / "hardening_manifest.json").write_text(_canonical(document) + "\n")

    def _coverage_check(self):
        """Check a trusted event prefix against current SQL and registration.

        This executes under the same broker lock as dispatch and report writing.
        Hashes bind broker-owned snapshots; they do not authenticate an arbitrary
        file supplied by an actor or a compromised Python process.
        """
        with self._lock:
            evidence = None
            try:
                if (self.manifest != self._coverage_manifest
                        or (self.directory / "broker_manifest.json").read_bytes()
                        != self._coverage_manifest_bytes):
                    raise ValueError("Immutable broker manifest changed")
                trace_bytes = "".join(_canonical(event) + "\n" for event in self.trace).encode()
                with tempfile.TemporaryDirectory(prefix="broker-coverage-") as temporary:
                    manifest_path, trace_path = Path(temporary) / "manifest.json", Path(temporary) / "trace.jsonl"
                    manifest_path.write_bytes(self._coverage_manifest_bytes)
                    trace_path.write_bytes(trace_bytes)
                    _, evidence = load_evidence(
                        manifest_path, trace_path,
                        expected_manifest_sha256=self._coverage_manifest_hash,
                        expected_trace_sha256=_hash(trace_bytes))
                errors = list(evidence.errors)
                if evidence.current_external_units != self._db_counts()["external_units"]:
                    errors.append("Live SQL background count differs from committed repair evidence")
                current_causes = frozenset(row[0] for row in self._db.execute(
                    "SELECT cause_id FROM jobs WHERE source_kind='external'"))
                if current_causes != self._coverage_initial_causes:
                    errors.append("Live background identities differ from initialization")
                obligation = self.guard.obligations.get("required_background_repair")
                registered = (evidence.registered is True
                              and frozenset(self._registered_recovery) == self._coverage_initial_causes
                              and (not self._coverage_initial_causes or (
                                  obligation is not None
                                  and obligation.identity == "required_background_repair"
                                  and obligation.cause_ids == self._coverage_initial_causes
                                  and obligation.deadline == 0
                                  and obligation.infeasible_until is None)))
                evidence = replace(evidence, registered=registered,
                                   errors=tuple(sorted(set(errors))))
                coverage = self._coverage_gate.check(evidence)
            except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
                coverage = CoverageDecision("DEFER", "LIVE_EVIDENCE_ERROR",
                                            "Trusted live evidence could not be verified: " + str(error))
            self._event("requirement_coverage_decision", hardening_version=VERSION,
                        decision=asdict(coverage),
                        evidence_prefix_sha256=evidence.prefix_sha256 if evidence else None,
                        evidence_before_sequence=evidence.before_sequence if evidence else None)
            return coverage

    def _decision(self):
        with self._lock:
            existing = super()._decision()
            coverage = self._coverage_check()
            outcome = compose_outcome(existing.outcome, coverage)
            if outcome == existing.outcome:
                return existing
            return Decision(outcome, coverage.code + ": " + coverage.reason,
                            existing.factual_qualified, existing.shadow_qualified,
                            existing.overdue_obligations)

    def _write_report(self, route):
        with self._lock:
            if route == "local":
                return super()._write_report(route)
            if route != "external_simulated":
                raise ValueError("Unknown report route")
            # Core CEG leases recheck only their own ledger. Recompose at the
            # callback boundary so that a lease cannot skip this extra veto.
            decision = self._decision()
            if decision.outcome != "ALLOW":
                self._event("requirement_coverage_execution_blocked", decision=asdict(decision),
                            hardening_version=VERSION)
                raise RuntimeError("External report failed final requirement/policy recheck: " + decision.reason)
            return super()._write_report(route)
