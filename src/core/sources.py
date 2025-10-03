"""Process data source abstractions.

This module defines a minimal interface used by the visualization / manager
layer so that we can plug different backends:

* Psutil polling (current behaviour)
* eBPF event driven (future work)
* Hybrid (psutil for fallback metrics + eBPF for precise events)

The goal is to:
  - Minimize churn inside the visualization logic
  - Allow incremental migration (start with existing psutil logic migrated here)
  - Provide clear extension points for later eBPF implementation
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Optional, Set
import psutil
from datetime import datetime

from .types import ProcessInfo, ProcessLifecycleEvent, IPCConnection


class IProcessSource(ABC):
    """Abstract interface every process data backend must implement."""

    @abstractmethod
    def update(self) -> None:
        """Advance internal state.

        Implementations may poll, drain eBPF ring buffers, etc. Should be cheap
        enough to call from the main loop at ~1Hz (or faster if event driven).
        """

    @abstractmethod
    def get_processes(self) -> Dict[int, ProcessInfo]:
        """Return current process snapshot keyed by PID."""

    @abstractmethod
    def drain_lifecycle_events(self) -> List[ProcessLifecycleEvent]:
        """Return and clear accumulated lifecycle events since last call."""

    @abstractmethod
    def get_ipc_connections(self, limit: int = 20) -> List[IPCConnection]:
        """Return a (possibly sampled) list of IPC connections."""


class PsutilProcessSource(IProcessSource):
    """Psutil based polling implementation (adapted from legacy ProcessManager).

    This keeps behaviour equivalent while exposing lifecycle events so the
    visualization layer can react uniformly across backends.
    """

    def __init__(self, max_processes: int = 300):
        self.max_processes = max_processes
        self._processes: Dict[int, ProcessInfo] = {}
        self._previous_pids: Set[int] = set()
        self._previous_exe: Dict[int, str] = {}
        self._lifecycle_buffer: List[ProcessLifecycleEvent] = []
        self._last_update = 0.0
        self.update_interval = 1.0

        # IPC caches
        self._recent_ipc: List[IPCConnection] = []

        # Filtering heuristics (copied from original with slight cleanup)
        self.important_names = {
            'python', 'chrome', 'firefox', 'safari', 'code', 'terminal',
            'finder', 'dock', 'systemuiserver', 'windowserver', 'kernel_task',
            'launchd', 'zoom', 'slack', 'discord', 'spotify', 'photoshop',
            'illustrator', 'aftereffects', 'node', 'java', 'docker'
        }
        self.excluded_patterns = {
            'com.apple.', 'cfprefsd', 'distnoted', 'trustd', 'secd',
            'bluetoothd', 'audiomxd', 'logd_helper', 'deleted'
        }

    # ---------------- IProcessSource API ---------------- #
    def update(self) -> None:  # type: ignore[override]
        now = time.time()
        if now - self._last_update < self.update_interval:
            return
        self._last_update = now

        new_snapshot: Dict[int, ProcessInfo] = {}
        current_pids: Set[int] = set()
        current_exe: Dict[int, str] = {}

        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'exe', 'memory_percent',
                                         'cpu_percent', 'num_threads', 'create_time',
                                         'status', 'cmdline']):
            try:
                info = proc.info
                pid = info['pid']
                name = (info['name'] or 'unknown')
                exe = info['exe'] or ''
                mem = info['memory_percent'] or 0.0
                cpu = info['cpu_percent'] or 0.0

                if not self._should_include(name, mem, cpu):
                    continue

                current_pids.add(pid)
                current_exe[pid] = exe

                is_new = pid not in self._previous_pids

                proc_info = ProcessInfo(
                    pid=pid,
                    ppid=info['ppid'] or 0,
                    name=name,
                    exe=exe,
                    memory_percent=mem,
                    cpu_percent=cpu,
                    num_threads=info['num_threads'] or 1,
                    create_time=info['create_time'] or 0.0,
                    status=info['status'] or 'unknown',
                    cmdline=info['cmdline'] or [],
                    birth_time=datetime.now() if is_new else (
                        self._processes[pid].birth_time if pid in self._processes else datetime.now()
                    ),
                    last_update=datetime.now(),
                    is_new=is_new,
                )

                new_snapshot[pid] = proc_info

                if is_new:
                    # Distinguish fork vs spawn later (need parent existence)
                    # For now we just enqueue spawn; adapter layer can refine.
                    self._lifecycle_buffer.append(ProcessLifecycleEvent(
                        event_type="spawn", pid=pid, ppid=proc_info.ppid, timestamp=now
                    ))

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # exec detection
        for pid, exepath in current_exe.items():
            if pid in self._previous_exe:
                prev = self._previous_exe[pid]
                if prev and exepath and prev != exepath:
                    self._lifecycle_buffer.append(ProcessLifecycleEvent(
                        event_type="exec", pid=pid, ppid=new_snapshot[pid].ppid if pid in new_snapshot else None, timestamp=now,
                        details={"old_exe": prev, "new_exe": exepath}
                    ))

        # exit detection
        for old_pid in self._previous_pids:
            if old_pid not in current_pids and old_pid in self._processes:
                self._lifecycle_buffer.append(ProcessLifecycleEvent(
                    event_type="exit", pid=old_pid, ppid=self._processes[old_pid].ppid, timestamp=now
                ))

        # finalize snapshot
        self._processes = new_snapshot
        self._previous_pids = current_pids
        self._previous_exe = current_exe

        # Sample IPC connections each cycle (simplified from legacy)
        self._recent_ipc = self._detect_ipc()[:20]

    def get_processes(self) -> Dict[int, ProcessInfo]:  # type: ignore[override]
        return self._processes.copy()

    def drain_lifecycle_events(self) -> List[ProcessLifecycleEvent]:  # type: ignore[override]
        buf = self._lifecycle_buffer
        self._lifecycle_buffer = []
        return buf

    def get_ipc_connections(self, limit: int = 20) -> List[IPCConnection]:  # type: ignore[override]
        return self._recent_ipc[:limit]

    # ---------------- Internal helpers ---------------- #
    def _should_include(self, name: str, mem: float, cpu: float) -> bool:
        lower = name.lower()
        if any(pat in lower for pat in self.excluded_patterns):
            return False
        if any(imp in lower for imp in self.important_names):
            return True
        if (mem or 0) > 0.1 or (cpu or 0) > 0.5:
            return True
        import random
        return random.random() < 0.8

    def _detect_ipc(self) -> List[IPCConnection]:
        conns: List[IPCConnection] = []
        try:
            for c in psutil.net_connections(kind='inet'):
                if (c.laddr and c.raddr and c.pid and
                        c.laddr.ip in ('127.0.0.1', '::1') and c.raddr.ip in ('127.0.0.1', '::1')):
                    # Represent this as a symmetric connection between pids sharing port pair
                    # (Simplified vs original aggregation to keep cost low)
                    # We only keep pid once (remote pid may not be resolvable here) so we mark parent-child style
                    conns.append(IPCConnection(pid_a=c.pid, pid_b=c.pid, kind="tcp-loop", metadata={
                        "lport": c.laddr.port, "rport": c.raddr.port
                    }))
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
        # Parent-child relationships as pseudo IPC
        for p in self._processes.values():
            if p.ppid in self._processes:
                conns.append(IPCConnection(pid_a=p.ppid, pid_b=p.pid, kind="parent-child"))
        return conns


class EbpfProcessSource(IProcessSource):
    """Placeholder eBPF source.

    The real implementation will:
      - Load BPF programs (fork/exec/exit, tcp/udp connect, unix sockets, pipes)
      - Read events from perf/ring buffers
      - Maintain a process map (can be sparse; complement with psutil if needed)
    For now this just raises NotImplementedError to show plug point.
    """

    def __init__(self):
        self._processes: Dict[int, ProcessInfo] = {}

    def update(self) -> None:  # type: ignore[override]
        raise NotImplementedError("eBPF source not implemented yet")

    def get_processes(self) -> Dict[int, ProcessInfo]:  # type: ignore[override]
        return self._processes

    def drain_lifecycle_events(self) -> List[ProcessLifecycleEvent]:  # type: ignore[override]
        return []

    def get_ipc_connections(self, limit: int = 20) -> List[IPCConnection]:  # type: ignore[override]
        return []
