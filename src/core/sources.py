"""Local collectors. Only agents and standalone local clients import psutil."""

from collections import Counter, deque
from pathlib import Path
import math
import socket
from threading import Event, Lock, Thread
import time
from typing import Optional
import uuid

import psutil

from .source import IProcessSource, SourceStatus
from .ipc import IPCDetector
from .network import NetworkSampler
from .peer_network import PeerNetworkSampler
from ..telemetry import MAX_EVENTS, Connection, LifecycleEvent, ProcessRecord, Snapshot


def boot_identity() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return f"boot-{psutil.boot_time():.6f}"


class PsutilProcessSource(IProcessSource):
    name = "psutil"

    def __init__(self, max_processes=2000, *, host_id=None, interval=1.0, network_interface=None,
                 network_peers="auto", network_scope="default"):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Collection interval must be finite and positive")
        self.max_processes = max_processes  # Collection is never display-limited.
        self.host_id = host_id or socket.gethostname()
        if not isinstance(self.host_id, str) or len(self.host_id) > 128:
            raise ValueError("Host ID must be text of at most 128 characters")
        self.hostname = socket.gethostname()
        self.boot_id = boot_identity()
        self.session_id = uuid.uuid4().hex
        self.update_interval = interval
        self._lock = Lock()
        self._shutdown = Event()
        self._ready = Event()
        self._poll_thread: Optional[Thread] = None
        self._snapshot: Optional[Snapshot] = None
        self._processes: dict[int, ProcessRecord] = {}
        self._events = deque(maxlen=MAX_EVENTS)
        self._event_id = 0
        self._sequence = 0
        self._event_stats = Counter()
        self._seen_events = set()
        self._error = None
        self._last_success = 0.0
        self._recent_ipc = ()
        self._recent_network = ()
        self._ipc_detector = IPCDetector()
        self._last_ipc_refresh = float("-inf")
        self._network_sampler = NetworkSampler(network_interface)
        self._network_activity = None
        self._peer_sampler = PeerNetworkSampler(mode=network_peers, network_scope=network_scope)
        self._network_peers = None

    def update(self):
        if self._poll_thread is None and not self._shutdown.is_set():
            self._poll_thread = Thread(target=self._poll_loop, name=type(self).__name__, daemon=True)
            self._poll_thread.start()
        if not self._ready.is_set():
            self._ready.wait(timeout=0.2)

    def get_snapshot(self):
        with self._lock:
            return self._snapshot

    @property
    def status(self):
        with self._lock:
            return SourceStatus(
                stale=self._snapshot is None or bool(self._error) or
                      time.monotonic() - self._last_success > max(5.0, self.update_interval * 3),
                error=self._error,
            )

    def _read_process(self, process):
        with process.oneshot():
            try:
                info = process.as_dict(attrs=[
                    "pid", "ppid", "name", "exe", "memory_percent", "cpu_percent",
                    "num_threads", "create_time", "status", "cmdline",
                ], ad_value=None)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                return None
        return ProcessRecord(
            pid=info["pid"], ppid=info["ppid"] or 0, name=info["name"] or "unknown",
            exe=info["exe"] or "", memory_percent=info["memory_percent"] or 0.0,
            cpu_percent=info["cpu_percent"] or 0.0, num_threads=info["num_threads"] or 0,
            create_time=info["create_time"] or 0.0, status=info["status"] or "unknown",
            cmdline=tuple(info["cmdline"] or ()),
        )

    def _emit(self, kind, process, *, details=None, deduplicate=False):
        key = kind, process.identity
        if deduplicate and key in self._seen_events:
            return
        self._seen_events.add(key)
        self._event_id += 1
        self._event_stats[kind] += 1
        self._events.append(LifecycleEvent(
            kind, process.pid, process.ppid, time.time(), details,
            self._event_id, process.create_time,
        ))

    def _scan(self):
        processes = {}
        for index, process in enumerate(psutil.process_iter()):
            if self._shutdown.is_set():
                return
            try:
                record = self._read_process(process)
                if record is not None:
                    processes[record.pid] = record
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            if index and index % 100 == 0 and self._shutdown.wait(0.004):
                return
        self._reconcile(processes)
        now = time.monotonic()
        if now - self._last_ipc_refresh >= 2.0:
            self._recent_ipc = tuple(self._detect_ipc(processes))
            self._recent_network = tuple(self._ipc_detector.network_flows)
            self._last_ipc_refresh = now
        if self._sequence == 0:
            self._event_stats["initial_scan"] = len(processes)
        self._processes = processes
        self._seen_events.clear()
        self._network_activity = self._network_sampler.sample()
        self._network_peers = self._peer_sampler.sample(self._network_activity)
        self._publish()

    def _reconcile(self, processes):
        for pid, old in self._processes.items():
            current = processes.get(pid)
            if current is None or current.identity != old.identity:
                self._emit("exit", old, deduplicate=True)
        for pid, current in processes.items():
            old = self._processes.get(pid)
            if old is None or old.identity != current.identity:
                self._emit("spawn", current, deduplicate=True)
            elif old.exe != current.exe or old.name != current.name:
                self._emit("exec", current, deduplicate=True)

    def _publish(self, error=None):
        if error:
            self._network_activity = self._network_sampler.reset()
            self._network_peers = self._peer_sampler.reset()
        self._sequence += 1
        # Failure preserves the last complete state and marks it stale.
        collected_at = self._snapshot.collected_at if error and self._snapshot else time.time()
        snapshot = Snapshot(
            host_id=self.host_id, hostname=self.hostname, boot_id=self.boot_id,
            session_id=self.session_id, sequence=self._sequence, collected_at=collected_at,
            source=self.name, processes=tuple(self._processes.values()),
            events=tuple(self._events), connections=self._recent_ipc,
            event_stats=dict(self._event_stats), error=error,
            network_flows=self._recent_network,
            network_activity=self._network_activity,
            network_peers=self._network_peers,
        )
        with self._lock:
            self._error = error
            self._snapshot = snapshot
            if not error:
                self._last_success = time.monotonic()
        self._ready.set()

    def _poll_loop(self):
        try:
            while not self._shutdown.is_set():
                started = time.monotonic()
                try:
                    self._scan()
                except Exception as exc:
                    self._publish(error=f"Collection failed: {exc}")
                self._shutdown.wait(max(0, self.update_interval - (time.monotonic() - started)))
        finally:
            self._peer_sampler.close()

    def _detect_ipc(self, processes):
        return self._ipc_detector.detect(processes)

    def shutdown(self):
        self._shutdown.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._peer_sampler.close()


