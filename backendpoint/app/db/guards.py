"""Application-level immutability guards (Spec 10.2).

Python-side mirror of the database triggers created by migration 0001 so
violations surface as early, typed exceptions even when the statement never
reaches PostgreSQL:

- ``audit_events`` is append-only: UPDATE and DELETE raise.
- ``pipeline_versions``: once ``is_immutable`` is true the content fields
  (``etl_plan_json``, ``hocon_text``, ``artifact_digest``) are read-only and
  the flag itself can never be unset.
- ``approval_requests`` decisions stay protected by the database trigger
  (``etl_guard_approval_decision``); no ORM listener is added for it here.

The listeners are registered once per process on the ORM mappers, so every
session of every engine is covered. The database triggers remain the outer
line of defence.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import attributes

from app.models.tables import AuditEvent, PipelineVersion

# Spec 10.2: these fields freeze when is_immutable becomes true.
_IMMUTABLE_CONTENT_FIELDS = ("etl_plan_json", "hocon_text", "artifact_digest")


class ImmutableRecordError(RuntimeError):
    """Raised when a write would violate an append-only / immutable rule."""


def _audit_event_before_update(mapper, connection, target) -> None:
    raise ImmutableRecordError(
        "audit_events is append-only: UPDATE is forbidden (Spec 10.2); "
        "append a corrective event instead"
    )


def _audit_event_before_delete(mapper, connection, target) -> None:
    raise ImmutableRecordError(
        "audit_events is append-only: DELETE is forbidden (Spec 10.2)"
    )


def _pipeline_version_before_update(mapper, connection, target) -> None:
    history = attributes.get_history(target, "is_immutable")
    was_immutable = bool(history.deleted[0]) if history.deleted else bool(
        target.is_immutable
    )
    if not was_immutable:
        return

    if history.added and not history.added[0]:
        raise ImmutableRecordError(
            "pipeline_versions.is_immutable cannot be unfrozen (Spec 10.2)"
        )
    for field in _IMMUTABLE_CONTENT_FIELDS:
        if attributes.get_history(target, field).has_changes():
            raise ImmutableRecordError(
                f"pipeline_versions.{field} is read-only once "
                "is_immutable=true (Spec 10.2)"
            )


_registered = False


def register_guards() -> None:
    """Attach the listeners exactly once per process."""

    global _registered
    if _registered:
        return
    event.listen(AuditEvent, "before_update", _audit_event_before_update)
    event.listen(AuditEvent, "before_delete", _audit_event_before_delete)
    event.listen(PipelineVersion, "before_update", _pipeline_version_before_update)
    _registered = True
