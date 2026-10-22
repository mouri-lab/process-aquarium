from dataclasses import replace
import os
from pathlib import Path
import queue
import subprocess
import sys
import textwrap
import threading
import time
from unittest.mock import Mock

import pytest

from src.agent import Agent
from src.presentation import ProcessManager
from src.remote import RemoteProcessSource
from src.transport import APIClient, RemoteError
from test_presentation import MemorySource
from test_server import service
from test_telemetry import sample


def test_agent_remote_roundtrip_outage_and_recovery(service):
    _, client = service
    local = MemorySource(sample())
    agent = Agent(local, client)
    assert agent.publish_once()
    assert not agent.publish_once()
    remote = RemoteProcessSource(client, host_id="host-a")
    assert remote.poll_once()
    manager = ProcessManager(source=remote)
    # Deterministic polling for this test; the CLI test exercises its thread.
    remote.update = lambda: None
    manager.update()
    original = manager.process_identity(42)
    real_client = remote.client
    remote.client = Mock()
    remote.client.request.side_effect = RemoteError("offline")
    assert not remote.poll_once()
    manager.update()
    assert manager.status.stale
    assert manager.process_identity(42) == original
    assert not manager.get_dying_processes()
    remote.client = real_client
    local.snapshot = sample(sequence=2, processes=[])
    assert agent.publish_once()
    assert remote.poll_once()
    manager.update()
    assert not manager.status.stale
    assert manager.get_process(42) is None
    assert manager.get_dying_processes()[0].pid == 42


def test_agent_retries_latest_state_and_rejects_superseded_session(service):
    _, client = service
    local = MemorySource(sample())
    flaky = Mock()
    flaky.request.side_effect = RemoteError("offline")
    agent = Agent(local, flaky)
    assert not agent.publish_once()
    local.snapshot = sample(sequence=2)
    agent.client = client
    assert agent.publish_once()
    assert client.request("GET", "/api/v1/snapshot?host=host-a")["sequence"] == 2
    client.request("POST", "/api/v1/snapshots", sample(session_id="replacement").to_dict())
    local.snapshot = sample(sequence=3)
    with pytest.raises(RuntimeError, match="superseded"):
        agent.publish_once()


def test_remote_requires_unambiguous_host_and_pins_selection(service):
    server, client = service
    for host in ("host-a", "host-b"):
        client.request("POST", "/api/v1/snapshots", sample(host_id=host).to_dict())
    source = RemoteProcessSource(client)
    assert not source.poll_once()
    assert "choose --host" in source.status.error
    selected = RemoteProcessSource(client, host_id="host-b")
    assert selected.poll_once()
    assert selected.get_snapshot().host_id == "host-b"


def test_remote_cli_never_imports_local_collection_or_gui(service):
    _, client = service
    client.request("POST", "/api/v1/snapshots", sample().to_dict())
    script = textwrap.dedent("""
        import builtins, importlib.abc, runpy, sys, threading
        class NoLocalDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in ('psutil', 'pygame', 'numpy', 'src.core.sources'):
                    raise AssertionError(f'Unexpected local dependency: {fullname}')
        sys.meta_path.insert(0, NoLocalDependencies())
        original_print = print
        def stop_after_report(*args, **kwargs):
            original_print(*args, **kwargs)
            if args and str(args[0]).startswith('[stats|psutil] procs=1 '):
                raise KeyboardInterrupt
        builtins.print = stop_after_report
        sys.argv = ['main.py', 'client', '--server', sys.argv[1], '--token', 'test-secret', '--headless']
        runpy.run_path('main.py', run_name='__main__')
        assert not any(t.name == 'RemoteProcessSource' for t in threading.enumerate())
    """)
    result = subprocess.run([sys.executable, "-c", script, client.server],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "host=host-a" in result.stdout


def test_separate_server_and_agent_processes_shutdown_cleanly():
    root = Path(__file__).resolve().parents[1]
    server = subprocess.Popen([sys.executable, "main.py", "server", "--port", "0"],
                              cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    agent = None
    try:
        lines = queue.Queue()
        reader = threading.Thread(target=lambda: lines.put(server.stdout.readline()), daemon=True)
        reader.start()
        address = lines.get(timeout=10).strip().split()[-1]
        assert address.startswith("http://127.0.0.1:")
        client = APIClient(address)
        agent = subprocess.Popen([sys.executable, "main.py", "agent", "--server", address,
                                  "--source", "psutil", "--host-id", "integration-host", "--interval", "0.1"],
                                 cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            hosts = client.request("GET", "/api/v1/hosts")["hosts"]
            if hosts and hosts[0]["sequence"] >= 2:
                assert hosts[0]["process_count"] > 0
                break
            time.sleep(0.05)
        else:
            pytest.fail("Agent failed to publish periodic samples")
    finally:
        for process in (agent, server):
            if process is not None:
                process.terminate()
                try:
                    _, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise
                assert process.returncode == 0, stderr
