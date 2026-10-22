from dataclasses import replace
import json

import pytest

from src.telemetry import (
    Connection, LifecycleEvent, ProcessRecord, ProtocolError, Snapshot,
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
