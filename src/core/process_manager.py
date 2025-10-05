"""Digital Life Aquarium - process management module

Compatibility wrapper designed to introduce an abstraction layer so the
legacy polling implementation (psutil) can be replaced by an event-driven
eBPF-based source in the future.

New: `src.core.sources` defines `IProcessSource` and `PsutilProcessSource`.
This module keeps the legacy public API (e.g. `update()`,
`get_process_statistics()`) while delegating to the configured source
internally.
"""

import psutil
import time
import random
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass
from datetime import datetime
import random

try:
    # 新しい抽象層 (存在しない場合でも旧来構造で動作できるよう try)
    from .sources import IProcessSource, PsutilProcessSource
    from .types import ProcessInfo as UnifiedProcessInfo, ProcessLifecycleEvent, IPCConnection
except Exception:
    IProcessSource = None  # type: ignore
    PsutilProcessSource = None  # type: ignore
    UnifiedProcessInfo = None  # type: ignore
    ProcessLifecycleEvent = None  # type: ignore
    IPCConnection = None  # type: ignore


if UnifiedProcessInfo is None:
    # フォールバック: 旧来データクラス (新しい types.py が見つからない場合用)
    @dataclass
    class ProcessInfo:  # type: ignore
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
        birth_time: datetime
        last_update: datetime
        is_new: bool = False
        is_dying: bool = False
else:
    # 新しい統一型を再エクスポート
    ProcessInfo = UnifiedProcessInfo  # type: ignore


