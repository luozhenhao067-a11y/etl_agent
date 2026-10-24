"""Masking rules from Spec 12.3 / contract 2.7.

Responses must never contain secrets, capability material, tokens, raw phone
numbers, raw e-mail addresses, full hosts, or JDBC credentials.
"""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "secret_ref",
    "secret_value",
    "token",
    "access_token",
    "refresh_token",
    "capability",
    "capability_token",
    "token_digest",
    "authorization",
    "private_key",
    "jti",
}

_PHONE_RE = re.compile(r"\b(1[3-9]\d)\d{4}(\d{4})\b")
_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_JDBC_CRED_RE = re.compile(r"(://)([^/@:\s]+):([^/@\s]+)@")
_IP_RE = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")
_KEY_VALUE_RE = re.compile(r"(?i)\b(password|passwd|pwd|token|secret)\s*=\s*[^\s,;]+")
_INLINE_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|token)\s*[:=]\s*\S+"
)


def contains_secret_material(value: str) -> bool:
    """Detect obvious credential material before accepting free text."""

    text = str(value)
    return bool(
        _INLINE_SECRET_RE.search(text)
        or _JDBC_CRED_RE.search(text)
        or "-----BEGIN" in text
    )


def mask_phone(value: str) -> str:
    text = str(value)
    if text.startswith("138****") or "****" in text[3:7]:
        return text
    if len(text) < 7:
        return "***"
    return f"{text[:3]}****{text[-4:]}"


def mask_email(value: str) -> str:
    text = str(value)
    at = text.find("@")
    if at <= 0:
        return "***"
    return f"{text[0]}***{text[at:]}"


def mask_host(value: str) -> str:
    text = str(value)
    parts = text.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return f"{parts[0]}.{parts[1]}.*.*"
    if len(text) <= 3:
        return "***"
    return f"{text[:3]}***"


def mask_jdbc_url(value: str) -> str:
    text = str(value)
    text = _JDBC_CRED_RE.sub(r"\1***:***@", text)
    scheme = text.find("://")
    if scheme >= 0:
        rest = text[scheme + 3 :]
        host = rest.split("/", 1)[0]
        if host:
            text = text[: scheme + 3] + mask_host(host) + rest[len(host) :]
    return text


def mask_secret_ref(value: str) -> str:
    text = str(value)
    last = text.rfind("/")
    if last >= 0:
        return f"{text[: last + 1]}***"
    return "***"


def sanitize_log_line(value: str) -> str:
    text = str(value)
    text = _PHONE_RE.sub(lambda m: f"{m.group(1)}****{m.group(2)}", text)
    text = _EMAIL_RE.sub(lambda m: f"{m.group(1)}***{m.group(2)}", text)
    text = _JDBC_CRED_RE.sub(r"\1***:***@", text)
    text = _KEY_VALUE_RE.sub(lambda m: f"{m.group(1)}=***", text)
    text = _IP_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}.*.*", text)
    return text


def _mask_for_key(key: str, value: Any) -> Any:
    lowered = key.lower()
    if value is None:
        return None
    if lowered in _SENSITIVE_KEYS:
        return "***"
    if not isinstance(value, str):
        return value
    if lowered in {"host", "hostname", "host_masked"}:
        return mask_host(value)
    if lowered in {"jdbc_url", "url", "connection_string"}:
        return mask_jdbc_url(value)
    if lowered in {"phone", "mobile", "phone_number"}:
        return mask_phone(value)
    if lowered in {"email", "mail"}:
        return mask_email(value)
    if lowered in {"username", "user"}:
        return mask_secret_ref(value) if "/" in value else (value[:3] + "***" if len(value) > 3 else "***")
    return sanitize_log_line(value)


def mask_structure(value: Any) -> Any:
    """Recursively mask a JSON-like structure by key name and value pattern."""

    if isinstance(value, dict):
        return {key: mask_structure(_mask_for_key(key, item)) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_structure(item) for item in value]
    if isinstance(value, str):
        return sanitize_log_line(value)
    return value


def sanitize_details(details: Any) -> dict[str, Any]:
    """Return a JSON object safe for an error ``details`` field."""

    if not isinstance(details, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in _SENSITIVE_KEYS:
            continue
        if isinstance(value, str):
            cleaned[key] = sanitize_log_line(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            cleaned[key] = value
        elif isinstance(value, (dict, list)):
            cleaned[key] = mask_structure(value)
        else:
            cleaned[key] = "***"
    return cleaned