class EbpfProcessSource(PsutilProcessSource):
    """BCC lifecycle events plus periodic psutil metrics and reconciliation."""

    name = "eBPF"
    BPF_PROGRAM = r"""
    struct fork_event_t { u64 ts; u32 ppid; u32 pid; };
    struct process_event_t { u64 ts; u32 pid; };
    BPF_PERF_OUTPUT(fork_events);
    BPF_PERF_OUTPUT(exec_events);
    BPF_PERF_OUTPUT(exit_events);
    TRACEPOINT_PROBE(sched, sched_process_fork) {
        struct fork_event_t evt = {};
        evt.ts = bpf_ktime_get_ns();
        evt.ppid = args->parent_pid;
        evt.pid = args->child_pid;
        fork_events.perf_submit(args, &evt, sizeof(evt));
        return 0;
    }
    TRACEPOINT_PROBE(sched, sched_process_exec) {
        struct process_event_t evt = {};
        evt.ts = bpf_ktime_get_ns();
        evt.pid = args->pid;
        exec_events.perf_submit(args, &evt, sizeof(evt));
        return 0;
    }
    TRACEPOINT_PROBE(sched, sched_process_exit) {
        u64 pid_tgid = bpf_get_current_pid_tgid();
        if ((u32)pid_tgid != (u32)(pid_tgid >> 32)) return 0;
        struct process_event_t evt = {};
        evt.ts = bpf_ktime_get_ns();
        evt.pid = args->pid;
        exit_events.perf_submit(args, &evt, sizeof(evt));
        return 0;
    }
    """

    def __init__(self, enable=True, **kwargs):
        super().__init__(**kwargs)
        self.available = False
        self.error = None
        self._bpf = None
        if not enable:
            self.error = "eBPF disabled"
            return
        try:
            from bcc import BPF

            self._bpf = BPF(text=self.BPF_PROGRAM)
            self._bpf["fork_events"].open_perf_buffer(self._handle_fork, lost_cb=self._lost_events)
            self._bpf["exec_events"].open_perf_buffer(self._handle_exec, lost_cb=self._lost_events)
            self._bpf["exit_events"].open_perf_buffer(self._handle_exit, lost_cb=self._lost_events)
            self.available = True
        except Exception as exc:
            self.error = f"eBPF unavailable: {exc}"
            self._cleanup_bpf()

    def _lost_events(self, cpu, count):
        self._event_stats["lost"] += count

    def _capture(self, pid):
        try:
            # The fork tracepoint also reports threads; retain process leaders.
            status = Path(f"/proc/{pid}/status")
            if status.exists():
                for line in status.read_text().splitlines():
                    if line.startswith("Tgid:") and int(line.split()[1]) != pid:
                        return None
            return self._read_process(psutil.Process(pid))
        except (psutil.Error, OSError):
            return None

    def _handle_fork(self, cpu, data, size):
        event = self._bpf["fork_events"].event(data)
        process = self._capture(event.pid)
        if process:
            self._emit("fork", process, details={"source": "ebpf"})
            self._emit("spawn", process, details={"source": "ebpf"})
            self._processes[process.pid] = process

    def _handle_exec(self, cpu, data, size):
        event = self._bpf["exec_events"].event(data)
        process = self._capture(event.pid)
        if process:
            self._emit("exec", process, details={"source": "ebpf"})
            self._processes[process.pid] = process

    def _handle_exit(self, cpu, data, size):
        event = self._bpf["exit_events"].event(data)
        process = self._processes.pop(event.pid, None)
        if process:
            self._emit("exit", process, details={"source": "ebpf"})

    def _poll_loop(self):
        next_scan = 0.0
        try:
            while not self._shutdown.is_set():
                if self.available:
                    try:
                        self._bpf.perf_buffer_poll(timeout=100)
                    except InterruptedError:
                        continue
                    except Exception as exc:
                        self.available = False
                        self.name = "psutil"
                        print(f"[eBPF] Poll failed: {exc}; continuing with psutil", flush=True)
                        self._cleanup_bpf()
                else:
                    self._shutdown.wait(0.1)
                if time.monotonic() >= next_scan:
                    try:
                        self._scan()
                    except Exception as exc:
                        self._publish(error=f"Collection failed: {exc}")
                    next_scan = time.monotonic() + self.update_interval
        finally:
            self._peer_sampler.close()
            self._cleanup_bpf()

    def _cleanup_bpf(self):
        if self._bpf is not None:
            try:
                self._bpf.cleanup()
            finally:
                self._bpf = None

    def shutdown(self):
        super().shutdown()
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._cleanup_bpf()
