"""Local in-process adapters for real (non-stub) runtime dependencies."""

from app.adapters.local.exec import LocalAsyncExecAdapter

__all__ = ["LocalAsyncExecAdapter"]
