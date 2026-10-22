from dataclasses import replace
from unittest.mock import Mock

from src.core.sources import EbpfProcessSource, PsutilProcessSource
from src.telemetry import MAX_EVENTS, snapshot_from_bytes
from test_telemetry import process


def test_collector_reconciles_pid_reuse_and_produces_wire_safe_samples(monkeypatch):
    source = PsutilProcessSource(host_id="test")
    source._processes = {42: process()}
    source._reconcile({42: process(create_time=2)})
    assert [event.event_type for event in source._events] == ["exit", "spawn"]
    source._publish()
    snapshot = source.get_snapshot()
    assert snapshot_from_bytes(snapshot.to_bytes()) == snapshot


def test_ebpf_hybrid_continues_to_refresh_metrics(monkeypatch):
    source = EbpfProcessSource(enable=False)
    values = [process(), replace(process(), cpu_percent=80, memory_percent=7)]
    monkeypatch.setattr("src.core.sources.psutil.process_iter", lambda: [Mock()])
    monkeypatch.setattr(source, "_read_process", lambda _: values.pop(0))
    monkeypatch.setattr(source, "_detect_ipc", lambda _: [])
    source._scan()
    source._scan()
    assert source.get_snapshot().processes[0].cpu_percent == 80
    assert source.get_snapshot().processes[0].memory_percent == 7
    assert source.get_snapshot().sequence == 2


def test_collector_failure_retains_last_sample():
    source = PsutilProcessSource()
    source._processes = {42: process()}
    source._publish()
    old = source.get_snapshot()
    source._publish(error="permission failure")
    current = source.get_snapshot()
    assert current.processes == old.processes
    assert current.collected_at == old.collected_at
    assert source.status.stale
    assert source.status.error == "permission failure"


def test_event_history_is_bounded():
    source = PsutilProcessSource()
    for _ in range(MAX_EVENTS + 10):
        source._emit("exec", process())
    source._publish()
    assert len(source.get_snapshot().events) == MAX_EVENTS
    assert source.get_snapshot().events[0].event_id == 11
