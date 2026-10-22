"""Collect locally and publish complete snapshots, retrying through outages."""

from threading import Event

from .core.source import IProcessSource
from .transport import APIClient, RemoteError


class Agent:
    def __init__(self, source: IProcessSource, client: APIClient, *, interval=0.2):
        self.source = source
        self.client = client
        self.interval = interval
        self._last_revision = None
        self._last_error = None

    def publish_once(self):
        self.source.update()
        snapshot = self.source.get_snapshot()
        if snapshot is None or snapshot.revision == self._last_revision:
            return False
        try:
            self.client.request("POST", "/api/v1/snapshots", snapshot.to_dict())
        except RemoteError as exc:
            if exc.status in (400, 401, 403, 409, 413, 415):
                raise RuntimeError(f"Agent rejected: {exc}") from None
            message = str(exc)
            if message != self._last_error:
                print(f"[agent] {message}; retaining latest state and retrying", flush=True)
                self._last_error = message
            return False
        self._last_revision = snapshot.revision
        self._last_error = None
        print(f"[agent] host={snapshot.host_id} sequence={snapshot.sequence} procs={len(snapshot.processes)}", flush=True)
        return True

    def run(self, stop=None):
        stop = stop if stop is not None else Event()
        while not stop.is_set():
            self.publish_once()
            stop.wait(self.interval)
