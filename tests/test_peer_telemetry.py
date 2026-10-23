from dataclasses import replace

import pytest

from src.telemetry import PeerNetworkActivity, PeerTraffic, ProtocolError, snapshot_from_dict
from src.server import SnapshotStore
from test_telemetry import sample


def host(name, address, peers=(), **kwargs):
    activity = PeerNetworkActivity("ready", "eth0", "lab", (address,), 1, peers)
    return replace(sample(host_id=name), network_peers=replace(activity, **kwargs))


def test_peer_roundtrip_and_older_agent():
    s = host("a", "10.0.0.1", (PeerTraffic("10.0.0.2", 100, 30),))
    assert snapshot_from_dict(s.to_dict()) == s
    data = sample().to_dict()
    del data["network_peers"]
    assert snapshot_from_dict(data).network_peers is None


@pytest.mark.parametrize("change", [
    {"interval_seconds": 0}, {"interval_seconds": float("inf")}, {"status": "warming"},
    {"source": "psutil"}, {"byte_basis": "payload"}, {"network_scope": ""},
    {"addresses": []}, {"addresses": ["0.0.0.0"]}, {"addresses": ["fe80::1%eth0"]},
    {"addresses": ["::ffff:10.0.0.1", "10.0.0.1"]},
    {"peers": [{"address": "10.0.0.1", "sent_bytes": 1, "received_bytes": 0}]},
    {"peers": [{"address": "10.0.0.2", "sent_bytes": True, "received_bytes": 0}]},
])
def test_malformed_measurements_rejected(change):
    data = host("a", "10.0.0.1").to_dict()
    data["network_peers"].update(change)
    with pytest.raises(ProtocolError):
        snapshot_from_dict(data)


def test_sender_wins_without_summing_reverse_observation():
    store = SnapshotStore()
    store.publish(host("a", "10.0.0.1", (PeerTraffic("10.0.0.2", 100, 35),)))
    store.publish(host("b", "10.0.0.2", (PeerTraffic("10.0.0.1", 30, 110),), interval_seconds=2))
    links = store.network_transfers()
    assert [(p["source"]["host_id"], p["bytes"], p["interval_seconds"]) for p in links] == [
        ("a", 100, 1), ("b", 30, 2)]
    store.publish(replace(host("a", "10.0.0.1"), sequence=2))
    links = store.network_transfers()
    assert len(links) == 1 and links[0]["source"]["host_id"] == "b"


def test_receiver_fallback_requires_live_identified_sender():
    now = [0]
    store = SnapshotStore(clock=lambda: now[0])
    store.publish(host("a", "10.0.0.1", status="denied", interval_seconds=None))
    store.publish(host("b", "10.0.0.2", (PeerTraffic("10.0.0.1", 0, 110),)))
    link, = store.network_transfers()
    assert link["bytes"] == 110 and link["observer"]["host_id"] == "b"
    now[0] = 6
    assert store.network_transfers() == []


def test_ambiguous_external_cross_scope_and_fixture_addresses_never_make_links():
    for change in [dict(network_scope="other"), dict(addresses=("10.0.0.3",))]:
        store = SnapshotStore()
        store.publish(host("a", "10.0.0.1", (PeerTraffic("10.0.0.2", 100, 0),)))
        store.publish(host("b", "10.0.0.2", **change))
        assert store.network_transfers() == []
    store = SnapshotStore()
    store.publish(host("a", "10.0.0.1", (PeerTraffic("10.0.0.2", 100, 0),)))
    store.publish(host("b", "10.0.0.2"))
    store.publish(host("c", "10.0.0.2"))
    assert store.network_transfers() == []
    store = SnapshotStore()
    store.publish(host("a", "10.0.0.1", (PeerTraffic("10.0.0.2", 100, 0),)))
    store.publish(replace(host("b", "10.0.0.2"), source="fixture"))
    assert store.network_transfers() == []


def test_multiple_addresses_of_one_peer_sum_once():
    store = SnapshotStore()
    store.publish(host("a", "10.0.0.1", (PeerTraffic("10.0.0.2", 100, 0), PeerTraffic("fd00::2", 200, 0))))
    store.publish(host("b", "10.0.0.2", addresses=("10.0.0.2", "fd00::2")))
    assert store.network_transfers()[0]["bytes"] == 300
