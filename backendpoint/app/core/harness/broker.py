"""Tool Broker: the only side-effect execution boundary (Spec 3.6).

The broker checks tool registration, a PDP allow decision, capability binding,
and replay consumption before invoking a registered handler. Handlers receive
the validated intent; the Evidence Ledger records only an output digest, while
the authorized caller additionally receives the handler's sanitized output to
build its API response.

Read-only and operations tools follow P-33: no execution capability, but PDP,
permission and replay checks still apply where required.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from app.core.harness.capability import CapabilityService
from app.core.harness.errors import HarnessError
from app.core.harness.models import (
    DIGEST_RE,
    ENVIRONMENTS,
    ToolHandler,
    ToolSpec,
    assert_no_secret_material,
    require_nonempty,
    require_tool_name,
    tool_specs,
)
from app.core.harness.pdp import PolicyDecisionPoint
from app.core.harness.replay import ReplayGuard
from app.core.masking import contains_secret_material
from app.core.utils import digest_of


class ToolDependencyError(Exception):
    """A registered tool's downstream dependency failed."""


class ToolUnavailableError(Exception):
    """A registered tool has no usable adapter."""


class ToolBroker:
    def __init__(
        self,
        *,
        capability: CapabilityService | None,
        replay: ReplayGuard,
        pdp: PolicyDecisionPoint | None = None,
        specs: dict[str, ToolSpec] | None = None,
    ) -> None:
        self._capability = capability
        self._replay = replay
        self._pdp = pdp
        self._specs = dict(specs or tool_specs())
        self._handlers: dict[str, ToolHandler] = {}

    def register_handler(self, tool: str, handler: ToolHandler) -> None:
        tool = require_tool_name(tool)
        if tool not in self._specs:
            raise ValueError(f"tool is not registered: {tool}")
        self._handlers[tool] = handler

    def registered_handlers(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def tool_spec(self, tool: str) -> ToolSpec | None:
        return self._specs.get(tool)

    async def execute(
        self,
        intent: dict[str, Any],
        *,
        policy_decision: dict[str, Any] | None,
        capability_token: str | None = None,
        idempotency_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        if not isinstance(intent, dict):
            raise HarnessError(400, "TB-400", "tool intent must be an object")
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
                raise ValueError("resource_scope is required")
            assert_no_secret_material(intent)
        except ValueError as exc:
            raise HarnessError(400, "TB-400", str(exc)) from None

        spec = self._specs.get(tool)
        if spec is None:
            raise HarnessError(400, "TB-400", "tool is not registered")

        self._require_policy_allow(
            policy_decision,
            intent=intent,
            tool=tool,
            actor_id=actor_id,
            project_id=project_id,
        )
        if tool not in self._handlers:
            raise HarnessError(503, "TB-503", "tool adapter is unavailable")

        if spec.requires_capability:
            if self._capability is None:
                raise HarnessError(503, "TB-503", "capability verifier is unavailable")
            if not capability_token:
                raise HarnessError(
                    403,
                    "TB-403",
                    "execution tool requires a capability",
                    {"reason": "CAPABILITY_REQUIRED"},
                )
            expected = self._expected_claims(intent, tool, actor_id, project_id, environment)
            verified = self._capability.verify(capability_token, expected)
            jti = verified["jti"]
            token_digest = verified["token_digest"]
            replay_key = f"capability:{jti}:{token_digest}"
            replay_scope = f"{tool}:{actor_id}:{project_id}:{environment}"
            await self._replay.reserve(replay_key, replay_scope)
            await self._replay.consume(replay_key)
            self._capability.consume(jti, token_digest)
        else:
            if spec.replay_required:
                try:
                    idempotency_key = require_nonempty(
                        idempotency_key or intent.get("idempotency_key"),
                        "idempotency_key",
                    )
                except ValueError as exc:
                    raise HarnessError(422, "RG-422", str(exc)) from None
                replay_key = f"{tool}:{actor_id}:{idempotency_key}"
                await self._replay.reserve(replay_key, replay_key)
                await self._replay.consume(replay_key)

        return await self._invoke(intent, tool, timeout_seconds)

    async def _invoke(
        self, intent: dict[str, Any], tool: str, timeout_seconds: float | None
    ) -> dict[str, Any]:
        handler = self._handlers[tool]
        try:
            if timeout_seconds is None:
                output = await handler(deepcopy(intent))
            else:
                output = await asyncio.wait_for(handler(deepcopy(intent)), timeout_seconds)
        except asyncio.TimeoutError:
            # A timeout may occur after the side effect. Do not report it as a
            # clean failure or retry automatically.
            return self._result(intent, tool, "UNKNOWN", "TB-504", None)
        except ToolDependencyError:
            return self._result(intent, tool, "FAILED", "TB-424", None)
        except ToolUnavailableError:
            raise HarnessError(503, "TB-503", "tool adapter is unavailable") from None
        except HarnessError:
            raise
        except Exception:
            # The side effect may or may not have happened. Never retry
            # automatically; surface UNKNOWN with a stable domain code.
            return self._result(intent, tool, "UNKNOWN", "TB-424", None)

        if not isinstance(output, dict):
            return self._result(intent, tool, "UNKNOWN", "TB-424", None)
        external_ref = output.get("external_ref")
        if external_ref is not None and (
            not isinstance(external_ref, str) or contains_secret_material(external_ref)
        ):
            external_ref = None
        return self._result(
            intent,
            tool,
            "SUCCEEDED",
            "",
            digest_of(output),
            external_ref=external_ref,
            output=output,
        )

    def _require_policy_allow(
        self,
        policy_decision: dict[str, Any] | None,
        *,
        intent: dict[str, Any],
        tool: str,
        actor_id: str,
        project_id: str,
    ) -> None:
        if self._pdp is None:
            raise HarnessError(503, "TB-503", "policy verifier is unavailable")
        if not isinstance(policy_decision, dict):
            raise HarnessError(403, "TB-403", "policy decision is required")
        decision_digest = policy_decision.get("decision_digest")
        if not isinstance(decision_digest, str) or not decision_digest:
            raise HarnessError(403, "TB-403", "policy decision digest is required")

        # Never trust a caller-supplied decision object. Resolve the digest
        # against the PDP's recorded decision and compare the binding fields.
        stored = self._pdp.get_decision(decision_digest)
        if stored is None:
            raise HarnessError(403, "TB-403", "policy decision is not registered")
        if stored.get("decision") != "ALLOW":
            raise HarnessError(403, "TB-403", "policy denied the tool call")
        if (
            stored.get("tool") != tool
            or stored.get("actor_id") != actor_id
            or stored.get("project_id") != project_id
            or stored.get("environment")
            != (intent.get("environment") or intent.get("env"))
            or stored.get("resource_scope") != intent.get("resource_scope")
            or stored.get("artifact_digest") != intent.get("artifact_digest")
            or stored.get("intent_digest") != digest_of(intent)
        ):
            raise HarnessError(403, "TB-403", "policy decision does not match the tool call")

    @staticmethod
    def _expected_claims(
        intent: dict[str, Any],
        tool: str,
        actor_id: str,
        project_id: str,
        environment: str,
    ) -> dict[str, Any]:
        try:
            preparation_id = require_nonempty(intent.get("preparation_id"), "preparation_id")
            execution_run_id = require_nonempty(
                intent.get("execution_run_id"), "execution_run_id"
            )
            artifact_digest = intent.get("artifact_digest")
            if not isinstance(artifact_digest, str) or not DIGEST_RE.fullmatch(
                artifact_digest
            ):
                raise ValueError("artifact_digest must be a 64-character lowercase SHA256")
        except ValueError as exc:
            raise HarnessError(400, "TB-400", str(exc)) from None
        return {
            "sub": actor_id,
            "project_id": project_id,
            "environment": environment,
            "tool": tool,
            "resource_scope": deepcopy(intent["resource_scope"]),
            "artifact_digest": artifact_digest,
            "preparation_id": preparation_id,
            "execution_run_id": execution_run_id,
        }

    @staticmethod
    def _result(
        intent: dict[str, Any],
        tool: str,
        status: str,
        domain_code: str,
        output_digest: str | None,
        *,
        external_ref: str | None = None,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": intent.get("request_id"),
            "tool": tool,
            "status": status,
            "domain_code": domain_code,
            "output_digest": output_digest,
            "output": output,
            "external_ref": external_ref,
            "audit_event_id": None,
        }
