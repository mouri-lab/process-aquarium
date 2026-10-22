"""Bounded JSON HTTP transport; no OS monitoring or GUI dependencies."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .telemetry import MAX_BODY_BYTES, ProtocolError, decode_json


class RemoteError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A configured credential must never follow a redirect to another host.
        return None


class APIClient:
    def __init__(self, server: str, *, token: str = "", timeout: float = 5.0):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Request timeout must be finite and positive")
        parsed = urlsplit(server)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Server must be an http(s) URL without credentials, query, or fragment")
        self.server = server.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._opener = build_opener(_NoRedirect())

    def request(self, method: str, path: str, payload=None):
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode("utf-8")
            if len(body) > MAX_BODY_BYTES:
                raise ProtocolError("Request body exceeds 16 MiB")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(self.server + path, data=body, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                return decode_json(response.read(MAX_BODY_BYTES + 1))
        except HTTPError as exc:
            try:
                error = decode_json(exc.read(8192)).get("error", exc.reason)
            except (ProtocolError, AttributeError):
                error = exc.reason
            finally:
                exc.close()
            raise RemoteError(f"HTTP {exc.code}: {error}", exc.code) from None
        except (URLError, OSError) as exc:
            # Do not echo URLs, request headers, or secrets in diagnostics.
            reason = getattr(exc, "reason", exc)
            raise RemoteError(f"Server unavailable: {reason}") from None
