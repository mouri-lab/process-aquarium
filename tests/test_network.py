from types import SimpleNamespace as NS

import psutil
import pytest

from src.core.network import NetworkSampler
from src.telemetry import NetworkActivity, ProtocolError, snapshot_from_dict
from test_telemetry import sample


@pytest.fixture
def network(monkeypatch):
    counters = {"en0": NS(bytes_sent=1000, bytes_recv=2000),
                "lo0": NS(bytes_sent=9999, bytes_recv=9999),
                "utun0": NS(bytes_sent=9999, bytes_recv=9999)}
    stats = {n: NS(isup=True, flags="loopback" if n == "lo0" else "up") for n in counters}
    addresses = {n: [NS(family=2, address="127.0.0.1" if n == "lo0" else "10.0.0.1")]
                 for n in counters}
    def read(*, pernic, nowrap):
        assert pernic and not nowrap
        return counters
    monkeypatch.setattr(psutil, "net_io_counters", read)
    monkeypatch.setattr(psutil, "net_if_stats", lambda: stats)
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: addresses)
    now = [0.0]
    return NetworkSampler(clock=lambda: now[0]), counters, stats, addresses, now


def test_measures_one_adapter_and_distinguishes_idle_from_baseline(network):
    sampler, counters, _, _, now = network
    assert sampler.sample() == NetworkActivity("warming", "en0")
    now[0] = 2
    counters["en0"] = NS(bytes_sent=1200, bytes_recv=2600)
    assert sampler.sample() == NetworkActivity("ready", "en0", 2, 200, 600)
    now[0] = 3
    assert sampler.sample() == NetworkActivity("ready", "en0", 1, 0, 0)


def test_reset_adapter_change_and_clock_reset_rebaseline(network):
    sampler, counters, _, addresses, now = network
    sampler.sample()
    now[0] = 1
    counters["en0"] = NS(bytes_sent=1, bytes_recv=2)
    assert sampler.sample().status == "warming"
    now[0] = 2
    assert sampler.sample().sent_bytes == 0
    addresses["en0"][0].address = "10.0.0.2"
    now[0] = 3
    assert sampler.sample().status == "warming"
    assert sampler.sample().status == "warming"  # no elapsed interval


def test_ambiguous_adapters_require_selection_and_never_sum(network):
    sampler, counters, stats, _, now = network
    counters["en1"] = NS(bytes_sent=500, bytes_recv=800)
    stats["en1"] = NS(isup=True, flags="up")
    assert sampler.sample().status == "ambiguous"
    sampler.interface = "utun0"  # VPN can be explicitly selected on its own
    assert sampler.sample().interface == "utun0"
    now[0] = 1
    assert sampler.sample().sent_bytes == 0
    sampler.interface = "lo0"
    assert sampler.sample().status == "unavailable"
    sampler.interface = "missing"
    assert sampler.sample().status == "unavailable"


@pytest.mark.parametrize("failure,status", [(PermissionError(), "denied"),
    (psutil.AccessDenied(), "denied"), (NotImplementedError(), "unsupported"), (OSError(), "error")])
def test_failure_and_recovery_cannot_replay_old_activity(network, monkeypatch, failure, status):
    sampler, _, _, _, now = network
    sampler.sample()
    read = psutil.net_io_counters
    def fail(**kwargs):
        raise failure
    monkeypatch.setattr(psutil, "net_io_counters", fail)
    now[0] = 1
    assert sampler.sample().status == status
    monkeypatch.setattr(psutil, "net_io_counters", read)
    now[0] = 2
    assert sampler.sample().status == "warming"


def test_down_interface_and_explicit_reset_clear_baseline(network):
    sampler, _, stats, _, now = network
    sampler.sample()
    stats["en0"].isup = False
    assert sampler.sample().status == "unavailable"
    stats["en0"].isup = True
    now[0] = 1
    assert sampler.sample().status == "warming"
    sampler.reset()
    now[0] = 2
    assert sampler.sample().status == "warming"


def test_activity_roundtrip_unknown_direction_and_old_agents():
    activity = NetworkActivity("ready", "eth0", 1.5, None, 100)
    data = sample(network_activity=activity).to_dict()
    assert snapshot_from_dict(data).network_activity == activity
    del data["network_activity"]
    assert snapshot_from_dict(data).network_activity is None


@pytest.mark.parametrize("change", [
    {"interval_seconds": 0}, {"interval_seconds": float("inf")},
    {"sent_bytes": -1}, {"sent_bytes": True}, {"received_bytes": 2**53},
    {"sent_bytes": None, "received_bytes": None}, {"status": "warming"},
    {"scope": "peer"}, {"source": "made-up"}, {"interface": ""},
])
def test_activity_rejects_fabricated_or_invalid_samples(change):
    data = sample(network_activity=NetworkActivity("ready", "en0", 1, 0, 100)).to_dict()
    data["network_activity"].update(change)
    with pytest.raises(ProtocolError):
        snapshot_from_dict(data)
