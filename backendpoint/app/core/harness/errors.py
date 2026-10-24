"""Internal Harness errors.

These codes are defined by Spec 3.4-3.9 and contract 4.2. They are internal:
the API layer must map them to a public domain code before returning a
response. Messages and details must never contain capability material or
secret values.
"""

from __future__ import annotations

from typing import Any


class HarnessError(Exception):
    """A fail-closed Harness rejection with a Spec error code."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "error_code": self.error_code,
            "message": self.message,
            "details": dict(self.details),
        }
