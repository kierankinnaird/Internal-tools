"""Keeps other web pages from using the person's browser to talk to the app.

The standalone app has no login: it trusts whoever can reach it, which is meant to be only the person at this computer.
But a web page the person has open in another tab can make their browser send requests to http://127.0.0.1:<port>, so
without a check any site could create or delete workpacks. Three small checks close that:

1. Changing requests (POST, PUT, PATCH, DELETE) must come from this app's own pages. The browser says where a request
   came from in the Origin header, or failing that Sec-Fetch-Site or Referer, and anything that is not this app is refused.
   Requests that carry none of those (curl, scripts, the test client) are not browsers, so they are let through.
2. Every request must be addressed to this computer by name (127.0.0.1, localhost or ::1). A hostile site can point its own
   name at 127.0.0.1 ("DNS rebinding") to read pages; its requests still carry its own name, so they are refused.
   To reach the app by another name, set the environment variable NMC_ALLOWED_HOSTS to a comma-separated list of names.
3. Other sites may not put the app in a frame, so a person cannot be tricked into clicking buttons inside it.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional
from urllib.parse import urlsplit

from flask import Flask, abort, request

DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "::1")
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ENV_VAR = "NMC_ALLOWED_HOSTS"


def allowed_hosts(extra: Optional[Iterable[str]] = None) -> set:
    """The names the app may be reached by: this computer, plus any extras and any listed in NMC_ALLOWED_HOSTS."""
    names = set(DEFAULT_ALLOWED_HOSTS) | {h.strip().lower() for h in (extra or []) if h and h.strip()}
    names |= {h.strip().lower() for h in os.environ.get(ENV_VAR, "").split(",") if h.strip()}
    return names


def hostname(host_header: str) -> str:
    """'127.0.0.1:5050' -> '127.0.0.1', '[::1]:5050' -> '::1'. Empty when it cannot be read."""
    try:
        return (urlsplit("//" + (host_header or "")).hostname or "").lower()
    except ValueError:
        return ""


def origin_of(url: str) -> str:
    """'http://localhost:5050/a/b?c' -> 'http://localhost:5050'. Empty when it is not a full address."""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return ""
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else ""


def cross_site_reason() -> Optional[str]:
    """Why the current changing request should be refused, or None when it came from this app (or from no browser)."""
    ours = request.host_url.rstrip("/").lower()
    origin = request.headers.get("Origin")
    if origin is not None:                              # sent by every browser on a POST; "null" is never one of our pages
        return None if origin.strip().lower() == ours else f"The request came from {origin}, not from this app"
    fetch_site = (request.headers.get("Sec-Fetch-Site") or "").lower()
    if fetch_site:
        return None if fetch_site in ("same-origin", "none") else "The request came from another site"
    referer = request.headers.get("Referer")
    if referer:
        return None if origin_of(referer) == ours else "The request came from another site"
    return None


def install(app: Flask, extra_hosts: Optional[Iterable[str]] = None) -> None:
    """Add the checks to an app. Call before any module is mounted."""
    names = allowed_hosts(extra_hosts)
    app.config["ALLOWED_HOSTS"] = sorted(names)

    @app.before_request
    def guard():
        if hostname(request.host) not in names:
            abort(400, "This address is not one the app answers to. Open it at http://127.0.0.1 or http://localhost.")
        if request.method not in SAFE_METHODS:
            reason = cross_site_reason()
            if reason:
                abort(403, f"Blocked for your safety: {reason}. Nothing was changed.")

    @app.after_request
    def no_framing(response):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        return response
