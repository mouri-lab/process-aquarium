"""Headless aggregation server retaining bounded, complete per-host state."""

from dataclasses import dataclass, field
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlsplit

from .telemetry import MAX_BODY_BYTES, ProtocolError, Snapshot, snapshot_from_bytes


WEB_ROOT = Path(__file__).resolve().parents[1] / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/aquarium.css": ("aquarium.css", "text/css; charset=utf-8"),
    "/app.mjs": ("app.mjs", "text/javascript; charset=utf-8"),
    "/world.mjs": ("world.mjs", "text/javascript; charset=utf-8"),
    "/renderer.mjs": ("renderer.mjs", "text/javascript; charset=utf-8"),
    "/fish.mjs": ("fish.mjs", "text/javascript; charset=utf-8"),
    "/geometry.mjs": ("geometry.mjs", "text/javascript; charset=utf-8"),
    "/effects.mjs": ("effects.mjs", "text/javascript; charset=utf-8"),
}


class ConflictError(ValueError):
    pass


class CapacityError(ValueError):
    pass


@dataclass
class _Host:
    snapshot: Snapshot
    received_at: float
    received_monotonic: float
    retired_sessions: set[str] = field(default_factory=set)


class SnapshotStore:
    def __init__(self, *, stale_after=5.0, retention=3600.0, max_hosts=128,
                 clock=time.monotonic, wall_clock=time.time):
        if (not math.isfinite(stale_after) or not math.isfinite(retention) or
                stale_after <= 0 or retention < stale_after or max_hosts < 1):
            raise ValueError("Require 0 < stale_after <= retention and max_hosts >= 1")
        self.stale_after = stale_after
        self.retention = retention
        self.max_hosts = max_hosts
        self._clock = clock
        self._wall_clock = wall_clock
        self._hosts: dict[str, _Host] = {}
        self._lock = threading.Lock()

    def _expire(self, now):
        for host_id in list(self._hosts):
            if now - self._hosts[host_id].received_monotonic > self.retention:
                del self._hosts[host_id]

    def publish(self, snapshot: Snapshot) -> bool:
        """Accept a new revision; identical retries never refresh freshness."""
        with self._lock:
            now = self._clock()
            self._expire(now)
            previous = self._hosts.get(snapshot.host_id)
            retired = set()
            if previous:
                old = previous.snapshot
                retired = previous.retired_sessions
                if snapshot.session_id == old.session_id:
                    if snapshot.sequence == old.sequence and snapshot == old:
                        return False
                    if snapshot.sequence <= old.sequence:
                        raise ConflictError("Snapshot sequence is not newer")
                    if snapshot.boot_id != old.boot_id:
                        raise ConflictError("Boot identity changed inside one session")
                    if snapshot.events and old.events and snapshot.events[-1].event_id < old.events[-1].event_id:
                        raise ConflictError("Event cursor moved backwards")
                else:
                    if snapshot.session_id in retired:
                        raise ConflictError("Agent session has been superseded")
                    if len(retired) >= 256:
                        raise CapacityError("Session limit reached for this host; wait for retention expiry")
                    retired = retired | {old.session_id}
            elif len(self._hosts) >= self.max_hosts:
                raise CapacityError("Host capacity reached")
            self._hosts[snapshot.host_id] = _Host(snapshot, self._wall_clock(), now, retired)
            return True

    def _status(self, host, now):
        snapshot = host.snapshot
        return {
            "host_id": snapshot.host_id, "hostname": snapshot.hostname,
            "boot_id": snapshot.boot_id, "session_id": snapshot.session_id,
            "sequence": snapshot.sequence, "source": snapshot.source,
            "process_count": len(snapshot.processes), "collected_at": snapshot.collected_at,
            "received_at": host.received_at,
            "stale": bool(snapshot.error) or now - host.received_monotonic > self.stale_after,
            "error": snapshot.error,
        }

    def hosts(self) -> list[dict]:
        with self._lock:
            now = self._clock()
            self._expire(now)
            return [self._status(self._hosts[key], now) for key in sorted(self._hosts)]

    def get(self, host_id: str) -> dict:
        with self._lock:
            now = self._clock()
            self._expire(now)
            host = self._hosts.get(host_id)
            if host is None:
                raise KeyError(host_id)
            return {**self._status(host, now), "snapshot": host.snapshot.to_dict()}


class TelemetryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, *, store=None, token=""):
        self.store = store if store is not None else SnapshotStore()
        self.token = token
        super().__init__(address, TelemetryHandler)


class TelemetryHandler(BaseHTTPRequestHandler):
    server: TelemetryHTTPServer

    def setup(self):
        super().setup()
        self.connection.settimeout(5.0)

    def log_message(self, format, *args):
        # No process command lines or credentials in HTTP access logs.
        pass

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authorized(self):
        expected = self.server.token
        actual = self.headers.get("Authorization", "")
        if expected and not hmac.compare_digest(actual.encode(), f"Bearer {expected}".encode()):
            self._json(401, {"error": "Bearer authentication required"})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path in STATIC_FILES:
            name, content_type = STATIC_FILES[path.path]
            try:
                body = (WEB_ROOT / name).read_bytes()
            except OSError:
                self._json(503, {"error": "Browser assets are missing"})
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if path.path == "/healthz":
            self._json(200, {"status": "ok", "schema_version": 1})
            return
        if not self._authorized():
            return
        if path.path == "/api/v1/hosts":
            self._json(200, {"hosts": self.server.store.hosts()})
        elif path.path == "/api/v1/snapshot":
            hosts = parse_qs(path.query).get("host", [])
            if len(hosts) != 1 or not hosts[0]:
                self._json(400, {"error": "Exactly one host query parameter is required"})
                return
            try:
                self._json(200, self.server.store.get(hosts[0]))
            except KeyError:
                self._json(404, {"error": "Host has not published a snapshot"})
        else:
            self._json(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if not self._authorized():
            return
        if urlsplit(self.path).path != "/api/v1/snapshots":
            self._json(404, {"error": "Unknown endpoint"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        try:
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                raise ValueError
            length = int(lengths[0])
            if length < 0:
                raise ValueError
        except ValueError:
            self._json(411, {"error": "A single Content-Length is required"})
            return
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "Snapshot exceeds 16 MiB"})
            return
        if self.headers.get_content_type() != "application/json":
            self._json(415, {"error": "Content-Type must be application/json"})
            return
        try:
            payload = self.rfile.read(length)
            if len(payload) != length:
                raise ProtocolError("Incomplete request body")
            snapshot = snapshot_from_bytes(payload)
            accepted = self.server.store.publish(snapshot)
        except ProtocolError as exc:
            self._json(400, {"error": str(exc)})
        except ConflictError as exc:
            self._json(409, {"error": str(exc)})
        except CapacityError as exc:
            self._json(503, {"error": str(exc)})
        except (TimeoutError, OSError):
            self._json(408, {"error": "Snapshot upload timed out"})
        else:
            self._json(200, {"accepted": accepted, "sequence": snapshot.sequence})
