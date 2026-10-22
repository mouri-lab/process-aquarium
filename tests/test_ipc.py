from dataclasses import replace
from types import SimpleNamespace as NS

import psutil

from src.core.ipc import IPCDetector, descriptor_groups
from test_telemetry import process


def test_machine_descriptor_parser_preserves_paths_and_does_not_join_generic_names():
    data = "p10\nf3\ntPIPE\ni123\nnpipe\np11\nf7\ntPIPE\ni123\nnpipe\nf8\ntunix\nn/private/a socket\np12\nf4\ntunix\nn/private/a socket\nf5\ntPIPE\nnpipe\np13\nf5\ntPIPE\nnpipe\n"
    groups = descriptor_groups(data, {10, 11, 12, 13})
    assert groups[("pipe", "inode::123")] == {10, 11}
    assert groups[("unix", "/private/a socket")] == {11, 12}
    assert not any(13 in owners for owners in groups.values())


def test_ipc_combines_network_unix_pipe_and_parent_fallback(monkeypatch):
    records = {pid: replace(process(), pid=pid, ppid=1) for pid in range(10, 17)}
    records[16] = replace(records[16], ppid=10)
    endpoint = lambda port: NS(ip="127.0.0.1", port=port)
    inet = [
        NS(pid=10, laddr=endpoint(8000), raddr=endpoint(10000)),
        NS(pid=11, laddr=endpoint(10000), raddr=endpoint(8000)),
    ]
    unix = [NS(pid=12, laddr="/tmp/app socket"), NS(pid=13, laddr="/tmp/app socket")]
    monkeypatch.setattr(
        psutil, "net_connections", lambda kind: inet if kind == "inet" else unix
    )
    detector = IPCDetector()
    monkeypatch.setattr(
        detector, "read_descriptors", lambda _: {("pipe", "123"): {14, 15}}
    )
    conns = detector.detect(records)
    assert {(c.pid_a, c.pid_b, c.kind) for c in conns} == {
        (10, 11, "tcp-loop"),
        (12, 13, "unix"),
        (14, 15, "pipe"),
        (10, 16, "parent-child"),
    }
    records[14] = replace(records[14], create_time=200)
    assert not any(c.kind == "pipe" for c in detector.detect(records))


def test_permissions_and_missing_lsof_keep_parent_relationships(monkeypatch):
    def denied(**kwargs):
        raise psutil.AccessDenied()

    monkeypatch.setattr(psutil, "net_connections", denied)
    detector = IPCDetector()
    monkeypatch.setattr(detector, "read_descriptors", lambda _: {})
    records = {10: replace(process(), pid=10), 11: replace(process(), pid=11, ppid=10)}
    conns = detector.detect(records)
    assert len(conns) == 1 and conns[0].kind == "parent-child"
