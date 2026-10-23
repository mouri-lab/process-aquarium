from unittest.mock import Mock

import pytest

from src.core.peer_network import PeerNetworkSampler
from src.telemetry import NetworkActivity, PeerTraffic, snapshot_from_bytes
from src.core.sources import PsutilProcessSource


@pytest.fixture
def sampler(monkeypatch):
    monkeypatch.setattr("src.core.peer_network.sys.platform", "linux")
    now = [0.0]
    counters = {}
    lost = [0]
    backend = Mock()
    backend.read.side_effect = lambda: (dict(counters), lost[0])
    factory = Mock(return_value=backend)
    inventory = Mock(return_value=(2, ("10.0.0.1",)))
    sampler = PeerNetworkSampler(clock=lambda: now[0], backend_factory=factory, inventory=inventory)
    return sampler, now, counters, lost, backend, factory, inventory


ACTIVITY = NetworkActivity("ready", "eth0", 1, 0, 0)


def test_cumulative_deltas_idle_and_new_peers(sampler):
    s, now, counts, _, _, factory, _ = sampler
    assert s.sample(ACTIVITY).status == "warming"
    now[0] = 2
    counts["10.0.0.2", 1] = 120
    counts["fd00::2", 0] = 300
    result = s.sample(ACTIVITY)
    assert result.interval_seconds == 2
    assert result.peers == (PeerTraffic("10.0.0.2", 120, 0), PeerTraffic("fd00::2", 0, 300))
    now[0] = 3
    assert s.sample(ACTIVITY).peers == ()
    factory.assert_called_once_with("eth0", ("10.0.0.1",))


def test_address_change_reset_and_overflow_do_not_invent_activity(sampler):
    s, now, counts, lost, backend, factory, inventory = sampler
    s.sample(ACTIVITY)
    now[0] = 1
    counts["10.0.0.2", 1] = 100
    inventory.return_value = (3, ("10.0.0.3",))
    assert s.sample(ACTIVITY).status == "warming"
    assert backend.close.call_count == 1
    now[0] = 2
    lost[0] = 1
    result = s.sample(ACTIVITY)
    assert result.status == "overflow" and not result.peers
    lost[0] = 0
    now[0] = 3
    assert s.sample(ACTIVITY).status == "warming"
    now[0] = 4
    counts["10.0.0.2", 1] = 1
    assert s.sample(ACTIVITY).status == "warming"
    now[0] = 5
    assert s.sample(ACTIVITY).peers == ()


@pytest.mark.parametrize("failure,status", [(PermissionError("blocked"), "denied"),
    (ImportError("bcc"), "unsupported"), (RuntimeError("verifier"), "error")])
def test_initialization_failure_backoff_and_recovery(sampler, failure, status):
    s, now, _, _, _, factory, _ = sampler
    factory.side_effect = failure
    result = s.sample(ACTIVITY)
    assert result.status == status and result.error
    now[0] = 1
    assert s.sample(ACTIVITY).status == status
    assert factory.call_count == 1
    now[0] = 31
    factory.side_effect = None
    assert s.sample(ACTIVITY).status == "warming"
    assert factory.call_count == 2


def test_down_interface_closes_observer_and_recovery_rebaselines(sampler):
    s, now, _, _, backend, _, _ = sampler
    s.sample(ACTIVITY)
    assert s.sample(NetworkActivity("unavailable", "eth0")).status == "unavailable"
    backend.close.assert_called_once()
    now[0] = 20
    assert s.sample(ACTIVITY).status == "warming"
    s.close()
    s.close()
    assert backend.close.call_count == 2


def test_disabled_and_non_linux_never_load_bcc(sampler, monkeypatch):
    s, _, _, _, _, factory, _ = sampler
    s.mode = "off"
    assert s.sample(ACTIVITY).status == "disabled"
    s.mode = "auto"
    monkeypatch.setattr("src.core.peer_network.sys.platform", "darwin")
    assert s.sample(ACTIVITY).status == "unsupported"
    factory.assert_not_called()


def test_source_publishes_peer_activity_and_cleans_up(sampler, monkeypatch):
    s, now, counts, _, backend, _, _ = sampler
    source = PsutilProcessSource(network_peers="off")
    source._peer_sampler = s
    monkeypatch.setattr("src.core.sources.psutil.process_iter", lambda: [])
    monkeypatch.setattr(source, "_detect_ipc", lambda _: [])
    monkeypatch.setattr(source._network_sampler, "sample", lambda: ACTIVITY)
    source._scan()
    now[0] = 1
    counts["10.0.0.2", 1] = 123
    source._scan()
    snapshot = snapshot_from_bytes(source.get_snapshot().to_bytes())
    assert snapshot.network_peers.peers[0].sent_bytes == 123
    source._publish(error="scan failed")
    assert source.get_snapshot().network_peers.status == "unavailable"
    assert source.get_snapshot().network_peers.peers == ()
    source.shutdown()
    backend.close.assert_called_once()
