import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import Mock

import pytest

import main
from src.headless import HeadlessMonitor


ROOT = Path(__file__).resolve().parents[1]


def test_headless_cli_collects_without_importing_gui():
    # Exercise the real collector and CLI in a fresh interpreter, even when
    # pygame happens to be installed in the test environment.
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import builtins
            import importlib.abc
            import runpy
            import sys
            import threading

            class NoGUI(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'pygame' or fullname.startswith(('pygame.', 'src.visuals')):
                        raise AssertionError(f'Unexpected GUI import: {fullname}')

            sys.meta_path.insert(0, NoGUI())
            original_print = print

            def interrupt_after_nonempty_report(*args, **kwargs):
                original_print(*args, **kwargs)
                if args and str(args[0]).startswith('[stats|psutil] procs=1 '):
                    raise KeyboardInterrupt

            builtins.print = interrupt_after_nonempty_report
            sys.argv = ['main.py', '--headless', '--source', 'psutil',
                        '--limit', '1', '--sort-by', 'pid', '--sort-order', 'asc']
            runpy.run_path('main.py', run_name='__main__')
            assert not any(t.name == 'PsutilProcessSource' for t in threading.enumerate())
            assert not any(m == 'pygame' or m.startswith('src.visuals') for m in sys.modules)
        """)],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "[stats|psutil] procs=1" in result.stdout
    assert "[Headless] 中断されました。終了します。" in result.stdout


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_interval_is_rejected_before_backend_creation(monkeypatch, value):
    factory = Mock()
    monkeypatch.setattr(main, "create_process_manager", factory)
    monkeypatch.setattr(sys, "argv", ["main.py", "--headless", f"--headless-interval={value}"])
    with pytest.raises(SystemExit) as exc:
        main.main_cli()
    assert exc.value.code == 2
    factory.assert_not_called()


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
def test_headless_monitor_validates_interval(interval):
    with pytest.raises(ValueError, match="finite positive"):
        HeadlessMonitor(Mock(), interval=interval)


def test_headless_preserves_ebpf_statistics(monkeypatch, capsys):
    manager = Mock()
    manager.get_process_statistics.return_value = {
        "data_source": "eBPF", "total_processes": 2, "new_processes": 1,
        "dying_processes": 0, "total_memory_percent": 1.25,
        "average_cpu_percent": 3.5, "total_threads": 4,
        "ebpf_events": "spawn:1 exec:0 exit:0",
    }
    monitor = HeadlessMonitor(manager)
    manager.update.side_effect = lambda: setattr(monitor, "running", False)
    monitor.run()
    assert (
        "[stats|eBPF] procs=2 new=1 dying=0 mem=1.25% cpu_avg=3.50% "
        "threads=4 events=[spawn:1 exec:0 exit:0]"
    ) in capsys.readouterr().out


def test_cli_shuts_down_backend_on_runner_failure(monkeypatch):
    manager = Mock()
    factory = Mock(return_value=manager)
    monkeypatch.setattr(main, "create_process_manager", factory)
    monkeypatch.setattr(HeadlessMonitor, "run", Mock(side_effect=RuntimeError("runner failed")))
    monkeypatch.setenv("AQUARIUM_SOURCE", "ebpf")
    monkeypatch.setenv("AQUARIUM_LIMIT", "12")
    monkeypatch.setenv("AQUARIUM_MAX_PROCESSES", "150")
    monkeypatch.setattr(sys, "argv", ["main.py", "--headless", "--source", "psutil", "--sort-by", "name"])
    with pytest.raises(RuntimeError, match="runner failed"):
        main.main_cli()
    factory.assert_called_once_with(
        "psutil", max_processes=150, process_limit=12, sort_by="name", sort_order="desc"
    )
    manager.shutdown.assert_called_once()


def test_missing_gui_dependency_reports_install_command_and_shuts_down(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "pygame", None)
    manager = Mock()
    monkeypatch.setattr(main, "create_process_manager", Mock(return_value=manager))
    monkeypatch.setattr(sys, "argv", ["main.py", "--source", "psutil"])
    with pytest.raises(SystemExit) as exc:
        main.main_cli()
    assert exc.value.code == 2
    assert "uv sync --extra gui" in capsys.readouterr().err
    manager.shutdown.assert_called_once()
