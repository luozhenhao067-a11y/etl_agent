"""ETL-Agent control-plane API layer.

This package contains only the FastAPI API layer. External dependencies
(Harness, Celery/SeaTunnel, Vault, PostgreSQL, authentication) are represented
by ports and stubs; they are not implemented in this delivery.
"""

__version__ = "1.0.0"
