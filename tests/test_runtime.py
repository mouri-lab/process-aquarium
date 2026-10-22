from unittest.mock import Mock

import pytest

from src.core import runtime
from src.core.types import ProcessLifecycleEvent


@pytest.mark.parametrize("available", [True, False])
def test_ebpf_selection_and_fallback(monkeypatch, capsys, available):
    ebpf = Mock(available=available)
    ebpf.drain_lifecycle_events.return_value = [
        ProcessLifecycleEvent("exec", 0, None, 0, {"warning": "bcc unavailable"})
    ]
    monkeypatch.setattr(runtime, "EbpfProcessSource", Mock(return_value=ebpf))

    manager = runtime.create_process_manager(
        "ebpf", max_processes=50, process_limit=7, sort_by="memory", sort_order="asc"
    )
    try:
        assert manager.max_processes == 50
        assert manager.process_limit == 7
        assert (manager.sort_by, manager.sort_order) == ("memory", "asc")
        if available:
            assert manager._external_source is ebpf
            ebpf.shutdown.assert_not_called()
        else:
            assert manager.get_data_source() == "psutil"
            ebpf.shutdown.assert_called_once()
            assert "bcc unavailable" in capsys.readouterr().out
    finally:
        manager.shutdown()


def test_ebpf_initialization_failure_falls_back(monkeypatch, capsys):
    monkeypatch.setattr(runtime, "EbpfProcessSource", Mock(side_effect=RuntimeError("permission denied")))
    manager = runtime.create_process_manager("ebpf")
    try:
        assert manager.get_data_source() == "psutil"
        assert "permission denied" in capsys.readouterr().out
    finally:
        manager.shutdown()


def test_explicit_psutil_does_not_initialize_ebpf(monkeypatch):
    ebpf = Mock(side_effect=AssertionError("eBPF must not be initialized"))
    monkeypatch.setattr(runtime, "EbpfProcessSource", ebpf)
    manager = runtime.create_process_manager("psutil")
    try:
        assert manager.get_data_source() == "psutil"
    finally:
        manager.shutdown()


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError, match="Unknown process source"):
        runtime.create_process_manager("unknown")
