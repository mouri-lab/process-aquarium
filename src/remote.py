"""Asynchronous telemetry client. Never inspects the viewer's local host."""

import math
from threading import Event, Lock, Thread
import time
from urllib.parse import urlencode

from .core.source import IProcessSource, SourceStatus
from .telemetry import ProtocolError, snapshot_from_dict
from .transport import APIClient, RemoteError


class RemoteProcessSource(IProcessSource):
    name = "remote"

    def __init__(self, client: APIClient, *, host_id=None, interval=1.0):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Polling interval must be finite and positive")
        self.client = client
        self.host_id = host_id
        self.interval = interval
        self._lock = Lock()
        self._shutdown = Event()
        self._ready = Event()
        self._thread = None
        self._snapshot = None
        self._stale = True
        self._error = "Waiting for telemetry"
        self._last_success = 0.0

    def update(self):
        if self._thread is None and not self._shutdown.is_set():
            self._thread = Thread(target=self._poll_loop, name="RemoteProcessSource", daemon=True)
            self._thread.start()
        if not self._ready.is_set():
            self._ready.wait(timeout=0.2)

    def poll_once(self):
        try:
            if self.host_id is None:
                response = self.client.request("GET", "/api/v1/hosts")
                hosts = response["hosts"]
                if not isinstance(hosts, list) or not hosts:
                    raise RemoteError("No agents have published yet")
                if len(hosts) != 1:
                    raise RemoteError("Multiple hosts available; choose --host")
                # Pin the selection. An outage must never silently switch hosts.
                self.host_id = hosts[0]["host_id"]
            response = self.client.request("GET", "/api/v1/snapshot?" + urlencode({"host": self.host_id}))
            snapshot = snapshot_from_dict(response["snapshot"])
            if snapshot.host_id != self.host_id or type(response.get("stale")) is not bool:
                raise ProtocolError("Unexpected host or invalid freshness status")
            with self._lock:
                old = self._snapshot
                if old and snapshot.session_id == old.session_id and snapshot.sequence < old.sequence:
                    raise ProtocolError("Server returned an older snapshot")
                self._snapshot = snapshot
                self._stale = response["stale"] or bool(snapshot.error)
                self._error = snapshot.error
                self._last_success = time.monotonic()
            return True
        except (RemoteError, ProtocolError, KeyError, TypeError, IndexError) as exc:
            with self._lock:
                self._stale = True
                self._error = str(exc)
            return False
        finally:
            self._ready.set()

    def _poll_loop(self):
        while not self._shutdown.is_set():
            self.poll_once()
            self._shutdown.wait(self.interval)

    def get_snapshot(self):
        with self._lock:
            return self._snapshot

    @property
    def status(self):
        with self._lock:
            return SourceStatus(
                stale=self._stale or time.monotonic() - self._last_success > max(5.0, self.interval * 3),
                error=self._error,
            )

    def shutdown(self):
        self._shutdown.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.client.timeout + 1)
