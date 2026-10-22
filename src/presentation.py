"""Client-side process selection and relationships, with no OS access."""

from collections import defaultdict
from typing import Optional

from .core.source import IProcessSource
from .telemetry import ProcessRecord, Snapshot


class ProcessManager:
    """Adapt complete telemetry to the existing native/text presentations.

    Filtering never changes the authoritative host state. All lifecycle
    comparisons precede display selection; source outages leave that state
    intact. IPC comes solely from telemetry, including for remote sources.
    """

    def __init__(self, max_processes=2000, *, source: IProcessSource):
        self.max_processes = max_processes
        self._external_source = source
        self.snapshot: Optional[Snapshot] = None
        self.processes: dict[int, ProcessRecord] = {}
        self._all_processes: dict[int, ProcessRecord] = {}
        self.process_families = {}
        self.process_limit = None
        self.sort_by = "cpu"
        self.sort_order = "desc"
        self._new = []
        self._dying = []
        self.recent_execs = []
        self.recent_forks = []
        self._event_session = None
        self._last_event = 0
        self.events_lost = 0

    @property
    def status(self):
        return self._external_source.status

    def set_process_limit(self, limit):
        if limit is not None and limit < 0:
            raise ValueError("Process limit must be >= 0")
        self.process_limit = limit or None
        self._select()

    def set_sort_config(self, sort_by, sort_order="desc"):
        if sort_by not in ("cpu", "memory", "name", "pid") or sort_order not in ("asc", "desc"):
            raise ValueError("Invalid process sorting configuration")
        self.sort_by, self.sort_order = sort_by, sort_order
        self._select()

    def _select(self):
        keys = {"cpu": lambda p: p.cpu_percent, "memory": lambda p: p.memory_percent,
                "name": lambda p: p.name.lower(), "pid": lambda p: p.pid}
        processes = sorted(self._all_processes.values(), key=keys[self.sort_by],
                           reverse=self.sort_order == "desc")
        if self.process_limit:
            processes = processes[:self.process_limit]
        self.processes = {p.pid: p for p in processes}
        families = defaultdict(list)
        for process in self.processes.values():
            if process.ppid > 0:
                families[process.ppid].append(process.pid)
        self.process_families = dict(families)

    def update(self):
        self._external_source.update()
        snapshot = self._external_source.get_snapshot()
        self._new, self._dying = [], []
        if snapshot is None or snapshot.error:
            return False
        if self.snapshot is not None and snapshot.revision == self.snapshot.revision:
            return False
        previous = self._all_processes
        if self.snapshot and (snapshot.host_id, snapshot.boot_id) != (self.snapshot.host_id, self.snapshot.boot_id):
            previous = {}
        current = {p.pid: p for p in snapshot.processes}
        self._new = [p for pid, p in current.items()
                     if pid not in previous or previous[pid].identity != p.identity]
        self._dying = [p for pid, p in previous.items()
                       if pid not in current or current[pid].identity != p.identity]
        self._all_processes = current
        self.snapshot = snapshot
        self._select()
        session = snapshot.host_id, snapshot.session_id
        if self._event_session != session:
            self._event_session, self._last_event = session, 0
            self.recent_execs.clear()
            self.recent_forks.clear()
        if snapshot.events and self._last_event and snapshot.events[0].event_id > self._last_event + 1:
            self.events_lost += snapshot.events[0].event_id - self._last_event - 1
        forks = set()
        for event in snapshot.events:
            if event.event_id <= self._last_event:
                continue
            process = current.get(event.pid)
            if process and (not event.create_time or event.create_time == process.create_time):
                if event.event_type == "exec":
                    self.recent_execs.append(event.pid)
                elif event.event_type in ("spawn", "fork") and event.ppid in current:
                    pair = event.ppid, event.pid
                    if pair not in forks:
                        self.recent_forks.append((current[event.ppid], process))
                        forks.add(pair)
            self._last_event = event.event_id
        self.recent_forks = self.recent_forks[-10:]
        self.recent_execs = self.recent_execs[-2048:]
        return True

    def get_all_processes(self):
        return self._all_processes.copy()

    def get_process(self, pid):
        return self._all_processes.get(pid)

    def process_identity(self, pid):
        process = self._all_processes.get(pid)
        if process is None or self.snapshot is None:
            return None
        return self.snapshot.host_id, self.snapshot.boot_id, *process.identity

    def get_new_processes(self):
        return list(self._new)

    def get_dying_processes(self):
        return list(self._dying)

    def get_data_source(self):
        return self.snapshot.source if self.snapshot else self._external_source.name

    def get_process_statistics(self):
        processes = self.processes.values()
        stats = {
            "total_processes": len(self.processes), "observed_processes": len(self._all_processes),
            "total_memory_percent": sum(p.memory_percent for p in processes),
            "average_cpu_percent": sum(p.cpu_percent for p in processes) / max(1, len(self.processes)),
            "total_threads": sum(p.num_threads for p in processes),
            "new_processes": len(self._new), "dying_processes": len(self._dying),
            "data_source": self.get_data_source(), "stale": self.status.stale,
            "error": self.status.error, "host_id": self.snapshot.host_id if self.snapshot else None,
            "events_lost": self.events_lost,
        }
        if self.snapshot and self.snapshot.source == "eBPF":
            stats["ebpf_events"] = " ".join(f"{k}:{v}" for k, v in self.snapshot.event_stats.items())
        return stats

    def detect_fork(self):
        forks, self.recent_forks = self.recent_forks, []
        return forks

    def detect_exec(self):
        execs = [self.processes[pid] for pid in dict.fromkeys(self.recent_execs) if pid in self.processes]
        self.recent_execs.clear()
        return execs

    def get_process_children(self, pid):
        return [self.processes[child] for child in self.process_families.get(pid, ())]

    def get_related_processes(self, pid, max_distance=2):
        start = self.processes.get(pid)
        if start is None or start.ppid <= 1:
            return []
        related, visited = [], set()

        def collect(current_pid, distance):
            if distance > max_distance or current_pid in visited or len(related) >= 8:
                return
            visited.add(current_pid)
            process = self.processes.get(current_pid)
            if process is None:
                return
            related.append(process)
            for child in self.process_families.get(current_pid, ()):
                collect(child, distance + 1)
            for sibling in self.process_families.get(process.ppid, ()):
                collect(sibling, distance + 1)

        collect(pid, 0)
        return related

    def detect_ipc_connections(self):
        if not self.snapshot:
            return []
        return [(self.processes[c.pid_a], self.processes[c.pid_b])
                for c in self.snapshot.connections
                if c.pid_a != c.pid_b and c.pid_a in self.processes and c.pid_b in self.processes][:100]

    def shutdown(self):
        self._external_source.shutdown()
