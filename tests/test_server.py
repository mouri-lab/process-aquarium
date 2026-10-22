from dataclasses import replace
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from src.server import CapacityError, ConflictError, SnapshotStore, TelemetryHTTPServer
from src.transport import APIClient, RemoteError
from test_telemetry import process, sample


@pytest.fixture
def service():
    server = TelemetryHTTPServer(("127.0.0.1", 0), token="test-secret")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    client = APIClient(f"http://127.0.0.1:{server.server_port}", token="test-secret")
    try:
        yield server, client
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_http_roundtrip_isolates_hosts_and_authenticates(service):
    server, client = service
    with pytest.raises(RemoteError) as exc:
        APIClient(client.server).request("GET", "/api/v1/hosts")
    assert exc.value.status == 401
    for host in ("host-a", "host-b"):
        assert client.request("POST", "/api/v1/snapshots", sample(host_id=host).to_dict())["accepted"]
    assert len(client.request("GET", "/api/v1/hosts")["hosts"]) == 2
    assert client.request("GET", "/api/v1/snapshot?host=host-b")["snapshot"]["host_id"] == "host-b"
    assert client.request("GET", "/healthz")["status"] == "ok"


def test_stale_state_is_retained_and_retries_do_not_refresh_it():
    now = [0.0]
    store = SnapshotStore(stale_after=2, retention=10, clock=lambda: now[0])
    assert store.publish(sample())
    now[0] = 3
    assert not store.publish(sample())
    assert store.get("host-a")["stale"]
    assert store.get("host-a")["snapshot"]["processes"]
    store.publish(sample(sequence=2))
    assert not store.get("host-a")["stale"]
    now[0] = 14
    assert store.hosts() == []


def test_out_of_order_and_superseded_sessions_cannot_replace_current_state():
    store = SnapshotStore()
    store.publish(sample(sequence=2))
    with pytest.raises(ConflictError):
        store.publish(sample(sequence=1))
    store.publish(sample(session_id="new-session"))
    with pytest.raises(ConflictError, match="superseded"):
        store.publish(sample(sequence=3))
    assert store.get("host-a")["session_id"] == "new-session"


def test_host_capacity_and_expiry_are_bounded():
    now = [0]
    store = SnapshotStore(stale_after=1, retention=2, max_hosts=1, clock=lambda: now[0])
    store.publish(sample())
    with pytest.raises(CapacityError):
        store.publish(sample(host_id="other"))
    now[0] = 3
    store.publish(sample(host_id="other"))
    assert len(store.hosts()) == 1


@pytest.mark.parametrize("body", [[], {"schema_version": 99}, {"not": "a snapshot"}])
def test_malformed_http_payload_does_not_change_store(service, body):
    server, client = service
    with pytest.raises(RemoteError) as exc:
        client.request("POST", "/api/v1/snapshots", body)
    assert exc.value.status == 400
    assert server.store.hosts() == []


def test_duplicate_and_conflicting_http_revisions(service):
    _, client = service
    payload = sample(sequence=2).to_dict()
    assert client.request("POST", "/api/v1/snapshots", payload)["accepted"]
    assert not client.request("POST", "/api/v1/snapshots", payload)["accepted"]
    with pytest.raises(RemoteError) as exc:
        client.request("POST", "/api/v1/snapshots", sample(sequence=1).to_dict())
    assert exc.value.status == 409


def test_non_utf8_process_names_survive_http_roundtrip(service):
    _, client = service
    record = replace(process(), name="process-\udcff")
    client.request("POST", "/api/v1/snapshots", sample(processes=[record]).to_dict())
    assert client.request("GET", "/api/v1/snapshot?host=host-a")["snapshot"]["processes"][0]["name"] == record.name
