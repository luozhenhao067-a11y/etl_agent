"""Policy Decision Point (Spec 3.4).

The PDP is side-effect free. It validates a ToolIntent, applies the configured
provisional policy, and returns a digest-bound decision. An evaluator or policy
failure never falls through to "allow".
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    DEFAULT_POLICY_VERSION,
    ENVIRONMENTS,
    RISK_LEVELS,
    Clock,
    ToolSpec,
    assert_no_secret_material,
    is_digest,
    isoformat,
    require_nonempty,
    require_tool_name,
    tool_specs,
    utcnow,
)
from app.core.utils import digest_of

PolicyEvaluator = Callable[[dict[str, Any], ToolSpec], dict[str, Any]]


class PolicyDecisionPoint:
    def __init__(
        self,
        *,
        specs: dict[str, ToolSpec] | None = None,
        policy_version: str = DEFAULT_POLICY_VERSION,
        clock: Clock = utcnow,
        deny_tools: set[str] | None = None,
        evaluator: PolicyEvaluator | None = None,
    ) -> None:
        self._specs = dict(specs or tool_specs())
        self._policy_version = policy_version
        self._clock = clock
        self._deny_tools = set(deny_tools or ())
        self._evaluator = evaluator
        self._decisions: dict[str, dict[str, Any]] = {}

    @property
    def policy_version(self) -> str:
        return self._policy_version

    def tool_spec(self, tool: str) -> ToolSpec | None:
        return self._specs.get(tool)

    def decide(self, intent: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(intent, dict):
            raise HarnessError(400, "PDP-400", "ToolIntent must be an object")

        try:
            tool = require_tool_name(intent.get("tool"))
            actor_id = require_nonempty(intent.get("actor_id") or intent.get("sub"), "actor_id")
            project_id = require_nonempty(intent.get("project_id"), "project_id")
            environment = require_nonempty(
                intent.get("environment") or intent.get("env"), "environment"
            )
            if environment not in ENVIRONMENTS:
                raise ValueError("environment must be prod, preprod or test")
            resource_scope = intent.get("resource_scope")
            if not isinstance(resource_scope, dict) or not resource_scope:
                raise HarnessError(
                    422,
                    "PDP-422",
                    "resource_scope is required",
                    {"field": "resource_scope"},
                )
            assert_no_secret_material(intent)
        except ValueError as exc:
            raise HarnessError(400, "PDP-400", str(exc)) from None

        spec = self._specs.get(tool)
        if spec is None:
            raise HarnessError(
                400,
                "PDP-400",
                "tool is not registered",
                {"field": "tool"},
            )

        scope_tools = resource_scope.get("tools")
        if scope_tools is not None:
            if not isinstance(scope_tools, list) or tool not in scope_tools:
                # The scope is intentionally free-form except that, when a
                # tool allow-list is supplied, it must contain the tool.
                raise HarnessError(
                    422,
                    "PDP-422",
                    "resource scope does not permit the requested tool",
                    {"field": "resource_scope.tools"},
                )

        artifact_digest = intent.get("artifact_digest")
        if artifact_digest is not None and not is_digest(artifact_digest):
            raise HarnessError(
                400,
                "PDP-400",
                "artifact_digest must be a 64-character lowercase SHA256",
                {"field": "artifact_digest"},
            )
        if spec.requires_capability and not is_digest(artifact_digest):
            raise HarnessError(
                422,
                "PDP-422",
                "artifact_digest is required for execution tools",
                {"field": "artifact_digest"},
            )

        requested_budget = intent.get("requested_budget")
        if requested_budget is not None:
            if not isinstance(requested_budget, dict):
                raise HarnessError(400, "PDP-400", "requested_budget must be an object")
            for key, value in requested_budget.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    raise HarnessError(
                        400,
                        "PDP-400",
                        "requested_budget values must be non-negative numbers",
                        {"field": f"requested_budget.{key}"},
                    )

        data_classification = intent.get("data_classification")
        if data_classification is not None and not isinstance(data_classification, str):
            raise HarnessError(
                400,
                "PDP-400",
                "data_classification must be a string",
                {"field": "data_classification"},
            )

        risk_level = spec.risk_level
        required_slots = list(spec.required_slots)
        constraints: dict[str, Any] = {
            "requires_capability": spec.requires_capability,
            "side_effect": spec.side_effect,
            "replay_required": spec.replay_required,
            "four_eye_minimum": bool(spec.requires_capability),
        }
        decision = "DENY" if tool in self._deny_tools else "ALLOW"

        if self._evaluator is not None:
            try:
                override = self._evaluator(deepcopy(intent), spec)
            except Exception as exc:  # policy engine must fail closed
                raise HarnessError(
                    500,
                    "PDP-500",
                    "policy engine failed",
                    {"reason": type(exc).__name__},
                ) from None
            if not isinstance(override, dict):
                raise HarnessError(500, "PDP-500", "policy engine returned an invalid result")
            if "decision" in override:
                if override["decision"] not in {"ALLOW", "DENY"}:
                    raise HarnessError(500, "PDP-500", "policy engine returned an invalid decision")
                decision = override["decision"]
            if "risk_level" in override:
                if override["risk_level"] not in RISK_LEVELS:
                    raise HarnessError(500, "PDP-500", "policy engine returned an invalid risk level")
                risk_level = override["risk_level"]
            if "required_slots" in override:
                slots = override["required_slots"]
                if not isinstance(slots, list) or not all(
                    isinstance(slot, str) and slot for slot in slots
                ):
                    raise HarnessError(500, "PDP-500", "policy engine returned invalid slots")
                # A policy may add controls, never remove the execution
                # four-eye minimum.
                if spec.requires_capability and len(set(slots)) < 2:
                    raise HarnessError(
                        500, "PDP-500", "policy may not lower the four-eye minimum"
                    )
                required_slots = sorted(set(slots))
            if "constraints" in override:
                if not isinstance(override["constraints"], dict):
                    raise HarnessError(500, "PDP-500", "policy engine returned invalid constraints")
                constraints.update(deepcopy(override["constraints"]))

        # A hard deny and the execution four-eye floor cannot be undone by an
        # evaluator override.
        if tool in self._deny_tools:
            decision = "DENY"
        if spec.requires_capability and len(set(required_slots)) < 2 and decision == "ALLOW":
            raise HarnessError(500, "PDP-500", "policy may not lower the four-eye minimum")
        if spec.requires_capability:
            constraints["four_eye_minimum"] = True

        now = self._clock()
        base = {
            "tool": tool,
            "actor_id": actor_id,
            "project_id": project_id,
            "environment": environment,
            "resource_scope": deepcopy(resource_scope),
            "artifact_digest": artifact_digest,
            "risk_level": risk_level,
            "required_slots": sorted(set(required_slots)),
            "constraints": constraints,
            "policy_version": self._policy_version,
            "decision": decision,
            "state": "EVALUATED" if decision == "ALLOW" else "DENIED",
            "decided_at": isoformat(now),
            "intent_digest": digest_of(intent),
        }
        decision_digest = digest_of(base)
        result = {**base, "decision_digest": decision_digest}
        self._decisions[decision_digest] = deepcopy(result)
        return deepcopy(result)

    def get_decision(self, decision_digest: str) -> dict[str, Any] | None:
        decision = self._decisions.get(decision_digest)
        return deepcopy(decision) if decision is not None else None

    def bind_to_preparation(
        self, decision_digest: str, preparation_id: str
    ) -> dict[str, Any]:
        # This state transition is specified in 3.4 but has no HTTP surface in
        # this delivery. It is kept in the kernel for the Commit flow.
        preparation_id = require_nonempty(preparation_id, "preparation_id")
        decision = self._decisions.get(decision_digest)
        if decision is None:
            raise KeyError(decision_digest)
        if decision["state"] != "EVALUATED":
            raise ValueError("only an evaluated decision can be bound")
        decision = deepcopy(decision)
        decision["state"] = "BOUND_TO_PREPARATION"
        decision["preparation_id"] = preparation_id
        self._decisions[decision_digest] = deepcopy(decision)
        return decision
