from dataclasses import replace

from src.core.source import SourceStatus
from src.presentation import ProcessManager
from src.telemetry import Connection, LifecycleEvent
from test_telemetry import process, sample


class MemorySource:
    name = "test"
    status = SourceStatus(stale=False)

    def __init__(self, snapshot):
        self.snapshot = snapshot

    def update(self):
        pass

    def get_snapshot(self):
        return self.snapshot

    def shutdown(self):
        pass


def test_display_limit_never_generates_lifecycle_exits():
    source = MemorySource(sample(processes=[process(pid=1), process(pid=2)]))
    manager = ProcessManager(source=source)
    manager.update()
    manager.set_sort_config("pid", "asc")
    manager.set_process_limit(1)
    assert list(manager.processes) == [1]
    manager.set_sort_config("pid", "desc")
    source.snapshot = replace(source.snapshot, sequence=2)
    manager.update()
    assert list(manager.processes) == [2]
    assert len(manager.get_all_processes()) == 2
    assert not manager.get_new_processes()
    assert not manager.get_dying_processes()


def test_outage_preserves_state_and_pid_reuse_replaces_identity():
    source = MemorySource(sample())
    manager = ProcessManager(source=source)
    manager.update()
    identity = manager.process_identity(42)
    source.status = SourceStatus(stale=True, error="offline")
    assert not manager.update()
    assert manager.process_identity(42) == identity
    assert not manager.get_dying_processes()
    source.status = SourceStatus(stale=False)
    source.snapshot = sample(sequence=2, processes=[process(create_time=2)])
    manager.update()
    assert manager.process_identity(42) != identity
    assert manager.get_dying_processes()[0].create_time == 1
    assert manager.get_new_processes()[0].create_time == 2
    source.snapshot = sample(sequence=3, processes=[])
    manager.update()
    assert manager.get_dying_processes()[0].pid == 42


def test_collection_error_does_not_erase_processes():
    source = MemorySource(sample())
    manager = ProcessManager(source=source)
    manager.update()
    source.snapshot = sample(sequence=2, processes=[], error="collection failed")
    assert not manager.update()
    assert manager.get_process(42)


def test_event_replay_is_independent_for_each_client():
    event = LifecycleEvent("exec", 42, 1, 100, event_id=1, create_time=1)
    source = MemorySource(sample(events=(event,)))
    first, second = ProcessManager(source=source), ProcessManager(source=source)
    for manager in (first, second):
        manager.update()
        assert len(manager.detect_exec()) == 1
    source.snapshot = replace(source.snapshot, sequence=2)
    for manager in (first, second):
        manager.update()
        assert manager.detect_exec() == []
    # An exec event belonging to a previous use of the PID cannot animate the replacement.
    source.snapshot = sample(sequence=3, processes=[process(create_time=2)],
                             events=(replace(event, event_id=2),))
    first.update()
    assert first.detect_exec() == []


def test_host_namespace_changes_and_ipc_only_uses_observed_data():
    source = MemorySource(sample(processes=[process(pid=1), process(pid=2)],
                                 connections=(Connection(1, 2, "tcp-loop"),)))
    manager = ProcessManager(source=source)
    manager.update()
    before = manager.process_identity(1)
    assert len(manager.detect_ipc_connections()) == 1
    source.snapshot = replace(source.snapshot, host_id="other", sequence=2, connections=())
    manager.update()
    assert manager.process_identity(1) != before
    assert manager.detect_ipc_connections() == []