class ProcessManager:
    """Main class that manages process information (compatibility wrapper).

    The public API is preserved for backwards compatibility while the actual
    data is delegated to an `IProcessSource` implementation. If no source is
    provided, a psutil-based source is used as a fallback.
    """

    def __init__(self, max_processes: int = 100, source: Optional[Any] = None):  # source: IProcessSource | None
        self.max_processes = max_processes
        self._external_source = source

    # Legacy fields (kept for compatibility / referenced by some logic)
        self.processes: Dict[int, ProcessInfo] = {}
        self.previous_pids: Set[int] = set()
        self.previous_process_exes: Dict[int, str] = {}
        self.update_interval = 1.0
        self.last_update = time.time()

    # Process relationship tracking
        self.process_families: Dict[int, List[int]] = {}
        self.recent_forks: List[tuple] = []
        self.recent_execs: List[int] = []

    # Parent-child bond system
        self.parent_child_bonds: Dict[int, float] = {}  # {child_pid: bond_creation_time}
        self.bond_duration = 90.0  # 90秒（1分30秒）で親離れ
        self.bond_weakening_start = 45.0  # 45秒後から結合が弱くなり始める

    # Important/excluded filters (used only when directly using psutil)
        self.important_processes = {
            'python', 'chrome', 'firefox', 'safari', 'code', 'terminal',
            'finder', 'dock', 'systemuiserver', 'windowserver', 'kernel_task',
            'launchd', 'zoom', 'slack', 'discord', 'spotify', 'photoshop',
            'illustrator', 'aftereffects', 'node', 'java', 'docker'
        }
        self.excluded_processes = {
            'com.apple.', 'cfprefsd', 'distnoted', 'trustd', 'secd',
            'bluetoothd', 'audiomxd', 'logd_helper', 'deleted'
        }

    # Process limit and sort configuration
        self.process_limit: Optional[int] = None
        self.sort_by: str = "cpu"  # cpu, memory, name, pid
        self.sort_order: str = "desc"  # asc, desc

        # ソース確立
        if self._external_source is None and PsutilProcessSource is not None:
            self._external_source = PsutilProcessSource(max_processes=max_processes)

    def get_all_processes(self) -> Dict[int, ProcessInfo]:
        """Return all process information."""
        return self.processes.copy()

    def set_process_limit(self, limit: Optional[int]) -> None:
        """Set a limit on the number of processes to display."""
        self.process_limit = limit
        if self._external_source is not None and hasattr(self._external_source, 'set_process_limit'):
            self._external_source.set_process_limit(limit)

    def set_sort_config(self, sort_by: str, sort_order: str = "desc") -> None:
        """Change sorting configuration."""
        if sort_by in ["cpu", "memory", "name", "pid"]:
            self.sort_by = sort_by
        if sort_order in ["asc", "desc"]:
            self.sort_order = sort_order
        if self._external_source is not None and hasattr(self._external_source, 'set_sort_config'):
            self._external_source.set_sort_config(sort_by, sort_order)

    def get_process(self, pid: int) -> Optional[ProcessInfo]:
        """Get process information for the specified PID."""
        return self.processes.get(pid)

    def update(self) -> None:
        """Update process information via the configured abstract source."""
        if self._external_source is not None:
            # 新実装経路
            self._external_source.update()
            snapshot = self._external_source.get_processes()

            # ソートと制限を適用
            snapshot = self._apply_sort_and_limit(snapshot)

            # 互換フィールドへ反映
            self.processes = snapshot
            current_pids = set(snapshot.keys())
            self.previous_pids = current_pids
            # 家族関係再構築
            self._update_process_families(snapshot)

            # exec / fork 検出: lifecycle events を利用
            if hasattr(self._external_source, 'drain_lifecycle_events'):
                try:
                    events = self._external_source.drain_lifecycle_events()
                except Exception:
                    events = []
                for ev in events:
                    if ev.event_type == 'exec':
                        self.recent_execs.append(ev.pid)
                    elif ev.event_type == 'spawn':
                        # spawn + 親存在なら fork とみなす
                        if ev.ppid and ev.ppid in snapshot:
                            parent = snapshot[ev.ppid]
                            child = snapshot.get(ev.pid)
                            if parent and child:
                                self.recent_forks.append((parent, child))
                                self.recent_forks = self.recent_forks[-10:]
            return

    # Fallback: legacy logic for environments without a sources module
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return
    # (The legacy implementation is kept minimal and may be removed in the future)
        new_snapshot: Dict[int, ProcessInfo] = {}
        current_pids: Set[int] = set()
        current_exe: Dict[int, str] = {}
        for proc in psutil.process_iter(['pid','ppid','name','exe','memory_percent','cpu_percent','num_threads','create_time','status','cmdline']):
            try:
                info = proc.info
                pid = info['pid']
                name = info['name'] or 'unknown'
                exe = info['exe'] or ''
                mem = info['memory_percent'] or 0.0
                cpu = info['cpu_percent'] or 0.0
                if not self._should_include_process(name, mem, cpu):
                    continue
                current_pids.add(pid)
                current_exe[pid] = exe
                is_new = pid not in self.previous_pids
                pinfo = ProcessInfo(
                    pid=pid, ppid=info['ppid'] or 0, name=name, exe=exe,
                    memory_percent=mem, cpu_percent=cpu,
                    num_threads=info['num_threads'] or 1,
                    create_time=info['create_time'] or 0.0,
                    status=info['status'] or 'unknown',
                    cmdline=info['cmdline'] or [],
                    birth_time=datetime.now() if is_new else (self.processes[pid].birth_time if pid in self.processes else datetime.now()),
                    last_update=datetime.now(), is_new=is_new
                )
                new_snapshot[pid] = pinfo
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # ソートと制限を適用
        new_snapshot = self._apply_sort_and_limit(new_snapshot)

        self._detect_exec_events(current_exe)
        self._update_process_families(new_snapshot)
        dying_processes = []
        for pid in self.previous_pids:
            if pid not in current_pids and pid in self.processes:
                process_name = self.processes[pid].name
                # print(f"⚰️ ProcessManager: プロセス終了検出 PID {pid} ({process_name}) - is_dying=True設定")
                self.processes[pid].is_dying = True
                dying_processes.append(pid)

        # if dying_processes:
        #     print(f"📊 ProcessManager: 今回のサイクルで{len(dying_processes)}個のプロセス終了を検出")
        prev_count = len(self.processes)
        self.processes = new_snapshot
        new_count = len(self.processes)
        # print(f"📊 ProcessManager更新: {prev_count} → {new_count} プロセス (現在PID数: {len(current_pids)})")

        self.previous_pids = current_pids
        self.previous_process_exes = current_exe
        self.last_update = current_time

    def _should_include_process(self, process_name: str, memory_percent: float, cpu_percent: float) -> bool:
        """Decide whether a process should be included for display."""
        # Noneチェック
        if memory_percent is None:
            memory_percent = 0.0
        if cpu_percent is None:
            cpu_percent = 0.0
        if process_name is None:
            process_name = "unknown"

    # Check excluded list
        for excluded in self.excluded_processes:
            if excluded in process_name.lower():
                return False

    # Always include important processes
        for important in self.important_processes:
            if important in process_name.lower():
                return True

        # Include processes that use a non-trivial amount of resources
        if memory_percent > 0.1 or cpu_percent > 0.5:  # lowered thresholds
            return True

        # Select other processes with a high probability (to relax limits)
        return random.random() < 0.8  # increased from ~30% to ~80%

    def _apply_sort_and_limit(self, processes: Dict[int, ProcessInfo]) -> Dict[int, ProcessInfo]:
        """Sort processes and apply the configured limit."""
        if not processes:
            return processes

        # プロセスリストに変換
        process_list = list(processes.values())

        # ソートキーを決定
        if self.sort_by == "cpu":
            key_func = lambda p: p.cpu_percent
        elif self.sort_by == "memory":
            key_func = lambda p: p.memory_percent
        elif self.sort_by == "name":
            key_func = lambda p: p.name.lower()
        elif self.sort_by == "pid":
            key_func = lambda p: p.pid
        else:
            key_func = lambda p: p.cpu_percent

        # ソート
        reverse = (self.sort_order == "desc")
        process_list.sort(key=key_func, reverse=reverse)

        # 制限を適用
        if self.process_limit is not None and self.process_limit > 0:
            process_list = process_list[:self.process_limit]

        # 辞書に戻す
        return {p.pid: p for p in process_list}

    def get_new_processes(self) -> List[ProcessInfo]:
        """Return a list of newly spawned processes."""
        return [proc for proc in self.processes.values() if proc.is_new]

    def get_dying_processes(self) -> List[ProcessInfo]:
        """Return a list of processes marked as dying/exiting."""
        return [proc for proc in self.processes.values() if proc.is_dying]

    def get_data_source(self) -> str:
        """Return the name of the currently active data source."""
        if self._external_source is not None:
            source_class = self._external_source.__class__.__name__
            if "Ebpf" in source_class:
                return "eBPF"
            elif "Psutil" in source_class:
                return "psutil"
            else:
                return source_class.replace("ProcessSource", "").lower()
        return "psutil"  # フォールバック時

    def get_process_statistics(self) -> Dict[str, any]:
        """Return summary statistics about the current process set."""
        total_processes = len(self.processes)
        total_memory = sum(proc.memory_percent for proc in self.processes.values())
        avg_cpu = sum(proc.cpu_percent for proc in self.processes.values()) / total_processes if total_processes > 0 else 0
        total_threads = sum(proc.num_threads for proc in self.processes.values())

        stats = {
            'total_processes': total_processes,
            'total_memory_percent': total_memory,
            'average_cpu_percent': avg_cpu,
            'total_threads': total_threads,
            'new_processes': len(self.get_new_processes()),
            'dying_processes': len(self.get_dying_processes()),
            'data_source': self.get_data_source()
        }

    # Include event stats if the backend source tracks eBPF-like events
        if (self._external_source is not None and
            hasattr(self._external_source, '_event_stats')):
            event_stats = self._external_source._event_stats
            if event_stats.get('initial_scan', 0) > 0:
                stats['ebpf_events'] = f"initial:{event_stats['initial_scan']} spawn:{event_stats['spawn']} exec:{event_stats['exec']} exit:{event_stats['exit']} captured:{event_stats['captured']}"
            else:
                stats['ebpf_events'] = f"spawn:{event_stats['spawn']} exec:{event_stats['exec']} exit:{event_stats['exit']} captured:{event_stats['captured']}"

        return stats

    def detect_fork(self) -> List[tuple]:
        """Detect fork operations (new parent-child relationships)."""
        forks = []
        for proc in self.get_new_processes():
            if proc.ppid in self.processes:
                parent = self.processes[proc.ppid]
                forks.append((parent, proc))

        # 最近のfork履歴を更新
        self.recent_forks.extend(forks)
        # 履歴は最大10個まで保持
        self.recent_forks = self.recent_forks[-10:]

        return forks

    def detect_exec(self) -> List[ProcessInfo]:
        """Detect exec operations (executable path changes)."""
        # recent_execsから該当するプロセス情報を取得
        execs = []
        for pid in self.recent_execs:
            if pid in self.processes:
                execs.append(self.processes[pid])

        # 履歴をクリア（一度検出したらクリア）
        self.recent_execs.clear()

        return execs

    def _detect_exec_events(self, current_process_exes: Dict[int, str]):
        """Internal helper to detect exec events by exe path differences."""
        for pid, current_exe in current_process_exes.items():
            if pid in self.previous_process_exes:
                previous_exe = self.previous_process_exes[pid]
                # 実行ファイルパスが変更された場合はexecとみなす
                if previous_exe and current_exe and previous_exe != current_exe:
                    self.recent_execs.append(pid)

    def _update_process_families(self, new_processes: Dict[int, ProcessInfo]):
        """Update process family relationships (parent/child mapping)."""
        current_time = time.time()
        self.process_families.clear()

        for proc in new_processes.values():
            if proc.ppid > 0:  # 親プロセスが存在する場合
                if proc.ppid not in self.process_families:
                    self.process_families[proc.ppid] = []
                self.process_families[proc.ppid].append(proc.pid)

                # 新しい親子関係の記録
                if proc.pid not in self.parent_child_bonds:
                    self.parent_child_bonds[proc.pid] = current_time

    # Remove bond records for processes that no longer exist
        existing_pids = set(new_processes.keys())
        self.parent_child_bonds = {
            pid: bond_time for pid, bond_time in self.parent_child_bonds.items()
            if pid in existing_pids
        }

    def get_process_children(self, pid: int) -> List[ProcessInfo]:
        """Get the list of child processes for the specified PID."""
        if pid not in self.process_families:
            return []

        children = []
        for child_pid in self.process_families[pid]:
            if child_pid in self.processes:
                children.append(self.processes[child_pid])
        return children

    def get_related_processes(self, pid: int, max_distance: int = 2) -> List[ProcessInfo]:
        """Return processes related to the given PID for schooling/flocking logic.

        This considers parent/child and sibling relationships and limits
        traversal depth via `max_distance`.
        """
        start_proc = self.processes.get(pid)
        if start_proc is None or start_proc.ppid <= 1:
            return []

        current_time = time.time()

    # # Processes under PID=1 use a lightweight limited-school formation (fast-path)
        # if start_proc.ppid <= 1:
        #     related = [start_proc]
        #     # 同名の兄弟プロセスのみ最大2つまで追加（シンプル処理）
        #     if start_proc.ppid in self.process_families:
        #         count = 0
        #         for sibling_pid in self.process_families[start_proc.ppid]:
        #             if (sibling_pid != pid and
        #                 count < 2 and
        #                 sibling_pid in self.processes):
        #                 sibling = self.processes[sibling_pid]
        #                 if sibling.name == start_proc.name:
        #                     related.append(sibling)
        #                     count += 1

        #     # PID=1配下でも孤立の場合は群れ形成
        #     if len(related) == 1:  # 自分だけの場合
        #         related = self._form_isolated_process_school(pid, related)

        #     return related        # 通常のプロセス：シンプルな群れ形成ロジック
        related = []
        visited = set()

        def collect_related(current_pid: int, distance: int):
            if distance > max_distance or current_pid in visited or len(related) >= 8:
                return

            visited.add(current_pid)
            current_proc = self.processes.get(current_pid)
            if current_proc is not None:
                related.append(current_proc)

            # 子プロセスを追加
            for child_pid in self.process_families.get(current_pid, []):
                collect_related(child_pid, distance + 1)

            # 兄弟プロセスを追加
            if current_proc is not None:
                parent_pid = current_proc.ppid
                for sibling_pid in self.process_families.get(parent_pid, []):
                    if sibling_pid != current_pid:
                        collect_related(sibling_pid, distance + 1)

        collect_related(pid, 0)

        # # 孤立プロセス（単独）の場合は他の孤立プロセスと大きな群れを形成
        # if len(related) == 1:  # 自分だけの場合
        #     related = self._form_isolated_process_school(pid, related)

        return related

    def _form_isolated_process_school(self, current_pid: int, current_related: List[ProcessInfo]) -> List[ProcessInfo]:
        """Form a large school from isolated processes (lightweight version)."""
        isolated_group = current_related.copy()  # 自分を含める

    # Lightweight: increase group size to reduce processing
        group_size = 100
        current_group_index = current_pid // group_size

    # Lightweight: only check processes within the same PID group range
        start_pid = current_group_index * group_size
        end_pid = start_pid + group_size

        count = 0
        for pid in range(start_pid, end_pid):
            if pid == current_pid or pid not in self.processes:
                continue

            # 簡易孤立判定（重い処理を削除）
            proc = self.processes[pid]

            # 子プロセスがある場合はスキップ
            if pid in self.process_families:
                continue

            isolated_group.append(proc)
            count += 1
            if count >= 8:  # 群れサイズを小さく制限
                break

        return isolated_group

    def _is_isolated_process(self, pid: int) -> bool:
        """Determine whether a process is isolated (lightweight check)."""
        # 軽量化：簡易判定のみ
        return pid not in self.process_families  # 子プロセスがない = 孤立

    def _should_maintain_parent_child_bond(self, child_pid: int, current_time: float) -> bool:
        """Decide whether a parent-child bond should be maintained."""
        bond_time = self.parent_child_bonds.get(child_pid)
        if bond_time is None:
            return True  # 新しいプロセスは結合を維持

        # 自分に子プロセスができたら即座に親離れ（大人になった証拠）
        if child_pid in self.process_families and len(self.process_families[child_pid]) > 0:
            return False  # 子を持ったプロセスは親離れ

        age = current_time - bond_time

        # 基本的な親離れ判定
        if age > self.bond_duration:
            return False  # 完全に親離れ

        # 結合が弱くなり始めた段階では確率的に親離れ
        if age > self.bond_weakening_start:
            weakening_progress = (age - self.bond_weakening_start) / (self.bond_duration - self.bond_weakening_start)
            # 時間が経つにつれて親離れの確率が上がる
            return random.random() > weakening_progress * 0.7  # 最大70%の確率で親離れ

        return True  # まだ親離れしない

    def detect_ipc_connections(self) -> List[tuple]:
        """Detect inter-process communication (IPC) connections (enhanced).

        Returns:
            List[tuple]: list of (ProcessInfo, ProcessInfo) tuples
        """
        if self._external_source is not None and hasattr(self._external_source, 'get_ipc_connections'):
            try:
                source_conns = self._external_source.get_ipc_connections(limit=20)
                if source_conns:
                    # source からの形式を (ProcessInfo, ProcessInfo) に変換
                    mapped = []
                    for conn in source_conns:
                        if hasattr(conn, 'pid_a') and hasattr(conn, 'pid_b'):
                            proc_a = self.processes.get(conn.pid_a)
                            proc_b = self.processes.get(conn.pid_b)
                            if proc_a and proc_b and proc_a != proc_b:
                                mapped.append((proc_a, proc_b))
                    if mapped:
                        return mapped[:20]
            except Exception:
                pass

        connections = []

    # Enhanced IPC detection
        try:
            # 1. Comprehensive file-descriptor based detection using lsof
            connections.extend(self._detect_lsof_connections())
        except Exception:
            pass

        try:
            # 2. Traditional network connection detection (extended)
            connections.extend(self._detect_network_connections())
        except Exception:
            pass

        try:
            # 3. Unix domain socket detection (detailed)
            connections.extend(self._detect_unix_sockets())
        except Exception:
            pass

        try:
            # 4. Shared memory detection
            connections.extend(self._detect_shared_memory())
        except Exception:
            pass

        try:
            # Infer IPC from network connections
            net_connections = psutil.net_connections(kind='inet')

            # Extract local loopback connections
            local_connections = {}
            for conn in net_connections:
                if (conn.laddr and conn.raddr and
                    conn.laddr.ip in ['127.0.0.1', '::1'] and
                    conn.raddr.ip in ['127.0.0.1', '::1'] and
                    conn.pid):

                    key = (min(conn.laddr.port, conn.raddr.port),
                           max(conn.laddr.port, conn.raddr.port))

                    if key not in local_connections:
                        local_connections[key] = []
                    local_connections[key].append(conn.pid)

            # Treat processes using the same port pair as connected
            for port_pair, pids in local_connections.items():
                if len(pids) >= 2:
                    unique_pids = list(set(pids))
                    for i in range(len(unique_pids)):
                        for j in range(i + 1, len(unique_pids)):
                            pid1, pid2 = unique_pids[i], unique_pids[j]
                            if pid1 in self.processes and pid2 in self.processes:
                                proc1 = self.processes[pid1]
                                proc2 = self.processes[pid2]
                                connections.append((proc1, proc2))

            # Detect Unix domain socket connections
            try:
                unix_connections = psutil.net_connections(kind='unix')
                unix_socket_map = {}

                for conn in unix_connections:
                    if conn.laddr and conn.pid and conn.pid in self.processes:
                        socket_path = conn.laddr
                        if socket_path not in unix_socket_map:
                            unix_socket_map[socket_path] = []
                        unix_socket_map[socket_path].append(conn.pid)

                # Treat processes sharing the same Unix socket path as connected
                for socket_path, pids in unix_socket_map.items():
                    if len(pids) >= 2:
                        unique_pids = list(set(pids))
                        for i in range(len(unique_pids)):
                            for j in range(i + 1, len(unique_pids)):
                                pid1, pid2 = unique_pids[i], unique_pids[j]
                                if pid1 in self.processes and pid2 in self.processes:
                                    proc1 = self.processes[pid1]
                                    proc2 = self.processes[pid2]
                                    # 既に追加されていない場合のみ追加
                                    if not any((p1.pid == proc1.pid and p2.pid == proc2.pid) or
                                              (p1.pid == proc2.pid and p2.pid == proc1.pid)
                                              for p1, p2 in connections):
                                        connections.append((proc1, proc2))

            except (psutil.AccessDenied, OSError):
                # Unixソケットへのアクセス権限がない場合はスキップ
                pass

            # Treat parent-child relationships as a form of IPC
            for proc in self.processes.values():
                if proc.ppid in self.processes:
                    parent = self.processes[proc.ppid]
                    # 既に追加されていない場合のみ追加
                    if not any((p1.pid == parent.pid and p2.pid == proc.pid) or
                              (p1.pid == proc.pid and p2.pid == parent.pid)
                              for p1, p2 in connections):
                        connections.append((parent, proc))

        except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
            # アクセス権限がない場合は親子関係のみ返す
            for proc in self.processes.values():
                if proc.ppid in self.processes:
                    parent = self.processes[proc.ppid]
                    connections.append((parent, proc))

        # Limit the number of returned connections for performance
        return connections[:50]

    def _detect_lsof_connections(self) -> List[tuple]:
        """Comprehensive file-descriptor based connection detection using lsof."""
        connections = []
        try:
            import subprocess
            # lsofで開いているファイルを調査
            result = subprocess.run(['lsof', '-n', '-P', '+c', '0'],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # ヘッダーをスキップ
                fd_map = {}  # file -> list of PIDs map

                for line in lines:
                    parts = line.split()
                    if len(parts) >= 9:
                        try:
                            pid = int(parts[1])
                            fd_type = parts[4]
                            name = ' '.join(parts[8:])

                            # 興味深いファイル記述子のみ処理
                            if fd_type in ['sock', 'PIPE', 'unix', 'IPv4', 'IPv6']:
                                if name not in fd_map:
                                    fd_map[name] = []
                                fd_map[name].append(pid)
                        except (ValueError, IndexError):
                            continue

                # Connect processes that share the same file descriptor
                for name, pids in fd_map.items():
                    if len(pids) >= 2:
                        unique_pids = list(set(pids))
                        for i in range(len(unique_pids)):
                            for j in range(i + 1, len(unique_pids)):
                                pid1, pid2 = unique_pids[i], unique_pids[j]
                                if pid1 in self.processes and pid2 in self.processes:
                                    connections.append((self.processes[pid1], self.processes[pid2]))
        except Exception:
            pass
        # Limit results because lsof is expensive
        return connections[:10]

    def _detect_network_connections(self) -> List[tuple]:
        """Network connection detection (extended)."""
        connections = []
        local_connections = {}

        for conn in psutil.net_connections(kind='inet'):
            if (conn.laddr and conn.raddr and conn.pid and
                conn.laddr.ip in ['127.0.0.1', '::1'] and
                conn.raddr.ip in ['127.0.0.1', '::1']):

                key = (min(conn.laddr.port, conn.raddr.port),
                       max(conn.laddr.port, conn.raddr.port))

                if key not in local_connections:
                    local_connections[key] = []
                local_connections[key].append(conn.pid)

        for port_pair, pids in local_connections.items():
            if len(pids) >= 2:
                unique_pids = list(set(pids))
                for i in range(len(unique_pids)):
                    for j in range(i + 1, len(unique_pids)):
                        pid1, pid2 = unique_pids[i], unique_pids[j]
                        if pid1 in self.processes and pid2 in self.processes:
                            connections.append((self.processes[pid1], self.processes[pid2]))
        return connections

    def _detect_unix_sockets(self) -> List[tuple]:
        """Unix domain socket detection (detailed)."""
        connections = []
        try:
            unix_connections = psutil.net_connections(kind='unix')
            socket_map = {}

            for conn in unix_connections:
                if conn.laddr and conn.pid and conn.pid in self.processes:
                    socket_path = conn.laddr
                    if socket_path not in socket_map:
                        socket_map[socket_path] = []
                    socket_map[socket_path].append(conn.pid)

            for socket_path, pids in socket_map.items():
                if len(pids) >= 2:
                    unique_pids = list(set(pids))
                    for i in range(len(unique_pids)):
                        for j in range(i + 1, len(unique_pids)):
                            pid1, pid2 = unique_pids[i], unique_pids[j]
                            if pid1 in self.processes and pid2 in self.processes:
                                proc1, proc2 = self.processes[pid1], self.processes[pid2]
                                if not any((p1.pid == proc1.pid and p2.pid == proc2.pid) or
                                          (p1.pid == proc2.pid and p2.pid == proc1.pid)
                                          for p1, p2 in connections):
                                    connections.append((proc1, proc2))
        except Exception:
            pass
        return connections

    def _detect_shared_memory(self) -> List[tuple]:
        """Shared memory connection detection."""
        connections = []
        try:
            import subprocess
            # Inspect shared memory segments using `ipcs`.
            # Detailed parsing of shared memory requires /proc/*/maps analysis
            # which is non-trivial, so keep a simple placeholder implementation.
            result = subprocess.run(['ipcs', '-m'], capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                pass
        except Exception:
            pass
        return connections

    def shutdown(self) -> None:
        """バックエンドソースを安全に停止"""
        if self._external_source is not None and hasattr(self._external_source, "shutdown"):
            try:
                self._external_source.shutdown()
            except Exception:
                pass

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass

def test_process_manager():
    """ProcessManagerのテスト関数"""
    manager = ProcessManager()

    print("=== Digital Life Aquarium - Process Monitor Test ===")
    print("プロセス情報を10秒間監視します...")

    for i in range(20):  # 10秒間（0.5秒間隔）
        manager.update()
        stats = manager.get_process_statistics()

        print(f"\n--- Update {i+1} ---")
        print(f"総プロセス数: {stats['total_processes']}")
        print(f"総メモリ使用率: {stats['total_memory_percent']:.2f}%")
        print(f"平均CPU使用率: {stats['average_cpu_percent']:.2f}%")
        print(f"総スレッド数: {stats['total_threads']}")
        print(f"新規プロセス: {stats['new_processes']}")
        print(f"消滅プロセス: {stats['dying_processes']}")

        # 新しいプロセスを表示
        new_procs = manager.get_new_processes()
        if new_procs:
            print("新しい生命体が誕生しました:")
            for proc in new_procs[:3]:  # 最大3つまで表示
                print(f"  - {proc.name} (PID: {proc.pid})")

        # fork操作を検知
        forks = manager.detect_fork()
        if forks:
            print("分裂が発生しました:")
            for parent, child in forks:
                print(f"  - {parent.name} → {child.name}")

        time.sleep(0.5)


if __name__ == "__main__":
    test_process_manager()
