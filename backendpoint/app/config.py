"""Runtime settings for the API-layer-only delivery."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """Environment-driven settings.

    Every value that the contract marks as pending is exposed as configuration
    and documented in README.md instead of being treated as a frozen default.
    """

    env: str = "dev"
    default_project_id: str = "prj_demo_001"
    page_size_default: int = 20
    page_size_max: int = 100
    max_file_size_bytes: int = 100 * 1024 * 1024
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    api_title: str = "ETL-Agent Control Plane API"
    api_version: str = "1.0.0"
    storage: str = "memory"  # "memory" | "postgres"
    # HARNESS=kernel wires the real Harness (Spec 3-5) instead of the
    # fail-closed stub; it requires STORAGE=postgres plus DATABASE_URL,
    # REDIS_URL and the Ed25519 signing keys.
    harness: str = "stub"  # "stub" | "kernel"
    # Data environment used in ToolIntents when the API contract carries no
    # environment fact (prepare, file.parse); one of prod, preprod, test.
    data_environment: str = "test"
    # Managed storage for uploaded file assets (API-07). The upload path writes
    # the bytes here; the file.parse tool reads them back by absolute path.
    file_storage_dir: str = "./data/files"

    def __post_init__(self) -> None:
        # The API sends credentials, so a wildcard origin is both unsafe and
        # invalid for browsers. Production must list explicit frontend origins.
        if "*" in self.cors_origins:
            raise ValueError(
                "CORS_ORIGINS must list explicit origins; wildcard '*' is not allowed"
            )
        if self.storage not in ("memory", "postgres"):
            raise ValueError(
                f"STORAGE must be 'memory' or 'postgres'; got {self.storage!r}"
            )
        if self.harness not in ("stub", "kernel"):
            raise ValueError(
                f"HARNESS must be 'stub' or 'kernel'; got {self.harness!r}"
            )
        if self.harness == "kernel" and self.storage != "postgres":
            raise ValueError("HARNESS=kernel requires STORAGE=postgres")
        if self.data_environment not in ("prod", "preprod", "test"):
            raise ValueError(
                "DATA_ENVIRONMENT must be prod, preprod or test; "
                f"got {self.data_environment!r}"
            )

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            env=os.getenv("APP_ENV", "dev"),
            default_project_id=os.getenv("DEFAULT_PROJECT_ID", "prj_demo_001"),
            page_size_default=_env_int("PAGE_SIZE_DEFAULT", 20),
            page_size_max=_env_int("PAGE_SIZE_MAX", 100),
            max_file_size_bytes=_env_int("MAX_FILE_SIZE_BYTES", 100 * 1024 * 1024),
            cors_origins=_env_csv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
            api_title=os.getenv("API_TITLE", "ETL-Agent Control Plane API"),
            api_version=os.getenv("API_VERSION", "1.0.0"),
            storage=os.getenv("STORAGE", "memory").strip().lower(),
            harness=os.getenv("HARNESS", "stub").strip().lower(),
            data_environment=os.getenv("DATA_ENVIRONMENT", "test").strip().lower(),
            file_storage_dir=os.getenv("FILE_STORAGE_DIR", "./data/files").strip() or "./data/files",
        )
