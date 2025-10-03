"""Core shared data types for process aquarium.

This module centralizes lightweight dataclasses that can be shared between
different process data sources (psutil based polling, eBPF event streaming, etc.).

Separating these from the legacy ``process_manager`` allows us to implement new
sources without circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Literal, Dict, Any


@dataclass
class ProcessInfo:
    """Represents a point-in-time snapshot of a process.

    NOTE: For performance visualization we keep only the fields we actually
    use in the rendering layer. Additional metrics (io, ctx switches, cgroup, …)
    can be appended later without breaking existing code if given defaults.
    """

    pid: int
    ppid: int
    name: str
    exe: str
    memory_percent: float
    cpu_percent: float
    num_threads: int
    create_time: float
    status: str
    cmdline: List[str]

    # Aquarium lifecycle attributes (visual layer metadata)
    birth_time: datetime
    last_update: datetime
    is_new: bool = False
    is_dying: bool = False

    # Optional future fields (left here commented as guidance)
    # io_read_bytes: int = 0
    # io_write_bytes: int = 0
    # ctx_switch_voluntary: int = 0
    # ctx_switch_involuntary: int = 0
    # cgroup: Optional[str] = None


LifecycleEventType = Literal["spawn", "fork", "exec", "exit"]


@dataclass
class ProcessLifecycleEvent:
    """Represents a *delta* in the process graph.

    For eBPF integration these will map 1:1 to kernel events (sched_process_fork,
    sched_process_exec, sched_process_exit) plus a synthesized *spawn* which is a
    convenience alias meaning a process first appeared in userland view.
    """

    event_type: LifecycleEventType
    pid: int
    ppid: Optional[int]
    timestamp: float
    details: Dict[str, Any] | None = None


@dataclass
class IPCConnection:
    """Represents an observed inter-process communication relationship.

    The *kind* field lets different sources (psutil scanning vs eBPF sockets /
    pipes / shared memory tracing) converge into a unified abstraction.
    """

    pid_a: int
    pid_b: int
    kind: str  # e.g. "tcp", "unix", "pipe", "parent-child"
    metadata: Dict[str, Any] | None = None
