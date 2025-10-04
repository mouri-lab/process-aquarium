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
from typing import Dict, Iterable, List, Optional, Set, Callable
from threading import Event, Lock, Thread
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
        self._last_ipc_refresh = 0.0
        self._ipc_refresh_interval = 2.0  # seconds

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

        # Async polling support
        self._lock = Lock()
        self._shutdown = Event()
        self._poll_thread: Optional[Thread] = None
        self._thread_started = False
        self._batch_size = 100
        self._batch_pause = 0.004  # seconds between psutil batches
        self._ready = Event()

    # ---------------- IProcessSource API ---------------- #
    def update(self) -> None:  # type: ignore[override]
        self._ensure_thread()
        if not self._ready.is_set():
            self._ready.wait(timeout=0.2)

    def get_processes(self) -> Dict[int, ProcessInfo]:  # type: ignore[override]
        with self._lock:
            return self._processes.copy()

    def drain_lifecycle_events(self) -> List[ProcessLifecycleEvent]:  # type: ignore[override]
        with self._lock:
            buf = self._lifecycle_buffer
            self._lifecycle_buffer = []
            return buf

    def get_ipc_connections(self, limit: int = 20) -> List[IPCConnection]:  # type: ignore[override]
        with self._lock:
            return self._recent_ipc[:limit]

    # ---------------- Thread management ---------------- #
    def _ensure_thread(self) -> None:
        if self._thread_started:
            return
        self._poll_thread = Thread(target=self._poll_loop, name="PsutilProcessSource", daemon=True)
        self._poll_thread.start()
        self._thread_started = True

    def shutdown(self) -> None:
        if not self._thread_started:
            return
        self._shutdown.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass

    # ---------------- Internal helpers ---------------- #
    def _poll_loop(self) -> None:
        attrs = ['pid', 'ppid', 'name', 'exe', 'memory_percent',
                 'cpu_percent', 'num_threads', 'create_time',
                 'status', 'cmdline']
        while not self._shutdown.is_set():
            loop_start = time.time()

            with self._lock:
                prev_processes = self._processes
                prev_pids = set(self._previous_pids)
                prev_exe = dict(self._previous_exe)

            new_snapshot: Dict[int, ProcessInfo] = {}
            current_pids: Set[int] = set()
            current_exe: Dict[int, str] = {}
            lifecycle_events: List[ProcessLifecycleEvent] = []
            now = time.time()
            processed = 0

            for proc in psutil.process_iter(attrs):
                if self._shutdown.is_set():
                    break
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

                    prev_info = prev_processes.get(pid)
                    is_new = pid not in prev_pids
                    birth_time = prev_info.birth_time if prev_info else datetime.now()

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
                        birth_time=birth_time if not is_new else datetime.now(),
                        last_update=datetime.now(),
                        is_new=is_new,
                    )

                    new_snapshot[pid] = proc_info

                    if is_new:
                        lifecycle_events.append(ProcessLifecycleEvent(
                            event_type="spawn", pid=pid, ppid=proc_info.ppid,
                            timestamp=now
                        ))

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

                processed += 1
                if processed % self._batch_size == 0:
                    if self._shutdown.wait(self._batch_pause):
                        return

            # exec detection
            for pid, exepath in current_exe.items():
                prev = prev_exe.get(pid)
                if prev and exepath and prev != exepath:
                    lifecycle_events.append(ProcessLifecycleEvent(
                        event_type="exec",
                        pid=pid,
                        ppid=new_snapshot[pid].ppid if pid in new_snapshot else None,
                        timestamp=now,
                        details={"old_exe": prev, "new_exe": exepath}
                    ))

            # exit detection
            for old_pid in prev_pids:
                if old_pid not in current_pids:
                    prev_info = prev_processes.get(old_pid)
                    lifecycle_events.append(ProcessLifecycleEvent(
                        event_type="exit",
                        pid=old_pid,
                        ppid=prev_info.ppid if prev_info else None,
                        timestamp=now
                    ))

            refresh_ipc = False
            if now - self._last_ipc_refresh >= self._ipc_refresh_interval:
                refresh_ipc = True
                self._last_ipc_refresh = now

            recent_ipc: Optional[List[IPCConnection]] = None
            if refresh_ipc:
                recent_ipc = self._detect_ipc(new_snapshot)[:20]

            with self._lock:
                self._processes = new_snapshot
                self._previous_pids = current_pids
                self._previous_exe = current_exe
                if lifecycle_events:
                    self._lifecycle_buffer.extend(lifecycle_events)
                if recent_ipc is not None:
                    self._recent_ipc = recent_ipc
                self._last_update = now
                self._ready.set()

            elapsed = time.time() - loop_start
            wait_time = max(0.0, self.update_interval - elapsed)
            if self._shutdown.wait(wait_time):
                break

    def _should_include(self, name: str, mem: float, cpu: float) -> bool:
        # すべてのプロセスを可視化するため、フィルタリングを無効化
        return True

        # 元のフィルタリングロジック（コメントアウト）
        # lower = name.lower()
        # if any(pat in lower for pat in self.excluded_patterns):
        #     return False
        # if any(imp in lower for imp in self.important_names):
        #     return True
        # if (mem or 0) > 0.1 or (cpu or 0) > 0.5:
        #     return True
        # import random
        # return random.random() < 0.8

    def _detect_ipc(self, processes: Dict[int, ProcessInfo]) -> List[IPCConnection]:
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
        for p in processes.values():
            if p.ppid in processes:
                conns.append(IPCConnection(pid_a=p.ppid, pid_b=p.pid, kind="parent-child"))
        return conns


