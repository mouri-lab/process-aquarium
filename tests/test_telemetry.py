from dataclasses import replace
import json

import pytest

from src.telemetry import (
    Connection, LifecycleEvent, NetworkFlow, ProcessRecord, ProtocolError, Snapshot,
    snapshot_from_bytes, snapshot_from_dict,
)


def sample(sequence=1, host_id="host-a", session_id="session-a", processes=None, **kwargs):
    return Snapshot(
        host_id=host_id, hostname="test-host", boot_id="boot-a", session_id=session_id,
        sequence=sequence, collected_at=100.0, source="psutil",
        processes=tuple(processes if processes is not None else [process()]), **kwargs,
    )


def process(pid=42, create_time=1.0, **kwargs):
    return ProcessRecord(pid=pid, ppid=1, name="テスト", exe="/bin/test",
                         memory_percent=1.2, cpu_percent=12.5, num_threads=2,
                         create_time=create_time, status="running", cmdline=("test",), **kwargs)


def test_protocol_roundtrip_preserves_identity_and_relationships():
    snapshot = sample(
        events=(LifecycleEvent("exec", 42, 1, 100, {"exe": "/bin/test"}, 1, 1),),
        connections=(Connection(1, 42, "parent-child"),), event_stats={"exec": 1},
        network_flows=(NetworkFlow(42, 1.0, "tcp", "127.0.0.1", 41000,
                                   "127.0.0.1", 5432, "ESTABLISHED"),),
    )
    assert snapshot_from_bytes(snapshot.to_bytes()) == snapshot
    assert "birth_time" not in snapshot.to_dict()["processes"][0]
    assert process().identity != process(create_time=2).identity


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"schema_version": True}, {"sequence": -1},
    {"sequence": True}, {"host_id": ""}, {"collected_at": float("inf")},
    {"processes": [{"pid": 1}]}, {"processes": [process(), process()]},
])
def test_malformed_snapshots_are_rejected(change):
    data = sample().to_dict()
    if "processes" in change and change["processes"] and isinstance(change["processes"][0], ProcessRecord):
        change = {"processes": data["processes"] * 2}
    data.update(change)
    with pytest.raises(ProtocolError):
        snapshot_from_dict(data)


def test_replayed_event_ids_are_rejected():
    snapshot = sample(events=(LifecycleEvent("spawn", 42, 1, 100, event_id=1),) * 2)
    with pytest.raises(ProtocolError, match="strictly increasing"):
        snapshot_from_bytes(snapshot.to_bytes())


@pytest.mark.parametrize("payload", [b'{', b'\xff', b'{"number": NaN}', b'[]'])
def test_invalid_json_is_rejected(payload):
    with pytest.raises(ProtocolError):
        snapshot_from_bytes(payload)


def test_numeric_overflow_and_deep_metadata_are_rejected():
    data = sample().to_dict()
    data["collected_at"] = 10**1000
    with pytest.raises(ProtocolError):
        snapshot_from_dict(data)
    details = {}
    for _ in range(10):
        details = {"nested": details}
    snapshot = sample(events=(LifecycleEvent("exec", 42, 1, 100, details, 1),))
    with pytest.raises(ProtocolError, match="deeply"):
        snapshot_from_bytes(snapshot.to_bytes())


def test_non_utf8_os_strings_survive_telemetry_encoding():
    record = replace(process(), name="worker-\udcff", cmdline=("worker", "argument-\udcff"))
    snapshot = sample(processes=[record])
    assert snapshot_from_bytes(snapshot.to_bytes()) == snapshot


def test_network_flows_are_optional_and_port_bounds_are_enforced():
    old = sample().to_dict()
    old.pop("network_flows")
    assert snapshot_from_dict(old).network_flows == ()
    flow = NetworkFlow(42, 1.0, "tcp", "127.0.0.1", 41000,
                       "127.0.0.1", 5432, "ESTABLISHED")
    data = sample(network_flows=(flow,)).to_dict()
    data["network_flows"][0]["remote_port"] = 65536
    with pytest.raises(ProtocolError, match="65535"):
        snapshot_from_dict(data)
