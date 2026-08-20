"""Logging utilities — small helpers to keep PII out of log output.

Used wherever we previously logged emails, tokens, or other sensitive
identifiers in cleartext. Keep this module dependency-free so it can be
imported safely from anywhere.
"""
from __future__ import annotations


def redact_email(email: str | None) -> str:
    """Return a privacy-safe form of an email for logs.

    Examples:
        "tauraj@example.com" -> "t***@example.com"
        ""                    -> "***"
        None                  -> "***"
    """
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[:1]}***@{domain}"


def redact_url_query(url: str | None) -> str:
    """Strip the query string from a URL so tokens/secrets in query params
    are not written to logs."""
    if not url:
        return ""
    base, _, _ = url.partition("?")
    return base or "***"