class EbpfProcessSource(IProcessSource):
    """eBPF ベースのプロセスイベントソース (fork/exec/exit MVP)。

    BCC を利用して kernel tracepoint からイベントを取得し lifecycle events
    を生成する。詳細メトリクス(CPU/MEM)は保持しないため、必要なら上位で
    ハイブリッド構成 (psutil 併用) を行う想定。
    """

    BPF_PROGRAM = r"""
    struct fork_event_t { u64 ts; u32 ppid; u32 pid; };
    struct exec_event_t { u64 ts; u32 pid; };
    struct exit_event_t { u64 ts; u32 pid; };

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
        struct exec_event_t evt = {};
        evt.ts = bpf_ktime_get_ns();
        evt.pid = args->pid;
        exec_events.perf_submit(args, &evt, sizeof(evt));
        return 0;
    }

    TRACEPOINT_PROBE(sched, sched_process_exit) {
        struct exit_event_t evt = {};
        evt.ts = bpf_ktime_get_ns();
        evt.pid = args->pid;
        exit_events.perf_submit(args, &evt, sizeof(evt));
        return 0;
    }
    """

    def __init__(self, enable: bool = True, hybrid_mode: bool = True):
        self.available = False
        self._processes: Dict[int, ProcessInfo] = {}
        self._lifecycle_buffer: List[ProcessLifecycleEvent] = []
        # ハイブリッドモード: 初期スキャン + eBPF イベント追跡
        self.hybrid_mode = hybrid_mode
        self._initial_scan_done = False
        # イベント統計
        self._event_stats = {"spawn": 0, "exec": 0, "exit": 0, "captured": 0, "initial_scan": 0}
        # 並行アクセス制御
        self._lock = Lock()
        self._shutdown = Event()
        self._ready = Event()
        self._poll_thread: Optional[Thread] = None
        self._thread_started = False
        self._poll_timeout_ms = 100  # perf buffer poll timeout (ms)
        if not enable:
            return
        try:
            from bcc import BPF  # type: ignore
        except Exception as e:  # bcc 未インストール or 権限不足
            with self._lock:
                self._lifecycle_buffer.append(ProcessLifecycleEvent(
                    event_type="exec", pid=0, ppid=None, timestamp=time.time(),
                    details={"warning": f"bcc unavailable: {e}"}
                ))
            return
        try:
            self._bpf = BPF(text=self.BPF_PROGRAM)
            self._bpf["fork_events"].open_perf_buffer(self._handle_fork)
            self._bpf["exec_events"].open_perf_buffer(self._handle_exec)
            self._bpf["exit_events"].open_perf_buffer(self._handle_exit)
            self.available = True

            # ハイブリッドモード: 初期スキャンで既存プロセスを収集
            if self.hybrid_mode:
                self._perform_initial_scan()
            else:
                self._ready.set()
        except Exception as e:
            # エラー詳細を判別して適切なメッセージを生成
            error_str = str(e)
            if "Operation not permitted" in error_str or "Permission denied" in error_str:
                error_detail = "root権限が必要です (sudo で実行してください)"
            elif "No such file or directory" in error_str and "tracepoint" in error_str:
                error_detail = "カーネルがeBPFトレースポイントをサポートしていません"
            elif "Invalid argument" in error_str:
                error_detail = "eBPFプログラムのロードに失敗 (カーネルバージョンが古い可能性)"
            elif "bpf" in error_str.lower() and "not" in error_str.lower():
                error_detail = "eBPFサブシステムが利用できません"
            else:
                error_detail = f"予期しないエラー: {e}"

            with self._lock:
                self._lifecycle_buffer.append(ProcessLifecycleEvent(
                    event_type="exec", pid=0, ppid=None, timestamp=time.time(),
                    details={"error": error_detail}
                ))
            self.available = False

    # ---------- perf buffer handlers ---------- #
    def _handle_fork(self, cpu, data, size):  # type: ignore[override]
        from bcc import BPF  # type: ignore
        evt = self._bpf["fork_events"].event(data)
        now = time.time()
        captured = self._populate_process(evt.pid, evt.ppid)
        with self._lock:
            self._event_stats["spawn"] += 1
            self._lifecycle_buffer.append(ProcessLifecycleEvent(
                event_type="spawn", pid=evt.pid, ppid=evt.ppid, timestamp=now,
                details={"source": "ebpf", "raw_ts": evt.ts}
            ))
            if captured:
                self._event_stats["captured"] += 1
        self._ready.set()

    def _handle_exec(self, cpu, data, size):  # type: ignore[override]
        evt = self._bpf["exec_events"].event(data)
        now = time.time()
        captured = self._populate_process(evt.pid)
        with self._lock:
            self._event_stats["exec"] += 1
            ppid = self._processes.get(evt.pid).ppid if evt.pid in self._processes else None
            self._lifecycle_buffer.append(ProcessLifecycleEvent(
                event_type="exec", pid=evt.pid, ppid=ppid,
                timestamp=now, details={"source": "ebpf", "raw_ts": evt.ts}
            ))
            if captured:
                self._event_stats["captured"] += 1
        self._ready.set()

    def _handle_exit(self, cpu, data, size):  # type: ignore[override]
        evt = self._bpf["exit_events"].event(data)
        now = time.time()
        with self._lock:
            self._event_stats["exit"] += 1
            ppid = self._processes.get(evt.pid).ppid if evt.pid in self._processes else None
            self._lifecycle_buffer.append(ProcessLifecycleEvent(
                event_type="exit", pid=evt.pid, ppid=ppid, timestamp=now,
                details={"source": "ebpf", "raw_ts": evt.ts}
            ))
            # 終了したプロセスを削除（メモリ効率化）
            if evt.pid in self._processes:
                del self._processes[evt.pid]
        self._ready.set()

    # ---------- helpers ---------- #
    def _populate_process(self, pid: int, ppid_hint: Optional[int] = None):
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                name = p.name()
                exe = ''
                try:
                    exe = p.exe()
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    pass  # exe取得失敗は無視

                info = ProcessInfo(
                    pid=pid,
                    ppid=p.ppid() if ppid_hint is None else ppid_hint,
                    name=name,
                    exe=exe,
                    memory_percent=p.memory_percent() or 0.0,
                    cpu_percent=0.0,  # CPU% は後で外部で更新され得る
                    num_threads=p.num_threads(),
                    create_time=p.create_time(),
                    status=p.status(),
                    cmdline=p.cmdline(),
                    birth_time=datetime.now(),
                    last_update=datetime.now(),
                    is_new=True
                )
            with self._lock:
                self._processes[pid] = info
            self._ready.set()
            print(f"[eBPF] プロセス捕捉成功: {name} (PID: {pid})")
            return True
        except psutil.NoSuchProcess:
            # プロセスが既に終了済み（短命プロセス）
            pass
        except psutil.AccessDenied:
            # 権限不足
            pass
        except Exception as e:
            # その他のエラー
            pass
        return False

    def _perform_initial_scan(self):
        """初期スキャン: 既存のプロセス群をpsutilで一度だけ取得"""
        print("[eBPF] 初期プロセススキャンを実行中...")
        start_time = time.time()
        count = 0
        snapshot: Dict[int, ProcessInfo] = {}

        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'exe', 'memory_percent',
                                         'cpu_percent', 'num_threads', 'create_time',
                                         'status', 'cmdline']):
            try:
                info = proc.info
                pid = info['pid']
                name = (info['name'] or 'unknown')

                # 簡単なフィルタリング（重要なプロセスのみ）
                if not self._should_include_in_scan(name, info.get('memory_percent', 0)):
                    continue

                proc_info = ProcessInfo(
                    pid=pid,
                    ppid=info['ppid'] or 0,
                    name=name,
                    exe=info['exe'] or '',
                    memory_percent=info['memory_percent'] or 0.0,
                    cpu_percent=info['cpu_percent'] or 0.0,
                    num_threads=info['num_threads'] or 1,
                    create_time=info['create_time'] or 0.0,
                    status=info['status'] or 'unknown',
                    cmdline=info['cmdline'] or [],
                    birth_time=datetime.now(),
                    last_update=datetime.now(),
                    is_new=False,  # 初期スキャンなので新規ではない
                )

                snapshot[pid] = proc_info
                count += 1

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        with self._lock:
            self._processes.update(snapshot)
            self._initial_scan_done = True
            self._event_stats["initial_scan"] = count
        self._ready.set()
        elapsed = time.time() - start_time
        print(f"[eBPF] 初期スキャン完了: {count}プロセス収集 ({elapsed:.2f}秒)")

    def _should_include_in_scan(self, name: str, mem_percent: float) -> bool:
        """初期スキャン時のフィルタリング（すべてのプロセスを表示）"""
        # すべてのプロセスを可視化するため、フィルタリングを無効化
        return True

        # 元のフィルタリングロジック（コメントアウト）
        # # システムプロセスは除外
        # excluded = {'kthreadd', 'ksoftirqd', 'rcu_', 'watchdog', 'swapper'}
        # if any(ex in name.lower() for ex in excluded):
        #     return False
        #
        # # メモリ使用量が一定以上、または重要なプロセス名
        # important = {'python', 'node', 'java', 'chrome', 'firefox', 'code', 'docker', 'nginx', 'apache'}
        # if any(imp in name.lower() for imp in important) or (mem_percent and mem_percent > 0.5):
        #     return True
        #
        # # ランダムサンプリング（負荷軽減）
        # import random
        # return random.random() < 0.3

    # ---------- IProcessSource API ---------- #
    def update(self) -> None:  # type: ignore[override]
        if not self.available:
            return
        self._ensure_thread()
        if not self._ready.is_set():
            self._ready.wait(timeout=0.2)

    def get_processes(self) -> Dict[int, ProcessInfo]:  # type: ignore[override]
        with self._lock:
            return self._processes.copy()

    def drain_lifecycle_events(self) -> List[ProcessLifecycleEvent]:  # type: ignore[override]
        with self._lock:
            buf = self._lifecycle_buffer
            self._lifecycle_buffer = []
            return buf

    def get_ipc_connections(self, limit: int = 20) -> List[IPCConnection]:  # type: ignore[override]
        # IPC は未実装 (TODO: ソケット tracepoint / kprobe 拡張)
        return []

    # ---------- Thread management ---------- #
    def _ensure_thread(self) -> None:
        if not self.available or self._thread_started:
            return
        self._poll_thread = Thread(target=self._poll_loop, name="EbpfProcessSource", daemon=True)
        self._poll_thread.start()
        self._thread_started = True

    def _poll_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                self._bpf.perf_buffer_poll(timeout=self._poll_timeout_ms)
                self._ready.set()
            except InterruptedError:
                continue
            except Exception as exc:
                if self._shutdown.is_set():
                    break
                with self._lock:
                    self._lifecycle_buffer.append(ProcessLifecycleEvent(
                        event_type="exec", pid=0, ppid=None, timestamp=time.time(),
                        details={"error": f"perf_buffer_poll failed: {exc}"}
                    ))
                self.available = False
                self._ready.set()
                break

    def shutdown(self) -> None:
        if not self._thread_started:
            return
        self._shutdown.set()
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=1.0)

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass
