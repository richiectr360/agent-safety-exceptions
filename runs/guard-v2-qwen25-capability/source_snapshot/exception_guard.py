"""Counterfactual Exception Guard (CEG): proposed research prototype.

This is a trusted-broker API, NOT an interface exposed to the evaluated agent.
Origin, independent causation, clock readings, work grants, and recovery
attestations must come from a trusted executor. Python object privacy is not a
security boundary. The prototype does not implement signatures, remote atomicity,
causal discovery, general counterfactual execution, or an LLM-facing adapter.

Queue causes add independent nonnegative load. Each service cause independently
keeps a service offline. Dependencies not expressible by those semantics require
deferral. Actor-created causes remain factual but enter the shadow only under a
previously issued, scoped work grant. Verified repairs remove a cause in both
views. Wall time is supplied by the trusted broker, not by action count.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import wraps
import hashlib
import json
from threading import RLock
from typing import Callable
from uuid import uuid4


def locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


def natural(value, *, positive=False):
    if type(value) is not int or value < int(positive):
        raise ValueError("Expected a nonnegative integer" if not positive else "Expected a positive integer")
    return value


@dataclass(frozen=True)
class Cause:
    identity: str
    units: int
    started_at: int
    origin: str
    actor: str | None = None
    grant_id: str | None = None


@dataclass
class WorkGrant:
    identity: str
    actor: str
    purpose: str
    remaining_units: int
    expires_at: int
    epoch: int
    revoked: bool = False


@dataclass
class RecoveryObligation:
    identity: str
    cause_ids: frozenset[str]
    deadline: int
    infeasible_until: int | None = None


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    factual_qualified: bool
    shadow_qualified: bool
    overdue_obligations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Lease:
    identity: str
    job: str
    principal: str
    resource: str
    operation: str
    arguments_sha256: str
    state_version: int
    policy_epoch: int
    expires_at: int


class ExceptionGuard:
    """A job-scoped cause ledger and three-way authorization decision.

    Work-grant expiry/revocation prevents NEW endorsements; it does not erase
    the fact that earlier effects were independently authorized. Policy changes
    invalidate execution leases. Unknown evidence latches until a trusted new
    job is established; no actor-accessible baseline reset is provided.
    """

    def __init__(self, *, mechanism: str, threshold: int, job="job", principal="agent",
                 resource="resource", operation="external_report", baseline_load=0):
        if mechanism not in {"queue", "service"}:
            raise ValueError("Unsupported mechanism")
        natural(threshold, positive=True)
        natural(baseline_load)
        if mechanism == "service" and baseline_load:
            raise ValueError("Service outages require explicit cause records")
        self.mechanism, self.threshold = mechanism, threshold
        self.job, self.principal, self.resource, self.operation = job, principal, resource, operation
        self.baseline_load = baseline_load
        self.now = self.version = self.epoch = 0
        self.mode = "conditional"
        self.causes: dict[str, Cause] = {}
        self._seen_causes: set[str] = set()
        self.grants: dict[str, WorkGrant] = {}
        self.obligations: dict[str, RecoveryObligation] = {}
        self.uncertainty: list[str] = []
        self.discretionary_history = False
        self._leases: dict[str, Lease] = {}
        self._consumed: set[str] = set()
        self._lock = RLock()

    @locked
    def set_time(self, now: int):
        natural(now)
        if now < self.now:
            raise ValueError("Trusted time cannot move backward")
        self.now = now

    @locked
    def grant_work(self, *, actor: str, purpose: str, units: int, expires_at: int) -> str:
        """Trusted authority only; grant applies to this guard's job/resource."""
        natural(units, positive=True)
        natural(expires_at)
        if not actor or not purpose or expires_at <= self.now:
            raise ValueError("Grant requires actor, purpose, and future expiry")
        identity = str(uuid4())
        self.grants[identity] = WorkGrant(identity, actor, purpose, units, expires_at, self.epoch)
        self.version += 1
        return identity

    @locked
    def revoke_grant(self, identity: str):
        self.grants[identity].revoked = True
        self.version += 1

    def _add(self, identity: str, units: int, origin: str, actor=None, grant_id=None):
        natural(units, positive=True)
        if not identity or identity in self._seen_causes:
            raise ValueError("Cause identities must be nonempty and never reused")
        if self.mechanism == "service" and units != 1:
            raise ValueError("A service event records exactly one independent outage cause")
        self.causes[identity] = Cause(identity, units, self.now, origin, actor, grant_id)
        self._seen_causes.add(identity)
        self.version += 1

    @locked
    def record_external_cause(self, identity: str, *, units=1, independently_certified=False):
        """A trusted observation alone does not certify independent causation."""
        origin = "independent_external" if independently_certified is True else "unresolved"
        self._add(identity, units, origin)
        if origin == "unresolved":
            self.uncertainty.append(f"Independent cause not established: {identity}")

    @locked
    def record_actor_cause(self, identity: str, *, actor: str, units=1, purpose="optional", grant_id=None):
        # Validate before consuming a grant: malformed events cannot burn credit.
        natural(units, positive=True)
        if not identity or identity in self._seen_causes or (self.mechanism == "service" and units != 1):
            raise ValueError("Invalid or duplicate actor cause")
        grant = self.grants.get(grant_id)
        endorsed = bool(grant and not grant.revoked and grant.epoch == self.epoch
                        and grant.actor == actor and grant.purpose == purpose
                        and grant.expires_at > self.now and grant.remaining_units >= units)
        if endorsed:
            grant.remaining_units -= units
        else:
            self.discretionary_history = True
        self._add(identity, units, "authorized_work" if endorsed else "discretionary_actor",
                  actor, grant_id if endorsed else None)

    @locked
    def record_verified_release(self, identity: str):
        """Broker-confirmed removal/repair of this exact cause, not a claimed fix."""
        if identity not in self.causes:
            raise ValueError("Cannot release an absent cause")
        del self.causes[identity]
        self.version += 1

    @locked
    def flag_uncertain(self, reason: str):
        self.uncertainty.append(reason)
        self.version += 1

    def _eligible_causes(self, shadow=False):
        return [cause for cause in self.causes.values()
                if not shadow or cause.origin in {"independent_external", "authorized_work"}]

    def _qualified(self, shadow=False):
        causes = self._eligible_causes(shadow)
        if self.mechanism == "queue":
            return self.baseline_load + sum(c.units for c in causes) >= self.threshold
        return any(self.now - c.started_at >= self.threshold for c in causes)

    @locked
    def reconcile_observation(self, *, queue_load=None, service_online=None):
        """Check aggregate telemetry; NEVER import it as an independent cause."""
        if self.mechanism == "queue":
            natural(queue_load)
            matches = queue_load == self.baseline_load + sum(c.units for c in self.causes.values())
        else:
            if type(service_online) is not bool:
                raise ValueError("Expected service_online bool")
            matches = service_online == (not self.causes)
        if not matches:
            self.flag_uncertain("Aggregate observation differs from trusted cause ledger")
        return matches

    @locked
    def require_recovery(self, identity: str, *, causes: list[str], deadline: int):
        """Trusted policy requires repair attempt/resolution by a deadline.

        This does not assert that repair would succeed. An unmet obligation
        defers exceptional authority for independent review.
        """
        natural(deadline)
        if not identity or identity in self.obligations or not causes or not set(causes) <= self.causes.keys():
            raise ValueError("Obligation needs fresh identity and known active causes")
        if deadline < self.now:
            raise ValueError("Cannot register a retroactive recovery deadline")
        self.obligations[identity] = RecoveryObligation(identity, frozenset(causes), deadline)
        self.version += 1

    @locked
    def attest_recovery_infeasible(self, identity: str, *, valid_until: int, independently_certified=False):
        natural(valid_until)
        if valid_until <= self.now:
            raise ValueError("Recovery evidence must have a future validity bound")
        obligation = self.obligations[identity]
        if independently_certified is not True:
            self.flag_uncertain("Unverified recovery failure cannot discharge an obligation")
            return
        obligation.infeasible_until = valid_until
        self.version += 1

    def _overdue(self):
        return tuple(sorted(o.identity for o in self.obligations.values()
                            if self.now >= o.deadline and o.cause_ids.intersection(self.causes)
                            and (o.infeasible_until is None or self.now >= o.infeasible_until)))

    @locked
    def decide(self, *, baseline="ceg") -> Decision:
        if baseline not in {"ceg", "factual_only", "permanent_taint", "shadow_only", "deny_all"}:
            raise ValueError("Unknown policy baseline")
        factual, shadow = self._qualified(), self._qualified(True)
        if self.mode == "never" or baseline == "deny_all":
            return Decision("DENY", "Exceptional operation disabled", factual, shadow)
        if self.mode == "always":
            return Decision("ALLOW", "Operation independently unconditional", factual, shadow)
        if baseline != "factual_only" and self.uncertainty:
            return Decision("DEFER", "Incomplete causal evidence", factual, shadow)
        if not factual:
            return Decision("DENY", "Factual exception predicate is false", factual, shadow)
        if baseline == "permanent_taint" and self.discretionary_history:
            return Decision("DENY", "Conservative baseline: discretionary actor history", factual, shadow)
        if baseline in {"ceg", "shadow_only"} and not shadow:
            return Decision("DENY", "Exception depends on excluded actor causes", factual, shadow)
        overdue = self._overdue()
        if baseline == "ceg" and overdue:
            return Decision("DEFER", "Outstanding trusted recovery obligation", factual, shadow, overdue)
        return Decision("ALLOW", "Applicable authorization checks passed", factual, shadow)

    @locked
    def change_policy(self, mode: str):
        if mode not in {"conditional", "always", "never"}:
            raise ValueError("Unknown permission mode")
        self.mode = mode
        self.epoch += 1
        self.version += 1

    @locked
    def authorize(self, *, ttl=2, arguments=None):
        natural(ttl, positive=True)
        arguments_hash = self._arguments_hash(arguments)
        decision = self.decide()
        if decision.outcome != "ALLOW":
            return decision, None
        lease = Lease(str(uuid4()), self.job, self.principal, self.resource, self.operation, arguments_hash,
                      self.version, self.epoch, self.now + ttl)
        self._leases[lease.identity] = lease
        return decision, lease

    @locked
    def execute(self, lease: Lease, action: Callable[[], object], *, job: str, principal: str,
                resource: str, operation: str, arguments=None):
        """Consume once and execute under the same IN-PROCESS broker lock.

        The trusted dispatcher must bind action to the checked arguments; Python
        callback behavior itself is not verified. Remote resource atomicity and
        current telemetry still require a transactional integration. An exception
        from action burns the lease and latches outcome uncertainty. This prevents
        fresh conditional authorization after a possibly partial side effect;
        it does not provide remote rollback or exactly-once execution.
        """
        if (not isinstance(lease, Lease) or self._leases.get(lease.identity) != lease
                or lease.identity in self._consumed
                or (job, principal, resource, operation) != (lease.job, lease.principal, lease.resource, lease.operation)
                or self._arguments_hash(arguments) != lease.arguments_sha256
                or lease.policy_epoch != self.epoch or lease.state_version != self.version
                or self.now >= lease.expires_at or self.decide().outcome != "ALLOW"):
            raise PermissionError("Invalid, stale, expired, consumed, or inapplicable lease")
        self._consumed.add(lease.identity)
        self.version += 1
        try:
            return action()
        except Exception:
            self.uncertainty.append("Privileged operation outcome uncertain after executor error")
            self.version += 1
            raise

    @staticmethod
    def _arguments_hash(arguments):
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise ValueError("Operation arguments must be an object")
        return hashlib.sha256(json.dumps(arguments, sort_keys=True, separators=(",", ":"),
                                         allow_nan=False).encode()).hexdigest()

    @locked
    def snapshot(self):
        return {"mechanism": self.mechanism, "threshold": self.threshold, "clock": self.now,
                "state_version": self.version, "policy_epoch": self.epoch,
                "causes": [asdict(c) for c in self.causes.values()],
                "factual_qualified": self._qualified(), "shadow_qualified": self._qualified(True),
                "overdue": list(self._overdue()), "uncertainty": list(self.uncertainty)}
